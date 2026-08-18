import io
import json
import logging
import os
import re
import pytest

from app.logging_config import setup_logging, JsonFormatter


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
