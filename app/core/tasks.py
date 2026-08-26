import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Set, Tuple, Any

logger = logging.getLogger(__name__)

class BackgroundSupervisor:
    def __init__(self):
        self.active_tasks: Set[asyncio.Task] = set()
        self.active_chat_sessions: Set[Tuple[str, str]] = set()

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

    def register_session(self, username: str, session_id: str):
        self.active_chat_sessions.add((username, session_id))
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "_active_chat_sessions"):
                main_mod._active_chat_sessions.add((username, session_id))
        except Exception:
            pass

    def unregister_session(self, username: str, session_id: str):
        self.active_chat_sessions.discard((username, session_id))
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "_active_chat_sessions"):
                main_mod._active_chat_sessions.discard((username, session_id))
        except Exception:
            pass

    @asynccontextmanager
    async def track_session(self, username: str, session_id: str):
        self.register_session(username, session_id)
        try:
            yield
        finally:
            self.unregister_session(username, session_id)


# Global instance
supervisor = BackgroundSupervisor()

def fire_and_forget(coro: Any) -> asyncio.Task:
    return supervisor.fire_and_forget(coro)
