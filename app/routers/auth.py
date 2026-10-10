import os
import secrets
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, Form, HTTPException, Depends
from fastapi.responses import RedirectResponse

from app.core.config import (
    COOKIE_SECURE,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    OAUTH_REDIRECT_URI,
)
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
    if not getattr(auth_service.backend, "is_password_supported", True):
        raise HTTPException(
            status_code=400,
            detail="Passwort-Authentifizierung ist in dieser Konfiguration nicht aktiviert."
        )

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


@router.get("/oauth/login")
async def oauth_login(request: Request):
    if not getattr(auth_service.backend, "is_oauth", False):
        raise HTTPException(status_code=400, detail="OAuth ist nicht aktiviert.")

    state = secrets.token_urlsafe(32)
    redirect_uri = OAUTH_REDIRECT_URI or str(request.url_for("oauth_callback"))

    try:
        auth_url, code_verifier = await auth_service.backend.get_authorization_url(
            redirect_uri=redirect_uri,
            state=state
        )
    except Exception as e:
        logger.error(f"Fehler bei Erstellung der OAuth Authorize-URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="OAuth Authorize-URL konnte nicht erstellt werden.")

    cookie_value = f"{state}:{code_verifier}"
    cookie_secure = COOKIE_SECURE or request.url.scheme == "https"

    redirect_resp = RedirectResponse(url=auth_url, status_code=302)
    redirect_resp.set_cookie(
        key="oauth_state",
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
        max_age=300
    )
    return redirect_resp


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None
):
    if not getattr(auth_service.backend, "is_oauth", False):
        raise HTTPException(status_code=400, detail="OAuth ist nicht aktiviert.")

    if error:
        logger.warning(f"OAuth Provider meldete Fehler: {error} ({error_description})")
        return RedirectResponse(url=f"/?error=oauth_{error}", status_code=302)

    if not code or not state:
        logger.warning("OAuth Callback aufgerufen ohne 'code' oder 'state'")
        return RedirectResponse(url="/?error=invalid_request", status_code=302)

    raw_state_cookie = request.cookies.get("oauth_state")
    if not raw_state_cookie:
        logger.warning("OAuth State-Cookie fehlt (abgelaufen oder Session verloren)")
        return RedirectResponse(url="/?error=state_mismatch", status_code=302)

    if ":" in raw_state_cookie:
        stored_state, stored_verifier = raw_state_cookie.split(":", 1)
    else:
        stored_state, stored_verifier = raw_state_cookie, None

    if not secrets.compare_digest(stored_state, state):
        logger.warning("OAuth State Mismatch festgestellt (potenzieller CSRF-Angriff)")
        return RedirectResponse(url="/?error=state_mismatch", status_code=302)

    redirect_uri = OAUTH_REDIRECT_URI or str(request.url_for("oauth_callback"))

    try:
        username = await auth_service.backend.exchange_code_for_user(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=stored_verifier
        )
    except Exception as e:
        logger.error(f"Fehler beim OAuth Code-Exchange: {e}", exc_info=True)
        return RedirectResponse(url="/?error=oauth_failed", status_code=302)

    session_token = auth_service.create_session(username)
    init_user_storage(username)
    logger.info(f"Benutzer '{username}' erfolgreich via OAuth authentifiziert.")

    redirect_resp = RedirectResponse(url="/", status_code=302)
    cookie_secure = COOKIE_SECURE or request.url.scheme == "https"
    redirect_resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
        max_age=SESSION_MAX_AGE_SECONDS
    )
    redirect_resp.delete_cookie(key="oauth_state")
    return redirect_resp


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
    is_oauth = getattr(auth_service.backend, "is_oauth", False)
    provider_name = getattr(auth_service.backend, "provider_name", "SSO") if is_oauth else None

    if username:
        resp = {"authenticated": True, "username": username}
        if is_oauth:
            resp["oauth_configured"] = True
            resp["provider_name"] = provider_name
        return resp

    if is_oauth:
        return {
            "authenticated": False,
            "oauth_configured": True,
            "provider_name": provider_name
        }
    return {"authenticated": False}
