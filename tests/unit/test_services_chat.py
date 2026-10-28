import os
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.services.storage_service import StorageService

@pytest.fixture
def chat_service(tmp_path):
    storage_svc = StorageService(data_dir=str(tmp_path / "data"))
    session_svc = SessionService(storage_service=storage_svc)
    return ChatService(storage_service=storage_svc, session_service=session_svc)

@pytest.fixture(autouse=True)
def mock_generate_chat_icon():
    with patch("app.services.chat_service.agy_client.generate_chat_icon", new_callable=AsyncMock) as mock_icon:
        yield mock_icon

@pytest.mark.asyncio
async def test_chat_service_prepare_display_message(chat_service):
    # Text only
    msg = chat_service.format_display_message("Hello", num_images=0, num_docs=0)
    assert msg == "Hello"
    
    # Images only
    msg = chat_service.format_display_message("Look", num_images=2, num_docs=0)
    assert "[2 Bild(er) angehängt]" in msg
    
    # Docs only
    msg = chat_service.format_display_message("", num_images=0, num_docs=1)
    assert "[1 Datei(en) gesendet]" in msg

@pytest.mark.asyncio
async def test_chat_service_process_message_non_streaming(chat_service, tmp_path):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Test Chat")
    
    with patch("app.services.chat_service.agy_client.process_message", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = {
            "reply": "Hello from AI",
            "context_truncated": False
        }
        
        result = await chat_service.process_chat(
            username=username,
            session_id=session_id,
            message="Hi",
            location="",
            valid_uploads=[]
        )
        
        assert result["reply"] == "Hello from AI"
        assert result["context_truncated"] is False
        
        # Verify history saved both user message and AI message
        history = await chat_service.session_service.get_session_history(username, session_id)
        assert len(history) == 2
        assert history[0]["text"] == "Hi"
        assert history[0]["is_user"] is True
        assert history[1]["text"] == "Hello from AI"
        assert history[1]["is_user"] is False

@pytest.mark.asyncio
async def test_chat_service_resumes_existing_conversation(chat_service, caplog):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Resume Chat")
    await chat_service.session_service.set_session_conversation_id(username, session_id, "conv-existing-123")
    
    # Mock agy stream
    async def mock_stream(*args, **kwargs):
        assert kwargs.get("conversation_id") == "conv-existing-123"
        yield {"type": "delta", "text": "Resumed reply"}
        yield {"type": "done", "reply": "Resumed reply"}
        
    import logging
    with caplog.at_level(logging.INFO):
        with patch("app.services.chat_service.agy_client.conversation_exists", return_value=True):
            with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream):
                generator = chat_service.stream_chat_generator(
                    username=username,
                    session_id=session_id,
                    message="Next message"
                )
                events = [ev async for ev in generator]
                assert any("[CONVERSATION RESUMING]" in record.message for record in caplog.records)
                assert "conv-existing-123" in caplog.text

@pytest.mark.asyncio
async def test_chat_service_seeds_and_captures_conversation_id(chat_service, caplog):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Seed Chat")
    # Simulate prior message in session history
    await chat_service.session_service.save_session_message(username, session_id, {"text": "Old message", "is_user": True})
    
    # Mock stream yielding init event with new conversation_id
    async def mock_stream(*args, **kwargs):
        assert kwargs.get("conversation_id") is None
        yield {"type": "init", "conversation_id": "conv-captured-456"}
        yield {"type": "delta", "text": "Seeded reply"}
        yield {"type": "done", "reply": "Seeded reply"}
        
    import logging
    with caplog.at_level(logging.INFO):
        with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream):
            generator = chat_service.stream_chat_generator(
                username=username,
                session_id=session_id,
                message="Prompt needing seeding"
            )
            events = [ev async for ev in generator]
            
            # Verify seeding log
            assert any("[CONVERSATION SEEDING]" in record.message for record in caplog.records)
            
            # Verify new conversation ID was persisted to session storage
            saved_conv_id = await chat_service.session_service.get_session_conversation_id(username, session_id)
            assert saved_conv_id == "conv-captured-456"

@pytest.mark.asyncio
async def test_chat_service_fallback_when_db_missing(chat_service, caplog):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Fallback Chat")
    await chat_service.session_service.set_session_conversation_id(username, session_id, "conv-deleted-999")
    await chat_service.session_service.save_session_message(username, session_id, {"text": "Old message", "is_user": True})
    
    async def mock_stream(*args, **kwargs):
        # Fallback triggered, so conversation_id must be None
        assert kwargs.get("conversation_id") is None
        yield {"type": "init", "conversation_id": "conv-healed-888"}
        yield {"type": "delta", "text": "Fallback reply"}
        yield {"type": "done", "reply": "Fallback reply"}
        
    import logging
    with caplog.at_level(logging.WARNING):
        with patch("app.services.chat_service.agy_client.conversation_exists", return_value=False):
            with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream):
                generator = chat_service.stream_chat_generator(
                    username=username,
                    session_id=session_id,
                    message="Prompt with missing DB"
                )
                events = [ev async for ev in generator]
                
                assert any("[CONVERSATION FALLBACK]" in record.message for record in caplog.records)
                assert "conv-deleted-999" in caplog.text
                
                saved_conv_id = await chat_service.session_service.get_session_conversation_id(username, session_id)
                assert saved_conv_id == "conv-healed-888"


@pytest.mark.asyncio
async def test_chat_service_triggers_icon_after_stream_done(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Kochen Chat")
    
    async def mock_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Leckere Pasta!"}
        yield {"type": "done", "reply": "Leckere Pasta!"}
        
    with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream):
        with patch("app.services.chat_service.agy_client.generate_chat_icon", new_callable=AsyncMock) as mock_icon:
            generator = chat_service.stream_chat_generator(
                username=username,
                session_id=session_id,
                message="Wie koche ich Pasta?"
            )
            events = [ev async for ev in generator]
            assert len(events) == 2
            
            mock_icon.assert_called_once()
            call_kwargs = mock_icon.call_args[1]
            assert "Wie koche ich Pasta?" in call_kwargs.get("user_context", "")
            assert "Leckere Pasta!" in call_kwargs.get("ai_context", "")


@pytest.mark.asyncio
async def test_chat_service_triggers_icon_after_process_chat(chat_service):
    username = "bob"
    session_id = await chat_service.session_service.create_session(username, "Reise Chat")
    
    with patch("app.services.chat_service.agy_client.process_message", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = {
            "reply": "Reiseziele in Italien",
            "context_truncated": False
        }
        with patch("app.services.chat_service.agy_client.generate_chat_icon", new_callable=AsyncMock) as mock_icon:
            result = await chat_service.process_chat(
                username=username,
                session_id=session_id,
                message="Wohin im Sommer verreisen?",
                location="",
                valid_uploads=[]
            )
            assert result["reply"] == "Reiseziele in Italien"
            mock_icon.assert_called_once()
            call_kwargs = mock_icon.call_args[1]
            assert "Wohin im Sommer verreisen?" in call_kwargs.get("user_context", "")
            assert "Reiseziele in Italien" in call_kwargs.get("ai_context", "")


@pytest.mark.asyncio
async def test_chat_service_injects_technical_prompt(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Technical Prompt Test")
    await chat_service.session_service.update_session_settings(
        username,
        session_id,
        prompt="Du bist ein präziser Assistent.",
        include_gps=True
    )

    with patch("app.services.chat_service.agy_client.process_message", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = {
            "reply": "Hier ist deine Datei: [test.csv](test.csv)",
            "context_truncated": False
        }
        result = await chat_service.process_chat(
            username=username,
            session_id=session_id,
            message="Erstelle test.csv",
            location="Lat: 52.520, Lon: 13.405",
            valid_uploads=[]
        )

        call_kwargs = mock_proc.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        assert "TECHNISCHE VORAUSSETZUNG:" in system_prompt
        assert "Du bist ein präziser Assistent." in system_prompt
        assert "Lat: 52.520, Lon: 13.405" in system_prompt
        assert f"/app/data/{username}/{session_id}/data/test.csv" in result["reply"]


@pytest.mark.asyncio
async def test_chat_service_stream_consumer_exception_handling(chat_service, caplog):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Error Chat")

    async def mock_failing_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Part 1"}
        raise RuntimeError("Subprocess pipe broken")

    import logging
    with caplog.at_level(logging.ERROR):
        with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_failing_stream):
            generator = chat_service.stream_chat_generator(
                username=username,
                session_id=session_id,
                message="Will crash mid-stream"
            )
            events = [ev async for ev in generator]

            assert any("Streaming-Fehler" in ev for ev in events)
            assert "Error in background_stream_consumer" in caplog.text


@pytest.mark.asyncio
async def test_chat_service_stream_finalize_without_done_event(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "No Done Chat")

    async def mock_stream_no_done(*args, **kwargs):
        yield {"type": "delta", "text": "Partial output without done event"}

    with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream_no_done):
        generator = chat_service.stream_chat_generator(
            username=username,
            session_id=session_id,
            message="No done test"
        )
        events = [ev async for ev in generator]
        assert any("done" in ev for ev in events)

        # Ensure history was finalized with the partial output
        history = await chat_service.session_service.get_session_history(username, session_id)
        assert len(history) == 2
        assert history[1]["text"] == "Partial output without done event"


@pytest.mark.asyncio
async def test_chat_service_sequential_queue_preserves_context_and_order(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Queue Chat")

    calls = []
    async def mock_stream(*args, **kwargs):
        new_msg = kwargs.get("new_message")
        ctx = kwargs.get("context_messages") or []
        calls.append({"msg": new_msg, "ctx_len": len(ctx), "conv_id": kwargs.get("conversation_id")})
        # Simulate slight processing delay so overlapping calls wait
        await asyncio.sleep(0.05)
        yield {"type": "init", "conversation_id": "conv-test-seq"}
        yield {"type": "delta", "text": f"Antwort auf {new_msg}"}
        yield {"type": "done", "reply": f"Antwort auf {new_msg}"}

    with patch.object(chat_service._agy, "stream_message", side_effect=mock_stream), \
         patch.object(chat_service._agy, "conversation_exists", return_value=True):
        # Fire 3 chat generators concurrently
        async def run_turn(text):
            gen = chat_service.stream_chat_generator(username=username, session_id=session_id, message=text)
            return [ev async for ev in gen]

        t1, t2, t3 = await asyncio.gather(
            run_turn("Nachricht 1"),
            run_turn("Nachricht 2"),
            run_turn("Nachricht 3")
        )

    # All three turns must have completed
    assert len(calls) == 3
    # Turn 1: 0 prior messages
    assert calls[0]["msg"] == "Nachricht 1"
    assert calls[0]["ctx_len"] == 0

    # Turn 2: must have Turn 1 (User 1 + AI 1) in context
    assert calls[1]["msg"] == "Nachricht 2"
    assert calls[1]["ctx_len"] == 2
    assert calls[1]["conv_id"] == "conv-test-seq"

    # Turn 3: must have Turn 1 + Turn 2 (User 1 + AI 1 + User 2 + AI 2) in context
    assert calls[2]["msg"] == "Nachricht 3"
    assert calls[2]["ctx_len"] == 4
    assert calls[2]["conv_id"] == "conv-test-seq"

    # Verify final session.json history has alternating [User 1, AI 1, User 2, AI 2, User 3, AI 3]
    history = await chat_service.session_service.get_session_history(username, session_id)
    assert len(history) == 6
    assert history[0]["text"] == "Nachricht 1" and history[0]["is_user"] is True
    assert history[1]["text"] == "Antwort auf Nachricht 1" and history[1]["is_user"] is False
    assert history[2]["text"] == "Nachricht 2" and history[2]["is_user"] is True
    assert history[3]["text"] == "Antwort auf Nachricht 2" and history[3]["is_user"] is False
    assert history[4]["text"] == "Nachricht 3" and history[4]["is_user"] is True
    assert history[5]["text"] == "Antwort auf Nachricht 3" and history[5]["is_user"] is False


@pytest.mark.asyncio
async def test_chat_service_cancel_queued_message_skips_execution(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Cancel Queue Chat")

    turn1_started = asyncio.Event()
    turn1_can_finish = asyncio.Event()
    calls = []

    async def mock_stream(*args, **kwargs):
        msg = kwargs.get("new_message")
        calls.append(msg)
        if msg == "Msg 1":
            turn1_started.set()
            await turn1_can_finish.wait()
        yield {"type": "done", "reply": f"Reply to {msg}"}

    with patch.object(chat_service._agy, "stream_message", side_effect=mock_stream):
        # Start turn 1
        t1_gen = chat_service.stream_chat_generator(username=username, session_id=session_id, message="Msg 1")
        t1_task = asyncio.create_task(t1_gen.__anext__())
        await turn1_started.wait()

        # Enqueue turn 2 with a specific message_id
        t2_gen = chat_service.stream_chat_generator(username=username, session_id=session_id, message="Msg 2", message_id="msg-to-cancel")
        # Read initial event (which should be queued)
        t2_first_event = await t2_gen.__anext__()
        assert "queued" in t2_first_event

        # Cancel turn 2 while turn 1 is still processing
        cancelled = await chat_service.cancel_queued_message(username, session_id, "msg-to-cancel")
        assert cancelled is True

        # Let turn 1 complete
        turn1_can_finish.set()
        await t1_task
        # Finish iterating t1
        async for _ in t1_gen:
            pass

        # Try iterating t2 - it should cleanly terminate without calling agy
        async for _ in t2_gen:
            pass

        # agy was ONLY called for Msg 1, NOT for Msg 2
        assert calls == ["Msg 1"]

        # session.json history contains only Msg 1 and Reply to Msg 1
        history = await chat_service.session_service.get_session_history(username, session_id)
        assert len(history) == 2
        assert history[0]["text"] == "Msg 1"
        assert history[1]["text"] == "Reply to Msg 1"




