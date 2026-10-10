import asyncio
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


@pytest.mark.asyncio
async def test_export_modal_lifecycle_and_download():
    """Verify export modal appears on click, disables button, shows progress, and closes upon download."""
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
            body='[{"id": "sess-export", "title": "Export Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-export/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-export/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        export_route_event = asyncio.Event()

        async def delayed_export_route(route):
            await export_route_event.wait()
            await route.fulfill(
                status=200,
                headers={
                    "Content-Disposition": 'attachment; filename="chat_export_test.zip"',
                    "Access-Control-Expose-Headers": "Content-Disposition"
                },
                content_type="application/zip",
                body=b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            )

        await page.route("**/api/sessions/sess-export/export", delayed_export_route)

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

        export_btn = page.locator("#export-session-btn")
        await expect(export_btn).to_be_visible()

        export_modal = page.locator("#export-modal")
        await expect(export_modal).to_be_hidden()

        # Click export button
        await export_btn.click()

        # 1. Export modal must now be visible with loading message
        await expect(export_modal).to_be_visible()
        status_msg = page.locator("#export-status-message")
        await expect(status_msg).to_contain_text("ZIP-Archiv wird vorbereitet")

        # 2. Export button in settings modal must be disabled
        await expect(export_btn).to_be_disabled()

        # 3. Release the export backend response and expect download
        async with page.expect_download() as download_info:
            export_route_event.set()
            download = await download_info.value

        assert download.suggested_filename == "chat_export_test.zip"

        # 4. Export modal should now disappear
        await expect(export_modal).to_be_hidden()

        await browser.close()


@pytest.mark.asyncio
async def test_export_modal_abort():
    """Verify export modal can be cancelled with cancel button, immediately closing modal."""
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
            body='[{"id": "sess-abort", "title": "Abort Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-abort/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-abort/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        export_route_event = asyncio.Event()
        await page.route("**/api/sessions/sess-abort/export", lambda route: export_route_event.wait())

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await page.locator("#system-prompt-btn").click()
        export_btn = page.locator("#export-session-btn")
        await export_btn.click()

        export_modal = page.locator("#export-modal")
        await expect(export_modal).to_be_visible()

        # User clicks cancel
        cancel_btn = page.locator("#export-cancel-btn")
        await expect(cancel_btn).to_be_visible()
        await cancel_btn.click()

        # Modal must be closed and export button re-enabled
        await expect(export_modal).to_be_hidden()
        await expect(export_btn).to_be_enabled()

        await browser.close()


@pytest.mark.asyncio
async def test_export_modal_error_handling():
    """Verify export modal displays error message and close button on server failure."""
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
            body='[{"id": "sess-err", "title": "Error Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-err/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-err/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))
        await page.route("**/api/sessions/sess-err/export", lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"detail": "Server-Fehler beim Archivieren"}'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await page.locator("#system-prompt-btn").click()
        export_btn = page.locator("#export-session-btn")
        await export_btn.click()

        export_modal = page.locator("#export-modal")
        await expect(export_modal).to_be_visible()

        # Should show error message
        status_msg = page.locator("#export-status-message")
        await expect(status_msg).to_contain_text("Server-Fehler beim Archivieren")

        # Cancel/Close button should now say "Schließen"
        cancel_btn = page.locator("#export-cancel-btn")
        await expect(cancel_btn).to_have_text("Schließen")
        await cancel_btn.click()

        # Modal should be closed
        await expect(export_modal).to_be_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_import_modal_lifecycle_and_steps():
    """Verify import modal opens on file selection, displays all 4 steps, and closes upon completion."""
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
            body='[{"id": "sess-imp", "title": "Neuer Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-imp/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-imp/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        import_route_event = asyncio.Event()

        async def delayed_import_route(route):
            await import_route_event.wait()
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "id": "sess-imp", "title": "Importierter Chat", "has_icon": false}'
            )

        await page.route("**/api/sessions/sess-imp/import", delayed_import_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Open settings modal
        await page.locator("#system-prompt-btn").click()
        await expect(page.locator("#import-session-btn")).to_be_visible()

        import_modal = page.locator("#import-modal")
        await expect(import_modal).to_be_hidden()

        # Trigger file selection
        mock_zip_bytes = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        await page.set_input_files("#import-session-input", files=[{
            "name": "chat_backup.zip",
            "mimeType": "application/zip",
            "buffer": mock_zip_bytes
        }])

        # 1. Import modal must now be visible with all 4 steps
        await expect(import_modal).to_be_visible()
        await expect(page.locator("#import-step-upload")).to_be_visible()
        await expect(page.locator("#import-step-verify")).to_be_visible()
        await expect(page.locator("#import-step-restore")).to_be_visible()
        await expect(page.locator("#import-step-finalize")).to_be_visible()

        # 2. Release server processing and expect successful finish
        import_route_event.set()

        # 3. Import modal and settings modal should both close
        await expect(import_modal).to_be_hidden()
        await expect(page.locator("#system-prompt-modal")).to_be_hidden()

        await browser.close()


@pytest.mark.asyncio
async def test_import_modal_abort():
    """Verify import modal can be cancelled with cancel button, closing modal immediately."""
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
            body='[{"id": "sess-imp-abort", "title": "Neuer Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-imp-abort/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-imp-abort/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        import_route_event = asyncio.Event()
        await page.route("**/api/sessions/sess-imp-abort/import", lambda route: import_route_event.wait())

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await page.locator("#system-prompt-btn").click()
        await expect(page.locator("#import-session-btn")).to_be_visible()

        mock_zip_bytes = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        await page.set_input_files("#import-session-input", files=[{
            "name": "chat_backup.zip",
            "mimeType": "application/zip",
            "buffer": mock_zip_bytes
        }])

        import_modal = page.locator("#import-modal")
        await expect(import_modal).to_be_visible()

        # User clicks cancel
        cancel_btn = page.locator("#import-cancel-btn")
        await expect(cancel_btn).to_be_visible()
        await cancel_btn.click()

        # Modal must be closed immediately
        await expect(import_modal).to_be_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_import_modal_error_handling():
    """Verify import modal displays step error and close button on server error (no alert popup)."""
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
            body='[{"id": "sess-imp-err", "title": "Neuer Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-imp-err/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-imp-err/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))
        await page.route("**/api/sessions/sess-imp-err/import", lambda route: route.fulfill(
            status=400,
            content_type="application/json",
            body='{"detail": "Keine session.json im ZIP-Archiv gefunden"}'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await page.locator("#system-prompt-btn").click()

        mock_zip_bytes = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        await page.set_input_files("#import-session-input", files=[{
            "name": "corrupt_backup.zip",
            "mimeType": "application/zip",
            "buffer": mock_zip_bytes
        }])

        import_modal = page.locator("#import-modal")
        await expect(import_modal).to_be_visible()

        # Should show error in error banner
        error_banner = page.locator("#import-modal-error-banner")
        await expect(error_banner).to_contain_text("Keine session.json im ZIP-Archiv gefunden")

        # Cancel/Close button should now say "Schließen"
        cancel_btn = page.locator("#import-cancel-btn")
        await expect(cancel_btn).to_have_text("Schließen")
        await cancel_btn.click()

        # Modal should be closed
        await expect(import_modal).to_be_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_import_modal_file_size_limit_2000mb():
    """Verify import allows files up to 2000MB and rejects files exceeding 2000MB."""
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
            body='[{"id": "sess-limit-2000", "title": "Neuer Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-limit-2000/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/sess-limit-2000/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        import_upload_started = asyncio.Event()
        await page.route("**/api/sessions/sess-limit-2000/import", lambda route: import_upload_started.set())

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await page.locator("#system-prompt-btn").click()
        await expect(page.locator("#import-session-btn")).to_be_visible()

        import_modal = page.locator("#import-modal")

        # 1. Test oversized file (> 2000 MB: 2001 MB)
        await page.evaluate("""() => {
            const input = document.getElementById('import-session-input');
            const file = new File(['mock content'], 'huge_chat.zip', { type: 'application/zip' });
            Object.defineProperty(file, 'size', { value: 2001 * 1024 * 1024 });
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            input.dispatchEvent(new Event('change'));
        }""")

        # Import modal should open and display the 2000 MB error
        await expect(import_modal).to_be_visible()
        upload_step = page.locator("#import-step-upload")
        await expect(upload_step).to_have_class("import-step-item error")
        await expect(page.locator("#import-step-upload-status")).to_have_text("Datei zu groß (max. 2000 MB)")
        error_banner = page.locator("#import-modal-error-banner")
        await expect(error_banner).to_contain_text("Das ausgewählte ZIP-Archiv überschreitet die Maximalgröße von 2000 MB.")

        # Close the modal via cancel button
        cancel_btn = page.locator("#import-cancel-btn")
        await expect(cancel_btn).to_have_text("Schließen")
        await cancel_btn.click()
        await expect(import_modal).to_be_hidden()

        # 2. Test 75 MB file (which was previously rejected by the 50 MB bug)
        await page.evaluate("""() => {
            const input = document.getElementById('import-session-input');
            const file = new File(['mock content'], 'valid_chat.zip', { type: 'application/zip' });
            Object.defineProperty(file, 'size', { value: 75 * 1024 * 1024 });
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            input.dispatchEvent(new Event('change'));
        }""")

        # Import modal should open and start uploading normally (step is active, not error)
        await expect(import_modal).to_be_visible()
        await expect(upload_step).to_have_class("import-step-item active")
        await expect(page.locator("#import-step-upload-status")).to_contain_text("Wird hochgeladen")
        await expect(error_banner).to_be_hidden()

        # Cancel the ongoing import
        await cancel_btn.click()
        await expect(import_modal).to_be_hidden()

        await browser.close()



