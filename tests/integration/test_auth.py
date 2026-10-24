import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.services.auth_service import auth_service

client = TestClient(app)

@patch("app.services.auth_service.auth_service.get_valid_users")
def test_login_success(mock_get_valid_users):
    mock_get_valid_users.return_value = {"alice": "secret123"}
    
    response = client.post("/api/auth/login", data={"username": "alice", "password": "secret123"})
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Check that cookie is set
    assert "session_token" in response.cookies

@patch("app.services.auth_service.auth_service.get_valid_users")
def test_login_failure(mock_get_valid_users):
    mock_get_valid_users.return_value = {"alice": "secret123"}
    
    response = client.post("/api/auth/login", data={"username": "alice", "password": "wrongpassword"})
    assert response.status_code == 401
    assert "session_token" not in response.cookies

@patch("app.services.auth_service.auth_service.active_sessions", {"fake-token-123": "alice"})
def test_status_authenticated():
    client.cookies.set("session_token", "fake-token-123")
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "username": "alice"}
    client.cookies.clear()

def test_status_unauthenticated():
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}

@patch("app.services.auth_service.auth_service.active_sessions", {"fake-token-123": "alice"})
def test_logout():
    client.cookies.set("session_token", "fake-token-123")
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    
    # Check session is removed
    assert response.cookies.get("session_token") is None or response.cookies.get("session_token") == '""' or response.cookies.get("session_token") == ""
    
    # Check next status call
    status_response = client.get("/api/auth/status")
    assert status_response.json() == {"authenticated": False}
    client.cookies.clear()


def test_oauth_login_endpoint_error_handling(caplog):
    from unittest.mock import AsyncMock
    import logging

    mock_oauth_backend = MagicMock()
    mock_oauth_backend.is_oauth = True
    mock_oauth_backend.get_authorization_url = AsyncMock(side_effect=RuntimeError("Discovery DNS lookup failed"))

    with patch.object(auth_service, "backend", mock_oauth_backend):
        with caplog.at_level(logging.ERROR):
            res = client.get("/api/auth/oauth/login", follow_redirects=False)

    assert res.status_code == 500
    assert "OAuth Authorize-URL konnte nicht erstellt werden" in res.json()["detail"]
    assert "Fehler bei Erstellung der OAuth Authorize-URL" in caplog.text


def test_oauth_callback_disabled_returns_400():
    mock_non_oauth_backend = MagicMock()
    mock_non_oauth_backend.is_oauth = False

    with patch.object(auth_service, "backend", mock_non_oauth_backend):
        res = client.get("/api/auth/oauth/callback?code=123&state=abc", follow_redirects=False)
    assert res.status_code == 400
    assert "OAuth ist nicht aktiviert" in res.json()["detail"]


def test_oauth_callback_missing_or_malformed_state_cookie(caplog):
    import logging
    mock_oauth_backend = MagicMock()
    mock_oauth_backend.is_oauth = True

    # 1. Missing cookie
    with patch.object(auth_service, "backend", mock_oauth_backend):
        with caplog.at_level(logging.WARNING):
            res = client.get("/api/auth/oauth/callback?code=123&state=abc", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/?error=state_mismatch"
    assert "OAuth State-Cookie fehlt" in caplog.text

    # 2. Malformed cookie without ':'
    client.cookies.set("oauth_state", "invalid_no_colon_token")
    with patch.object(auth_service, "backend", mock_oauth_backend):
        with caplog.at_level(logging.WARNING):
            res = client.get("/api/auth/oauth/callback?code=123&state=abc", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/?error=state_mismatch"
    client.cookies.clear()

