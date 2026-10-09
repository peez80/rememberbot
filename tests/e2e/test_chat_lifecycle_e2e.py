import json
import re
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8031


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
async def test_new_chat_button_flow_e2e():
    """Verify clicking #new-chat-btn calls POST /api/sessions, adds session to sidebar, and resets chat view."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-old", "title": "Bestehender Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": False}
        ]

        async def sessions_route(route):
            if route.request.method == "GET":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(sessions_state)
                )
            elif route.request.method == "POST":
                new_session = {
                    "id": "sess-created-123",
                    "title": "Neuer Chat",
                    "created_at": "2026-01-01T00:05:00Z",
                    "has_icon": False
                }
                sessions_state.insert(0, new_session)
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(new_session)
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions", sessions_route)

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal if present
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)
        await expect(page.locator(".session-item").first).to_contain_text("Bestehender Chat")

        # Click New Chat button
        new_chat_btn = page.locator("#new-chat-btn")
        await expect(new_chat_btn).to_be_visible()
        await new_chat_btn.click()

        # Verify new session added and highlighted active
        await expect(page.locator(".session-item")).to_have_count(2)
        new_session_item = page.locator(".session-item[data-session-id='sess-created-123']")
        await expect(new_session_item).to_be_visible()
        await expect(new_session_item).to_have_class(re.compile(r"active"))

        # Verify header title updated
        header_title = page.locator("#header-chat-title")
        await expect(header_title).to_have_text("Neuer Chat")

        await browser.close()


@pytest.mark.asyncio
async def test_delete_chat_with_confirmation_e2e():
    """Verify clicking .delete-btn triggers confirm dialog and deletes the session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-to-delete", "title": "Zu löschender Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": False},
            {"id": "sess-keep", "title": "Bleibender Chat", "created_at": "2026-01-01T00:01:00Z", "has_icon": False}
        ]

        async def sessions_route(route):
            if route.request.method == "GET":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(sessions_state)
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions", sessions_route)

        deleted_session_ids = []

        async def delete_route(route):
            if route.request.method == "DELETE":
                url = route.request.url
                s_id = url.split("/api/sessions/")[1]
                deleted_session_ids.append(s_id)
                nonlocal sessions_state
                sessions_state = [s for s in sessions_state if s["id"] != s_id]
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"status": "deleted"})
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions/*", delete_route)

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        # Accept confirm dialog automatically
        dialog_messages = []
        async def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            await dialog.accept()
        page.on("dialog", handle_dialog)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(2)

        # Click delete button of the first session
        delete_btn = page.locator(".session-item[data-session-id='sess-to-delete'] .delete-btn")
        await expect(delete_btn).to_be_visible()
        await delete_btn.click()

        # Verify confirmation prompt was shown
        assert any("löschen" in msg.lower() for msg in dialog_messages)

        # Verify DELETE was invoked for the correct session
        assert "sess-to-delete" in deleted_session_ids

        # Verify session item is removed from DOM
        await expect(page.locator(".session-item")).to_have_count(1)
        await expect(page.locator(".session-item").first).to_contain_text("Bleibender Chat")

        await browser.close()


@pytest.mark.asyncio
async def test_session_icon_rendering_sidebar_and_header_e2e():
    """Verify custom SVG icon vs robot fallback rendering in sidebar and header."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_data = [
            {"id": "sess-icon", "title": "Icon Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": True},
            {"id": "sess-plain", "title": "Plain Chat", "created_at": "2026-01-01T00:01:00Z", "has_icon": False}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="10" fill="#3b82f6"/></svg>'
        await page.route("**/api/sessions/sess-icon/icon*", lambda route: route.fulfill(
            status=200,
            content_type="image/svg+xml",
            body=svg_content
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # 1. Sidebar verification:
        # sess-icon must have img.session-list-icon
        icon_chat_item = page.locator(".session-item[data-session-id='sess-icon']")
        await expect(icon_chat_item.locator("img.session-list-icon")).to_be_visible()

        # sess-plain must have i.ph-robot.session-list-icon
        plain_chat_item = page.locator(".session-item[data-session-id='sess-plain']")
        await expect(plain_chat_item.locator("i.session-list-icon")).to_be_visible()

        # 2. Header verification for sess-icon (selected by default as first session):
        header_img = page.locator("#header-chat-icon")
        header_default = page.locator("#header-default-icon")
        await expect(header_img).to_be_visible()
        await expect(header_default).not_to_be_visible()

        # 3. Switch to sess-plain:
        await plain_chat_item.click()

        # Header icon should dynamically swap: default robot visible, img hidden
        await expect(header_default).to_be_visible()
        await expect(header_img).not_to_be_visible()

        # 4. Switch back to sess-icon:
        await icon_chat_item.click()
        await expect(header_img).to_be_visible()
        await expect(header_default).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_system_prompt_settings_modal_flow_e2e():
    """Verify opening chat settings modal, changing settings, saving, and DOM updates."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-settings", "title": "Ursprünglicher Titel", "created_at": "2026-01-01T00:00:00Z", "has_icon": False}
        ]

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_state)
        ))

        await page.route("**/api/models", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "default_model": "gemini-3.8-flash",
                "default_thinking_effort": "medium",
                "model_catalog": {
                    "default": {"label": "Standard", "supports_thinking": True, "allowed_efforts": ["low", "medium", "high"]},
                    "gemini-3.8-flash": {"label": "Gemini 3.8 Flash", "supports_thinking": True, "allowed_efforts": ["low", "medium", "high"]}
                }
            })
        ))

        settings_state = {
            "title": "Ursprünglicher Titel",
            "prompt": "Du bist ein Experte.",
            "include_gps": False,
            "model": "gemini-3.8-flash",
            "thinking_effort": "medium"
        }

        saved_settings = {}

        async def settings_route(route):
            if route.request.method == "GET":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(settings_state)
                )
            elif route.request.method == "PUT":
                payload = json.loads(route.request.post_data)
                saved_settings.update(payload)
                if "title" in payload:
                    sessions_state[0]["title"] = payload["title"]
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"status": "success", **payload})
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions/sess-settings/settings", settings_route)

        async def title_route(route):
            if route.request.method == "PUT":
                payload = json.loads(route.request.post_data)
                saved_settings.update(payload)
                sessions_state[0]["title"] = payload.get("title", "")
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"status": "success", "title": payload.get("title", "")})
                )
            else:
                await route.fallback()

        await page.route("**/api/sessions/sess-settings/title", title_route)

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

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

        # Modify values
        title_input = page.locator("#chat-title-input")
        prompt_input = page.locator("#system-prompt-input")
        effort_select = page.locator("#chat-thinking-effort-select")
        gps_checkbox = page.locator("#gps-setting-input")

        await title_input.fill("Aktualisierter Chat-Titel")
        await prompt_input.fill("Neuer maßgeschneiderter System-Prompt")
        await effort_select.select_option("high")
        await gps_checkbox.check()

        # Save settings
        save_btn = page.locator("#save-prompt-btn")
        await save_btn.click()

        # Modal must close
        await expect(modal).not_to_be_visible()

        # Verify saved payload
        assert saved_settings.get("title") == "Aktualisierter Chat-Titel"
        assert saved_settings.get("prompt") == "Neuer maßgeschneiderter System-Prompt"
        assert saved_settings.get("thinking_effort") == "high"
        assert saved_settings.get("include_gps") is True

        # Header title must reflect the update
        await expect(page.locator("#header-chat-title")).to_have_text("Aktualisierter Chat-Titel")

        await browser.close()


@pytest.mark.asyncio
async def test_mobile_sidebar_toggle_e2e():
    """Verify opening and closing sidebar on mobile viewport."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Mobile viewport (iPhone SE size)
        page = await browser.new_page(viewport={"width": 375, "height": 667})

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-mobile", "title": "Mobile Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": False}]'
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        sidebar = page.locator("#sidebar")
        menu_btn = page.locator("#menu-btn")
        close_btn = page.locator("#close-sidebar-btn")

        # Sidebar is initially closed on mobile (no .open class)
        await expect(sidebar).not_to_have_class(re.compile(r"open"))

        # Click menu button to open sidebar
        await menu_btn.click()
        await expect(sidebar).to_have_class(re.compile(r"open"))

        # Click close button to close sidebar
        await close_btn.click()
        await expect(sidebar).not_to_have_class(re.compile(r"open"))

        await browser.close()
