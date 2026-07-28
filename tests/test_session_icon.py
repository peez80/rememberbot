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
async def test_generate_chat_icon_fallback(tmp_path):
    output_path = str(tmp_path / "icon.svg")
    await agy_client.generate_chat_icon("Kochen Rezept", output_path)
    assert os.path.exists(output_path)
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<svg" in content
