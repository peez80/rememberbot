"""Pydantic domain models and API contracts."""
from .chat import ChatMessage, AttachmentMeta, ChatStreamEvent, ChatProcessResult
from .session import SessionMetadata, SessionSettingsRequest, SessionTitleRequest, SessionCreateResponse
from .auth import UserCredentials, AuthSessionData, AuthStatusResponse

__all__ = [
    "ChatMessage",
    "AttachmentMeta",
    "ChatStreamEvent",
    "ChatProcessResult",
    "SessionMetadata",
    "SessionSettingsRequest",
    "SessionTitleRequest",
    "SessionCreateResponse",
    "UserCredentials",
    "AuthSessionData",
    "AuthStatusResponse",
]
