from abc import ABC, abstractmethod
from typing import Dict

class BaseUserBackend(ABC):
    """
    Abstract base class for all authentication and user provider backends in RememberBot.
    Decouples credentials verification from session lifecycle and rate limiting.
    """

    is_oauth: bool = False
    is_password_supported: bool = True

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Unique identifier of the backend (e.g. 'json')."""
        ...

    @abstractmethod
    def authenticate(self, username: str, password: str) -> bool:
        """
        Validates user credentials.
        Returns True if username exists and password matches, False otherwise.
        """
        ...

    @abstractmethod
    def user_exists(self, username: str) -> bool:
        """Checks whether the specified username exists in this backend."""
        ...

    def get_valid_users(self) -> Dict[str, str]:
        """
        Returns a mapping of {username: password_or_hash} if supported by the backend.
        Returns an empty dict if the backend does not support user enumeration.
        """
        return {}
