import json
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8011

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


@pytest.mark.asyncio
async def test_thinking_animation_chat_switch_e2e():
    """Verify that switching chats and returning preserves the typing/thinking animation."""
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
            {"id": "sess-1", "title": "Chat Eins", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "sess-2", "title": "Chat Zwei", "created_at": "2026-01-01T00:00:01Z"}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        # Mock Settings
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        # History & Status state for sess-1
        sess1_state = {"processing": True, "completed": False}

        async def history_route(route):
            url = route.request.url
            if "sess-1" in url:
                if not sess1_state["completed"]:
                    headers = {"X-Is-Processing": "true" if sess1_state["processing"] else "false"}
                    await route.fulfill(
                        status=200,
                        headers=headers,
                        content_type="application/json",
                        body=json.dumps([{"text": "Erste Nachricht", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"}])
                    )
                else:
                    headers = {"X-Is-Processing": "false"}
                    await route.fulfill(
                        status=200,
                        headers=headers,
                        content_type="application/json",
                        body=json.dumps([
                            {"text": "Erste Nachricht", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
                            {"text": "Antwort von agy auf Chat Eins", "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
                        ])
                    )
            elif "sess-2" in url:
                headers = {"X-Is-Processing": "false"}
                await route.fulfill(
                    status=200,
                    headers=headers,
                    content_type="application/json",
                    body=json.dumps([{"text": "Nachricht in Chat Zwei", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"}])
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions/*/history", history_route)

        async def status_route(route):
            url = route.request.url
            if "sess-1" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "sess-1", "is_processing": sess1_state["processing"]})
                )
            else:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "sess-2", "is_processing": False})
                )

        await page.route("**/api/sessions/*/status", status_route)

        # Chat POST for sess-1 simulates long wait
        async def chat_route(route):
            await asyncio.sleep(5) # Long wait
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Antwort von agy auf Chat Eins", "context_truncated": False, "timestamp": "2026-01-01T00:00:05Z"})
            )

        await page.route("**/api/sessions/sess-1/chat", chat_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal if present
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Chat 1 is selected by default and starts with processing = True
        typing_indicator = page.locator("#typing-indicator")
        await expect(typing_indicator).to_be_visible(timeout=3000)

        # Switch to Chat 2
        chat2_item = page.locator(".session-item:has-text('Chat Zwei')")
        await chat2_item.click()

        # Verify Chat 2 is displayed and typing indicator is NOT visible
        await expect(page.locator("text='Nachricht in Chat Zwei'")).to_be_visible()
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        # Switch back to Chat 1 while still processing
        chat1_item = page.locator(".session-item:has-text('Chat Eins')")
        await chat1_item.click()

        # CRITICAL TEST: Typing indicator MUST be visible again in Chat 1!
        await expect(page.locator("#typing-indicator")).to_be_visible(timeout=3000)

        # Now simulate backend finishing processing
        sess1_state["processing"] = False
        sess1_state["completed"] = True

        # Polling or fetch should finish, typing indicator should vanish, and AI reply appears
        await expect(page.locator("text='Antwort von agy auf Chat Eins'")).to_be_visible(timeout=5000)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_thinking_animation_reload_e2e():
    """Verify that reloading/reopening the browser while agy is thinking restores the animation."""
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
            {"id": "sess-reload", "title": "Reload Chat", "created_at": "2026-01-01T00:00:00Z"}
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

        sess_state = {"processing": True, "completed": False}

        async def history_route(route):
            if not sess_state["completed"]:
                headers = {"X-Is-Processing": "true" if sess_state["processing"] else "false"}
                await route.fulfill(
                    status=200,
                    headers=headers,
                    content_type="application/json",
                    body=json.dumps([{"text": "Prompt vor dem Reload", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"}])
                )
            else:
                headers = {"X-Is-Processing": "false"}
                await route.fulfill(
                    status=200,
                    headers=headers,
                    content_type="application/json",
                    body=json.dumps([
                        {"text": "Prompt vor dem Reload", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
                        {"text": "Antwort nach Reload", "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
                    ])
                )

        await page.route("**/api/sessions/*/history", history_route)

        async def status_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "sess-reload", "is_processing": sess_state["processing"]})
            )

        await page.route("**/api/sessions/*/status", status_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Typing indicator should be visible initially because processing is True
        await expect(page.locator("#typing-indicator")).to_be_visible(timeout=3000)

        # Now simulate user reloading the browser (F5) while thinking
        await page.reload()

        # CRITICAL TEST: Typing indicator must still be visible immediately after reload!
        await expect(page.locator("#typing-indicator")).to_be_visible(timeout=3000)

        # Simulate backend finishing
        sess_state["processing"] = False
        sess_state["completed"] = True

        # Poller should detect completion, remove typing indicator and display AI response
        await expect(page.locator("text='Antwort nach Reload'")).to_be_visible(timeout=5000)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()
