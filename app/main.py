import os
import asyncio
import logging
from typing import List, Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ChatMessage,
    SessionSettingsRequest,
    SessionTitleRequest,
    SessionCreateResponse,
    SessionMetadata,
    AuthStatusResponse,
)

from .logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from .core.tasks import supervisor, fire_and_forget
from .core.formatters import format_thought_blocks, format_local_links
from .agy_client import agy_client
from .storage import (
    init_storage, DATA_DIR, atomic_write_json, sanitize_svg,
    create_session, get_sessions, get_session_history,
    save_session_message, update_session_title, delete_session,
    get_session_settings, update_session_settings, init_user_storage,
    get_session_icon_path, get_session_icon_target_path,
    cleanup_deleted_sessions,
    check_session_exists, get_session_title, generate_thumbnail,
    export_session_archive, import_session_archive
)

from .services.auth_service import auth_service, get_current_user
from .routers.auth import router as auth_router
from .routers.sessions import router as sessions_router
from .routers.files import router as files_router
from .routers.chat import router as chat_router

app = FastAPI(title="RememberBot")

# SEC-09: Global HTTP Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=()"
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' data: https://fonts.gstatic.com https://unpkg.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: /uploads/ /api/; "
            "connect-src 'self' https://unpkg.com https://cdn.jsdelivr.net;"
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handlers for complete error observability
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    log_fn = logger.error if exc.status_code >= 500 else logger.warning
    log_fn(f"HTTP {exc.status_code} on {request.method} {request.url.path}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Interner Serverfehler"})

# Initialize storage on startup
init_storage()

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = os.path.join(static_dir, "favicon.png")
    if not os.path.exists(favicon_path):
        logger.warning(f"Favicon not found at {favicon_path}")
        raise HTTPException(status_code=404, detail="Favicon not found")
    return FileResponse(favicon_path)

# --- Router Registration ---
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(files_router)
app.include_router(chat_router)

# Compatibility aliases for existing tests
ACTIVE_SESSIONS = auth_service.active_sessions
_failed_login_attempts = auth_service.failed_login_attempts
get_valid_users = auth_service.get_valid_users
load_auth_sessions = auth_service.load_auth_sessions
save_auth_sessions = auth_service.save_auth_sessions

# Compatibility aliases for tasks and active chat sessions
_active_tasks = supervisor.active_tasks
_active_chat_sessions = supervisor.active_chat_sessions

def _handle_bg_task_done(task: asyncio.Task):
    supervisor._handle_bg_task_done(task)

def _format_local_links(text: str, username: str, session_id: str) -> str:
    return format_local_links(text, username, session_id)

def _format_thoughts_for_storage(text: str) -> str:
    return format_thought_blocks(text, is_streaming=False)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load index.html from {index_file}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load index.html")
