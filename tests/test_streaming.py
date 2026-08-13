import json
import pytest
import asyncio
import httpx
import threading
import time
import uvicorn
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright, expect

from app.main import app, get_current_user
from app.agy_client import AgyClient

client = TestClient(app)

SERVER_PORT = 8016

@pytest.fixture(scope="module", autouse=True)
def run_test_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    time.sleep(1)
    yield
    server.should_exit = True


def mock_auth():
    app.dependency_overrides[get_current_user] = lambda: "testuser"

def clear_mock_auth():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.fixture(autouse=True)
def run_around_tests():
    mock_auth()
    yield
    clear_mock_auth()


@pytest.mark.asyncio
async def test_agy_client_stream_message():
    """Verify that stream_message parses NDJSON events and yields text deltas."""
    agy = AgyClient()
    
    # Mock subprocess
    mock_ndjson_lines = [
        b'{"event":"init","conversation_id":"conv-123"}\n',
        b'{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"Hallo "}}\n',
        b'{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"Welt!"}}\n',
        b'{"event":"result","result":{"status":"SUCCESS","response":"Hallo Welt!"}}\n',
    ]
    
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    
    async def mock_readline():
        if mock_ndjson_lines:
            return mock_ndjson_lines.pop(0)
        return b''

    mock_proc.stdout.readline = mock_readline
    mock_proc.stderr.read = AsyncMock(return_value=b'')
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        chunks = []
        async for chunk in agy.stream_message(context_messages=[], new_message="Hi"):
            chunks.append(chunk)
            
        deltas = [c["text"] for c in chunks if c["type"] == "delta"]
        assert "".join(deltas) == "Hallo Welt!"
        
        done_events = [c for c in chunks if c["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["reply"] == "Hallo Welt!"


@patch("app.main.get_sessions")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_settings")
@patch("app.main.agy_client")
@pytest.mark.asyncio
async def test_chat_endpoint_streaming_sse(
    mock_agy_client, mock_get_settings, mock_save_msg, mock_get_history, mock_get_sessions
):
    """Verify that /api/sessions/{id}/chat with stream=true yields text/event-stream chunks."""
    mock_get_sessions.return_value = [{"id": "sess-stream", "title": "Neuer Chat"}]
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    async def mock_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Token1 "}
        yield {"type": "delta", "text": "Token2 "}
        yield {"type": "done", "reply": "Token1 Token2 ", "context_truncated": False}

    mock_agy_client.stream_message.side_effect = mock_stream

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.post(
            "/api/sessions/sess-stream/chat",
            data={"message": "Erzähle mir was", "stream": "true"},
            headers={"Accept": "text/event-stream"}
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        delta_texts = [e["text"] for e in events if e.get("type") == "delta"]
        assert delta_texts == ["Token1 ", "Token2 "]

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["reply"] == "Token1 Token2"

        # Verify messages saved to database
        assert mock_save_msg.call_count == 2
        user_msg = mock_save_msg.call_args_list[0][0][2]
        ai_msg = mock_save_msg.call_args_list[1][0][2]
        assert user_msg["text"] == "Erzähle mir was"
        assert ai_msg["text"] == "Token1 Token2"


@pytest.mark.asyncio
async def test_streaming_ui_progressive_rendering_e2e():
    """Verify that the frontend receives streaming tokens and progressively renders markdown."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        # Mock Sessions
        sessions_data = [
            {"id": "sess-live", "title": "Live Chat", "created_at": "2026-01-01T00:00:00Z"}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-live", "is_processing": false}'
        ))

        # Mock SSE Streaming chat endpoint
        async def sse_chat(route):
            # Send SSE payload
            sse_body = (
                'data: {"type": "delta", "text": "**Hallo** "}\n\n'
                'data: {"type": "delta", "text": "aus dem *Stream*!"}\n\n'
                'data: {"type": "done", "reply": "**Hallo** aus dem *Stream*!", "timestamp": "2026-01-01T00:00:05Z"}\n\n'
            )
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-live/chat", sse_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Type message and send
        await page.fill("#message-input", "Stream bitte")
        await page.click("#send-btn")

        # Verify that the AI message bubble appears with the rendered markdown
        ai_message = page.locator(".ai-message:has-text('Hallo aus dem Stream!')")
        await expect(ai_message).to_be_visible(timeout=5000)

        # Verify bold and italic tags rendered via markdown
        bold_elem = page.locator(".ai-message strong:has-text('Hallo')")
        italic_elem = page.locator(".ai-message em:has-text('Stream')")
        await expect(bold_elem).to_be_visible()
        await expect(italic_elem).to_be_visible()

        # Typing indicator must be gone
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()
