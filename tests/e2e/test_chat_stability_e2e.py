import json
import pytest
import asyncio
import threading
import time
import uvicorn
from playwright.async_api import async_playwright, expect

from app.main import app, get_current_user

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
