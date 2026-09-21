import os
import pytest
from app.services.storage_service import StorageService
from app.services.session_service import SessionService

@pytest.fixture
def session_service(tmp_path):
    data_dir = str(tmp_path / "data")
    storage_svc = StorageService(data_dir=data_dir)
    return SessionService(storage_service=storage_svc)

@pytest.mark.asyncio
async def test_session_lifecycle(session_service):
    session_id = await session_service.create_session("alice", "My First Chat")
    assert session_id is not None
    assert await session_service.check_session_exists("alice", session_id) is True
    
    # Title
    title = await session_service.get_session_title("alice", session_id)
    assert title == "My First Chat"
    
    await session_service.update_session_title("alice", session_id, "Updated Chat")
    assert await session_service.get_session_title("alice", session_id) == "Updated Chat"
    
    # Settings
    settings = await session_service.get_session_settings("alice", session_id)
    assert settings == {"prompt": "", "include_gps": False, "model": "gemini-3.8-flash", "thinking_effort": "medium"}
    
    await session_service.update_session_settings("alice", session_id, "New prompt", True)
    settings = await session_service.get_session_settings("alice", session_id)
    assert settings == {"prompt": "New prompt", "include_gps": True, "model": "gemini-3.8-flash", "thinking_effort": "medium"}
    
    # Messages
    await session_service.save_session_message("alice", session_id, {"text": "Hello", "is_user": True})
    history = await session_service.get_session_history("alice", session_id)
    assert len(history) == 1
    assert history[0]["text"] == "Hello"
    
    # Sessions list
    sessions = await session_service.get_sessions("alice")
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["title"] == "Updated Chat"

@pytest.mark.asyncio
async def test_session_export_and_import(session_service):
    session_id = await session_service.create_session("alice", "Export Chat")
    await session_service.save_session_message("alice", session_id, {
        "text": f"Uploaded [photo.png](/uploads/{session_id}/photo.png)",
        "is_user": True,
        "image_urls": [f"/uploads/{session_id}/photo.png"]
    })
    
    zip_bytes = await session_service.export_session_archive("alice", session_id)
    assert zip_bytes is not None
    assert len(zip_bytes) > 0
    
    # Import into a new session for bob
    target_id = await session_service.create_session("bob", "New Chat")
    result = await session_service.import_session_archive("bob", target_id, zip_bytes)
    assert result["id"] == target_id
    assert result["title"] == "Export Chat"
    
    # Check history in target session is remapped to bob and target_id
    bob_history = await session_service.get_session_history("bob", target_id)
    assert len(bob_history) == 1
    assert f"/uploads/{target_id}/photo.png" in bob_history[0]["text"]
    assert bob_history[0]["image_urls"] == [f"/uploads/{target_id}/photo.png"]

@pytest.mark.asyncio
async def test_session_conversation_id_storage(session_service):
    session_id = await session_service.create_session("alice", "Conv ID Chat")
    
    # Initially None
    conv_id = await session_service.get_session_conversation_id("alice", session_id)
    assert conv_id is None
    
    # Update conversation ID
    await session_service.set_session_conversation_id("alice", session_id, "test-conv-uuid-1234")
    
    # Read back
    updated_id = await session_service.get_session_conversation_id("alice", session_id)
    assert updated_id == "test-conv-uuid-1234"
    
    # Clear conversation ID
    await session_service.set_session_conversation_id("alice", session_id, None)
    assert await session_service.get_session_conversation_id("alice", session_id) is None

