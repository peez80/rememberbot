import pytest
import asyncio
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app, get_current_user

client = TestClient(app)

def mock_auth():
    app.dependency_overrides[get_current_user] = lambda: "testuser"

def clear_mock_auth():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.fixture(autouse=True)
def run_around_tests():
    mock_auth()
    yield
    clear_mock_auth()


def test_status_unauthenticated():
    clear_mock_auth()
    response = client.get("/api/sessions/sess-123/status")
    assert response.status_code == 401


@patch("app.main.check_session_exists")
def test_session_status_endpoint_idle(mock_exists):
    mock_exists.return_value = True
    
    response = client.get("/api/sessions/sess-123/status")
    assert response.status_code == 200
    assert response.json() == {"id": "sess-123", "is_processing": False}


@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_history")
def test_history_header_idle(mock_get_history, mock_exists, mock_title):
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = [{"text": "Hello", "is_user": True, "image_urls": [], "images": None, "timestamp": None}]
    
    response = client.get("/api/sessions/sess-123/history")
    assert response.status_code == 200
    assert response.headers.get("X-Is-Processing") == "false"


@patch("app.main.check_session_exists")
def test_session_status_not_found(mock_exists):
    mock_exists.return_value = False
    
    response = client.get("/api/sessions/unknown-session/status")
    assert response.status_code == 404


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_session_status_endpoint_processing(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    processing_event = asyncio.Event()
    continue_event = asyncio.Event()

    async def slow_process(*args, **kwargs):
        processing_event.set()
        await continue_event.wait()
        return {"reply": "Fertig gedacht.", "context_truncated": False}

    mock_agy_client.process_message.side_effect = slow_process

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        # Start chat processing task
        chat_task = asyncio.create_task(
            async_client.post(
                "/api/sessions/sess-123/chat",
                data={"message": "Wie ist das Wetter?"},
            )
        )

        # Wait until agy is inside process_message
        await asyncio.wait_for(processing_event.wait(), timeout=2.0)

        # Verify status endpoint returns is_processing: True
        status_resp = await async_client.get("/api/sessions/sess-123/status")
        assert status_resp.status_code == 200
        assert status_resp.json() == {"id": "sess-123", "is_processing": True}

        # Verify history endpoint returns X-Is-Processing: true header
        history_resp = await async_client.get("/api/sessions/sess-123/history")
        assert history_resp.status_code == 200
        assert history_resp.headers.get("X-Is-Processing") == "true"

        # Allow process_message to complete
        continue_event.set()
        chat_response = await chat_task
        assert chat_response.status_code == 200
        assert chat_response.json()["reply"] == "Fertig gedacht."

        # Verify status returns is_processing: False after completion
        status_after = await async_client.get("/api/sessions/sess-123/status")
        assert status_after.status_code == 200
        assert status_after.json() == {"id": "sess-123", "is_processing": False}

        # Verify history returns X-Is-Processing: false header
        history_after = await async_client.get("/api/sessions/sess-123/history")
        assert history_after.status_code == 200
        assert history_after.headers.get("X-Is-Processing") == "false"


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_session_status_multi_session_concurrency(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    sess1_event = asyncio.Event()
    sess1_continue = asyncio.Event()

    async def sess1_process(*args, **kwargs):
        sess1_event.set()
        await sess1_continue.wait()
        return {"reply": "Chat 1 Reply", "context_truncated": False}

    mock_agy_client.process_message.side_effect = sess1_process

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        task1 = asyncio.create_task(
            async_client.post("/api/sessions/sess-1/chat", data={"message": "Message 1"})
        )

        await asyncio.wait_for(sess1_event.wait(), timeout=2.0)

        # Check sess-1 is processing, sess-2 is idle
        res1 = await async_client.get("/api/sessions/sess-1/status")
        res2 = await async_client.get("/api/sessions/sess-2/status")
        assert res1.json()["is_processing"] is True
        assert res2.json()["is_processing"] is False

        sess1_continue.set()
        await task1

        res1_after = await async_client.get("/api/sessions/sess-1/status")
        assert res1_after.json()["is_processing"] is False


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_session_status_cleanup_on_error(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    async def fail_process(*args, **kwargs):
        raise RuntimeError("Subprocess crashed")

    mock_agy_client.process_message.side_effect = fail_process

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        # Request should fail with 500 or error
        with pytest.raises(Exception):
            await async_client.post("/api/sessions/sess-123/chat", data={"message": "Hello"})

        # Despite error, status must be cleaned up to False
        status_resp = await async_client.get("/api/sessions/sess-123/status")
        assert status_resp.status_code == 200
        assert status_resp.json() == {"id": "sess-123", "is_processing": False}
