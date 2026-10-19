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


@pytest.mark.asyncio
async def test_stream_disconnect_while_agy_still_working_shows_typing_and_polls_e2e():
    """Verify that if the mobile connection drops after the server accepted the chat turn and agy is still working,
    NO connection error is shown; instead the typing indicator remains visible and status polling loads the final result."""
    import asyncio
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        backend_state = {
            "processing": False,
            "history": []
        }

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-work", "title": "Working Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-work/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        async def history_route(route):
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "true" if backend_state["processing"] else "false"},
                content_type="application/json",
                body=json.dumps(backend_state["history"])
            )
        await page.route("**/api/sessions/sess-work/history", history_route)

        async def status_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "sess-work", "is_processing": backend_state["processing"]})
            )
        await page.route("**/api/sessions/sess-work/status", status_route)

        async def chat_route(route):
            # Server receives message, saves user message, and starts agy processing
            backend_state["processing"] = True
            backend_state["history"] = [
                {"text": "Starte lange Aufgabe", "is_user": True, "timestamp": "2026-01-01T00:01:00Z"}
            ]
            await asyncio.sleep(0.15)
            # Simulate smartphone OS dropping the connection while agy continues in background
            await route.abort("failed")

        await page.route("**/api/sessions/sess-work/chat", chat_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator("#chat-container")).to_be_visible()

        await page.fill("#message-input", "Starte lange Aufgabe")
        await page.click("#send-btn")

        # Wait for the aborted chat request and recovery check to settle
        await page.wait_for_timeout(500)

        # 1. No error message should be shown!
        await expect(page.locator(".error-message")).to_have_count(0)

        # 2. The working animation (#typing-indicator) MUST still be visible because agy is still working
        await expect(page.locator("#typing-indicator")).to_be_visible()

        # 3. Now simulate agy finishing in the background
        backend_state["history"].append({
            "text": "Aufgabe erfolgreich im Hintergrund beendet!",
            "is_user": False,
            "timestamp": "2026-01-01T00:01:10Z"
        })
        backend_state["processing"] = False

        # Polling should pick up completion, show the final answer, and remove typing indicator
        await expect(page.locator("text='Aufgabe erfolgreich im Hintergrund beendet!'")).to_be_visible(timeout=4000)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()
        await expect(page.locator(".error-message")).to_have_count(0)

        await browser.close()


@pytest.mark.asyncio
async def test_stream_disconnect_after_agy_completed_in_background_shows_result_immediately_e2e():
    """Verify that if the mobile connection drops and agy has already finished in the background,
    the completed answer is loaded immediately without flashing or keeping a connection error."""
    import asyncio
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        backend_state = {
            "processing": False,
            "history": []
        }

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-done", "title": "Done Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-done/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        async def history_route(route):
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "true" if backend_state["processing"] else "false"},
                content_type="application/json",
                body=json.dumps(backend_state["history"])
            )
        await page.route("**/api/sessions/sess-done/history", history_route)

        async def status_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "sess-done", "is_processing": backend_state["processing"]})
            )
        await page.route("**/api/sessions/sess-done/status", status_route)

        async def chat_route(route):
            # Server processed and finished while phone was asleep, then socket broke on wake-up
            backend_state["processing"] = False
            backend_state["history"] = [
                {"text": "Schnelle Aufgabe", "is_user": True, "timestamp": "2026-01-01T00:01:00Z"},
                {"text": "Direktes Ergebnis nach Aufwachen", "is_user": False, "timestamp": "2026-01-01T00:01:03Z"}
            ]
            await asyncio.sleep(0.15)
            await route.abort("failed")

        await page.route("**/api/sessions/sess-done/chat", chat_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator("#chat-container")).to_be_visible()

        await page.fill("#message-input", "Schnelle Aufgabe")
        await page.click("#send-btn")

        # Result must appear directly without any error message
        await expect(page.locator("text='Direktes Ergebnis nach Aufwachen'")).to_be_visible(timeout=3000)
        await expect(page.locator(".error-message")).to_have_count(0)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_visibilitychange_aborts_zombie_stream_and_syncs_state_e2e():
    """Verify that if a chat request hangs as a zombie socket while the browser was hidden,
    returning to the app (visibilitychange -> visible) aborts the zombie stream and syncs the result."""
    import asyncio
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        backend_state = {
            "processing": False,
            "history": []
        }

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-zombie", "title": "Zombie Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-zombie/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        async def history_route(route):
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "true" if backend_state["processing"] else "false"},
                content_type="application/json",
                body=json.dumps(backend_state["history"])
            )
        await page.route("**/api/sessions/sess-zombie/history", history_route)

        async def status_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "sess-zombie", "is_processing": backend_state["processing"]})
            )
        await page.route("**/api/sessions/sess-zombie/status", status_route)

        async def zombie_chat_route(route):
            # Backend finishes work, but TCP connection hangs for 10s (simulating mobile OS zombie socket)
            backend_state["processing"] = False
            backend_state["history"] = [
                {"text": "Aufgabe vor Standby", "is_user": True, "timestamp": "2026-01-01T00:01:00Z"},
                {"text": "Ergebnis trotz Zombie-Socket geladen", "is_user": False, "timestamp": "2026-01-01T00:01:05Z"}
            ]
            await asyncio.sleep(10.0)
            try:
                await route.abort("failed")
            except Exception:
                pass

        await page.route("**/api/sessions/sess-zombie/chat", zombie_chat_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator("#chat-container")).to_be_visible()

        await page.fill("#message-input", "Aufgabe vor Standby")
        await page.click("#send-btn")

        await page.wait_for_timeout(150)

        # Simulate phone going to background (hidden) and then waking up (visible)
        await page.evaluate("""() => {
            Object.defineProperty(document, 'visibilityState', {
                configurable: true,
                get: function() { return 'hidden'; }
            });
            document.dispatchEvent(new Event('visibilitychange'));
        }""")

        await page.wait_for_timeout(100)

        await page.evaluate("""() => {
            Object.defineProperty(document, 'visibilityState', {
                configurable: true,
                get: function() { return 'visible'; }
            });
            document.dispatchEvent(new Event('visibilitychange'));
        }""")

        # Should recover quickly (well before the 10s zombie timeout!) without error
        await expect(page.locator("text='Ergebnis trotz Zombie-Socket geladen'")).to_be_visible(timeout=2000)
        await expect(page.locator(".error-message")).to_have_count(0)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_mid_sse_stream_premature_close_recovers_seamlessly_e2e():
    """Verify that if an SSE stream emits partial delta tokens and then closes prematurely without a 'done' event
    while agy is still working, the partial stream is cleaned up, typing indicator stays active, and polling loads the final answer."""
    import asyncio
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        backend_state = {
            "processing": False,
            "history": []
        }

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-mid", "title": "Mid Stream Drop", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-mid/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        async def history_route(route):
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "true" if backend_state["processing"] else "false"},
                content_type="application/json",
                body=json.dumps(backend_state["history"])
            )
        await page.route("**/api/sessions/sess-mid/history", history_route)

        async def status_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "sess-mid", "is_processing": backend_state["processing"]})
            )
        await page.route("**/api/sessions/sess-mid/status", status_route)

        async def premature_sse_chat(route):
            backend_state["processing"] = True
            backend_state["history"] = [
                {"text": "Stream mit Unterbrechung", "is_user": True, "timestamp": "2026-01-01T00:01:00Z"}
            ]
            # Stream closes after a delta event WITHOUT sending a 'done' event
            sse_body = 'data: {"type": "delta", "text": "Unvollständiger Stream..."}\n\n'
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-mid/chat", premature_sse_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator("#chat-container")).to_be_visible()

        await page.fill("#message-input", "Stream mit Unterbrechung")
        await page.click("#send-btn")

        await page.wait_for_timeout(400)

        # Typing indicator must be visible, and no error message
        await expect(page.locator(".error-message")).to_have_count(0)
        await expect(page.locator("#typing-indicator")).to_be_visible()

        # Complete in background
        backend_state["history"].append({
            "text": "Vollständige Antwort nach Stream-Abbruch!",
            "is_user": False,
            "timestamp": "2026-01-01T00:01:08Z"
        })
        backend_state["processing"] = False

        await expect(page.locator("text='Vollständige Antwort nach Stream-Abbruch!'")).to_be_visible(timeout=4000)
        await expect(page.locator("#typing-indicator")).not_to_be_visible()
        await expect(page.locator(".error-message")).to_have_count(0)

        await browser.close()


