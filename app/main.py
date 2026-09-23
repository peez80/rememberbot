import os
import re
import asyncio
import logging
from contextlib import asynccontextmanager
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

from .core.config import AGY_DEFAULT_MODEL, AGY_DEFAULT_THINKING_EFFORT
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


async def validate_agy_default_configuration():
    """
    Validates the configured AGY default model and thinking effort at startup via a probe call to agy.
    Logs success with info or failure with warning and fallback.
    """
    if not AGY_DEFAULT_MODEL and not AGY_DEFAULT_THINKING_EFFORT:
        logger.debug("Keine abweichenden AGY Defaults für Modell oder Thinking Effort gesetzt. Startup-Validierung übersprungen.")
        return

    probe_cmd = ["agy", "--dangerously-skip-permissions"]
    if AGY_DEFAULT_MODEL:
        probe_cmd.extend(["--model", AGY_DEFAULT_MODEL])
    if AGY_DEFAULT_THINKING_EFFORT:
        probe_cmd.extend(["--effort", AGY_DEFAULT_THINKING_EFFORT])
    probe_cmd.extend(["--prompt", "ping"])

    try:
        process = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            logger.warning(
                f"Startup-Validierung von agy dauerte länger als 10s (Timeout). "
                f"Modell='{AGY_DEFAULT_MODEL}', Effort='{AGY_DEFAULT_THINKING_EFFORT}'."
            )
            return

        if process.returncode == 0:
            logger.info(
                f"Startup-Validierung der agy Default-Konfiguration erfolgreich: "
                f"Modell='{AGY_DEFAULT_MODEL}', Thinking Effort='{AGY_DEFAULT_THINKING_EFFORT}'."
            )
        else:
            stderr_str = stderr_bytes.decode('utf-8', errors='replace').strip()
            logger.warning(
                f"Startup-Validierung der agy Default-Konfiguration fehlgeschlagen "
                f"(Exit-Code {process.returncode}, Modell='{AGY_DEFAULT_MODEL}', Thinking Effort='{AGY_DEFAULT_THINKING_EFFORT}'): {stderr_str}. "
                "Verwende Fallback auf Standard-CLI-Verhalten."
            )
    except FileNotFoundError:
        logger.info("agy Executable nicht gefunden bei Startup-Validierung (Mock- oder Dev-Modus aktiv).")
    except Exception as e:
        logger.warning(
            f"Unerwarteter Fehler bei Startup-Validierung der agy-Konfiguration "
            f"(Modell='{AGY_DEFAULT_MODEL}', Thinking Effort='{AGY_DEFAULT_THINKING_EFFORT}'): {e}",
            exc_info=True
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("PYTEST_CURRENT_TEST") and os.getenv("TESTING") != "1":
        await validate_agy_default_configuration()
    yield


app = FastAPI(title="RememberBot", lifespan=lifespan)

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

class NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that serves files with Cache-Control: no-cache to enforce browser revalidation."""
    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = os.path.join(static_dir, "favicon.png")
    if not os.path.exists(favicon_path):
        logger.warning(f"Favicon not found at {favicon_path}")
        raise HTTPException(status_code=404, detail="Favicon not found")
    return FileResponse(favicon_path, headers={"Cache-Control": "no-cache"})

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

def _get_static_asset_version(relative_path: str) -> str:
    """Returns the mtime timestamp of a static asset as a cache-busting version string."""
    try:
        full_path = os.path.join(static_dir, relative_path)
        return str(int(os.path.getmtime(full_path)))
    except OSError:
        return "1"

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            content = f.read()

        styles_v = _get_static_asset_version("styles.css")
        main_v = _get_static_asset_version(os.path.join("js", "main.js"))
        favicon_v = _get_static_asset_version("favicon.png")

        content = re.sub(r'href="/static/styles\.css(\?v=[^"\'\s]*)?"', f'href="/static/styles.css?v={styles_v}"', content)
        content = re.sub(r'src="/static/js/main\.js(\?v=[^"\'\s]*)?"', f'src="/static/js/main.js?v={main_v}"', content)
        content = re.sub(r'href="/static/favicon\.png(\?v=[^"\'\s]*)?"', f'href="/static/favicon.png?v={favicon_v}"', content)

        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        logger.error(f"Failed to load index.html from {index_file}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load index.html")
