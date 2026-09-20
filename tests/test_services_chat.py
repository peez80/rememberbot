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

