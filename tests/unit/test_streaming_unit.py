import pytest
from unittest.mock import patch, AsyncMock
from app.agy_client import AgyClient

@pytest.mark.asyncio
async def test_agy_client_stream_message():
    """Verify that stream_message parses NDJSON events and yields text deltas."""
    agy = AgyClient()
    
    # Mock subprocess
    mock_ndjson_lines = [
        b'{"event":"init","conversation_id":"conv-123"}\n',
        b'{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"Hallo "}}\n',
        b'{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"Welt!"}}\n',
        b'{"event":"result","result":{"status":"SUCCESS","response":"Hallo Welt!"}}\n',
    ]
    
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    
    async def mock_readline():
        if mock_ndjson_lines:
            return mock_ndjson_lines.pop(0)
        return b''

    mock_proc.stdout.readline = mock_readline
    mock_proc.stderr.read = AsyncMock(return_value=b'')
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        chunks = []
        async for chunk in agy.stream_message(context_messages=[], new_message="Hi"):
            chunks.append(chunk)
            
        deltas = [c["text"] for c in chunks if c["type"] == "delta"]
        assert "".join(deltas) == "Hallo Welt!"
        
        done_events = [c for c in chunks if c["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["reply"] == "Hallo Welt!"
