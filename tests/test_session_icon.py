import pytest
import os
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.storage import get_session_icon_path, DATA_DIR, init_session_storage
from app.agy_client import agy_client

client = TestClient(app)


def mock_auth():
    from app.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "testuser"


def clear_mock_auth():
    from app.main import get_current_user
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture(autouse=True)
def run_around_tests():
    clear_mock_auth()
    yield
    clear_mock_auth()


@pytest.mark.asyncio
async def test_get_session_icon_path_returns_none_when_missing(tmp_path):
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_session_storage("testuser", "sess-1")
        assert get_session_icon_path("testuser", "sess-1") is None


@pytest.mark.asyncio
async def test_get_session_icon_path_returns_filepath_when_exists(tmp_path):
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_session_storage("testuser", "sess-1")
        icon_file = os.path.join(tmp_path, "testuser", "sessions", "sess-1", "icon.svg")
        with open(icon_file, "w", encoding="utf-8") as f:
            f.write("<svg></svg>")
        assert get_session_icon_path("testuser", "sess-1") == icon_file


@pytest.mark.asyncio
async def test_get_sessions_includes_has_icon_flag(tmp_path):
    mock_auth()
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_session_storage("testuser", "sess-1")
        session_file = os.path.join(tmp_path, "testuser", "sessions", "sess-1", "session.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z", "history": []}, f)
        
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "has_icon" in data[0]
        assert data[0]["has_icon"] is False


@pytest.mark.asyncio
async def test_get_session_icon_endpoint_404_and_200(tmp_path):
    mock_auth()
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_session_storage("testuser", "sess-1")
        session_file = os.path.join(tmp_path, "testuser", "sessions", "sess-1", "session.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z", "history": []}, f)
        
        # 404 when no icon
        res_404 = client.get("/api/sessions/sess-1/icon")
        assert res_404.status_code == 404

        # Create icon file
        icon_file = os.path.join(tmp_path, "testuser", "sessions", "sess-1", "icon.svg")
        with open(icon_file, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="10" fill="#10b981"/></svg>')

        # 200 when icon exists
        res_200 = client.get("/api/sessions/sess-1/icon")
        assert res_200.status_code == 200
        assert "image/svg" in res_200.headers["content-type"]
        assert "<svg" in res_200.text


@pytest.mark.asyncio
async def test_config_icon_generation_timeout_default():
    from app.core.config import ICON_GENERATION_TIMEOUT_SECONDS
    assert ICON_GENERATION_TIMEOUT_SECONDS == 180.0


@pytest.mark.asyncio
async def test_generate_chat_icon_failure_does_not_create_file(tmp_path, caplog):
    import logging
    from unittest.mock import AsyncMock

    output_path = str(tmp_path / "icon.svg")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"Error: model failed")
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with caplog.at_level(logging.ERROR):
            await agy_client.generate_chat_icon("Kochen Rezept", output_path)

    # Verification: No fallback file should be written on failure
    assert not os.path.exists(output_path)
    assert "Error: model failed" in caplog.text


@pytest.mark.asyncio
async def test_generate_chat_icon_timeout_does_not_create_file(tmp_path, caplog):
    import logging
    import asyncio
    from unittest.mock import AsyncMock
    from app.core.config import ICON_GENERATION_TIMEOUT_SECONDS

    output_path = str(tmp_path / "icon.svg")
    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()) as mock_wait_for:
            with caplog.at_level(logging.WARNING):
                await agy_client.generate_chat_icon("Meeting Notes", output_path)

            mock_wait_for.assert_called_once()
            call_kwargs = mock_wait_for.call_args[1]
            assert call_kwargs.get("timeout") == ICON_GENERATION_TIMEOUT_SECONDS
            assert ICON_GENERATION_TIMEOUT_SECONDS == 180.0
            assert mock_process.kill.called
            # Verification: No fallback file should be written on timeout
            assert not os.path.exists(output_path)
            assert f"timed out after {ICON_GENERATION_TIMEOUT_SECONDS}s" in caplog.text


@pytest.mark.asyncio
async def test_generate_chat_icon_with_context_and_cli_args(tmp_path):
    from unittest.mock import AsyncMock

    output_path = str(tmp_path / "icon.svg")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect rx="22" width="100" height="100"/></svg>', b"")
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await agy_client.generate_chat_icon(
            title="Kochen Rezept",
            output_path=output_path,
            user_context="Ich suche ein Rezept für Pasta Carbonara",
            ai_context="Hier ist ein traditionelles italienisches Rezept für Spaghetti Carbonara"
        )

    assert os.path.exists(output_path)
    mock_exec.assert_called_once()
    called_cmd = mock_exec.call_args[0]
    
    # Check CLI flags
    assert "--effort" in called_cmd
    effort_idx = called_cmd.index("--effort")
    assert called_cmd[effort_idx + 1] == "low"
    assert "--disable-slash-commands" in called_cmd

    # Check prompt contents
    prompt_idx = called_cmd.index("--prompt")
    prompt = called_cmd[prompt_idx + 1]
    assert "Kochen Rezept" in prompt
    assert "Pasta Carbonara" in prompt
    assert "Spaghetti Carbonara" in prompt


@pytest.mark.asyncio
async def test_generate_chat_icon_strips_thinking_tags(tmp_path):
    from unittest.mock import AsyncMock

    output_path = str(tmp_path / "icon.svg")
    mock_process = AsyncMock()
    # Output includes <thought> with a fake <svg>...</svg> inside, followed by the real SVG
    raw_output = (
        b"<thought>Let me draft an <svg>fake</svg> icon idea.</thought>\n"
        b"```xml\n"
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="#ff0000"/></svg>\n'
        b"```"
    )
    mock_process.communicate.return_value = (raw_output, b"")
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await agy_client.generate_chat_icon("Design Icon", output_path)

    assert os.path.exists(output_path)
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "circle" in content
    assert "fake" not in content


