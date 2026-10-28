import asyncio
import pytest
from app.core.tasks import BackgroundSupervisor

@pytest.mark.asyncio
async def test_background_supervisor_task_lifecycle():
    supervisor = BackgroundSupervisor()
    
    executed = False
    async def sample_coro():
        nonlocal executed
        await asyncio.sleep(0.01)
        executed = True
        
    task = supervisor.fire_and_forget(sample_coro())
    assert task in supervisor.active_tasks
    await task
    # Allow done callback to process
    await asyncio.sleep(0.01)
    assert executed is True
    assert task not in supervisor.active_tasks

@pytest.mark.asyncio
async def test_background_supervisor_session_tracking():
    supervisor = BackgroundSupervisor()
    session_key = ("testuser", "sess-123")
    
    assert not supervisor.is_session_active("testuser", "sess-123")
    
    async with supervisor.track_session("testuser", "sess-123"):
        assert supervisor.is_session_active("testuser", "sess-123")
        assert session_key in supervisor.active_chat_sessions
        
    assert not supervisor.is_session_active("testuser", "sess-123")
    assert session_key not in supervisor.active_chat_sessions


@pytest.mark.asyncio
async def test_background_supervisor_multi_turn_session_tracking():
    supervisor = BackgroundSupervisor()
    session_key = ("testuser", "sess-multi")

    supervisor.register_session("testuser", "sess-multi", turn_id="turn-1")
    supervisor.register_session("testuser", "sess-multi", turn_id="turn-2")
    assert supervisor.is_session_active("testuser", "sess-multi")
    assert session_key in supervisor.active_chat_sessions

    # Unregistering turn-1 must keep session active while turn-2 is still registered
    supervisor.unregister_session("testuser", "sess-multi", turn_id="turn-1")
    assert supervisor.is_session_active("testuser", "sess-multi")
    assert session_key in supervisor.active_chat_sessions

    # Unregistering turn-2 clears the session active state
    supervisor.unregister_session("testuser", "sess-multi", turn_id="turn-2")
    assert not supervisor.is_session_active("testuser", "sess-multi")
    assert session_key not in supervisor.active_chat_sessions

