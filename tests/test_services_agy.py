import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.agy_service import AGYService

@pytest.fixture
def agy_service():
    return AGYService()

@pytest.mark.asyncio
async def test_agy_service_estimate_tokens(agy_service):
    tokens = agy_service.estimate_tokens("Hello world from unit test")
    assert tokens > 0
    assert agy_service.estimate_tokens("") == 0

@pytest.mark.asyncio
async def test_agy_service_prune_history(agy_service):
    messages = [
        {"text": "msg 1", "is_user": True},
        {"text": "msg 2", "is_user": False},
        {"text": "msg 3", "is_user": True},
        {"text": "msg 4", "is_user": False}
    ]
    # Small budget to force pruning
    pruned, was_truncated = agy_service.prune_history_to_token_budget(messages, max_tokens=2)
    assert was_truncated is True
    assert len(pruned) < len(messages)

@pytest.mark.asyncio
async def test_agy_service_generate_chat_icon(agy_service, tmp_path):
    target_path = str(tmp_path / "icon.svg")
    
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>', b'')
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        await agy_service.generate_chat_icon("Meeting Notes", target_path)
        
    import os
    assert os.path.exists(target_path)
    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "<svg" in content
