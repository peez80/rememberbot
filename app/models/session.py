from typing import Optional, List
from pydantic import BaseModel, Field

class SessionMetadata(BaseModel):
    id: str
    title: str = "Neuer Chat"
    created_at: Optional[str] = None
    has_icon: bool = False

class SessionSettingsRequest(BaseModel):
    prompt: str = ""
    include_gps: bool = False

class SessionTitleRequest(BaseModel):
    title: str

class SessionCreateResponse(BaseModel):
    id: str
    title: str = "Neuer Chat"

class SessionImportResponse(BaseModel):
    success: bool
    id: str
    title: str = "Importierter Chat"
    has_icon: bool = False
