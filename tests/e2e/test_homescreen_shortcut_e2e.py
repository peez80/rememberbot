import json
import re
import pytest
import threading
import time
import uvicorn
from urllib.parse import quote
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8061


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


def _build_sse_response(reply_text: str) -> str:
    events = [
        {"type": "processing", "message_id": "msg-shortcut-1"},
        {"type": "delta", "text": reply_text},
        {
            "type": "done",
            "reply": reply_text,
            "timestamp": "2026-11-11T07:30:00Z",
            "context_truncated": False,
        },
    ]
    return "".join(f"data: {json.dumps(ev)}\n\n" for ev in events)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_shortcut_url_autosend_and_reload_guard_e2e():
    """
    Verify opening /?session=<target>&prompt=<text>&autosend=1&title=<name>:
    1. Selects the target session (even if not the first session in the list).
    2. Automatically sends the prompt message to the target session via SSE.
    3. Cleans the URL via history.replaceState so a subsequent page reload does NOT resend the message.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-first", "title": "Allgemeiner Chat", "created_at": "2026-11-11T07:00:00Z", "has_icon": False},
            {"id": "sess-target", "title": "Ernährungstagebuch", "created_at": "2026-11-10T07:00:00Z", "has_icon": False},
        ]

        histories = {
            "sess-first": [],
            "sess-target": [],
        }
        chat_calls = []

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_state)
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-target", "is_processing": false, "queued_count": 0, "is_generating_icon": false, "has_icon": false}'
        ))

        async def history_route(route):
            url = route.request.url
            sess_id = "sess-target" if "sess-target" in url else "sess-first"
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "false"},
                content_type="application/json",
                body=json.dumps(histories[sess_id])
            )

        await page.route("**/api/sessions/*/history", history_route)

        async def chat_route(route):
            url = route.request.url
            post_data = route.request.post_data or ""
            chat_calls.append({"url": url, "body": post_data})
            histories["sess-target"].append({
                "id": "msg-user-1",
                "text": "1 Tasse Kaffee eintragen",
                "is_user": True,
                "timestamp": "2026-11-11T07:30:00Z"
            })
            histories["sess-target"].append({
                "id": "msg-ai-1",
                "text": "Kaffee wurde im Ernährungstagebuch vermerkt!",
                "is_user": False,
                "timestamp": "2026-11-11T07:30:01Z"
            })
            await route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_build_sse_response("Kaffee wurde im Ernährungstagebuch vermerkt!")
            )

        await page.route("**/api/sessions/*/chat", chat_route)

        shortcut_url = (
            f"http://127.0.0.1:{SERVER_PORT}/?session=sess-target"
            f"&prompt={quote('1 Tasse Kaffee eintragen')}&autosend=1&title={quote('Kaffee Shortcut')}"
        )
        await page.goto(shortcut_url)

        # 1. Target session must be selected and active
        target_item = page.locator(".session-item[data-session-id='sess-target']")
        await expect(target_item).to_have_class(re.compile(r"active"))
        await expect(page.locator("#header-chat-title")).to_have_text("Ernährungstagebuch")

        # 2. Message and AI reply must be rendered in chat
        await expect(page.locator(".user-message")).to_contain_text("1 Tasse Kaffee eintragen")
        await expect(page.locator(".ai-message")).to_contain_text("Kaffee wurde im Ernährungstagebuch vermerkt!")
        assert len(chat_calls) == 1
        assert "/api/sessions/sess-target/chat" in chat_calls[0]["url"]

        # 3. URL must be cleaned via history.replaceState to prevent duplicate sends on reload
        await expect(page).to_have_url(f"http://127.0.0.1:{SERVER_PORT}/")

        # 4. Reloading the page must NOT send the shortcut message again
        await page.reload()
        await expect(page.locator(".ai-message")).to_contain_text("Kaffee wurde im Ernährungstagebuch vermerkt!")
        assert len(chat_calls) == 1

        await browser.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_shortcut_setup_modal_and_banner_workflow_e2e():
    """
    Verify creating a shortcut via the Chat Settings Modal:
    1. Clicking #open-shortcut-modal-btn opens #shortcut-modal with current session title prefilled.
    2. Entering title & prompt and clicking #activate-shortcut-setup-btn navigates to the shortcut URL
       WITH sessionStorage guard so the message is NOT sent during setup.
    3. Setup banner (#shortcut-setup-banner) is visible, document.title is updated, and exiting setup resets URL.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-100", "title": "Fitness Tracker", "created_at": "2026-11-11T07:00:00Z", "has_icon": False}
        ]
        chat_calls = []

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_state)
        ))
        await page.route("**/api/sessions/models/catalog", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"default_model": "gemini-3.8-flash-medium", "default_effort": "medium", "model_catalog": {}}'
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
        await page.route("**/api/sessions/*/chat", lambda route: (
            chat_calls.append(route.request.url),
            route.fulfill(status=200, content_type="application/json", body='{"reply": "ok"}')
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}/")
        await expect(page.locator("#header-chat-title")).to_have_text("Fitness Tracker")

        # Open chat settings modal
        settings_btn = page.locator("#system-prompt-btn")
        await expect(settings_btn).to_be_enabled()
        await settings_btn.click()
        await expect(page.locator("#system-prompt-modal")).to_be_visible()

        # Click "Homescreen-Shortcut" button
        open_shortcut_btn = page.locator("#open-shortcut-modal-btn")
        await expect(open_shortcut_btn).to_be_visible()
        await open_shortcut_btn.click()

        # Shortcut modal opens, settings modal closes
        await expect(page.locator("#system-prompt-modal")).to_be_hidden()
        shortcut_modal = page.locator("#shortcut-modal")
        await expect(shortcut_modal).to_be_visible()

        # Title input is prefilled with current chat title
        title_input = page.locator("#shortcut-title-input")
        await expect(title_input).to_have_value("Fitness Tracker")

        # Fill custom shortcut name and recurring message
        await title_input.fill("Training erledigt")
        prompt_input = page.locator("#shortcut-prompt-input")
        await prompt_input.fill("Trage 45 Minuten Krafttraining für heute ein.")

        # Activate setup mode
        await page.locator("#activate-shortcut-setup-btn").click()

        # Setup banner must be visible and URL updated with shortcut parameters
        setup_banner = page.locator("#shortcut-setup-banner")
        await expect(setup_banner).to_be_visible()
        await expect(setup_banner).to_contain_text("Training erledigt")
        await expect(setup_banner).to_contain_text("Trage 45 Minuten Krafttraining für heute ein.")
        await expect(page).to_have_title("Training erledigt")
        assert "session=sess-100" in page.url
        assert "autosend=1" in page.url

        # Crucially: no chat message was sent during setup!
        assert len(chat_calls) == 0

        # Click "Fertig" (#exit-shortcut-setup-btn) to exit setup mode
        await page.locator("#exit-shortcut-setup-btn").click()
        await expect(setup_banner).to_be_hidden()
        await expect(page).to_have_url(f"http://127.0.0.1:{SERVER_PORT}/")
        assert len(chat_calls) == 0

        await browser.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_shortcut_persists_across_login_e2e():
    """
    Verify that when a user taps a shortcut while unauthenticated,
    the pending shortcut is preserved across login and automatically executed once logged in.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        is_logged_in = False
        chat_calls = []

        async def auth_status_route(route):
            if is_logged_in:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"authenticated": true, "username": "alice"}'
                )
            else:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"authenticated": false}'
                )

        await page.route("**/api/auth/status", auth_status_route)

        async def login_route(route):
            nonlocal is_logged_in
            is_logged_in = True
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true}'
            )

        await page.route("**/api/auth/login", login_route)

        sessions_state = [
            {"id": "sess-other", "title": "Anderer Chat", "created_at": "2026-11-11T07:00:00Z", "has_icon": False},
            {"id": "sess-after-login", "title": "Tagesjournal", "created_at": "2026-11-10T07:00:00Z", "has_icon": False},
        ]

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_state)
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": false}'
        ))
        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-after-login", "is_processing": false, "queued_count": 0, "is_generating_icon": false, "has_icon": false}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        async def chat_route(route):
            chat_calls.append(route.request.url)
            await route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_build_sse_response("Journal-Eintrag nach Login gespeichert!")
            )

        await page.route("**/api/sessions/*/chat", chat_route)

        shortcut_url = (
            f"http://127.0.0.1:{SERVER_PORT}/?session=sess-after-login"
            f"&prompt={quote('Guten Morgen Eintrag')}&autosend=1"
        )
        await page.goto(shortcut_url)

        # Auth modal must open first
        await expect(page.locator("#auth-modal")).to_be_visible()
        assert len(chat_calls) == 0

        # Log in
        await page.locator("#login-username").fill("alice")
        await page.locator("#login-password").fill("secret123")
        await page.locator("#verify-btn").click()

        # After login, target session must be selected and message automatically sent
        await expect(page.locator("#auth-modal")).to_be_hidden()
        await expect(page.locator("#header-chat-title")).to_have_text("Tagesjournal")
        await expect(page.locator(".user-message")).to_contain_text("Guten Morgen Eintrag")
        await expect(page.locator(".ai-message")).to_contain_text("Journal-Eintrag nach Login gespeichert!")
        assert len(chat_calls) == 1
        assert "/api/sessions/sess-after-login/chat" in chat_calls[0]

        await browser.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_shortcut_nonexistent_session_shows_error_without_sending_e2e():
    """
    Verify that if a shortcut references a deleted or non-existent session_id,
    no message is sent to a wrong session and an error message is shown in the chat.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        sessions_state = [
            {"id": "sess-existing", "title": "Bestehender Chat", "created_at": "2026-11-11T07:00:00Z", "has_icon": False},
        ]
        chat_calls = []

        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_state)
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
        await page.route("**/api/sessions/*/chat", lambda route: (
            chat_calls.append(route.request.url),
            route.fulfill(status=200, content_type="application/json", body='{"reply": "ok"}')
        ))

        await page.goto(
            f"http://127.0.0.1:{SERVER_PORT}/?session=sess-deleted-999&prompt=NichtSenden&autosend=1"
        )

        await expect(page.locator("#header-chat-title")).to_have_text("Bestehender Chat")
        await expect(page.locator(".error-message")).to_be_visible()
        assert len(chat_calls) == 0

        await browser.close()
