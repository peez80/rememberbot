import pytest
import subprocess
import json
from unittest.mock import patch, MagicMock
from app.agy_client import AgyClient

@pytest.fixture
def client():
    return AgyClient(executable_path="dummy_agy")

@patch("app.agy_client.os.path.exists")
@patch("app.agy_client.os.listdir")
@pytest.mark.asyncio
async def test_is_authenticated_via_dir(mock_listdir, mock_exists, client):
    # Setup mock to return true for dir exists and has content
    mock_exists.return_value = True
    mock_listdir.return_value = ["credentials.json"]
    
    assert client.is_authenticated() == True
    
@patch("app.agy_client.os.path.exists")
@patch("app.agy_client.subprocess.run")
@pytest.mark.asyncio
async def test_is_authenticated_via_cli(mock_run, mock_exists, client):
    # Setup mock: dir doesn't exist, but CLI runs fine
    def mock_exists_side_effect(path):
        if "antigravity-cli" in path:
            return False
        return True
    mock_exists.side_effect = mock_exists_side_effect
    
    mock_run.return_value = MagicMock(returncode=0)
    
    assert client.is_authenticated() == True
    mock_run.assert_called_once()

@patch("app.agy_client.subprocess.Popen")
@pytest.mark.asyncio
async def test_get_login_url_success(mock_popen, client):
    # Setup a mock process that yields a URL
    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = [
        "Please visit this URL to login:\n",
        "https://antigravity.google/auth?code=xyz\n",
        "Enter code:\n",
        ""
    ]
    mock_popen.return_value = mock_process
    
    url = client.get_login_url()
    
    assert url == "https://antigravity.google/auth?code=xyz"
    mock_popen.assert_called_once()

@patch("app.agy_client.os.remove")
@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_process_message_success(mock_create, mock_remove, client, tmp_path):
    expected_response = {
        "reply": "Apfel notiert!",
        "context_truncated": False
    }
    
    # Mock the Process object returned by create_subprocess_exec
    mock_process = MagicMock()
    # communicate() is an async function that returns (stdout, stderr)
    async def mock_communicate():
        return (b"Apfel notiert!\n", b"")
    mock_process.communicate = mock_communicate
    mock_process.returncode = 0
    mock_create.return_value = mock_process
    
    context = [{"is_user": True, "text": "Hallo", "timestamp": "2024-01-01T12:00Z"}]
    message = "Ein Apfel."
    
    result = await client.process_message(context, message, cwd=str(tmp_path))
    
    assert result == expected_response
    mock_create.assert_called_once()
    
    # Check if prompt formatting was correct
    args, kwargs = mock_create.call_args
    assert "--prompt" in args
    prompt_arg = args[args.index("--prompt") + 1]
    
    assert "<chat_history>" not in prompt_arg
    assert "Lies zwingend die Datei" in prompt_arg
    assert "<current_message>" in prompt_arg
    assert "User: Ein Apfel." in prompt_arg
    
    # Check file operations
    mock_remove.assert_called_once()
    removed_path = mock_remove.call_args[0][0]
    assert removed_path.endswith(".txt")
    assert "chat_context_" in removed_path
    
    # Verify file contents since os.remove was mocked and file is still there
    with open(removed_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<chat_history>" in content
    assert "[2024-01-01T12:00Z] User: Hallo" in content

@patch("app.agy_client.os.remove")
@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_process_message_with_conversation_id(mock_create, mock_remove, client, tmp_path):
    expected_response = {
        "reply": "Apfel notiert!",
        "context_truncated": False
    }
    
    mock_process = MagicMock()
    async def mock_communicate():
        return (b"Apfel notiert!\n", b"")
    mock_process.communicate = mock_communicate
    mock_process.returncode = 0
    mock_create.return_value = mock_process
    
    context = [{"is_user": True, "text": "Hallo", "timestamp": "2024-01-01T12:00Z"}]
    message = "Ein Apfel."
    
    result = await client.process_message(context, message, cwd=str(tmp_path), conversation_id="conv-test-123")
    
    assert result == expected_response
    mock_create.assert_called_once()
    
    args, kwargs = mock_create.call_args
    assert "--conversation" in args
    conv_arg = args[args.index("--conversation") + 1]
    assert conv_arg == "conv-test-123"
    
    assert "--prompt" in args
    prompt_arg = args[args.index("--prompt") + 1]
    assert "Lies zwingend die Datei" not in prompt_arg
    assert "<chat_history>" not in prompt_arg
    assert "User: Ein Apfel." in prompt_arg
    
    # No temporary file should have been written or removed
    mock_remove.assert_not_called()

@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_stream_message_with_conversation_id_and_init(mock_create, client, tmp_path):
    mock_ndjson_lines = [
        b'{"event":"init","conversation_id":"conv-new-999"}\n',
        b'{"event":"step_update","step_update":{"text_delta":"Hallo"}}\n',
        b'{"event":"result","result":{"response":"Hallo"}}\n'
    ]
    
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def mock_readline():
        if mock_ndjson_lines:
            return mock_ndjson_lines.pop(0)
        return b''
    mock_proc.stdout.readline = mock_readline
    mock_proc.stderr.read = MagicMock(return_value=b'')
    async def mock_wait(): return 0
    mock_proc.wait = mock_wait
    mock_create.return_value = mock_proc
    
    events = []
    async for ev in client.stream_message(
        context_messages=[{"text": "old"}],
        new_message="new",
        conversation_id="conv-resume-555"
    ):
        events.append(ev)
        
    args, _ = mock_create.call_args
    assert "--conversation" in args
    assert args[args.index("--conversation") + 1] == "conv-resume-555"
    
    init_events = [e for e in events if e.get("type") == "init"]
    assert len(init_events) == 1
    assert init_events[0]["conversation_id"] == "conv-new-999"

def test_conversation_exists(client, tmp_path):
    # Non-existent ID returns False
    assert client.conversation_exists("non-existent-conv-id") is False
    assert client.conversation_exists(None) is False
    assert client.conversation_exists("") is False
    
    # Existing mock db
    with patch("os.path.isfile", return_value=True):
        assert client.conversation_exists("some-conv-id") is True


@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_process_message_with_multiple_images(mock_create, client):
    mock_process = MagicMock()
    async def mock_communicate():
        return (b"ok\n", b"")
    mock_process.communicate = mock_communicate
    mock_process.returncode = 0
    mock_create.return_value = mock_process
    
    result = await client.process_message([], "Essen", ["/tmp/image1.jpg", "/tmp/image2.jpg"])
    
    assert result["reply"] == "ok"
    
    # Verify image paths are included in prompt
    args, kwargs = mock_create.call_args
    prompt_arg = args[args.index("--prompt") + 1]
    assert "/tmp/image1.jpg" in prompt_arg
    assert "/tmp/image2.jpg" in prompt_arg

@patch("app.agy_client.os.remove")
@patch("app.agy_client.asyncio.sleep")
@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_process_message_retry_success(mock_create, mock_sleep, mock_remove, client, tmp_path):
    # Mock CLI failing twice, then succeeding
    expected_response = {
        "reply": "Apfel notiert!",
        "context_truncated": False
    }
    
    mock_process_fail_1 = MagicMock()
    async def comm_fail_1(): return (b"", b"error 1")
    mock_process_fail_1.communicate = comm_fail_1
    mock_process_fail_1.returncode = 1

    mock_process_fail_2 = MagicMock()
    async def comm_fail_2(): return (b"", b"error 2")
    mock_process_fail_2.communicate = comm_fail_2
    mock_process_fail_2.returncode = 1

    mock_process_success = MagicMock()
    async def comm_success(): return (b"Apfel notiert!\n", b"")
    mock_process_success.communicate = comm_success
    mock_process_success.returncode = 0
    
    mock_create.side_effect = [
        mock_process_fail_1,
        mock_process_fail_2,
        mock_process_success
    ]
    
    result = await client.process_message([{"text": "ctx"}], "Ein Apfel.", cwd=str(tmp_path))
    
    assert result == expected_response
    assert mock_create.call_count == 3
    assert mock_sleep.call_count == 2
    mock_remove.assert_called_once()

@patch("app.agy_client.os.remove")
@patch("app.agy_client.asyncio.sleep")
@patch("app.agy_client.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_process_message_retry_failure(mock_create, mock_sleep, mock_remove, client, tmp_path):
    # Mock CLI failing 6 times (1 initial + 5 retries)
    def create_failing_mock(i):
        m = MagicMock()
        async def comm(): return (b"", f"error {i}".encode())
        m.communicate = comm
        m.returncode = 1
        return m

    mock_create.side_effect = [create_failing_mock(i) for i in range(6)]
    
    result = await client.process_message([{"text": "ctx"}], "Ein Apfel.", cwd=str(tmp_path))
    
    assert "nach 5 erfolglosen Versuchen" in result["reply"]
    assert mock_create.call_count == 6
    assert mock_sleep.call_count == 5
    mock_remove.assert_called_once()
