import json
import re
import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8009

@pytest.fixture(scope="module", autouse=True)
def run_test_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    time.sleep(1)  # wait for server to start
    yield
    server.should_exit = True


@pytest.mark.asyncio
async def test_visibility_sync_recovers_error_e2e():
    """Verify that returning to the app (visibilitychange) reloads history and clears errors."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        # Mock Session List
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        
        # Initial empty history
        history_called = {"count": 0}
        async def history_route(route):
            history_called["count"] += 1
            if history_called["count"] == 1:
                # First load: empty history
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='[]'
                )
            else:
                # Subsequent load (after visibilitychange): return the full conversation
                history_data = [
                    {"text": "Hello", "is_user": True, "timestamp": "2026-01-01T00:01:00Z"},
                    {"text": "Correct AI Response from Backend", "is_user": False, "timestamp": "2026-01-01T00:01:05Z"}
                ]
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(history_data)
                )

        await page.route("**/api/sessions/sess-1/history", history_route)

        # Mock Settings
        await page.route("**/api/sessions/sess-1/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        # Mock Chat API to simulate connection drop (abort or 500)
        await page.route("**/api/sessions/sess-1/chat", lambda route: route.abort("failed"))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly just in case
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Wait for app to initialize
        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Type a message and send it
        await page.fill("#message-input", "Hello")
        await page.click("#send-btn")

        # The fetch should fail because we aborted the route.
        # It should show the connection error message.
        await expect(page.locator("text='Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.'")).to_be_visible()

        # Now simulate the user coming back to the browser (visibilitychange)
        # We need to dispatch a visibilitychange event with visibilityState = 'visible'
        await page.evaluate("""() => {
            // We can't trivially override document.visibilityState natively, 
            // but the event listener only checks document.visibilityState.
            // In playwright, the page is normally 'visible'. We just need to fire the event.
            Object.defineProperty(document, 'visibilityState', {
                get: function() { return 'visible'; }
            });
            document.dispatchEvent(new Event('visibilitychange'));
        }""")

        # Wait a moment for history fetch to occur
        await page.wait_for_timeout(500)

        # The error message should be gone
        await expect(page.locator("text='Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.'")).not_to_be_visible()
        
        # The correct AI response should now be displayed
        await expect(page.locator("text='Correct AI Response from Backend'")).to_be_visible()

        await browser.close()
