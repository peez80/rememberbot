import json
import pytest
import httpx
from unittest.mock import patch
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

@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.get_session_settings")
@pytest.mark.asyncio
async def test_chat_endpoint_streaming_sse(
    mock_get_settings, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client
):
    """Verify that /api/sessions/{id}/chat with stream=true yields text/event-stream chunks."""
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}

    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    async def mock_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Token1 "}
        yield {"type": "delta", "text": "Token2 "}
        yield {"type": "done", "reply": "Token1 Token2 ", "context_truncated": False}

    mock_agy_client.stream_message.side_effect = mock_stream

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.post(
            "/api/sessions/sess-stream/chat",
            data={"message": "Erzähle mir was", "stream": "true"},
            headers={"Accept": "text/event-stream"}
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        delta_texts = [e["text"] for e in events if e.get("type") == "delta"]
        assert delta_texts == ["Token1 ", "Token2 "]

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["reply"] == "Token1 Token2"

        # Verify messages saved to database
        assert mock_save_msg.call_count == 2
        user_msg = mock_save_msg.call_args_list[0][0][2]
        ai_msg = mock_save_msg.call_args_list[1][0][2]
        assert user_msg["text"] == "Erzähle mir was"
        assert ai_msg["text"] == "Token1 Token2"


@pytest.mark.asyncio
async def test_stream_chat_generator_unregisters_session_on_prepare_error():
    """Verify that supervisor.is_session_active is cleared if _prepare_chat_turn raises in stream_chat_generator."""
    from app.core.tasks import supervisor
    from app.services.chat_service import chat_service

    username = "testuser"
    session_id = "sess-prep-err"
    supervisor.register_session(username, session_id)
    assert supervisor.is_session_active(username, session_id) is True

    with patch.object(chat_service, "_prepare_chat_turn", side_effect=RuntimeError("Prepare failed")):
        with pytest.raises(RuntimeError, match="Prepare failed"):
            gen = chat_service.stream_chat_generator(
                username=username,
                session_id=session_id,
                message="Hallo"
            )
            await gen.__anext__()

    assert supervisor.is_session_active(username, session_id) is False


@pytest.mark.asyncio
async def test_stream_chat_continues_in_background_if_disconnected_during_prepare():
    """Verify that if the client disconnects (CancelledError) while _prepare_chat_turn is still running,
    the turn preparation is shielded, background_stream_consumer completes the AI response, and unregisters the session."""
    import asyncio
    from unittest.mock import AsyncMock
    from app.core.tasks import supervisor
    from app.services.chat_service import chat_service

    username = "testuser"
    session_id = "sess-prep-cancel"

    async def slow_prepare(*args, **kwargs):
        await asyncio.sleep(0.25)
        return {
            "history": [],
            "is_first_message": False,
            "system_prompt": "sys",
            "cwd": "/tmp",
            "conversation_id": "conv-1",
            "stored_conv_id": "conv-1",
            "model": None,
            "thinking_effort": None,
        }

    async def mock_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Hintergrund "}
        yield {"type": "done", "reply": "Hintergrund Antwort", "context_truncated": False}

    mock_finalize = AsyncMock(return_value={"reply": "Hintergrund Antwort", "timestamp": "2026-01-01T00:00:05Z"})

    with patch.object(chat_service, "_prepare_chat_turn", side_effect=slow_prepare), \
         patch.object(chat_service._agy, "stream_message", side_effect=mock_stream), \
         patch.object(chat_service, "_finalize_chat_turn", mock_finalize):

        gen = chat_service.stream_chat_generator(
            username=username,
            session_id=session_id,
            message="Test während Prepare"
        )

        # Start iterating generator, then cancel after 50ms while slow_prepare (250ms) is still running
        next_task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        assert supervisor.is_session_active(username, session_id) is True
        next_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await next_task

        # Wait for background consumer to finish slow_prepare + mock_stream + mock_finalize
        await asyncio.sleep(0.4)

        mock_finalize.assert_awaited_once()
        assert supervisor.is_session_active(username, session_id) is False


@pytest.mark.asyncio
async def test_queued_chat_emits_queued_and_processing_sse_events():
    """Verify that submitting a message while another message is being processed emits 'queued' immediately,
    followed by 'processing', deltas, and 'done' once the prior turn finishes."""
    import asyncio
    from app.services.chat_service import chat_service
    from app.main import app

    turn1_blocker = asyncio.Event()

    async def mock_stream(*args, **kwargs):
        msg = kwargs.get("new_message")
        if msg == "First message":
            yield {"type": "delta", "text": "Reply 1"}
            await turn1_blocker.wait()
            yield {"type": "done", "reply": "Reply 1"}
        else:
            yield {"type": "delta", "text": "Reply 2"}
            yield {"type": "done", "reply": "Reply 2"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session first
        sess_res = await client.post("/api/sessions")
        session_id = sess_res.json()["id"]

        with patch.object(chat_service._agy, "stream_message", side_effect=mock_stream):
            # Start first message
            t1_task = asyncio.create_task(client.post(
                f"/api/sessions/{session_id}/chat",
                data={"message": "First message", "stream": "true"},
                headers={"Accept": "text/event-stream"}
            ))
            await asyncio.sleep(0.05)

            # Start second message while first is waiting on blocker
            t2_task = asyncio.create_task(client.post(
                f"/api/sessions/{session_id}/chat",
                data={"message": "Second message", "stream": "true"},
                headers={"Accept": "text/event-stream"}
            ))
            await asyncio.sleep(0.05)

            # Unblock turn 1 so both can complete sequentially
            turn1_blocker.set()
            t1_response, t2_response = await asyncio.gather(t1_task, t2_task)

            assert t1_response.status_code == 200
            assert t2_response.status_code == 200

            # t2_response must contain 'event: queued' and 'event: processing'
            assert "event: queued" in t2_response.text
            assert "event: processing" in t2_response.text


@pytest.mark.asyncio
async def test_delete_queued_message_endpoint():
    """Verify DELETE /api/sessions/{id}/queue/{message_id} functionality and error handling."""
    from app.main import app
    from app.services.session_service import session_service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        sess_res = await client.post("/api/sessions")
        session_id = sess_res.json()["id"]

        # Manually save a queued message
        await session_service.save_session_message("testuser", session_id, {
            "id": "queued-to-delete",
            "text": "Waiting message",
            "is_user": True,
            "status": "queued"
        })

        # Delete it via endpoint
        del_res = await client.delete(f"/api/sessions/{session_id}/queue/queued-to-delete")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        # Deleting again returns 409
        del_again = await client.delete(f"/api/sessions/{session_id}/queue/queued-to-delete")
        assert del_again.status_code == 409

        # Bad session ID or message ID returns 400
        bad_res = await client.delete(f"/api/sessions/{session_id}/queue/invalid*id")
        assert bad_res.status_code == 400


@pytest.mark.asyncio
async def test_chat_endpoint_accepts_and_validates_custom_message_id():
    """Verify that POST /api/sessions/{session_id}/chat accepts client-provided message_id and validates it."""
    from app.main import app
    from app.services.session_service import session_service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        sess_res = await client.post("/api/sessions")
        session_id = sess_res.json()["id"]

        # Valid custom message_id
        custom_id = "msg-client-test-12345"
        res = await client.post(
            f"/api/sessions/{session_id}/chat",
            data={
                "message": "Custom ID message",
                "message_id": custom_id,
                "stream": "false"
            }
        )
        assert res.status_code == 200

        history = await session_service.get_session_history("testuser", session_id)
        user_msgs = [m for m in history if m.get("is_user")]
        assert len(user_msgs) >= 1
        assert user_msgs[0].get("id") == custom_id

        # Invalid custom message_id (contains path traversal or invalid characters)
        bad_res = await client.post(
            f"/api/sessions/{session_id}/chat",
            data={
                "message": "Bad ID message",
                "message_id": "../../bad_id!",
                "stream": "false"
            }
        )
        assert bad_res.status_code == 400
        assert "Ungültige Nachrichten-ID" in bad_res.text




