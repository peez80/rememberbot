import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)

def test_login_with_json_backend_integration(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "users.json").write_text('{"alice": "secret123"}', encoding="utf-8")

    from app.services.user_backends.json_backend import JsonUserBackend
    from app.services.auth_service import auth_service

    auth_service.failed_login_attempts.clear()
    orig_backend = auth_service.backend
    custom_backend = JsonUserBackend(data_dir=data_dir)
    auth_service.backend = custom_backend

    try:
        # Successful login
        res = client.post("/api/auth/login", data={"username": "alice", "password": "secret123"})
        assert res.status_code == 200
        assert res.json() == {"success": True}
        assert "session_token" in res.cookies

        # Failed login
        res_bad = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
        assert res_bad.status_code == 401
    finally:
        auth_service.backend = orig_backend
        auth_service.failed_login_attempts.clear()


def test_invalid_user_backend_validation_raises():
    from app.services.user_backends.factory import validate_user_backend
    with pytest.raises(ValueError) as exc:
        validate_user_backend("invalid_test_backend")
    assert "invalid_test_backend" in str(exc.value)
