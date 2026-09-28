import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app

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
