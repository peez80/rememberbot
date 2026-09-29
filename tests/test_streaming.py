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


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_chat_endpoint_streaming_sse(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    """Verify that /api/sessions/{id}/chat with stream=true yields text/event-stream chunks."""
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
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


@pytest.mark.asyncio
async def test_streaming_thinking_block_e2e():
    """Verify that SSE stream with <thinking> tags renders collapsible .ai-reasoning block."""
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
            {"id": "sess-thinking", "title": "Thinking Chat", "created_at": "2026-01-01T00:00:00Z"}
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
            body='{"id": "sess-thinking", "is_processing": false}'
        ))

        # Mock SSE Streaming chat endpoint with thinking tags
        async def sse_thinking_chat(route):
            sse_body = (
                'data: {"type": "delta", "text": "<thinking>\\nSchritt 1: Berechne etwas\\n"}\n\n'
                'data: {"type": "delta", "text": "</thinking>\\nDas ist das finale Ergebnis!"}\n\n'
                'data: {"type": "done", "reply": "<thinking>\\nSchritt 1: Berechne etwas\\n</thinking>\\nDas ist das finale Ergebnis!", "timestamp": "2026-01-01T00:00:05Z"}\n\n'
            )
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-thinking/chat", sse_thinking_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Type message and send
        await page.fill("#message-input", "Erkläre mir was")
        await page.click("#send-btn")

        # Verify details.ai-reasoning appears
        reasoning_box = page.locator(".ai-message details.ai-reasoning")
        await expect(reasoning_box).to_be_visible(timeout=5000)

        # Summary text is visible
        summary = reasoning_box.locator("summary")
        await expect(summary).to_have_text("Gedankengang der KI")

        # Click summary to toggle open
        await summary.click()
        await expect(reasoning_box).to_have_attribute("open", "")
        await expect(reasoning_box.locator(".reasoning-content")).to_contain_text("Schritt 1: Berechne etwas")

        # Final answer is visible in the bubble
        ai_message = page.locator(".ai-message")
        await expect(ai_message).to_contain_text("Das ist das finale Ergebnis!")

        await browser.close()


@pytest.mark.asyncio
async def test_thinking_box_persists_on_session_switch_and_history_e2e():
    """Verify that .ai-reasoning thinking box persists across session switching and reloads."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        # Mock Sessions: s1 and s2
        sessions_data = [
            {"id": "sess-alpha", "title": "Alpha Chat", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "sess-beta", "title": "Beta Chat", "created_at": "2026-01-01T00:00:01Z"}
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

        await page.route("**/api/sessions/sess-alpha/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body=json.dumps([
                {
                    "text": "<thinking>Alpha interne Gedanken</thinking>Antwort in Alpha",
                    "is_user": False,
                    "timestamp": "2026-01-01T00:00:02Z"
                }
            ])
        ))

        await page.route("**/api/sessions/sess-beta/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body=json.dumps([
                {
                    "text": "Einfacher Text ohne Gedanken in Beta",
                    "is_user": False,
                    "timestamp": "2026-01-01T00:00:03Z"
                }
            ])
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"is_processing": false}'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Select Alpha Chat
        alpha_item = page.locator(".session-item:has-text('Alpha Chat')")
        await alpha_item.click()

        # Verify details.ai-reasoning is rendered in Alpha Chat
        alpha_box = page.locator(".ai-message details.ai-reasoning")
        await expect(alpha_box).to_be_visible(timeout=5000)
        await expect(alpha_box.locator("summary")).to_have_text("Gedankengang der KI")

        # Open and check content
        await alpha_box.locator("summary").click()
        await expect(alpha_box).to_have_attribute("open", "")
        await expect(alpha_box.locator(".reasoning-content")).to_contain_text("Alpha interne Gedanken")

        # Switch to Beta Chat
        beta_item = page.locator(".session-item:has-text('Beta Chat')")
        await beta_item.click()

        # In Beta Chat, verify simple text and NO details.ai-reasoning
        await expect(page.locator(".ai-message:has-text('Einfacher Text ohne Gedanken in Beta')")).to_be_visible(timeout=5000)
        await expect(page.locator(".ai-message details.ai-reasoning")).to_have_count(0)

        # Switch back to Alpha Chat
        await alpha_item.click()

        # In Alpha Chat, verify details.ai-reasoning is STILL PRESENT in the DOM
        reopened_box = page.locator(".ai-message details.ai-reasoning")
        await expect(reopened_box).to_be_visible(timeout=5000)
        await expect(reopened_box.locator("summary")).to_have_text("Gedankengang der KI")
        await reopened_box.locator("summary").click()
        await expect(reopened_box.locator(".reasoning-content")).to_contain_text("Alpha interne Gedanken")

        # Reload page and verify it remains present
        await page.reload()
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")
        await alpha_item.click()
        await expect(page.locator(".ai-message details.ai-reasoning")).to_be_visible(timeout=5000)

        await browser.close()


@pytest.mark.asyncio
async def test_streaming_thinking_mid_stream_click_e2e():
    """Verify that clicking .ai-reasoning during active streaming keeps it open across subsequent tokens."""
    from app.services.session_service import session_service
    from app.services.agy_service import AGYService

    # Setup session in backend
    session_id = await session_service.create_session("testuser", "Mid Stream Chat")

    async def slow_stream(*args, **kwargs):
        yield {"type": "delta", "text": "<thinking>\nSchritt 1: Analysiere\n"}
        await asyncio.sleep(0.4)
        yield {"type": "delta", "text": "</thinking>\nAntwort Teil 1. "}
        await asyncio.sleep(0.6)
        yield {"type": "delta", "text": "Antwort Teil 2. "}
        await asyncio.sleep(0.6)
        yield {"type": "delta", "text": "Antwort Teil 3."}
        await asyncio.sleep(0.3)
        yield {
            "type": "done",
            "reply": "<thinking>\nSchritt 1: Analysiere\n</thinking>\nAntwort Teil 1. Antwort Teil 2. Antwort Teil 3.",
            "timestamp": "2026-01-01T00:00:05Z"
        }

    try:
        with patch.object(AGYService, "stream_message", side_effect=slow_stream), \
             patch.object(AGYService, "generate_chat_icon", new=AsyncMock()):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # Mock Auth
                await page.route("**/api/auth/status", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"authenticated": true, "username": "testuser"}'
                ))

                # Mock Sessions list to contain exactly our created session
                sessions_data = [
                    {"id": session_id, "title": "Mid Stream Chat", "created_at": "2026-01-01T00:00:00Z"}
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
                    body=json.dumps({"id": session_id, "is_processing": False})
                ))

                await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
                await page.evaluate("""() => {
                    const modal = document.getElementById('auth-modal');
                    if (modal) modal.remove();
                }""")

                # Wait for session item and select it
                sess_item = page.locator(".session-item:has-text('Mid Stream Chat')")
                await expect(sess_item).to_be_visible(timeout=5000)
                await sess_item.click()

                # Fill and send message
                await page.fill("#message-input", "Erkläre mir das")
                await page.click("#send-btn")

                # Wait for thinking box to appear
                box = page.locator(".ai-message details.ai-reasoning")
                await expect(box).to_be_visible(timeout=5000)

                # Wait until "Antwort Teil 1." appears in the message (box has auto-closed at </thinking>)
                await expect(page.locator(".ai-message")).to_contain_text("Antwort Teil 1.", timeout=5000)

                # User clicks summary WHILE stream is still active
                await box.locator("summary").click()

                # Verify it is open
                await expect(box).to_have_attribute("open", "", timeout=1000)

                # Wait for Teil 2 and Teil 3 to stream in
                await expect(page.locator(".ai-message")).to_contain_text("Antwort Teil 3.", timeout=5000)

                # The box must STILL be open!
                await expect(box).to_have_attribute("open", "")
                await expect(box.locator(".reasoning-content")).to_contain_text("Schritt 1: Analysiere")

                # Wait for streaming class to be removed (finalization)
                await expect(page.locator(".ai-message.streaming")).to_have_count(0, timeout=5000)

                # After finalization, the box MUST STILL BE OPEN!
                await expect(box).to_have_attribute("open", "")

                await browser.close()
    finally:
        await session_service.delete_session("testuser", session_id)


