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

from app.main import app, get_current_user, _active_chat_sessions

client = TestClient(app)

SERVER_PORT = 8015

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


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_session_marked_processing_immediately(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    """Verify that _active_chat_sessions contains the session as soon as chat endpoint starts."""
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    started_event = asyncio.Event()
    finish_event = asyncio.Event()

    async def controlled_process(*args, **kwargs):
        started_event.set()
        await finish_event.wait()
        return {"reply": "Fertig.", "context_truncated": False}

    mock_agy_client.process_message.side_effect = controlled_process

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        chat_task = asyncio.create_task(
            async_client.post(
                "/api/sessions/sess-fast/chat",
                data={"message": "Hallo"},
            )
        )

        await asyncio.wait_for(started_event.wait(), timeout=2.0)

        # Status must be True
        status_resp = await async_client.get("/api/sessions/sess-fast/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_processing"] is True

        # User message must have been saved to history before process_message returned
        assert mock_save_msg.called
        first_call_args = mock_save_msg.call_args_list[0]
        # args: (username, session_id, user_msg_data)
        saved_msg = first_call_args[0][2]
        assert saved_msg["is_user"] is True
        assert saved_msg["text"] == "Hallo"

        finish_event.set()
        await chat_task

        # Status must be False after completion
        status_after = await async_client.get("/api/sessions/sess-fast/status")
        assert status_after.json()["is_processing"] is False


@pytest.mark.asyncio
async def test_message_and_typing_indicator_never_disappear_during_send_e2e():
    """Verify that during message sending, DOM never loses the user message or typing indicator."""
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
            {"id": "sess-stable", "title": "Stabiler Chat", "created_at": "2026-01-01T00:00:00Z"}
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

        # Initially empty history
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        # Status route returning false initially
        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-stable", "is_processing": false}'
        ))

        # Chat endpoint with delayed response (simulating thinking time)
        async def slow_chat(route):
            await asyncio.sleep(1.5)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "KI Antwort ist da!", "context_truncated": False, "timestamp": "2026-01-01T00:00:05Z"})
            )

        await page.route("**/api/sessions/sess-stable/chat", slow_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal if present
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Initial greeting should be visible
        await expect(page.locator("text='Hallo, wie geht es dir heute?'")).to_be_visible()

        # Type message and send
        await page.fill("#message-input", "Mein wichtiger Prompt")
        await page.click("#send-btn")

        # 1. Initial greeting must be gone
        await expect(page.locator("text='Hallo, wie geht es dir heute?'")).not_to_be_visible()

        # 2. User message MUST be in DOM
        user_msg = page.locator(".user-message:has-text('Mein wichtiger Prompt')")
        await expect(user_msg).to_be_visible()

        # 3. Typing indicator MUST be visible
        typing_indicator = page.locator("#typing-indicator")
        await expect(typing_indicator).to_be_visible()

        # 4. Check repeatedly during the 1.5s in-flight time that user message and typing indicator DO NOT vanish
        for _ in range(5):
            await page.wait_for_timeout(200)
            # Must still be visible
            assert await user_msg.is_visible(), "User message vanished during in-flight request!"
            assert await typing_indicator.is_visible(), "Typing indicator vanished during in-flight request!"

        # 5. When response finishes, AI reply appears and typing indicator disappears
        await expect(page.locator("text='KI Antwort ist da!'")).to_be_visible(timeout=3000)
        await expect(typing_indicator).not_to_be_visible()
        assert await user_msg.is_visible(), "User message disappeared after reply was appended!"

        await browser.close()
