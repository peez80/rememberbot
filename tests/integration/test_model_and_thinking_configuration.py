import os
import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.core.config import (
    MODEL_CATALOG,
    validate_model_and_effort,
    AGY_DEFAULT_MODEL,
    AGY_DEFAULT_THINKING_EFFORT,
)
from app.models.session import SessionSettingsRequest
from app.services.storage_service import StorageService
from app.services.session_service import SessionService
from app.agy_client import AgyClient
from app.services.chat_service import ChatService
from app.main import validate_agy_default_configuration


# 1. Tests für den Modell- und Thinking-Katalog (Option B)
def test_model_catalog_structure():
    assert "default" in MODEL_CATALOG
    assert "gemini-3.1-pro" in MODEL_CATALOG
    assert "gemini-3.8-flash" in MODEL_CATALOG
    assert "gemini-3.7-flash" in MODEL_CATALOG
    assert "claude-sonnet-4-6" in MODEL_CATALOG
    assert "claude-opus-4-6-thinking" in MODEL_CATALOG
    assert "gpt-oss-120b-medium" in MODEL_CATALOG

    # Default catalog entry should have low, medium, high efforts and default_effort medium
    assert MODEL_CATALOG["default"]["allowed_efforts"] == ["low", "medium", "high"]
    assert MODEL_CATALOG["default"]["default_effort"] == "medium"

    # Gemini 3.1 Pro only supports low and high (medium is NOT supported by agy)
    assert MODEL_CATALOG["gemini-3.1-pro"]["allowed_efforts"] == ["low", "high"]
    assert MODEL_CATALOG["gemini-3.1-pro"]["supports_thinking"] is True

    # Flash models support low, medium, high
    assert "medium" in MODEL_CATALOG["gemini-3.8-flash"]["allowed_efforts"]
    assert "high" in MODEL_CATALOG["gemini-3.8-flash"]["allowed_efforts"]
    assert MODEL_CATALOG["gemini-3.8-flash"]["supports_thinking"] is True

    # Claude and GPT models do not support --effort
    assert MODEL_CATALOG["claude-sonnet-4-6"]["supports_thinking"] is False
    assert MODEL_CATALOG["claude-sonnet-4-6"]["allowed_efforts"] == []
    assert MODEL_CATALOG["gpt-oss-120b-medium"]["supports_thinking"] is False


def test_validate_model_and_effort():
    # Valid combinations
    ok, err = validate_model_and_effort(None, None)
    assert ok is True
    assert err is None

    # Gemini 3.1 Pro: low and high are valid, medium is invalid
    ok, err = validate_model_and_effort("gemini-3.1-pro", "high")
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("gemini-3.1-pro", "low")
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("gemini-3.1-pro", "medium")
    assert ok is False
    assert "medium" in err

    # Gemini 3.8 Flash: low, medium, high are valid
    ok, err = validate_model_and_effort("gemini-3.8-flash", "high")
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("gemini-3.8-flash", "medium")
    assert ok is True
    assert err is None

    # Claude: thinking effort must be None or empty
    ok, err = validate_model_and_effort("claude-sonnet-4-6", None)
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("claude-sonnet-4-6", "")
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("claude-sonnet-4-6", "high")
    assert ok is False
    assert "keine manuelle Thinking-Effort" in err

    # Unknown model
    ok, err = validate_model_and_effort("unknown-model-xyz", "low")
    assert ok is False
    assert "unknown-model-xyz" in err


# 2. Test für SessionSettingsRequest Pydantic-Validierung
def test_session_settings_request_model():
    req = SessionSettingsRequest(prompt="Test", include_gps=True, model="gemini-3.8-flash", thinking_effort="medium")
    assert req.model == "gemini-3.8-flash"
    assert req.thinking_effort == "medium"


# 3. Tests für Session-Persistenz im SessionService & storage.py
@pytest.mark.asyncio
async def test_session_settings_model_and_effort_persistence(tmp_path):
    data_dir = str(tmp_path / "data")
    storage_svc = StorageService(data_dir=data_dir)
    session_svc = SessionService(storage_service=storage_svc)

    session_id = await session_svc.create_session("alice", "Test Chat")

    # Initial settings (defaults should be gemini-3.8-flash and medium)
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings.get("model") == "gemini-3.8-flash"
    assert settings.get("thinking_effort") == "medium"

    # Update with Pro and high effort
    await session_svc.update_session_settings("alice", session_id, "Prompt", False, model="gemini-3.1-pro", thinking_effort="high")
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "gemini-3.1-pro"
    assert settings["thinking_effort"] == "high"

    # Update with Claude (no effort)
    await session_svc.update_session_settings("alice", session_id, "Prompt", False, model="claude-sonnet-4-6", thinking_effort=None)
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "claude-sonnet-4-6"
    assert settings["thinking_effort"] is None


@pytest.mark.asyncio
async def test_session_settings_legacy_model_fallback(tmp_path):
    # If settings.json contains a deprecated/unknown model like 'gemini-2.5-pro'
    data_dir = str(tmp_path / "data")
    storage_svc = StorageService(data_dir=data_dir)
    session_svc = SessionService(storage_service=storage_svc)

    session_id = await session_svc.create_session("alice", "Legacy Chat")
    settings_file = tmp_path / "data" / "alice" / "sessions" / session_id / "settings.json"
    settings_data = {
        "prompt": "Old prompt",
        "include_gps": False,
        "model": "gemini-2.5-pro",
        "thinking_effort": "high"
    }
    with open(settings_file, "w") as f:
        json.dump(settings_data, f)

    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "gemini-3.8-flash"
    assert settings["thinking_effort"] == "medium"


# 4. Tests für AgyClient CLI-Flags (--model und --effort)
@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_agy_client_passes_model_and_effort_flags(mock_create, tmp_path):
    client = AgyClient()
    mock_proc = MagicMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[
        b'{"event":"result","result":{"response":"Hello"}}\n',
        b''
    ])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0
    mock_create.return_value = mock_proc

    chunks = [
        c async for c in client.stream_message(
            [], "Hi", cwd=str(tmp_path), model="gemini-3.1-pro", thinking_effort="high"
        )
    ]
    assert len(chunks) > 0
    mock_create.assert_called_once()
    args, _ = mock_create.call_args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "gemini-3.1-pro"
    assert "--effort" in args
    assert args[args.index("--effort") + 1] == "high"


@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_agy_client_omits_effort_for_non_thinking_models(mock_create, tmp_path):
    client = AgyClient()
    mock_proc = MagicMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[
        b'{"event":"result","result":{"response":"Hello"}}\n',
        b''
    ])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0
    mock_create.return_value = mock_proc

    chunks = [
        c async for c in client.stream_message(
            [], "Hi", cwd=str(tmp_path), model="claude-sonnet-4-6", thinking_effort=None
        )
    ]
    assert len(chunks) > 0
    mock_create.assert_called_once()
    args, _ = mock_create.call_args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--effort" not in args


@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_agy_client_omits_flags_when_default_or_none(mock_create, tmp_path):
    client = AgyClient()
    mock_proc = MagicMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=[
        b'{"event":"result","result":{"response":"Hello"}}\n',
        b''
    ])
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0
    mock_create.return_value = mock_proc

    chunks = [
        c async for c in client.stream_message(
            [], "Hi", cwd=str(tmp_path), model=None, thinking_effort=None
        )
    ]
    assert len(chunks) > 0
    mock_create.assert_called_once()
    args, _ = mock_create.call_args
    assert "--model" not in args
    assert "--effort" not in args


# 5. Tests für Startup-Validierung mit caplog
@pytest.mark.asyncio
async def test_startup_validation_success(caplog):
    import logging

    with patch("app.main.AGY_DEFAULT_MODEL", "gemini-3.1-pro"), \
         patch("app.main.AGY_DEFAULT_THINKING_EFFORT", "high"), \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"OK", b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        with caplog.at_level(logging.INFO):
            await validate_agy_default_configuration()

        assert any("Startup-Validierung" in record.message and "erfolgreich" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_startup_validation_failure_fallback(caplog):
    import logging

    with patch("app.main.AGY_DEFAULT_MODEL", "gemini-invalid"), \
         patch("app.main.AGY_DEFAULT_THINKING_EFFORT", "extreme"), \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: unsupported model"))
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        with caplog.at_level(logging.WARNING):
            await validate_agy_default_configuration()

        assert any("Startup-Validierung" in record.message and "fehlgeschlagen" in record.message for record in caplog.records)


# 6. Tests für API-Endpoints (GET und PUT Settings)
def test_api_get_and_put_settings():
    from app.main import app
    from app.services.auth_service import auth_service
    from app.services.session_service import session_service

    client = TestClient(app)
    # Auth cookie
    token = "test-token-model"
    auth_service.active_sessions[token] = "testuser"
    client.cookies.set("session_token", token)

    with patch.object(session_service, "check_session_exists", AsyncMock(return_value=True)), \
         patch.object(session_service, "get_session_settings", AsyncMock(return_value={"prompt": "P", "include_gps": False, "model": "gemini-3.1-pro", "thinking_effort": "high"})), \
         patch.object(session_service, "update_session_settings", AsyncMock(return_value=None)):

        # GET
        resp = client.get("/api/sessions/sess1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "gemini-3.1-pro"
        assert data["thinking_effort"] == "high"

        # Catalog
        resp_cat = client.get("/api/sessions/models/catalog")
        assert resp_cat.status_code == 200
        assert "model_catalog" in resp_cat.json()

        # PUT valid
        resp_put = client.put("/api/sessions/sess1/settings", json={
            "prompt": "New",
            "include_gps": True,
            "model": "gemini-3.1-pro",
            "thinking_effort": "low"
        })
        assert resp_put.status_code == 200
        assert resp_put.json()["success"] is True

        # PUT invalid effort (gemini-3.1-pro with medium, which agy disallows)
        resp_put_invalid = client.put("/api/sessions/sess1/settings", json={
            "prompt": "New",
            "include_gps": True,
            "model": "gemini-3.1-pro",
            "thinking_effort": "medium"
        })
        assert resp_put_invalid.status_code == 422
        assert "medium" in resp_put_invalid.json()["detail"]
