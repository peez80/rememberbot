import os
import logging
from fastapi import APIRouter, Request, Response, Form, HTTPException, Depends

from app.core.config import COOKIE_SECURE, SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS
from app.models.auth import AuthStatusResponse
from app.services.auth_service import auth_service
from app.storage import init_user_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...)
):
    client_ip = request.client.host if request.client else "unknown"

    if not auth_service.check_rate_limit(client_ip, username):
        raise HTTPException(
            status_code=429,
            detail="Zu viele fehlgeschlagene Login-Versuche. Bitte warte eine Minute.",
            headers={"Retry-After": "60"}
        )

    if auth_service.authenticate(username, password):
        auth_service.clear_failed_attempts(client_ip, username)
        session_token = auth_service.create_session(username)

        cookie_secure = COOKIE_SECURE or request.url.scheme == "https"
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_token,
            httponly=True,
            samesite="lax",
            secure=cookie_secure,
            max_age=SESSION_MAX_AGE_SECONDS
        )

        init_user_storage(username)
        logger.info(f"User '{username}' logged in successfully from {client_ip}")
        return {"success": True}

    auth_service.record_failed_attempt(client_ip, username)
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_service.invalidate_session(session_token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True}


@router.get("/status")
async def auth_status(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    username = auth_service.verify_session(session_token)
    if username:
        return {"authenticated": True, "username": username}
    return {"authenticated": False}
