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
