import pytest
import re
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth_service import auth_service
from app.services.user_backends.oauth_backend import OAuthUserBackend
from app.services.oauth.client import OAuthClient
from tests.mocks.mock_oauth_server import MockOAuthTransport

client = TestClient(app, follow_redirects=False)

@pytest.fixture
def setup_oauth_backend(tmp_path):
    from app.services.storage_service import storage_service
    orig_backend = auth_service.backend
    data_dir = str(tmp_path / "data")
    storage_service.data_dir = data_dir
    transport = MockOAuthTransport(
        issuer_url="https://idp.example.com",
        client_id="client-id-123",
        client_secret="client-secret-456",
        valid_code="valid-code-777",
        valid_token="token-abc-999",
        user_claims={
            "preferred_username": "bob",
            "sub": "user_id_bob",
            "email": "bob@example.com"
        }
    )
    oauth_client = OAuthClient(
        issuer_url="https://idp.example.com",
        client_id="client-id-123",
        client_secret="client-secret-456",
        provider_name="Nextcloud",
        transport=transport
    )
    backend = OAuthUserBackend(data_dir=data_dir, client=oauth_client)
    auth_service.backend = backend
    yield backend, transport, data_dir
    auth_service.backend = orig_backend
    del storage_service.data_dir


def test_auth_status_reports_oauth_configured(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is False
    assert data["oauth_configured"] is True
    assert data["provider_name"] == "Nextcloud"


def test_auth_status_reports_oauth_configured_when_authenticated(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    session_token = auth_service.create_session("bob")
    client.cookies.set("session_token", session_token)
    try:
        res = client.get("/api/auth/status")
        assert res.status_code == 200
        data = res.json()
        assert data["authenticated"] is True
        assert data["username"] == "bob"
        assert data["oauth_configured"] is True
        assert data["provider_name"] == "Nextcloud"
    finally:
        client.cookies.clear()
        auth_service.invalidate_session(session_token)


def test_oauth_login_initiates_redirect_and_sets_cookie(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    res = client.get("/api/auth/oauth/login")
    assert res.status_code == 302
    assert "oauth_state" in res.cookies

    location = res.headers.get("location", "")
    assert "https://idp.example.com/oauth/authorize" in location
    assert "response_type=code" in location
    assert "client_id=client-id-123" in location
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
    assert "state=" in location


def test_oauth_callback_successful_flow(setup_oauth_backend):
    backend, transport, data_dir = setup_oauth_backend
    # 1. Step: Start login to get cookie and state
    res_login = client.get("/api/auth/oauth/login")
    state_cookie = res_login.cookies.get("oauth_state")
    location = res_login.headers.get("location")
    
    # Extract state from redirect URL
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(location).query)
    returned_state = qs["state"][0]

    # Set expected PKCE challenge on transport for validation
    code_challenge = qs.get("code_challenge", [""])[0]
    transport.set_expected_pkce(code_challenge)

    # 2. Step: Provider redirects back to callback with code & state
    callback_client = TestClient(app, follow_redirects=False)
    callback_client.cookies.set("oauth_state", state_cookie)

    res_cb = callback_client.get(f"/api/auth/oauth/callback?code=valid-code-777&state={returned_state}")
    assert res_cb.status_code == 302
    assert res_cb.headers.get("location") == "/"
    assert "session_token" in res_cb.cookies

    # Check that oauth_state cookie is deleted
    cb_cookie = res_cb.cookies.get("oauth_state")
    assert cb_cookie is None or cb_cookie == '""' or cb_cookie == ""

    # Verify session is valid and user storage initialized
    status_res = callback_client.get("/api/auth/status")
    data = status_res.json()
    assert data["authenticated"] is True
    assert data["username"] == "bob"
    assert data["oauth_configured"] is True
    assert data["provider_name"] == "Nextcloud"

    import os
    assert os.path.exists(os.path.join(data_dir, "bob"))


def test_oauth_callback_csrf_state_mismatch(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    res_login = client.get("/api/auth/oauth/login")
    state_cookie = res_login.cookies.get("oauth_state")

    test_c = TestClient(app, follow_redirects=False)
    test_c.cookies.set("oauth_state", state_cookie)

    # Calling callback with manipulated state
    res_cb = test_c.get("/api/auth/oauth/callback?code=valid-code-777&state=evil-hacked-state")
    assert res_cb.status_code == 302
    assert "error=state_mismatch" in res_cb.headers.get("location", "")
    assert "session_token" not in res_cb.cookies


def test_oauth_callback_missing_state_or_code(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    test_c = TestClient(app, follow_redirects=False)
    
    # Missing code
    res1 = test_c.get("/api/auth/oauth/callback?state=xyz")
    assert res1.status_code == 302
    assert "error=invalid_request" in res1.headers.get("location", "")

    # Missing state
    res2 = test_c.get("/api/auth/oauth/callback?code=xyz")
    assert res2.status_code == 302
    assert "error=invalid_request" in res2.headers.get("location", "")


def test_oauth_callback_provider_error(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    test_c = TestClient(app, follow_redirects=False)

    res = test_c.get("/api/auth/oauth/callback?error=access_denied&error_description=User+denied+access")
    assert res.status_code == 302
    assert "error=oauth_access_denied" in res.headers.get("location", "")


def test_oauth_callback_token_exchange_failure(setup_oauth_backend):
    backend, transport, _ = setup_oauth_backend
    transport.simulate_token_status_code = 500

    res_login = client.get("/api/auth/oauth/login")
    state_cookie = res_login.cookies.get("oauth_state")
    from urllib.parse import parse_qs, urlparse
    returned_state = parse_qs(urlparse(res_login.headers.get("location")).query)["state"][0]

    test_c = TestClient(app, follow_redirects=False)
    test_c.cookies.set("oauth_state", state_cookie)

    res_cb = test_c.get(f"/api/auth/oauth/callback?code=some-code&state={returned_state}")
    assert res_cb.status_code == 302
    assert "error=oauth_failed" in res_cb.headers.get("location", "")
    assert "session_token" not in res_cb.cookies


def test_password_login_disabled_when_oauth_backend_active(setup_oauth_backend):
    res = client.post("/api/auth/login", data={"username": "bob", "password": "any"})
    assert res.status_code in (400, 401)
    assert "session_token" not in res.cookies


def test_oauth_disabled_when_json_backend_active():
    from app.services.user_backends.json_backend import JsonUserBackend
    orig_backend = auth_service.backend
    auth_service.backend = JsonUserBackend()
    try:
        res = client.get("/api/auth/oauth/login")
        assert res.status_code == 400
        assert "OAuth ist nicht aktiviert" in res.json().get("detail", "")
    finally:
        auth_service.backend = orig_backend
