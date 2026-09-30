import pytest
import asyncio
import httpx
from unittest.mock import patch, AsyncMock
from app.main import app, get_current_user

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

@patch("app.services.chat_service.chat_service.agy_service")
@patch("app.services.session_service.session_service.get_session_history", new_callable=AsyncMock)
@patch("app.services.session_service.session_service.save_session_message", new_callable=AsyncMock)
@patch("app.services.session_service.session_service.get_session_title", new_callable=AsyncMock)
@patch("app.services.session_service.session_service.check_session_exists", new_callable=AsyncMock)
@patch("app.services.session_service.session_service.get_session_settings", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_session_marked_processing_immediately(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    """Verify that _active_chat_sessions contains the session as soon as chat endpoint starts."""
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    started_event = asyncio.Event()
    finish_event = asyncio.Event()

    async def controlled_process(*args, **kwargs):
        started_event.set()
        await finish_event.wait()
        return {"reply": "Fertig.", "context_truncated": False}

    mock_agy_client.process_message.side_effect = controlled_process

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        chat_task = asyncio.create_task(
            async_client.post(
                "/api/sessions/sess-fast/chat",
                data={"message": "Hallo"},
            )
        )

        await asyncio.wait_for(started_event.wait(), timeout=2.0)

        # Status must be True
        status_resp = await async_client.get("/api/sessions/sess-fast/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_processing"] is True

        # User message must have been saved to history before process_message returned
        assert mock_save_msg.called
        first_call_args = mock_save_msg.call_args_list[0]
        # args: (username, session_id, user_msg_data)
        saved_msg = first_call_args[0][2]
        assert saved_msg["is_user"] is True
        assert saved_msg["text"] == "Hallo"

        finish_event.set()
        await chat_task

        # Status must be False after completion
        status_after = await async_client.get("/api/sessions/sess-fast/status")
        assert status_after.json()["is_processing"] is False
