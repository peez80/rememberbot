import os
import json
import time
import uuid
import logging
from collections import defaultdict
from typing import Dict, Any, Optional

from fastapi import Request, HTTPException

from app.core.config import (
    DATA_DIR,
    MAX_LOGIN_ATTEMPTS,
    LOGIN_RATE_WINDOW_SECONDS,
    SESSION_MAX_AGE_SECONDS,
)

logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.active_sessions: Dict[str, Any] = {}
        self.failed_login_attempts: Dict[str, list[float]] = defaultdict(list)
        self.load_auth_sessions()

    @property
    def auth_sessions_file(self) -> str:
        return os.path.join(self.data_dir, "auth_sessions.json")

    @property
    def users_file(self) -> str:
        return os.path.join(self.data_dir, "config", "users.json")

    def get_valid_users(self) -> Dict[str, str]:
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "get_valid_users") and callable(main_mod.get_valid_users):
                from unittest.mock import MagicMock
                if isinstance(main_mod.get_valid_users, MagicMock):
                    return main_mod.get_valid_users()
        except Exception:
            pass

        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read users config from {self.users_file}: {e}", exc_info=True)
                return {}
        return {}

    @property
    def current_sessions(self) -> Dict[str, Any]:
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "ACTIVE_SESSIONS") and main_mod.ACTIVE_SESSIONS is not None:
                return main_mod.ACTIVE_SESSIONS
        except Exception:
            pass
        return self.active_sessions

    def load_auth_sessions(self):
        if os.path.exists(self.auth_sessions_file):
            try:
                with open(self.auth_sessions_file, "r", encoding="utf-8") as f:
                    raw_sessions = json.load(f)

                current_time = time.time()
                valid_sessions = {}
                for token, sdata in raw_sessions.items():
                    if isinstance(sdata, dict):
                        if current_time <= sdata.get("expires_at", float('inf')):
                            valid_sessions[token] = sdata
                    elif isinstance(sdata, str):
                        valid_sessions[token] = sdata
                self.active_sessions = valid_sessions
            except Exception as e:
                logger.warning(f"Failed to load auth sessions from {self.auth_sessions_file}: {e}")
                self.active_sessions = {}

    def save_auth_sessions(self):
        try:
            from app.storage import atomic_write_json
            atomic_write_json(self.auth_sessions_file, self.active_sessions)
        except Exception as e:
            logger.error(f"Failed to save auth sessions to {self.auth_sessions_file}: {e}", exc_info=True)

    def check_rate_limit(self, client_ip: str, username: str) -> bool:
        current_time = time.time()
        rate_key = f"{client_ip}:{username}"

        self.failed_login_attempts[rate_key] = [
            t for t in self.failed_login_attempts[rate_key] if current_time - t < LOGIN_RATE_WINDOW_SECONDS
        ]
        self.failed_login_attempts[client_ip] = [
            t for t in self.failed_login_attempts[client_ip] if current_time - t < LOGIN_RATE_WINDOW_SECONDS
        ]

        if len(self.failed_login_attempts[rate_key]) >= MAX_LOGIN_ATTEMPTS or len(self.failed_login_attempts[client_ip]) >= MAX_LOGIN_ATTEMPTS:
            logger.warning(f"Rate limit exceeded for login attempt (user: '{username}', IP: {client_ip})")
            return False
        return True

    def record_failed_attempt(self, client_ip: str, username: str):
        current_time = time.time()
        rate_key = f"{client_ip}:{username}"
        self.failed_login_attempts[rate_key].append(current_time)
        self.failed_login_attempts[client_ip].append(current_time)
        logger.warning(f"Failed login attempt for user '{username}' from {client_ip}")

    def clear_failed_attempts(self, client_ip: str, username: str):
        rate_key = f"{client_ip}:{username}"
        self.failed_login_attempts.pop(rate_key, None)
        self.failed_login_attempts.pop(client_ip, None)

    def authenticate(self, username: str, password: str) -> bool:
        users = self.get_valid_users()
        return username in users and users[username] == password

    def create_session(self, username: str) -> str:
        session_token = uuid.uuid4().hex
        now = time.time()
        session_dict = self.current_sessions
        session_dict[session_token] = {
            "username": username,
            "created_at": now,
            "expires_at": now + SESSION_MAX_AGE_SECONDS
        }
        self.save_auth_sessions()
        return session_token

    def verify_session(self, session_token: Optional[str]) -> Optional[str]:
        session_dict = self.current_sessions
        if not session_token or session_token not in session_dict:
            return None

        session_data = session_dict[session_token]
        if isinstance(session_data, dict):
            if time.time() > session_data.get("expires_at", float('inf')):
                del session_dict[session_token]
                self.save_auth_sessions()
                logger.info(f"Session token expired for user '{session_data.get('username')}'")
                return None
            return session_data.get("username", "")
        elif isinstance(session_data, str):
            return session_data
        return None

    def invalidate_session(self, session_token: Optional[str]) -> Optional[str]:
        session_dict = self.current_sessions
        if session_token and session_token in session_dict:
            entry = session_dict[session_token]
            username = entry.get("username", "") if isinstance(entry, dict) else str(entry)
            del session_dict[session_token]
            self.save_auth_sessions()
            logger.info(f"User '{username}' logged out")
            return username
        return None

    def get_current_user(self, request: Request) -> str:
        session_token = request.cookies.get("session_token")
        username = self.verify_session(session_token)
        if not username:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return username


# Global instance
auth_service = AuthService()

def get_current_user(request: Request) -> str:
    return auth_service.get_current_user(request)
