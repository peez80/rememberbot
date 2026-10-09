import os
import json
import logging
import pytest
from app.services.user_backends.base import BaseUserBackend
from app.services.user_backends.json_backend import JsonUserBackend
from app.services.user_backends.factory import get_user_backend, validate_user_backend

def test_base_user_backend_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseUserBackend()


def test_json_user_backend_authentication(tmp_path):
    data_dir = str(tmp_path / "data")
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    users_file = config_dir / "users.json"
    users_file.write_text(json.dumps({"alice": "secret123", "bob": "pw456"}), encoding="utf-8")

    backend = JsonUserBackend(data_dir=data_dir)
    assert backend.backend_name == "json"
    assert backend.user_exists("alice") is True
    assert backend.user_exists("unknown") is False

    # Valid credentials
    assert backend.authenticate("alice", "secret123") is True
    assert backend.authenticate("bob", "pw456") is True

    # Invalid credentials
    assert backend.authenticate("alice", "wrongpw") is False
    assert backend.authenticate("unknown", "secret123") is False

    # Valid users dict
    assert backend.get_valid_users() == {"alice": "secret123", "bob": "pw456"}


def test_json_user_backend_missing_and_corrupt_file(tmp_path, caplog):
    data_dir = str(tmp_path / "data")
    backend = JsonUserBackend(data_dir=data_dir)

    # Missing file returns empty dict
    assert backend.get_valid_users() == {}
    assert backend.authenticate("alice", "secret123") is False

    # Corrupt JSON file logs error with traceback and returns empty dict
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    corrupt_file = config_dir / "users.json"
    corrupt_file.write_text("{invalid json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        users = backend.get_valid_users()
        assert users == {}
        assert "Failed to read users config" in caplog.text


def test_json_user_backend_custom_users_file(tmp_path):
    custom_file = tmp_path / "custom" / "my_users.json"
    custom_file.parent.mkdir(parents=True, exist_ok=True)
    custom_file.write_text(json.dumps({"charlie": "custom_pass"}), encoding="utf-8")

    backend = JsonUserBackend(users_file_path=str(custom_file))
    assert backend.authenticate("charlie", "custom_pass") is True
    assert backend.user_exists("charlie") is True


def test_factory_get_user_backend(tmp_path):
    data_dir = str(tmp_path / "data")

    # "json"
    backend_json = get_user_backend("json", data_dir=data_dir)
    assert isinstance(backend_json, JsonUserBackend)

    # "file" alias
    backend_file = get_user_backend("file", data_dir=data_dir)
    assert isinstance(backend_file, JsonUserBackend)

    # Case-insensitive
    backend_case = get_user_backend("JSON", data_dir=data_dir)
    assert isinstance(backend_case, JsonUserBackend)

    # Invalid backend raises ValueError
    with pytest.raises(ValueError) as exc_info:
        get_user_backend("ldap")
    assert "Unbekanntes Benutzerbackend 'ldap'" in str(exc_info.value) or "Unsupported" in str(exc_info.value)


def test_validate_user_backend():
    assert validate_user_backend("json") == "json"
    assert validate_user_backend("file") == "file"
    assert validate_user_backend("JSON") == "json"

    with pytest.raises(ValueError) as exc_info:
        validate_user_backend("unknown_backend")
    assert "unknown_backend" in str(exc_info.value)
