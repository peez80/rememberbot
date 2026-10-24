import time
import pytest
from app.core.config import is_safe_session_id
from app.services.agy_service import agy_service
from app.services.auth_service import AuthService

def test_vuln07_session_id_rejects_leading_hyphen_or_underscore():
    """Verify that is_safe_session_id strictly rejects IDs starting with '-' or '_' to prevent CLI option injection."""
    # Invalid IDs with leading flags / symbols
    assert is_safe_session_id("-session") is False
    assert is_safe_session_id("--all") is False
    assert is_safe_session_id("-rf") is False
    assert is_safe_session_id("_leading_underscore") is False
    assert is_safe_session_id("-") is False

    # Valid IDs starting with alphanumeric characters
    assert is_safe_session_id("sess123") is True
    assert is_safe_session_id("0a1b2c3d4e5f") is True
    assert is_safe_session_id("chat-session_1") is True
    assert is_safe_session_id("Session-2026") is True

def test_vuln07_conversation_exists_rejects_leading_hyphen():
    """Verify that conversation_exists rejects IDs starting with hyphens or non-alphanumeric characters."""
    assert agy_service.conversation_exists("-conv123") is False
    assert agy_service.conversation_exists("--dangerous-flag") is False
    assert agy_service.conversation_exists("_conv") is False

def test_vuln08_rate_limit_prunes_empty_keys(tmp_path):
    """Verify that AuthService.check_rate_limit removes expired keys from failed_login_attempts to prevent memory leaks."""
    service = AuthService(data_dir=str(tmp_path))
    service.failed_login_attempts.clear()

    client_ip = "192.168.1.100"
    username = "attacker"
    rate_key = f"{client_ip}:{username}"

    # Record old failed attempt (older than 60 seconds)
    old_time = time.time() - 120.0
    service.failed_login_attempts[rate_key] = [old_time]
    service.failed_login_attempts[client_ip] = [old_time]

    assert rate_key in service.failed_login_attempts
    assert client_ip in service.failed_login_attempts

    # Calling check_rate_limit should filter out old attempts and prune the empty keys
    allowed = service.check_rate_limit(client_ip, username)
    assert allowed is True

    # Empty keys must be purged from the dictionary to avoid memory leak
    assert rate_key not in service.failed_login_attempts
    assert client_ip not in service.failed_login_attempts
