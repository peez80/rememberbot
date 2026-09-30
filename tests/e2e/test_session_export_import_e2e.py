import json
import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8029


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
async def test_settings_modal_export_import_button_visibility_new_chat():
    """Verify export & import buttons in settings modal for a new chat (empty history)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-new", "title": "Neuer Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-new/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-new/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Open settings modal
        settings_btn = page.locator("#system-prompt-btn")
        await expect(settings_btn).to_be_enabled()
        await settings_btn.click()

        modal = page.locator("#system-prompt-modal")
        await expect(modal).to_be_visible()

        export_btn = page.locator("#export-session-btn")
        import_btn = page.locator("#import-session-btn")

        # In a new chat with empty history, both export and import buttons must be visible
        await expect(export_btn).to_be_visible()
        await expect(import_btn).to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_settings_modal_import_button_hidden_when_chat_has_history():
    """Verify export button is visible but import button is hidden when chat has messages."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-existing", "title": "Bestehender Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-existing/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "Existierender Prompt", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-existing/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"text": "Hallo, existierende Nachricht", "is_user": true, "timestamp": "2026-01-01T00:00:00Z"}]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Wait for history to load
        await page.wait_for_selector(".message")

        # Open settings modal
        settings_btn = page.locator("#system-prompt-btn")
        await expect(settings_btn).to_be_enabled()
        await settings_btn.click()

        modal = page.locator("#system-prompt-modal")
        await expect(modal).to_be_visible()

        export_btn = page.locator("#export-session-btn")
        import_btn = page.locator("#import-session-btn")

        # Export button must still be visible, but import button must be hidden
        await expect(export_btn).to_be_visible()
        await expect(import_btn).to_be_hidden()

        await browser.close()
