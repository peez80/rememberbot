import os
import json
import pytest
import asyncio
import logging
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.core.config import (
    MODEL_CATALOG,
    validate_model_and_effort,
    parse_agy_models_output,
    AGY_DEFAULT_MODEL,
    AGY_DEFAULT_THINKING_EFFORT,
)
from app.models.session import SessionSettingsRequest
from app.services.storage_service import StorageService
from app.services.session_service import SessionService
from app.services.agy_service import AGYService
from app.agy_client import AgyClient
from app.services.chat_service import ChatService
from app.main import validate_agy_default_configuration


EXPECTED_AGY_MODELS = {
    "gemini-4-argon-medium": "Gemini 4 Argon (Medium)",
    "gemini-4-argon-high": "Gemini 4 Argon (High)",
    "gemini-4-argon-low": "Gemini 4 Argon (Low)",
    "gemini-3.8-flash-high": "Gemini 3.8 Flash (High)",
    "gemini-3.8-flash-medium": "Gemini 3.8 Flash (Medium)",
    "gemini-3.8-flash-low": "Gemini 3.8 Flash (Low)",
    "claude-opus-5-5-low": "Claude Opus 5.5 (Low)",
    "claude-opus-5-5-medium": "Claude Opus 5.5 (Medium)",
    "claude-opus-5-5-high": "Claude Opus 5.5 (High)",
    "claude-sonnet-5-5-low": "Claude Sonnet 5.5 (Low)",
    "claude-sonnet-5-5-medium": "Claude Sonnet 5.5 (Medium)",
    "claude-sonnet-5-5-high": "Claude Sonnet 5.5 (High)",
    "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
}


# 1. Tests für den Modell-Katalog und das Parsing von `agy models`
def test_model_catalog_structure():
    assert "default" in MODEL_CATALOG
    for model_id, expected_label in EXPECTED_AGY_MODELS.items():
        assert model_id in MODEL_CATALOG, f"Missing {model_id} in MODEL_CATALOG"
        assert MODEL_CATALOG[model_id]["label"] == expected_label
        assert MODEL_CATALOG[model_id]["supports_thinking"] is False
        assert MODEL_CATALOG[model_id]["allowed_efforts"] == []


def test_parse_agy_models_output():
    raw_stdout = (
        "\r\x1b[K⠋ Fetching available models...\r\x1b[K"
        "gemini-4-argon-medium\tGemini 4 Argon (Medium)\n"
        "gemini-4-argon-high\tGemini 4 Argon (High)\n"
        "claude-sonnet-5-5-low\tClaude Sonnet 5.5 (Low)\n"
        "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
    )
    parsed = parse_agy_models_output(raw_stdout)
    assert "default" in parsed
    assert parsed["gemini-4-argon-medium"]["label"] == "Gemini 4 Argon (Medium)"
    assert parsed["gemini-4-argon-high"]["label"] == "Gemini 4 Argon (High)"
    assert parsed["claude-sonnet-5-5-low"]["label"] == "Claude Sonnet 5.5 (Low)"
    assert parsed["gpt-oss-120b-medium"]["label"] == "GPT-OSS 120B (Medium)"
    assert parsed["gemini-4-argon-high"]["supports_thinking"] is False


@pytest.mark.asyncio
async def test_agy_service_get_model_catalog_dynamic_and_cached(caplog):
    service = AGYService(executable_path="agy")
    sample_stdout = (
        b"gemini-4-argon-medium\tGemini 4 Argon (Medium)\n"
        b"gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"
    )
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(sample_stdout, b"Fetching available models...\n"))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        catalog1 = await service.get_model_catalog(force_refresh=True)
        assert "gemini-4-argon-medium" in catalog1
        assert catalog1["gemini-4-argon-medium"]["label"] == "Gemini 4 Argon (Medium)"
        assert mock_exec.call_count == 1

        # Second call uses cache without spawning another subprocess
        catalog2 = await service.get_model_catalog()
        assert catalog2 == catalog1
        assert mock_exec.call_count == 1

    # Fallback and warning log when agy binary is missing
    service_missing = AGYService(executable_path="nonexistent-agy-bin")
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")):
        with caplog.at_level(logging.WARNING):
            fallback_catalog = await service_missing.get_model_catalog(force_refresh=True)
            assert "default" in fallback_catalog
            assert "gemini-3.8-flash-medium" in fallback_catalog
            assert any("Fallback" in r.message or "nicht gefunden" in r.message for r in caplog.records)


def test_validate_model_and_effort():
    # Valid combinations
    ok, err = validate_model_and_effort(None, None)
    assert ok is True
    assert err is None

    ok, err = validate_model_and_effort("default", None)
    assert ok is True
    assert err is None

    # Valid flat models from agy models
    for model_id in ("gemini-4-argon-high", "gemini-3.8-flash-medium", "claude-sonnet-5-5-low", "gpt-oss-120b-medium"):
        ok, err = validate_model_and_effort(model_id, None)
        assert ok is True
        assert err is None

    # Legacy base model + effort combination resolves cleanly
    ok, err = validate_model_and_effort("gemini-3.8-flash", "high")
    assert ok is True
    assert err is None

    # Conflicting effort with suffixed model ID must be rejected
    ok, err = validate_model_and_effort("gemini-4-argon-high", "low")
    assert ok is False
    assert "low" in err

    # Unknown model
    ok, err = validate_model_and_effort("unknown-model-xyz", None)
    assert ok is False
    assert "unknown-model-xyz" in err


# 2. Test für SessionSettingsRequest Pydantic-Validierung
def test_session_settings_request_model():
    req = SessionSettingsRequest(prompt="Test", include_gps=True, model="gemini-4-argon-high", thinking_effort=None)
    assert req.model == "gemini-4-argon-high"
    assert req.thinking_effort is None


# 3. Tests für Session-Persistenz im SessionService & storage.py
@pytest.mark.asyncio
async def test_session_settings_model_and_effort_persistence(tmp_path):
    data_dir = str(tmp_path / "data")
    storage_svc = StorageService(data_dir=data_dir)
    session_svc = SessionService(storage_service=storage_svc)

    session_id = await session_svc.create_session("alice", "Test Chat")

    # Initial settings (default should be gemini-3.8-flash-medium and thinking_effort None)
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings.get("model") == "gemini-3.8-flash-medium"
    assert settings.get("thinking_effort") is None

    # Update with Gemini 4 Argon (High)
    await session_svc.update_session_settings("alice", session_id, "Prompt", False, model="gemini-4-argon-high", thinking_effort=None)
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "gemini-4-argon-high"
    assert settings["thinking_effort"] is None

    # Update with Claude Sonnet 5.5 (Medium)
    await session_svc.update_session_settings("alice", session_id, "Prompt", False, model="claude-sonnet-5-5-medium", thinking_effort=None)
    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "claude-sonnet-5-5-medium"
    assert settings["thinking_effort"] is None


@pytest.mark.asyncio
async def test_session_settings_legacy_model_fallback(tmp_path):
    data_dir = str(tmp_path / "data")
    storage_svc = StorageService(data_dir=data_dir)
    session_svc = SessionService(storage_service=storage_svc)

    session_id = await session_svc.create_session("alice", "Legacy Chat")
    session_file = tmp_path / "data" / "alice" / "sessions" / session_id / "session.json"

    # Case 1: Legacy base model + effort -> migrates to suffixed model ID
    with open(session_file, "w") as f:
        json.dump({
            "title": "Legacy Chat",
            "prompt": "Old prompt",
            "include_gps": False,
            "model": "gemini-3.8-flash",
            "thinking_effort": "high"
        }, f)

    settings = await session_svc.get_session_settings("alice", session_id)
    assert settings["model"] == "gemini-3.8-flash-high"
    assert settings["thinking_effort"] is None

    # Case 2: Deprecated/unknown model -> falls back to AGY_DEFAULT_MODEL
    with open(session_file, "w") as f:
        json.dump({
            "title": "Legacy Chat",
            "prompt": "Old prompt",
            "include_gps": False,
            "model": "gemini-2.5-pro",
            "thinking_effort": "high"
        }, f)

    settings_fallback = await session_svc.get_session_settings("alice", session_id)
    assert settings_fallback["model"] == "gemini-3.8-flash-medium"
    assert settings_fallback["thinking_effort"] is None


# 4. Tests für AgyClient CLI-Flags (--model ohne redundantes --effort)
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
            [], "Hi", cwd=str(tmp_path), model="gemini-4-argon-high", thinking_effort=None
        )
    ]
    assert len(chunks) > 0
    mock_create.assert_called_once()
    args, _ = mock_create.call_args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "gemini-4-argon-high"
    assert "--effort" not in args


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
            [], "Hi", cwd=str(tmp_path), model="claude-sonnet-5-5-medium", thinking_effort="high"
        )
    ]
    assert len(chunks) > 0
    mock_create.assert_called_once()
    args, _ = mock_create.call_args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5-medium"
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
    with patch("app.main.AGY_DEFAULT_MODEL", "gemini-3.8-flash-medium"), \
         patch("app.main.AGY_DEFAULT_THINKING_EFFORT", "medium"), \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"OK", b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        with caplog.at_level(logging.INFO):
            await validate_agy_default_configuration()

        assert any("Startup-Validierung" in record.message and "erfolgreich" in record.message for record in caplog.records)
        args, _ = mock_exec.call_args
        assert "--model" in args
        assert "gemini-3.8-flash-medium" in args
        assert "--effort" not in args


@pytest.mark.asyncio
async def test_startup_validation_failure_fallback(caplog):
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
    from app.services.agy_service import agy_service

    client = TestClient(app)
    token = "test-token-model"
    auth_service.active_sessions[token] = "testuser"
    client.cookies.set("session_token", token)

    with patch.object(session_service, "check_session_exists", AsyncMock(return_value=True)), \
         patch.object(session_service, "get_session_settings", AsyncMock(return_value={"prompt": "P", "include_gps": False, "model": "gemini-4-argon-high", "thinking_effort": None})), \
         patch.object(session_service, "update_session_settings", AsyncMock(return_value=None)), \
         patch.object(agy_service, "get_model_catalog", AsyncMock(return_value=MODEL_CATALOG)):

        # GET
        resp = client.get("/api/sessions/sess1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "gemini-4-argon-high"
        assert data["thinking_effort"] is None

        # Catalog
        resp_cat = client.get("/api/sessions/models/catalog")
        assert resp_cat.status_code == 200
        cat_json = resp_cat.json()
        assert "model_catalog" in cat_json
        assert "gemini-4-argon-high" in cat_json["model_catalog"]

        # PUT valid
        resp_put = client.put("/api/sessions/sess1/settings", json={
            "prompt": "New",
            "include_gps": True,
            "model": "gemini-4-argon-high",
            "thinking_effort": None
        })
        assert resp_put.status_code == 200
        assert resp_put.json()["success"] is True

        # PUT invalid model
        resp_put_invalid = client.put("/api/sessions/sess1/settings", json={
            "prompt": "New",
            "include_gps": True,
            "model": "non-existent-model-999",
            "thinking_effort": None
        })
        assert resp_put_invalid.status_code == 422
        assert "non-existent-model-999" in resp_put_invalid.json()["detail"]

