import time
import pytest
from app.services.auth_service import AuthService

@pytest.fixture
def auth_service(tmp_path):
    data_dir = str(tmp_path / "data")
    service = AuthService(data_dir=data_dir)
    return service

def test_auth_service_users_config(tmp_path):
    data_dir = str(tmp_path / "data")
    service = AuthService(data_dir=data_dir)
    
    # Empty config when file doesn't exist
    assert service.get_valid_users() == {}
    
    # Save users
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "users.json").write_text('{"alice": "secret123", "bob": "pw456"}')
    
    users = service.get_valid_users()
    assert users == {"alice": "secret123", "bob": "pw456"}

def test_auth_service_authenticate(tmp_path):
    data_dir = str(tmp_path / "data")
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "users.json").write_text('{"alice": "secret123"}')
    
    service = AuthService(data_dir=data_dir)
    
    assert service.authenticate("alice", "secret123") is True
    assert service.authenticate("alice", "wrong") is False
    assert service.authenticate("unknown", "secret123") is False

def test_auth_service_rate_limiting(auth_service):
    # Should allow 4 attempts
    for _ in range(4):
        assert auth_service.check_rate_limit("127.0.0.1", "alice") is True
        auth_service.record_failed_attempt("127.0.0.1", "alice")
        
    # 5th attempt is recorded
    auth_service.record_failed_attempt("127.0.0.1", "alice")
    # Now rate limit should be reached
    assert auth_service.check_rate_limit("127.0.0.1", "alice") is False

def test_auth_service_session_tokens(auth_service):
    token = auth_service.create_session("alice")
    assert token is not None
    assert auth_service.verify_session(token) == "alice"
    
    auth_service.invalidate_session(token)
    assert auth_service.verify_session(token) is None


def test_auth_service_backend_injection():
    class DummyBackend:
        backend_name = "dummy"
        def authenticate(self, username, password):
            return username == "testuser" and password == "testpass"
        def user_exists(self, username):
            return username == "testuser"
        def get_valid_users(self):
            return {"testuser": "testpass"}

    dummy = DummyBackend()
    service = AuthService(backend=dummy)
    assert service.authenticate("testuser", "testpass") is True
    assert service.authenticate("testuser", "wrong") is False
    assert service.get_valid_users() == {"testuser": "testpass"}


def test_auth_service_load_sessions_valid_and_expired(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sessions_file = data_dir / "auth_sessions.json"

    now = time.time()
    sessions_file.write_text(
        f'{{"valid_tok": {{"username": "alice", "expires_at": {now + 1000}}}, '
        f'"expired_tok": {{"username": "bob", "expires_at": {now - 100}}}, '
        f'"legacy_tok": "charlie"}}'
    )

    service = AuthService(data_dir=str(data_dir))
    assert service.verify_session("valid_tok") == "alice"
    assert service.verify_session("expired_tok") is None
    assert service.verify_session("legacy_tok") == "charlie"


def test_auth_service_load_sessions_corrupted_json(tmp_path, caplog):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sessions_file = data_dir / "auth_sessions.json"
    sessions_file.write_text("NOT_VALID_JSON{{{")

    import logging
    with caplog.at_level(logging.WARNING, logger="app.services.auth_service"):
        service = AuthService(data_dir=str(data_dir))

    assert "Failed to load auth sessions" in caplog.text
    assert service.active_sessions == {}


def test_auth_service_save_sessions_io_error(tmp_path, caplog, monkeypatch):
    data_dir = str(tmp_path / "data")
    service = AuthService(data_dir=data_dir)

    import logging
    def mock_atomic_write(*args, **kwargs):
        raise OSError("Disk write failed")

    monkeypatch.setattr("app.storage.atomic_write_json", mock_atomic_write)

    with caplog.at_level(logging.ERROR, logger="app.services.auth_service"):
        service.create_session("alice")

    assert "Failed to save auth sessions" in caplog.text


def test_auth_service_rate_limit_prunes_empty_keys(tmp_path):
    service = AuthService(data_dir=str(tmp_path))
    service.failed_login_attempts.clear()

    client_ip = "192.168.1.100"
    username = "attacker"
    rate_key = f"{client_ip}:{username}"

    old_time = time.time() - 120.0
    service.failed_login_attempts[rate_key] = [old_time]
    service.failed_login_attempts[client_ip] = [old_time]

    assert rate_key in service.failed_login_attempts
    assert client_ip in service.failed_login_attempts

    allowed = service.check_rate_limit(client_ip, username)
    assert allowed is True

    assert rate_key not in service.failed_login_attempts
    assert client_ip not in service.failed_login_attempts

