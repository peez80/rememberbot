import io
import json
import logging
import os
import re
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.logging_config import setup_logging, JsonFormatter
from app.main import app, fire_and_forget, get_current_user
from app.storage import (
    get_sessions, get_session_history, save_session_message,
    update_session_title, delete_session, get_session_settings,
    update_session_settings, DATA_DIR
)
from app.agy_client import agy_client


def test_setup_logging_text_format(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_FORMAT", "text")

    setup_logging()

    root_logger = logging.getLogger()
    assert root_logger.level == logging.INFO
    assert len(root_logger.handlers) >= 1

    handler = root_logger.handlers[0]
    formatter = handler.formatter
    assert formatter is not None

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="/app/app/main.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None
    )
    formatted = formatter.format(record)
    
    # Pattern: YYYY-MM-DD HH:MM:SS [INFO   ] test_logger (main.py:42) - Test message
    pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\s*\] test_logger \(main\.py:42\) - Test message$"
    assert re.match(pattern, formatted), f"Formatted string '{formatted}' did not match pattern '{pattern}'"


def test_setup_logging_json_format(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "json")

    setup_logging()

    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) >= 1

    handler = root_logger.handlers[0]
    formatter = handler.formatter
    assert isinstance(formatter, JsonFormatter)

    record = logging.LogRecord(
        name="test_json_logger",
        level=logging.DEBUG,
        pathname="/app/app/agy_client.py",
        lineno=105,
        msg="Agy process started",
        args=(),
        exc_info=None
    )
    formatted = formatter.format(record)
    
    data = json.loads(formatted)
    assert data["level"] == "DEBUG"
    assert data["logger"] == "test_json_logger"
    assert data["file"] == "agy_client.py"
    assert data["line"] == 105
    assert data["message"] == "Agy process started"
    assert "timestamp" in data


def test_setup_logging_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_FORMAT", "text")

    setup_logging()

    root_logger = logging.getLogger()
    assert root_logger.level == logging.WARNING


# --- Phase 1 (Red): Error & Observability Tests ---

def test_global_exception_handler_logging(caplog):
    """Verify that unhandled exceptions produce HTTP 500 and a logger.error entry with traceback."""
    test_app_client = TestClient(app, raise_server_exceptions=False)
    
    # Add a temporary test endpoint that raises an unexpected exception
    @app.get("/api/test-crash")
    async def crash_endpoint():
        raise RuntimeError("Simulated unhandled server crash")
        
    with caplog.at_level(logging.ERROR):
        response = test_app_client.get("/api/test-crash")
        assert response.status_code == 500
        assert any(
            ("Unhandled exception on GET /api/test-crash" in record.message or "Simulated unhandled server crash" in record.message)
            for record in caplog.records if record.levelno >= logging.ERROR
        )


def test_validation_error_logging(caplog):
    """Verify that Pydantic request validation errors produce HTTP 422 and a logger.warning entry."""
    app.dependency_overrides[get_current_user] = lambda: "testuser"
    try:
        test_app_client = TestClient(app)
        with patch("app.main.check_session_exists", return_value=True):
            with caplog.at_level(logging.WARNING):
                # Send an invalid payload where include_gps is a string that cannot be cast or wrong schema
                response = test_app_client.put(
                    "/api/sessions/sess-123/settings",
                    json={"prompt": 12345, "include_gps": "invalid_boolean_type"}
                )
                assert response.status_code == 422
                assert any(
                    "Validation error on PUT /api/sessions/sess-123/settings" in record.message
                    for record in caplog.records if record.levelno >= logging.WARNING
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_http_exception_handler_logging(caplog):
    """Verify that 4xx HTTP exceptions are logged at WARNING level."""
    test_app_client = TestClient(app)
    with caplog.at_level(logging.WARNING):
        response = test_app_client.get("/api/sessions/unknown-id/history")
        assert response.status_code == 401
        assert any(
            ("HTTP 401" in record.message or "Unauthorized" in record.message or "Not authenticated" in record.message)
            for record in caplog.records if record.levelno >= logging.WARNING
        )


@pytest.mark.asyncio
async def test_fire_and_forget_exception_logging(caplog):
    """Verify that unhandled exceptions in background fire_and_forget tasks are caught and logged."""
    async def failing_bg_coro():
        raise ValueError("Background job failed catastrophically")

    with caplog.at_level(logging.ERROR):
        fire_and_forget(failing_bg_coro())
        # Let the event loop run to execute the task and its callback
        await asyncio.sleep(0.05)
        
        assert any(
            ("Unhandled exception in background task" in record.message and "Background job failed catastrophically" in str(record.exc_info))
            for record in caplog.records if record.levelno >= logging.ERROR
        ) or any(
            "Background job failed catastrophically" in record.message
            for record in caplog.records if record.levelno >= logging.ERROR
        )


@pytest.mark.asyncio
async def test_storage_corrupt_session_logging(tmp_path, monkeypatch, caplog):
    """Verify that corrupt session.json files are logged with warnings/errors rather than silently swallowed."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    user_sessions_dir = tmp_path / "testuser" / "sessions" / "corrupt_session"
    user_sessions_dir.mkdir(parents=True)
    (user_sessions_dir / "session.json").write_text("{invalid json content!@#", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        sessions = await get_sessions("testuser")
        assert sessions == []
        assert any(
            ("Failed to read session file" in record.message or "corrupt_session" in record.message)
            for record in caplog.records if record.levelno >= logging.WARNING
        )

    with caplog.at_level(logging.ERROR):
        history = await get_session_history("testuser", "corrupt_session")
        assert history == []
        assert any(
            ("Failed to read session history" in record.message or "corrupt_session" in record.message)
            for record in caplog.records if record.levelno >= logging.ERROR
        )


@pytest.mark.asyncio
async def test_storage_write_failure_logging(tmp_path, monkeypatch, caplog):
    """Verify that I/O write failures in storage are logged with ERROR level."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    user_sessions_dir = tmp_path / "testuser" / "sessions" / "sess-1"
    user_sessions_dir.mkdir(parents=True)
    (user_sessions_dir / "session.json").write_text('{"title": "Old", "history": []}', encoding="utf-8")
    
    with patch("builtins.open", side_effect=OSError("Read-only file system")):
        with caplog.at_level(logging.ERROR):
            await save_session_message("testuser", "sess-1", {"text": "hello", "is_user": True})
            assert any(
                "Failed to save message" in record.message
                for record in caplog.records if record.levelno >= logging.ERROR
            )

        with caplog.at_level(logging.ERROR):
            await update_session_title("testuser", "sess-1", "New Title")
            assert any(
                ("Failed to update title" in record.message or "Failed to update session title" in record.message)
                for record in caplog.records if record.levelno >= logging.ERROR
            )


@pytest.mark.asyncio
async def test_agy_stream_process_failure_logging(caplog):
    """Verify that when agy stream process exits with non-zero return code, stderr is captured and logged."""
    mock_process = AsyncMock()
    mock_process.stdout.readline = AsyncMock(side_effect=[b"", b""])
    mock_process.stderr.read = AsyncMock(return_value=b"FATAL: out of memory allocating CUDA tensor")
    mock_process.wait = AsyncMock()
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with caplog.at_level(logging.ERROR):
            events = []
            async for event in agy_client.stream_message([], "hello"):
                events.append(event)
            
            assert any(
                ("FATAL: out of memory allocating CUDA tensor" in record.message and "code 1" in record.message)
                for record in caplog.records if record.levelno >= logging.ERROR
            ) or any(
                "FATAL: out of memory allocating CUDA tensor" in record.message
                for record in caplog.records if record.levelno >= logging.ERROR
            )


@pytest.mark.asyncio
async def test_agy_process_message_unexpected_error_logging(caplog):
    """Verify that unexpected exceptions in agy process_message are logged with exc_info."""
    with patch("asyncio.create_subprocess_exec", side_effect=PermissionError("Permission denied to execute agy")):
        with caplog.at_level(logging.ERROR):
            res = await agy_client.process_message([], "hello")
            assert ("fehler" in res.get("reply", "").lower() or "permission" in res.get("reply", "").lower() or "entschuldigung" in res.get("reply", "").lower())
            assert any(
                ("Permission denied" in record.message or "Unexpected error in process_message" in record.message)
                for record in caplog.records if record.levelno >= logging.ERROR
            )


def test_auth_and_security_logging(caplog, tmp_path, monkeypatch):
    """Verify login failures, path traversal attempts, and unauthorized data access are logged with WARNING."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    test_app_client = TestClient(app)

    # 1. Failed login
    with caplog.at_level(logging.WARNING):
        response = test_app_client.post("/api/auth/login", data={"username": "alice", "password": "wrong_password"})
        assert response.status_code == 401
        assert any(
            ("Failed login attempt for user 'alice'" in record.message or "Invalid credentials" in record.message)
            for record in caplog.records if record.levelno >= logging.WARNING
        )

    # 2. Path traversal attempt on data download
    app.dependency_overrides[get_current_user] = lambda: "alice"
    try:
        with caplog.at_level(logging.WARNING):
            # Using encoded slashes so client doesn't normalize path before sending
            response = test_app_client.get("/app/data/alice/sess1/data/subdir%2F..%2F..%2F..%2Fetc%2Fpasswd")
            assert response.status_code in (400, 404)
            assert any(
                ("path traversal" in record.message.lower() or "invalid path" in record.message.lower() or "400" in record.message or "404" in record.message)
                for record in caplog.records if record.levelno >= logging.WARNING
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

