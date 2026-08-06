import pytest
import os
import json
from unittest.mock import patch, mock_open, MagicMock

# New test for user storage initialization
@patch('app.storage.os.makedirs')
@pytest.mark.asyncio
async def test_init_user_storage(mock_makedirs):
    from app.storage import init_user_storage
    init_user_storage("testuser")
    
    # Check that it creates sessions directory for the user
    calls = [call.args[0] for call in mock_makedirs.call_args_list]
    assert any("testuser" in path and "sessions" in path for path in calls)


@patch('app.storage.os.path.exists')
@patch('app.storage.uuid.uuid4')
@patch('app.storage.datetime')
@patch('builtins.open', new_callable=mock_open)
@pytest.mark.asyncio
async def test_create_session(mock_file, mock_datetime, mock_uuid, mock_exists):
    from app.storage import create_session
    mock_uuid.return_value.hex = "12345"
    mock_exists.return_value = True
    
    mock_now = MagicMock()
    mock_now.isoformat.return_value = "2026-07-06T12:00:00+00:00"
    mock_datetime.now.return_value = mock_now
    
    username = "testuser"
    session_id = await create_session(username, "Test Chat")
    
    assert session_id == "12345"
    mock_file.assert_called_once()
    assert "testuser" in mock_file.call_args[0][0]
    assert "12345" in mock_file.call_args[0][0]
    assert mock_file.call_args[0][0].endswith("session.json")
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    assert loaded_data["id"] == "12345"
    assert loaded_data["title"] == "Test Chat"
    assert loaded_data["history"] == []

@patch('app.storage.os.path.exists')
@patch('app.storage.os.listdir')
@patch('app.storage.os.path.isdir')
@patch('app.storage.os.path.isfile')
@patch('builtins.open', new_callable=mock_open)
@pytest.mark.asyncio
async def test_get_sessions(mock_file, mock_isfile, mock_isdir, mock_listdir, mock_exists):
    from app.storage import get_sessions
    
    mock_exists.return_value = True
    mock_listdir.return_value = ["DELETED_1", "2", "other.txt"]
    mock_isdir.side_effect = lambda path: "1" in path or "2" in path
    mock_isfile.return_value = True
    
    session1 = json.dumps({"id": "1", "title": "A", "created_at": "2026-07-06T12:00:00+00:00", "history": []})
    session2 = json.dumps({"id": "2", "title": "B", "created_at": "2026-07-07T12:00:00+00:00", "history": []})
    
    mock_file.side_effect = [
        mock_open(read_data=session2).return_value
    ]
    
    username = "testuser"
    sessions = await get_sessions(username)
    
    assert len(sessions) == 1
    assert sessions[0]["id"] == "2"

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_get_session_history(mock_exists, mock_file):
    from app.storage import get_session_history
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "title": "Chat",
        "created_at": "2026-07-06T12:00:00+00:00",
        "history": [{"text": "Hi", "is_user": True, "images": [{"url": "/uploads/test.png", "width": 800, "height": 600}]}]
    })
    mock_file.return_value.read.return_value = session_data
    
    history = await get_session_history("testuser", "123")
    
    assert len(history) == 1
    assert history[0]["text"] == "Hi"
    assert len(history[0]["images"]) == 1
    assert history[0]["images"][0]["width"] == 800
    assert "testuser" in mock_exists.call_args[0][0]

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_save_session_message(mock_exists, mock_file):
    from app.storage import save_session_message
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "title": "Chat",
        "created_at": "2026-07-06T12:00:00+00:00",
        "history": []
    })
    
    mock_file.return_value.read.return_value = session_data
    
    await save_session_message("testuser", "123", {"text": "Hello", "is_user": True, "images": [{"url": "/img.png", "width": 100, "height": 100}]})
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    assert len(loaded_data["history"]) == 1
    assert loaded_data["history"][0]["text"] == "Hello"
    assert loaded_data["history"][0]["images"][0]["width"] == 100

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_update_session_title(mock_exists, mock_file):
    from app.storage import update_session_title
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "title": "Neuer Chat",
        "created_at": "2026-07-06T12:00:00+00:00",
        "history": []
    })
    
    mock_file.return_value.read.return_value = session_data
    
    await update_session_title("testuser", "123", "New Title")
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    assert loaded_data["title"] == "New Title"

@patch('app.storage.os.rename')
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_delete_session(mock_exists, mock_rename):
    from app.storage import delete_session
    mock_exists.return_value = True
    
    await delete_session("testuser", "123")
    
    mock_rename.assert_called_once()
    args = mock_rename.call_args[0]
    assert args[0].endswith("123")
    assert args[1].endswith("DELETED_123")

@patch('app.storage.os.path.exists')
@patch('app.storage.os.listdir')
@patch('app.storage.os.path.isdir')
@patch('app.storage.os.path.isfile')
@patch('builtins.open', new_callable=mock_open)
@pytest.mark.asyncio
async def test_undelete_session_restores_access(mock_file, mock_isfile, mock_isdir, mock_listdir, mock_exists):
    from app.storage import get_sessions
    
    mock_exists.return_value = True
    mock_listdir.return_value = ["DELETED_1"]
    mock_isdir.return_value = True
    mock_isfile.return_value = True
    
    session1 = json.dumps({"id": "1", "title": "A", "created_at": "2026-07-06T12:00:00+00:00", "history": []})
    mock_file.return_value.read.return_value = session1
    
    username = "testuser"
    
    # Check that it's hidden while deleted
    sessions = await get_sessions(username)
    assert len(sessions) == 0
    
    # Simulate undoing the rename
    mock_listdir.return_value = ["1"]
    
    # Check that it appears again
    sessions = await get_sessions(username)
    assert len(sessions) == 1
    assert sessions[0]["id"] == "1"

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_get_session_prompt(mock_exists, mock_file):
    from app.storage import get_session_prompt
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "system_prompt": "You are a chef."
    })
    mock_file.return_value.read.return_value = session_data
    
    prompt = await get_session_prompt("testuser", "123")
    assert prompt == "You are a chef."

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_get_session_prompt_fallback(mock_exists, mock_file):
    from app.storage import get_session_prompt
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123"
    })
    mock_file.return_value.read.return_value = session_data
    
    prompt = await get_session_prompt("testuser", "123")
    assert prompt == ""

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_update_session_prompt(mock_exists, mock_file):
    from app.storage import update_session_prompt
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "system_prompt": ""
    })
    
    mock_file.return_value.read.return_value = session_data
    
    await update_session_prompt("testuser", "123", "New Prompt")
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    assert loaded_data["system_prompt"] == "New Prompt"

@patch('builtins.open', new_callable=mock_open)
@patch('app.storage.os.path.exists')
@pytest.mark.asyncio
async def test_update_session_title(mock_exists, mock_file):
    from app.storage import update_session_title
    mock_exists.return_value = True
    
    session_data = json.dumps({
        "id": "123",
        "title": "Neuer Chat"
    })
    
    mock_file.return_value.read.return_value = session_data
    
    await update_session_title("testuser", "123", "Mein Titel")
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    assert loaded_data["title"] == "Mein Titel"

@patch('app.storage.os.path.exists')
@patch('app.storage.uuid.uuid4')
@patch('builtins.open', new_callable=mock_open)
@pytest.mark.asyncio
async def test_session_json_schema(mock_file, mock_uuid, mock_exists):
    """
    Stellt sicher, dass die Struktur der session.json bei Änderungen nicht 
    unbeabsichtigt geändert wird und bestehende Daten inkompatibel werden.
    """
    from app.storage import create_session
    mock_uuid.return_value.hex = "schema-test-id"
    mock_exists.return_value = True
    
    await create_session("testuser", "Schema Test Chat")
    
    handle = mock_file()
    written_data = "".join([call.args[0] for call in handle.write.call_args_list])
    loaded_data = json.loads(written_data)
    
    expected_schema = {
        "id": str,
        "title": str,
        "created_at": str,
        "history": list,
        "system_prompt": str
    }
    
    # 1. Prüfe, ob alle erwarteten Keys vorhanden sind und den richtigen Typ haben
    for key, expected_type in expected_schema.items():
        assert key in loaded_data, f"Fehlender Key in session.json: {key}"
        assert isinstance(loaded_data[key], expected_type), f"Falscher Typ für {key}: Erwartet {expected_type.__name__}, erhalten {type(loaded_data[key]).__name__}"
        
    # 2. Prüfe, ob keine unerwarteten Keys vorhanden sind (Strict Mode)
    for key in loaded_data.keys():
        assert key in expected_schema, f"Unerwarteter Key in session.json: {key}. Das Schema hat sich geändert!"
