from typing import Optional
from pydantic import BaseModel

class UserCredentials(BaseModel):
    username: str
    password: str

class AuthSessionData(BaseModel):
    username: str
    created_at: float
    expires_at: float

class AuthStatusResponse(BaseModel):
    authenticated: bool
    username: str = ""
