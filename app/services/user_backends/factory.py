import logging
from typing import Optional, Type
from app.core.config import USER_BACKEND
from .base import BaseUserBackend
from .json_backend import JsonUserBackend
from .oauth_backend import OAuthUserBackend

logger = logging.getLogger(__name__)

USER_BACKEND_REGISTRY: dict[str, Type[BaseUserBackend]] = {
    "json": JsonUserBackend,
    "file": JsonUserBackend,
    "oauth": OAuthUserBackend,
    "oidc": OAuthUserBackend,
    "nextcloud": OAuthUserBackend,
}

def validate_user_backend(backend_name: Optional[str] = None) -> str:
    """
    Validates whether the requested backend is registered.
    Returns normalized backend name or raises ValueError.
    """
    name = (backend_name or USER_BACKEND).strip().lower()
    if name not in USER_BACKEND_REGISTRY:
        allowed = ", ".join(sorted(USER_BACKEND_REGISTRY.keys()))
        raise ValueError(
            f"Unbekanntes Benutzerbackend '{name}'. "
            f"Erlaubte Backends: {allowed}."
        )
    return name


def get_user_backend(backend_type: Optional[str] = None, **kwargs) -> BaseUserBackend:
    """
    Factory creating an instance of the configured or requested user backend.
    """
    name = validate_user_backend(backend_type)
    backend_cls = USER_BACKEND_REGISTRY[name]
    return backend_cls(**kwargs)
