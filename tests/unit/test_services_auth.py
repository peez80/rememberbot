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
