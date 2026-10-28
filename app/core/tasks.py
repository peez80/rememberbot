import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Set, Tuple, Any, Dict

logger = logging.getLogger(__name__)

class BackgroundSupervisor:
    def __init__(self):
        self.active_tasks: Set[asyncio.Task] = set()
        self.active_chat_sessions: Set[Tuple[str, str]] = set()
        self._session_turns: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    def _handle_bg_task_done(self, task: asyncio.Task):
        self.active_tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc:
                logger.error(f"Background task failed with unhandled exception: {exc}", exc_info=exc)

    def create_task(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.active_tasks.add(task)
        task.add_done_callback(self._handle_bg_task_done)
        return task

    def fire_and_forget(self, coro: Any) -> asyncio.Task:
        return self.create_task(coro)

    def is_session_active(self, username: str, session_id: str) -> bool:
        return (username, session_id) in self.active_chat_sessions

    def register_session(self, username: str, session_id: str, turn_id: str = "default"):
        key = (username, session_id)
        if key not in self.active_chat_sessions:
            self._session_turns[key].clear()
        self._session_turns[key].add(turn_id)
        self.active_chat_sessions.add(key)

    def unregister_session(self, username: str, session_id: str, turn_id: str = "default"):
        key = (username, session_id)
        turns = self._session_turns.get(key)
        if turns is not None:
            turns.discard(turn_id)
            turns.discard("default")
            if not turns:
                self._session_turns.pop(key, None)
                self.active_chat_sessions.discard(key)
        else:
            self.active_chat_sessions.discard(key)

    @asynccontextmanager
    async def track_session(self, username: str, session_id: str, turn_id: str = "default"):
        self.register_session(username, session_id, turn_id)
        try:
            yield
        finally:
            self.unregister_session(username, session_id, turn_id)


# Global instance
supervisor = BackgroundSupervisor()

def fire_and_forget(coro: Any) -> asyncio.Task:
    return supervisor.fire_and_forget(coro)
