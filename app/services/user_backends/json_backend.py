import os
import json
import secrets
import logging
from typing import Dict, Optional
from app.core.config import DATA_DIR, USERS_FILE_PATH
from .base import BaseUserBackend

logger = logging.getLogger(__name__)

class JsonUserBackend(BaseUserBackend):
    """
    File-based JSON user backend reading users and passwords from users.json.
    Secures password comparisons using secrets.compare_digest.
    """

    def __init__(self, data_dir: str = DATA_DIR, users_file_path: Optional[str] = None):
        self.data_dir = data_dir
        self._users_file_path = users_file_path

    @property
    def backend_name(self) -> str:
        return "json"

    @property
    def users_file(self) -> str:
        if self._users_file_path:
            return self._users_file_path
        if USERS_FILE_PATH:
            return USERS_FILE_PATH
        return os.path.join(self.data_dir, "config", "users.json")

    def get_valid_users(self) -> Dict[str, str]:
        """Reads users.json and returns user credentials dictionary."""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    logger.error(
                        f"Invalid JSON format in users config {self.users_file}: expected dictionary, got {type(data).__name__}"
                    )
                    return {}
            except Exception as e:
                logger.error(f"Failed to read users config from {self.users_file}: {e}", exc_info=True)
                return {}
        return {}

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticates user with constant-time password comparison."""
        users = self.get_valid_users()
        if username not in users:
            return False
        return secrets.compare_digest(users[username], password)

    def user_exists(self, username: str) -> bool:
        """Checks if a user exists in the configured users.json."""
        users = self.get_valid_users()
        return username in users
