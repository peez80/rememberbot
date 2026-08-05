import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app

client = TestClient(app)

# Helper to mock authentication
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
async def test_index_route(tmp_path):
    with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=lambda: "<html>Mock</html>"))))):
        response = client.get("/")
        assert response.status_code == 200
        assert "Mock" in response.text

@pytest.mark.asyncio
async def test_unauthenticated_access():
    assert client.post("/api/sessions").status_code == 401
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions/123/history").status_code == 401
    assert client.delete("/api/sessions/123").status_code == 401
    assert client.get("/api/sessions/123/prompt").status_code == 401
    assert client.put("/api/sessions/123/prompt", json={"prompt":"test"}).status_code == 401
    assert client.post("/api/sessions/123/chat", data={"message":"test"}).status_code == 401
    assert client.get("/uploads/123/test.jpg").status_code == 401

@patch("app.main.create_session")
@pytest.mark.asyncio
async def test_create_session_endpoint(mock_create):
    mock_auth()
    mock_create.return_value = "sess-123"
    response = client.post("/api/sessions")
    assert response.status_code == 200
    assert response.json() == {"id": "sess-123", "title": "Neuer Chat"}
    mock_create.assert_called_once_with("testuser", "Neuer Chat")

@patch("app.main.get_sessions")
@pytest.mark.asyncio
async def test_get_sessions_endpoint(mock_get):
    mock_auth()
    mock_get.return_value = [{"id": "1", "title": "Chat 1"}]
    response = client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == [{"id": "1", "title": "Chat 1"}]
    mock_get.assert_called_once_with("testuser")

@patch("app.main.get_sessions")
@patch("app.main.get_session_history")
@pytest.mark.asyncio
async def test_get_history_endpoint(mock_history, mock_get_sessions):
    mock_auth()
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Test"}]
    mock_history.return_value = [{"text": "Hi", "is_user": True, "image_urls": [], "images": None, "timestamp": None}]
    response = client.get("/api/sessions/sess-123/history")
    assert response.status_code == 200
    assert response.json() == [{"text": "Hi", "is_user": True, "image_urls": [], "images": None, "timestamp": None}]
    mock_history.assert_called_once_with("testuser", "sess-123")

@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_sessions")
@patch("app.main.update_session_title")
@patch("app.main.get_session_prompt")
@pytest.mark.asyncio
async def test_chat_endpoint_text_only(mock_get_prompt, mock_update_title, mock_get_sessions, mock_save_msg, mock_get_history, mock_agy_client):
    mock_auth()
    mock_get_history.return_value = []
    mock_get_prompt.return_value = "Test prompt"
    # Mock get_sessions to return a session with "Neuer Chat" title to test auto-rename
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Neuer Chat"}]
    
    mock_response = {
        "reply": "Pizza wurde erfasst.",
        "context_truncated": False
    }
    async def mock_process(*args, **kwargs):
        return mock_response
    mock_agy_client.process_message.side_effect = mock_process
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon
    
    response = client.post("/api/sessions/sess-123/chat", data={"message": "Ich habe Pizza gegessen"})
    
    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["reply"] == "Pizza wurde erfasst."
    
    # Verify agy_client was called
    mock_agy_client.process_message.assert_called_once()
    
    # Verify title update
    mock_update_title.assert_called_once_with("testuser", "sess-123", "Ich habe Pizza gegessen")
    
    # Verify messages saved
    assert mock_save_msg.call_count == 2
    user_msg_call = mock_save_msg.call_args_list[0][0][2]
    assert user_msg_call["text"] == "Ich habe Pizza gegessen"
    assert user_msg_call["is_user"] is True

@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_sessions")
@patch("app.main.update_session_title")
@patch("app.main.get_session_prompt")
@pytest.mark.asyncio
async def test_chat_endpoint_with_image(mock_get_prompt, mock_update_title, mock_get_sessions, mock_save_msg, mock_get_history, mock_agy_client):
    mock_auth()
    mock_get_history.return_value = []
    mock_get_prompt.return_value = "Test prompt"
    mock_get_sessions.return_value = [{"id": "sess-img-123", "title": "Neuer Chat"}]
    
    mock_response = {
        "reply": "Schönes Bild.",
        "context_truncated": False
    }
    async def mock_process(*args, **kwargs):
        return mock_response
    mock_agy_client.process_message.side_effect = mock_process
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon
    
    import base64
    # Minimal 1x1 transparent PNG
    png_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    
    files = {"images": ("test.png", png_data, "image/png")}
    data = {"message": "Schau dir das an"}
    
    response = client.post("/api/sessions/sess-img-123/chat", data=data, files=files)
    
    assert response.status_code == 200
    
    # Verify messages saved
    assert mock_save_msg.call_count == 2
    user_msg_call = mock_save_msg.call_args_list[0][0][2]
    
    assert user_msg_call["text"] == "Schau dir das an [1 Bild(er) angehängt]"
    assert user_msg_call["is_user"] is True
    assert "images" in user_msg_call
    assert len(user_msg_call["images"]) == 1
    assert "url" in user_msg_call["images"][0]
    assert user_msg_call["images"][0]["width"] == 1
    assert user_msg_call["images"][0]["height"] == 1

@patch("app.main.delete_session")
@patch("app.main.get_sessions")
@pytest.mark.asyncio
async def test_delete_session_endpoint(mock_get_sessions, mock_delete_session):
    mock_auth()
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Test"}]
    
    response = client.delete("/api/sessions/sess-123")
    assert response.status_code == 200
    assert response.json() == {"success": True}
    mock_delete_session.assert_called_once_with("testuser", "sess-123")
    
    # Test not found
    response = client.delete("/api/sessions/unknown")
    assert response.status_code == 404

@patch("app.main.get_sessions")
@patch("app.main.get_session_prompt")
@pytest.mark.asyncio
async def test_get_prompt_endpoint(mock_get_prompt, mock_get_sessions):
    mock_auth()
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Test"}]
    mock_get_prompt.return_value = "Test prompt"
    response = client.get("/api/sessions/sess-123/prompt")
    assert response.status_code == 200
    assert response.json() == {"prompt": "Test prompt"}
    mock_get_prompt.assert_called_once_with("testuser", "sess-123")

@patch("app.main.get_sessions")
@patch("app.main.update_session_prompt")
@pytest.mark.asyncio
async def test_update_prompt_endpoint(mock_update_prompt, mock_get_sessions):
    mock_auth()
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Test"}]
    response = client.put("/api/sessions/sess-123/prompt", json={"prompt": "New prompt"})
    assert response.status_code == 200
    assert response.json() == {"success": True}
    mock_update_prompt.assert_called_once_with("testuser", "sess-123", "New prompt")

@patch("app.main.os.path.exists")
@pytest.mark.asyncio
async def test_uploads_endpoint(mock_exists):
    mock_auth()
    mock_exists.return_value = True
    with patch("app.main.FileResponse") as mock_fileresponse:
        mock_fileresponse.return_value = MagicMock()
        response = client.get("/uploads/123/test.jpg")
        assert response.status_code == 200
        mock_fileresponse.assert_called_once()
        assert "testuser" in mock_fileresponse.call_args[0][0]
        assert "123" in mock_fileresponse.call_args[0][0]
        assert mock_fileresponse.call_args[0][0].endswith("test.jpg")

@patch("app.main.update_session_title")
@patch("app.main.get_sessions")
@patch("app.main.agy_client")
@pytest.mark.asyncio
async def test_update_title_endpoint(mock_agy_client, mock_get_sessions, mock_update_title):
    mock_auth()
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    # Mocking get_sessions to allow the endpoint to verify the session exists
    mock_get_sessions.return_value = [{"id": "sess-123", "title": "Old Title"}]
    
    response = client.put("/api/sessions/sess-123/title", json={"title": "New Title"})
    assert response.status_code == 200
    assert response.json() == {"success": True}
    mock_update_title.assert_called_once_with("testuser", "sess-123", "New Title")

@patch("app.main.get_sessions")
@pytest.mark.asyncio
async def test_update_title_endpoint_not_found(mock_get_sessions):
    mock_auth()
    mock_get_sessions.return_value = [{"id": "sess-456", "title": "Old Title"}]
    
    response = client.put("/api/sessions/sess-123/title", json={"title": "New Title"})
    assert response.status_code == 404
