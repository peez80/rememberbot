import os
import io
import json
import base64
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.agy_client import AgyClient
from app.storage import DATA_DIR

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
    mock_auth()
    yield
    clear_mock_auth()


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.update_session_title")
@patch("app.main.get_session_settings")
def test_upload_single_document_file(mock_get_settings, mock_update_title, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client, tmp_path):
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "System prompt", "include_gps": False}
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    
    mock_response = {
        "reply": "PDF-Inhalt erfolgreich analysiert.",
        "context_truncated": False
    }
    async def mock_process(*args, **kwargs):
        return mock_response
    mock_agy_client.process_message.side_effect = mock_process
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    pdf_bytes = b"%PDF-1.4 sample pdf content for test"
    files = [("files", ("Finanzbericht.pdf", pdf_bytes, "application/pdf"))]
    data = {"message": "Analysiere diesen Bericht"}
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.post("/api/sessions/sess-doc-123/chat", data=data, files=files)
        
        assert response.status_code == 200
        json_resp = response.json()
        assert json_resp["reply"] == "PDF-Inhalt erfolgreich analysiert."
        
        # Verify user message saved with file metadata
        assert mock_save_msg.call_count == 2
        user_msg_call = mock_save_msg.call_args_list[0][0][2]
        
        assert user_msg_call["text"] == "Analysiere diesen Bericht [1 Datei(en) angehängt]"
        assert user_msg_call["is_user"] is True
        assert "files" in user_msg_call
        assert len(user_msg_call["files"]) == 1
        
        file_info = user_msg_call["files"][0]
        assert file_info["name"] == "Finanzbericht.pdf"
        assert file_info["size"] == len(pdf_bytes)
        assert file_info["is_image"] is False
        assert file_info["url"].startswith("/uploads/sess-doc-123/")
        assert file_info["url"].endswith("Finanzbericht.pdf")
        
        # Verify file is saved in uploads directory on disk
        uploads_dir = tmp_path / "testuser" / "sessions" / "sess-doc-123" / "uploads"
        saved_files = list(uploads_dir.iterdir())
        assert len(saved_files) == 1
        assert saved_files[0].read_bytes() == pdf_bytes


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.update_session_title")
@patch("app.main.get_session_settings")
def test_mixed_image_and_document_upload(mock_get_settings, mock_update_title, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client, tmp_path):
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    
    async def mock_process(*args, **kwargs):
        return {"reply": "Alles verarbeitet.", "context_truncated": False}
    mock_agy_client.process_message.side_effect = mock_process
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    csv_bytes = b"id,name,score\n1,Alice,95\n2,Bob,88"
    
    files = [
        ("files", ("diagram.png", png_bytes, "image/png")),
        ("files", ("daten.csv", csv_bytes, "text/csv"))
    ]
    data = {"message": "Hier sind Diagramm und Daten"}
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.post("/api/sessions/sess-mix-123/chat", data=data, files=files)
        assert response.status_code == 200
        
        user_msg_call = mock_save_msg.call_args_list[0][0][2]
        assert user_msg_call["text"] == "Hier sind Diagramm und Daten [1 Bild(er), 1 Datei(en) angehängt]"
        
        # Verify images entry (backward compatibility)
        assert "images" in user_msg_call
        assert len(user_msg_call["images"]) == 1
        assert user_msg_call["images"][0]["width"] == 1
        assert user_msg_call["images"][0]["height"] == 1
        
        # Verify files entry
        assert "files" in user_msg_call
        assert len(user_msg_call["files"]) == 2
        
        img_meta = [f for f in user_msg_call["files"] if f["is_image"]][0]
        doc_meta = [f for f in user_msg_call["files"] if not f["is_image"]][0]
        
        assert img_meta["name"] == "diagram.png"
        assert img_meta["is_image"] is True
        assert doc_meta["name"] == "daten.csv"
        assert doc_meta["is_image"] is False


@patch("app.main.check_session_exists")
def test_upload_file_limit_exceeded(mock_exists, tmp_path):
    mock_exists.return_value = True
    
    # 11 files (max allowed is 10)
    files = [("files", (f"file_{i}.txt", b"test", "text/plain")) for i in range(11)]
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.post("/api/sessions/sess-limit-123/chat", data={"message": "Zu viele Dateien"}, files=files)
        assert response.status_code == 400
        assert "Maximal 10 Dateien erlaubt" in response.json().get("error", "")


@pytest.mark.asyncio
async def test_build_prompt_with_attachments_in_agy_client(tmp_path):
    client = AgyClient(executable_path="dummy_agy")
    
    attachments = [
        {"path": "/app/data/user/sessions/123/uploads/abc_report.pdf", "name": "report.pdf", "size": 102400, "is_image": False},
        {"path": "/app/data/user/sessions/123/uploads/def_script.py", "name": "script.py", "size": 2048, "is_image": False},
        {"path": "/app/data/user/sessions/123/uploads/ghi_photo.png", "name": "photo.png", "size": 51200, "is_image": True}
    ]
    
    image_paths = ["/app/data/user/sessions/123/uploads/ghi_photo.png"]
    
    prompt, history_file = client._build_prompt_and_history(
        context_messages=[],
        new_message="Bitte überprüfe diese Dateien.",
        image_paths=image_paths,
        attachments=attachments,
        system_prompt="Du bist ein nützlicher Assistent.",
        cwd=str(tmp_path)
    )
    
    assert "report.pdf" in prompt
    assert "script.py" in prompt
    assert "/app/data/user/sessions/123/uploads/abc_report.pdf" in prompt
    assert "100.0 KB" in prompt or "102400" in prompt or "KB" in prompt
    assert "ghi_photo.png" in prompt
    assert "<system_instructions>" in prompt
    assert "User: Bitte überprüfe diese Dateien." in prompt


def test_download_non_image_upload_with_content_disposition(tmp_path):
    session_id = "sess-dl-123"
    filename = "9a8b7c6d_Datenbericht.csv"
    uploads_dir = tmp_path / "testuser" / "sessions" / session_id / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    csv_content = b"col1,col2\nval1,val2"
    file_path = uploads_dir / filename
    file_path.write_bytes(csv_content)
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.get(f"/uploads/{session_id}/{filename}")
        assert response.status_code == 200
        assert response.content == csv_content
        assert "public" in response.headers.get("cache-control", "")
        assert "immutable" in response.headers.get("cache-control", "")
        disposition = response.headers.get("content-disposition", "")
        assert "Datenbericht.csv" in disposition or filename in disposition


@patch("app.main.agy_client")
@patch("app.main.get_session_history")
@patch("app.main.save_session_message")
@patch("app.main.get_session_title")
@patch("app.main.check_session_exists")
@patch("app.main.update_session_title")
@patch("app.main.get_session_settings")
def test_upload_logging(mock_get_settings, mock_update_title, mock_exists, mock_title, mock_save_msg, mock_get_history, mock_agy_client, tmp_path, caplog):
    mock_get_history.return_value = []
    mock_get_settings.return_value = {"prompt": "", "include_gps": False}
    mock_exists.return_value = True
    mock_title.return_value = "Neuer Chat"
    
    async def mock_process(*args, **kwargs):
        return {"reply": "OK", "context_truncated": False}
    mock_agy_client.process_message.side_effect = mock_process
    
    async def mock_generate_icon(*args, **kwargs):
        pass
    mock_agy_client.generate_chat_icon.side_effect = mock_generate_icon

    files = [("files", ("test_log.txt", b"Hello log", "text/plain"))]
    
    import logging
    with caplog.at_level(logging.INFO):
        with patch("app.main.DATA_DIR", str(tmp_path)):
            response = client.post("/api/sessions/sess-log-123/chat", data={"message": "Logging test"}, files=files)
            assert response.status_code == 200
            
    # Check that upload was logged
    log_messages = [record.message for record in caplog.records]
    assert any("sess-log-123" in msg or "testuser" in msg or "file" in msg.lower() for msg in log_messages)

