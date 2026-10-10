import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect
from app.services.auth_service import auth_service
from app.services.user_backends.oauth_backend import OAuthUserBackend
from app.services.oauth.client import OAuthClient
from tests.mocks.mock_oauth_server import MockOAuthTransport

SERVER_PORT = 8049

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


@pytest.fixture
def mock_oauth_env(tmp_path):
    orig_backend = auth_service.backend
    data_dir = str(tmp_path / "data")
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        client_id="client-e2e",
        client_secret="secret-e2e",
    )
    oauth_client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="client-e2e",
        client_secret="secret-e2e",
        provider_name="Nextcloud",
        transport=transport
    )
    backend = OAuthUserBackend(data_dir=data_dir, client=oauth_client)
    auth_service.backend = backend
    yield backend
    auth_service.backend = orig_backend


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_oauth_login_modal_display_e2e(mock_oauth_env):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Navigate to app
        await page.goto(f"http://127.0.0.1:{SERVER_PORT}/")

        # 1. Auth modal should be visible
        modal = page.locator("#auth-modal")
        await expect(modal).to_be_visible()

        # 2. Password form must be hidden in OAuth mode
        form = page.locator("#auth-form")
        await expect(form).to_be_hidden()

        # 3. OAuth button container must be visible
        btn_container = page.locator("#oauth-login-container")
        await expect(btn_container).to_be_visible()

        # 4. OAuth button should have the provider text
        btn = page.locator("#oauth-login-btn")
        await expect(btn).to_be_visible()
        await expect(btn).to_contain_text("Mit Nextcloud anmelden")

        await browser.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_oauth_error_banner_and_url_cleanup_e2e(mock_oauth_env):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Navigate with error query param
        await page.goto(f"http://127.0.0.1:{SERVER_PORT}/?error=state_mismatch")

        # Error banner should be visible
        error_banner = page.locator("#auth-error-banner")
        await expect(error_banner).to_be_visible()
        await expect(error_banner).to_contain_text("Sicherheitsfehler")

        # URL query parameter should have been cleaned by history.replaceState
        await expect(page).to_have_url(f"http://127.0.0.1:{SERVER_PORT}/")

        await browser.close()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_oauth_login_modal_display_after_logout_e2e(mock_oauth_env):
    session_token = auth_service.create_session("alice")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.add_cookies([
                {
                    "name": "session_token",
                    "value": session_token,
                    "domain": "127.0.0.1",
                    "path": "/"
                }
            ])
            page = await context.new_page()

            # Handle confirm dialog on logout
            page.on("dialog", lambda dialog: dialog.accept())

            # Navigate to app (user is authenticated)
            await page.goto(f"http://127.0.0.1:{SERVER_PORT}/")

            # Modal must be hidden initially
            modal = page.locator("#auth-modal")
            await expect(modal).to_be_hidden()

            # User clicks logout
            logout_btn = page.locator("#logout-btn")
            await expect(logout_btn).to_be_visible()
            await logout_btn.click()

            # Auth modal must appear
            await expect(modal).to_be_visible()

            # Form must be hidden and SSO button must be visible immediately (without page reload)
            form = page.locator("#auth-form")
            await expect(form).to_be_hidden()

            btn_container = page.locator("#oauth-login-container")
            await expect(btn_container).to_be_visible()

            btn = page.locator("#oauth-login-btn")
            await expect(btn).to_be_visible()
            await expect(btn).to_contain_text("Mit Nextcloud anmelden")

            await browser.close()
    finally:
        auth_service.invalidate_session(session_token)
