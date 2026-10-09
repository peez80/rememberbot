import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.services.storage_service import StorageService
from app.core.formatters import format_local_links

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
async def test_chat_service_injects_technical_prompt_non_streaming(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Test Chat")
    
    with patch("app.services.chat_service.agy_client.process_message", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = {
            "reply": "Hier ist deine Datei: [test.csv](test.csv)",
            "context_truncated": False
        }
        
        result = await chat_service.process_chat(
            username=username,
            session_id=session_id,
            message="Erstelle test.csv",
            location="",
            valid_uploads=[]
        )
        
        assert mock_proc.called
        call_kwargs = mock_proc.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        
        assert "TECHNISCHE VORAUSSETZUNG:" in system_prompt
        expected_dir = os.path.abspath(os.path.join(chat_service.storage_service.data_dir, username, "sessions", session_id, "data"))
        assert expected_dir in system_prompt
        assert "Erstelle für alle generierten Dateien einen Markdown-Link in der Antwort." in system_prompt
        assert "[datei.ext](datei.ext)" in system_prompt
        assert "Dateiname.pdf" not in system_prompt
        
        # Verify reply was formatted with application download endpoint
        assert f"/app/data/{username}/{session_id}/data/test.csv" in result["reply"]

@pytest.mark.asyncio
async def test_chat_service_injects_technical_prompt_streaming(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Streaming Chat")
    
    async def mock_stream(*args, **kwargs):
        yield {"type": "delta", "text": "Hier ist [output.txt](output.txt)"}
        yield {"type": "done", "reply": "Hier ist [output.txt](output.txt)"}
        
    with patch("app.services.chat_service.agy_client.stream_message", side_effect=mock_stream) as mock_stream_fn:
        generator = chat_service.stream_chat_generator(
            username=username,
            session_id=session_id,
            message="Erstelle output.txt",
            location="",
            valid_uploads=[]
        )
        events = [ev async for ev in generator]
        
        assert mock_stream_fn.called
        call_kwargs = mock_stream_fn.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        
        assert "TECHNISCHE VORAUSSETZUNG:" in system_prompt
        expected_dir = os.path.abspath(os.path.join(chat_service.storage_service.data_dir, username, "sessions", session_id, "data"))
        assert expected_dir in system_prompt
        assert "Erstelle für alle generierten Dateien einen Markdown-Link in der Antwort." in system_prompt
        
        assert any(f"/app/data/{username}/{session_id}/data/output.txt" in ev for ev in events)

@pytest.mark.asyncio
async def test_technical_prompt_combines_with_location_and_custom_prompt(chat_service):
    username = "alice"
    session_id = await chat_service.session_service.create_session(username, "Prompt Combo Chat")
    await chat_service.session_service.update_session_settings(
        username,
        session_id,
        prompt="Du bist ein erfahrener Datenanalyst.",
        include_gps=True
    )
    
    with patch("app.services.chat_service.agy_client.process_message", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = {"reply": "Verstanden.", "context_truncated": False}
        
        await chat_service.process_chat(
            username=username,
            session_id=session_id,
            message="Hallo",
            location="Lat: 48.137, Lon: 11.575",
            valid_uploads=[]
        )
        
        system_prompt = mock_proc.call_args.kwargs.get("system_prompt", "")
        assert "TECHNISCHE VORAUSSETZUNG:" in system_prompt
        assert "Lat: 48.137, Lon: 11.575" in system_prompt
        assert "Du bist ein erfahrener Datenanalyst." in system_prompt

def test_format_local_links_relative_and_dot_slash():
    username = "bob"
    session_id = "sess_456"
    text = "Hier ist [daten.csv](daten.csv) und [bericht.pdf](./bericht.pdf) und [unterordner](sub/file.txt)"
    result = format_local_links(text, username, session_id)
    
    assert f"[{'daten.csv'}](/app/data/{username}/{session_id}/data/daten.csv)" in result
    assert f"[{'bericht.pdf'}](/app/data/{username}/{session_id}/data/bericht.pdf)" in result
    assert "./" not in result
    assert f"[{'unterordner'}](/app/data/{username}/{session_id}/data/sub/file.txt)" in result

def test_format_local_links_raw_container_path():
    username = "bob"
    session_id = "sess_456"
    raw_path = f"/app/data/{username}/sessions/{session_id}/data/export.csv"
    text = f"Die Datei liegt unter {raw_path} zur Abholung bereit."
    result = format_local_links(text, username, session_id)
    
    # Must be rewritten to the public download route without /sessions/
    expected_link = f"/app/data/{username}/{session_id}/data/export.csv"
    assert expected_link in result
    assert f"/app/data/{username}/sessions/{session_id}/data/" not in result

def test_format_local_links_auto_links_existing_files(tmp_path):
    username = "alice"
    session_id = "sess_789"
    user_data_dir = tmp_path / username / "sessions" / session_id / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create an actual generated file
    (user_data_dir / "tabelle.csv").write_text("a,b,c\n1,2,3")
    # Create internal seeding files that must NOT be auto-linked
    (user_data_dir / "chat_context_abcdef12.txt").write_text("old history")
    (user_data_dir / ".hidden_file").write_text("hidden")
    
    # AI mentioned tabelle.csv and chat_context in text but without markdown links
    text = "Ich habe die Datei `tabelle.csv` erstellt. chat_context_abcdef12.txt ist intern."
    result = format_local_links(text, username, session_id, user_data_dir=str(user_data_dir))
    
    # tabelle.csv should be auto-linked
    assert f"/app/data/{username}/{session_id}/data/tabelle.csv" in result
    # chat_context and hidden file should NOT be linked
    assert f"/app/data/{username}/{session_id}/data/chat_context_abcdef12.txt" not in result
    assert f"/app/data/{username}/{session_id}/data/.hidden_file" not in result

def test_format_local_links_with_whitespace_between_brackets_and_parentheses():
    username = "peez"
    session_id = "0a1b70b006104e08ae18243fbacab197"
    text = (
        "in deiner Datei [diary_09-2026.json] "
        f"(/app/data/{username}/sessions/{session_id}/data/diary_09-2026.json) eingetragen"
    )
    result = format_local_links(text, username, session_id)
    # Must remove the whitespace between ] and ( and rewrite the path
    expected = f"[diary_09-2026.json](/app/data/{username}/{session_id}/data/diary_09-2026.json)"
    assert expected in result
    assert "[diary_09-2026.json] (" not in result

def test_format_local_links_relative_with_whitespace():
    username = "peez"
    session_id = "0a1b70b006104e08ae18243fbacab197"
    text = "Hier ist [daten.csv] (daten.csv) und [bericht.pdf]  (./bericht.pdf)"
    result = format_local_links(text, username, session_id)
    assert f"[daten.csv](/app/data/{username}/{session_id}/data/daten.csv)" in result
    assert f"[bericht.pdf](/app/data/{username}/{session_id}/data/bericht.pdf)" in result
    assert "] (" not in result
    assert "]  (" not in result

def test_format_local_links_already_public_url_with_whitespace():
    username = "peez"
    session_id = "0a1b70b006104e08ae18243fbacab197"
    text = f"Download: [diary_09-2026.json] (/app/data/{username}/{session_id}/data/diary_09-2026.json)"
    result = format_local_links(text, username, session_id)
    expected = f"[diary_09-2026.json](/app/data/{username}/{session_id}/data/diary_09-2026.json)"
    assert expected in result
    assert "] (" not in result

def test_technical_prompt_warns_against_whitespace(chat_service):
    prompt, _ = chat_service._build_session_system_prompt("alice", "sess_123", {})
    assert "Setze kein Leerzeichen zwischen die eckigen und runden Klammern" in prompt or "WICHTIG: Setze NIEMALS ein Leerzeichen" in prompt

def test_format_local_links_ignores_placeholder_filenames():
    username = "peez"
    session_id = "0a1b70b006104e08ae18243fbacab197"
    text = (
        "Hier ist deine Datei [tabelle.csv](tabelle.csv). "
        "Beispiel: [Dateiname.pdf](Dateiname.pdf) oder [dateiname.ext](dateiname.ext) oder [filename.pdf](filename.pdf)."
    )
    result = format_local_links(text, username, session_id)
    # Real file tabelle.csv must be rewritten to download URL
    assert f"[tabelle.csv](/app/data/{username}/{session_id}/data/tabelle.csv)" in result
    # Placeholders must NOT be rewritten to /app/data/... download URLs
    assert f"/app/data/{username}/{session_id}/data/Dateiname.pdf" not in result
    assert f"/app/data/{username}/{session_id}/data/dateiname.ext" not in result
    assert f"/app/data/{username}/{session_id}/data/filename.pdf" not in result
    assert "[Dateiname.pdf](Dateiname.pdf)" in result

def test_technical_prompt_forbids_placeholders(chat_service):
    prompt, _ = chat_service._build_session_system_prompt("alice", "sess_123", {})
    assert "[Dateiname.pdf](Dateiname.pdf)" not in prompt
    assert "Dateiname.pdf" not in prompt
    assert "Gib niemals Platzhalter, Beispiele oder Formatierungshinweise in deiner Antwort an den Nutzer aus." in prompt


