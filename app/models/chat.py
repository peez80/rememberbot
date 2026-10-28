from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class AttachmentMeta(BaseModel):
    name: str
    path: str
    size: int = 0
    is_image: bool = False
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

class ChatMessage(BaseModel):
    id: Optional[str] = None
    text: str
    is_user: bool
    status: Optional[str] = None  # None or "queued"
    image_urls: List[str] = Field(default_factory=list)
    images: Optional[List[Dict[str, Any]]] = None
    files: Optional[List[Dict[str, Any]]] = None
    timestamp: Optional[str] = None

class ChatStreamEvent(BaseModel):
    type: str  # "delta", "done", "error", "queued", "processing"
    text: Optional[str] = None
    reply: Optional[str] = None
    message_id: Optional[str] = None
    context_truncated: Optional[bool] = False
    timestamp: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class ChatProcessResult(BaseModel):
    reply: str
    context_truncated: bool = False
    timestamp: Optional[str] = None
