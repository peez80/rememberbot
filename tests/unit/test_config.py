import os
import logging
import pytest
from app.core import config

def test_get_env_str(monkeypatch):
    monkeypatch.setenv("TEST_STR_VAR", "  hello world  ")
    assert config.get_env_str("TEST_STR_VAR", "default") == "hello world"

    monkeypatch.delenv("TEST_STR_VAR", raising=False)
    assert config.get_env_str("TEST_STR_VAR", "default") == "default"


def test_get_env_int(monkeypatch, caplog):
    monkeypatch.setenv("TEST_INT_VAR", "42")
    assert config.get_env_int("TEST_INT_VAR", 10) == 42

    monkeypatch.delenv("TEST_INT_VAR", raising=False)
    assert config.get_env_int("TEST_INT_VAR", 10) == 10

    # Invalid int should log warning and return default
    with caplog.at_level(logging.WARNING):
        monkeypatch.setenv("TEST_INT_VAR", "not-a-number")
        assert config.get_env_int("TEST_INT_VAR", 10) == 10
        assert "Ungültiger Integer-Wert" in caplog.text or "not-a-number" in caplog.text


def test_get_env_float(monkeypatch, caplog):
    monkeypatch.setenv("TEST_FLOAT_VAR", "3.14")
    assert config.get_env_float("TEST_FLOAT_VAR", 1.0) == 3.14

    monkeypatch.delenv("TEST_FLOAT_VAR", raising=False)
    assert config.get_env_float("TEST_FLOAT_VAR", 1.0) == 1.0

    # Invalid float should log warning and return default
    with caplog.at_level(logging.WARNING):
        monkeypatch.setenv("TEST_FLOAT_VAR", "invalid-float")
        assert config.get_env_float("TEST_FLOAT_VAR", 1.0) == 1.0
        assert "Ungültiger Float-Wert" in caplog.text or "invalid-float" in caplog.text


def test_get_env_bool(monkeypatch, caplog):
    for truthy in ("true", "1", "yes", "on", "TRUE", "True"):
        monkeypatch.setenv("TEST_BOOL_VAR", truthy)
        assert config.get_env_bool("TEST_BOOL_VAR", False) is True

    for falsy in ("false", "0", "no", "off", "FALSE", "False"):
        monkeypatch.setenv("TEST_BOOL_VAR", falsy)
        assert config.get_env_bool("TEST_BOOL_VAR", True) is False

    monkeypatch.delenv("TEST_BOOL_VAR", raising=False)
    assert config.get_env_bool("TEST_BOOL_VAR", True) is True

    # Invalid bool should log warning and return default
    with caplog.at_level(logging.WARNING):
        monkeypatch.setenv("TEST_BOOL_VAR", "maybe")
        assert config.get_env_bool("TEST_BOOL_VAR", True) is True
        assert "Ungültiger Boolean-Wert" in caplog.text or "maybe" in caplog.text


def test_get_env_list(monkeypatch):
    monkeypatch.setenv("TEST_LIST_VAR", "http://a.com, http://b.com,http://c.com")
    assert config.get_env_list("TEST_LIST_VAR", ["default"]) == ["http://a.com", "http://b.com", "http://c.com"]

    monkeypatch.delenv("TEST_LIST_VAR", raising=False)
    assert config.get_env_list("TEST_LIST_VAR", ["default"]) == ["default"]

    # Empty string should return default
    monkeypatch.setenv("TEST_LIST_VAR", "   ")
    assert config.get_env_list("TEST_LIST_VAR", ["default"]) == ["default"]


def test_default_config_constants():
    # Verify standard values are present and correctly typed
    assert config.USER_BACKEND == "json"
    assert config.USERS_FILE_PATH is None or isinstance(config.USERS_FILE_PATH, str)
    assert config.SESSION_COOKIE_NAME == "session_token"
    assert config.SESSION_MAX_AGE_SECONDS == 2592000
    assert config.COOKIE_SECURE is False or isinstance(config.COOKIE_SECURE, bool)
    assert config.MAX_LOGIN_ATTEMPTS == 5
    assert config.LOGIN_RATE_WINDOW_SECONDS == 60
    assert config.MAX_UPLOADS_PER_MESSAGE == 10
    assert config.MAX_UPLOAD_FILE_SIZE == 25 * 1024 * 1024
    assert config.MAX_ZIP_UPLOAD_SIZE == 500 * 1024 * 1024
    assert config.MAX_ZIP_FILES_COUNT == 1000
    assert config.MAX_ZIP_UNCOMPRESSED_BYTES == 1000 * 1024 * 1024
    assert config.THUMBNAIL_MAX_DIMENSION == 400
    assert config.AGY_EXECUTABLE_PATH == "agy"
    assert "conversations" in config.AGY_CONVERSATIONS_DIR
    assert isinstance(config.CORS_ALLOWED_ORIGINS, list)
    assert "http://localhost:8000" in config.CORS_ALLOWED_ORIGINS
