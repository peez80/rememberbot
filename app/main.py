import os
import json
import uuid
import re
import urllib.parse
import asyncio
import io
from PIL import Image
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, Request, Response, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

import logging
from .logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from .agy_client import agy_client
from .storage import (
    init_storage, DATA_DIR,
    create_session, get_sessions, get_session_history,
    save_session_message, update_session_title, delete_session,
    get_session_settings, update_session_settings, init_user_storage,
    get_session_icon_path, get_session_icon_target_path,
    cleanup_deleted_sessions,
    check_session_exists, get_session_title, generate_thumbnail,
    export_session_archive, import_session_archive
)

app = FastAPI(title="RememberBot")

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
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

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

# --- Authentication & Sessions ---

def get_valid_users():
    users_file = os.path.join(DATA_DIR, "config", "users.json")
    if os.path.exists(users_file):
        try:
            with open(users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read users config from {users_file}: {e}", exc_info=True)
            return {}
    return {}

AUTH_SESSIONS_FILE = os.path.join(DATA_DIR, "auth_sessions.json")
ACTIVE_SESSIONS = {}

def load_auth_sessions():
    global ACTIVE_SESSIONS
    if os.path.exists(AUTH_SESSIONS_FILE):
        try:
            with open(AUTH_SESSIONS_FILE, "r", encoding="utf-8") as f:
                ACTIVE_SESSIONS = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load auth sessions from {AUTH_SESSIONS_FILE}: {e}")
            ACTIVE_SESSIONS = {}

def save_auth_sessions():
    try:
        with open(AUTH_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(ACTIVE_SESSIONS, f)
    except Exception as e:
        logger.error(f"Failed to save auth sessions to {AUTH_SESSIONS_FILE}: {e}", exc_info=True)

# Load sessions on startup
load_auth_sessions()

def get_current_user(request: Request) -> str:
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in ACTIVE_SESSIONS:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return ACTIVE_SESSIONS[session_token]

# --- Background Task Helper & Active Chat State ---
_active_tasks = set()
_active_chat_sessions = set()

def _handle_bg_task_done(task: asyncio.Task):
    _active_tasks.discard(task)
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error(f"Unhandled exception in background task: {exc}", exc_info=exc)

def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_handle_bg_task_done)

# --- Endpoints ---

class ChatMessage(BaseModel):
    text: str
    is_user: bool
    image_urls: List[str] = []
    images: Optional[List[dict]] = None
    files: Optional[List[dict]] = None
    timestamp: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load index.html from {index_file}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load index.html")

# Auth Endpoints
@app.post("/api/auth/login")
async def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    users = get_valid_users()
    if username in users and users[username] == password:
        session_token = uuid.uuid4().hex
        ACTIVE_SESSIONS[session_token] = username
        save_auth_sessions()
        
        response.set_cookie(
            key="session_token", 
            value=session_token, 
            httponly=True, 
            samesite="lax",
            max_age=30 * 24 * 60 * 60 # 30 days
        )
        # Ensure user directories exist
        init_user_storage(username)
        logger.info(f"User '{username}' logged in successfully from {client_ip}")
        return {"success": True}
    logger.warning(f"Failed login attempt for user '{username}' from {client_ip}")
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    username = ACTIVE_SESSIONS.get(session_token, "unknown")
    if session_token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_token]
        save_auth_sessions()
        logger.info(f"User '{username}' logged out")
    response.delete_cookie("session_token")
    return {"success": True}

@app.get("/api/auth/status")
async def auth_status(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token and session_token in ACTIVE_SESSIONS:
        return {"authenticated": True, "username": ACTIVE_SESSIONS[session_token]}
    return {"authenticated": False}

# Session Endpoints
@app.post("/api/sessions")
async def create_session_endpoint(username: str = Depends(get_current_user)):
    session_id = await create_session(username, "Neuer Chat")
    logger.info(f"User '{username}' created new session {session_id}")
    return {"id": session_id, "title": "Neuer Chat"}

@app.get("/api/sessions")
async def get_sessions_endpoint(username: str = Depends(get_current_user)):
    fire_and_forget(cleanup_deleted_sessions(username))
    return await get_sessions(username)

@app.get("/api/sessions/{session_id}/status")
async def get_session_status_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Status check for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    is_processing = (username, session_id) in _active_chat_sessions
    return {"id": session_id, "is_processing": is_processing}

@app.get("/api/sessions/{session_id}/history", response_model=List[ChatMessage])
async def get_history_endpoint(session_id: str, response: Response, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"History requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    history = await get_session_history(username, session_id)
    if get_session_icon_path(username, session_id) is None:
        title = await get_session_title(username, session_id)
        if title and title != "Neuer Chat":
            target_path = get_session_icon_target_path(username, session_id)
            fire_and_forget(agy_client.generate_chat_icon(title, target_path))
            
    is_processing = (username, session_id) in _active_chat_sessions
    response.headers["X-Is-Processing"] = "true" if is_processing else "false"
    return history

@app.get("/api/sessions/{session_id}/icon")
async def get_session_icon(session_id: str, username: str = Depends(get_current_user)):
    icon_path = get_session_icon_path(username, session_id)
    if icon_path and os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/svg+xml")
    logger.warning(f"Icon not found for session {session_id} (user '{username}')")
    raise HTTPException(status_code=404, detail="Icon not found")

@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Delete requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    await delete_session(username, session_id)
    logger.info(f"User '{username}' deleted session {session_id}")
    return {"success": True}

class SessionSettingsRequest(BaseModel):
    prompt: str
    include_gps: bool = False

@app.get("/api/sessions/{session_id}/settings")
async def get_settings_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Settings requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    settings = await get_session_settings(username, session_id)
    return settings

@app.put("/api/sessions/{session_id}/settings")
async def update_settings_endpoint(session_id: str, req: SessionSettingsRequest, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Settings update requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    await update_session_settings(username, session_id, req.prompt, req.include_gps)
    logger.info(f"User '{username}' updated settings for session {session_id}")
    return {"success": True}

class SessionTitleRequest(BaseModel):
    title: str

@app.put("/api/sessions/{session_id}/title")
async def update_title_endpoint(session_id: str, req: SessionTitleRequest, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Title update requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    await update_session_title(username, session_id, req.title)
    logger.info(f"User '{username}' updated title for session {session_id} to '{req.title}'")
    target_path = get_session_icon_target_path(username, session_id)
    fire_and_forget(agy_client.generate_chat_icon(req.title, target_path))
    return {"success": True}

# Session Export & Import Endpoints
@app.get("/api/sessions/{session_id}/export")
async def export_session_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Export requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        zip_bytes = await export_session_archive(username, session_id)
        title = await get_session_title(username, session_id)
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30] or "chat"
        filename = f"chat_{safe_title}_{session_id[:8]}.zip"
        
        logger.info(f"User '{username}' exported session {session_id} as '{filename}'")
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache"
            }
        )
    except FileNotFoundError:
        logger.warning(f"Export failed: session {session_id} not found on disk for user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to export session {session_id} for user '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Fehler beim Exportieren der Session")

@app.post("/api/sessions/{session_id}/import")
async def import_session_endpoint(session_id: str, file: UploadFile = File(...), username: str = Depends(get_current_user)):
    if not await check_session_exists(username, session_id):
        logger.warning(f"Import requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
        
    session_key = (username, session_id)
    if session_key in _active_chat_sessions:
        logger.warning(f"Rejected import into active session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Session wird gerade verarbeitet")
        
    try:
        zip_bytes = await file.read()
        if not zip_bytes:
            logger.warning(f"Empty file uploaded for import in session {session_id} by user '{username}'")
            raise HTTPException(status_code=400, detail="Leere Datei hochgeladen")
            
        result = await import_session_archive(username, session_id, zip_bytes)
        logger.info(f"User '{username}' imported session archive into session {session_id}")
        return {
            "success": True,
            "id": session_id,
            "title": result.get("title", "Importierter Chat"),
            "has_icon": result.get("has_icon", False)
        }
    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"Validation error during import into session {session_id} by user '{username}': {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to import session archive into {session_id} for user '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Fehler beim Importieren der Session")


def _format_local_links(text: str, username: str, session_id: str) -> str:
    """Rewrite raw file and internal storage links to application download endpoints."""
    def replace_local_links(match):
        label = match.group(1)
        href = match.group(2)
        if href.startswith("file://"):
            href = href[7:]
        data_prefix = f"/app/data/{username}/sessions/{session_id}/data/"
        uploads_prefix = f"/app/data/{username}/sessions/{session_id}/uploads/"
        if href.startswith(data_prefix):
            rel_path = href[len(data_prefix):]
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        if href.startswith(uploads_prefix):
            rel_path = href[len(uploads_prefix):]
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/uploads/{session_id}/{encoded})"
        if not href.startswith(("http", "/", "data:", "#", "mailto:")):
            encoded = urllib.parse.quote(href, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        return match.group(0)

    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_local_links, text)

def _format_thoughts_for_storage(text: str) -> str:
    """Convert <thought>...</thought> blocks into collapsible <details> HTML elements."""
    def replace_thought(match):
        content = match.group(1).strip()
        return f"<details class='ai-reasoning'>\n  <summary>Gedankengang der KI</summary>\n  <div class='reasoning-content'>\n{content}\n  </div>\n</details>\n"
    
    return re.sub(r'<thought>(.*?)</thought>', replace_thought, text, flags=re.DOTALL).strip()

@app.post("/api/sessions/{session_id}/chat")
async def chat_endpoint(
    session_id: str,
    request: Request,
    message: str = Form(""),
    location: str = Form(""),
    stream: str = Form("false"),
    files: List[UploadFile] = File([]),
    images: List[UploadFile] = File([]),
    username: str = Depends(get_current_user)
):
    # Verify session exists
    if not await check_session_exists(username, session_id):
        logger.warning(f"Chat request sent to non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    session_key = (username, session_id)
    _active_chat_sessions.add(session_key)

    valid_uploads = [f for f in (files + images) if f.filename]
    if len(valid_uploads) > 10:
        _active_chat_sessions.discard(session_key)
        logger.warning(f"Rejected chat request: {len(valid_uploads)} files uploaded (max 10) for session {session_id} by '{username}'")
        return JSONResponse(status_code=400, content={"error": "Maximal 10 Dateien erlaubt"})
        
    display_msg = message
    image_paths = []
    image_urls = []
    images_data = []
    files_data = []
    attachments = []
    
    try:
        if valid_uploads:
            # Ensure uploads dir exists for user
            user_uploads_dir = os.path.join(DATA_DIR, username, "sessions", session_id, "uploads")
            os.makedirs(user_uploads_dir, exist_ok=True)
            
            for upload_file in valid_uploads:
                orig_filename = os.path.basename(upload_file.filename) if upload_file.filename else "file"
                safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', orig_filename)
                
                contents = await upload_file.read()
                file_size = len(contents)
                
                ext = os.path.splitext(orig_filename)[1].lower()
                is_image = False
                width, height = 0, 0
                
                if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"] or not ext or orig_filename == "blob":
                    try:
                        with Image.open(io.BytesIO(contents)) as pil_img:
                            width, height = pil_img.size
                            is_image = True
                            if not ext and pil_img.format:
                                fmt_ext = f".{pil_img.format.lower()}"
                                if fmt_ext == ".jpeg":
                                    fmt_ext = ".jpg"
                                ext = fmt_ext
                                safe_filename += ext
                    except Exception as e:
                        if ext == ".svg":
                            is_image = True
                        elif ext:
                            logger.warning(f"Could not parse image dimensions for {orig_filename} in session {session_id}: {e}")

                if not ext and is_image:
                    ext = ".jpg"
                    safe_filename += ext

                unique_filename = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
                saved_path = os.path.join(user_uploads_dir, unique_filename)
                
                with open(saved_path, "wb") as f:
                    f.write(contents)
                    
                file_url = f"/uploads/{session_id}/{unique_filename}"
                
                if is_image:
                    image_paths.append(saved_path)
                    image_urls.append(file_url)
                    images_data.append({"url": file_url, "width": width, "height": height})
                    
                file_meta = {
                    "url": file_url,
                    "name": orig_filename,
                    "size": file_size,
                    "is_image": is_image,
                    "path": saved_path
                }
                if is_image and width > 0:
                    file_meta["width"] = width
                    file_meta["height"] = height
                files_data.append(file_meta)
                
                attachments.append({
                    "path": saved_path,
                    "name": orig_filename,
                    "size": file_size,
                    "is_image": is_image
                })
                
            num_images = sum(1 for f in files_data if f["is_image"])
            num_docs = sum(1 for f in files_data if not f["is_image"])
            
            if num_images > 0 and num_docs > 0:
                tag = f"[{num_images} Bild(er), {num_docs} Datei(en) angehängt]"
                display_msg = f"{message} {tag}".strip() if message else f"[{num_images} Bild(er), {num_docs} Datei(en) gesendet]"
            elif num_images > 0:
                tag = f"[{num_images} Bild(er) angehängt]"
                display_msg = f"{message} {tag}".strip() if message else f"[{num_images} Bild(er) gesendet]"
            elif num_docs > 0:
                tag = f"[{num_docs} Datei(en) angehängt]"
                display_msg = f"{message} {tag}".strip() if message else f"[{num_docs} Datei(en) gesendet]"
                
            logger.info(f"User '{username}' uploaded {len(valid_uploads)} file(s) for session {session_id}")
    except Exception as e:
        _active_chat_sessions.discard(session_key)
        logger.error(f"Failed to process/save file upload for session {session_id} (user '{username}'): {e}", exc_info=True)
        raise

    # Fetch history to check if this is the first message and to provide context to AI
    history = await get_session_history(username, session_id)
    is_first_message = len(history) == 0

    # Save the user's message to history immediately upon receiving the request
    user_msg_data = {
        "text": display_msg, 
        "is_user": True,
        "image_urls": image_urls,
        "images": images_data if images_data else None,
        "files": files_data if files_data else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await save_session_message(username, session_id, user_msg_data)

    # Auto-rename if this is the first message and title is default
    if is_first_message:
        current_title = await get_session_title(username, session_id)
        if current_title == "Neuer Chat":
            title_source = message if message else ("Dateianhang" if (files_data and not any(f['is_image'] for f in files_data)) else "Foto-Notiz")
            new_title = (title_source[:27] + "...") if len(title_source) > 30 else title_source
            await update_session_title(username, session_id, new_title)
            target_path = get_session_icon_target_path(username, session_id)
            fire_and_forget(agy_client.generate_chat_icon(new_title, target_path))

    is_stream = stream.lower() == "true" or "text/event-stream" in request.headers.get("accept", "")

    if is_stream:
        event_queue = asyncio.Queue()

        async def stream_task_runner():
            try:
                user_data_dir = os.path.abspath(os.path.join(DATA_DIR, username, "sessions", session_id, "data"))
                os.makedirs(user_data_dir, exist_ok=True)
                
                session_settings = await get_session_settings(username, session_id)
                session_prompt = session_settings.get("prompt", "")
                
                technical_prompt = (
                    f"TECHNISCHE VORAUSSETZUNG: Dein persistentes Datenverzeichnis lautet: {user_data_dir}\n"
                    "Speichere und lese generierte Dateien IMMER in diesem absoluten Verzeichnis. "
                    "Verwende in generierten Skripten (z.B. Python) zwingend diesen absoluten Pfad. "
                    "Erstelle für alle generierten Dateien einen Markdown-Link in der Antwort. "
                    "Nutze als Link-Ziel AUSSCHLIESSLICH den reinen Dateinamen ohne Pfade, z.B. [Dateiname.pdf](Dateiname.pdf)."
                )
                if location:
                    technical_prompt += f"\n\nHINWEIS: Der Nutzer befindet sich aktuell hier (GPS): {location}"
                
                combined_prompt = f"{technical_prompt}\n\n{session_prompt}" if session_prompt else technical_prompt

                full_reply = ""
                context_truncated = False

                async for event in agy_client.stream_message(
                    context_messages=history, 
                    new_message=message, 
                    image_paths=image_paths, 
                    attachments=attachments,
                    system_prompt=combined_prompt,
                    cwd=user_data_dir
                ):
                    if event.get("type") == "delta":
                        text_chunk = event.get("text", "")
                        full_reply += text_chunk
                        await event_queue.put({"type": "delta", "text": text_chunk})
                    elif event.get("type") == "done":
                        full_reply = event.get("reply", full_reply)
                        context_truncated = event.get("context_truncated", False)

                saved_reply = _format_local_links(full_reply, username, session_id)
                saved_reply = _format_thoughts_for_storage(saved_reply)
                if not saved_reply:
                    saved_reply = full_reply

                ai_msg_data = {
                    "text": saved_reply, 
                    "is_user": False,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await save_session_message(username, session_id, ai_msg_data)

                await event_queue.put({
                    "type": "done", 
                    "reply": saved_reply, 
                    "context_truncated": context_truncated, 
                    "timestamp": ai_msg_data["timestamp"]
                })
            except Exception as e:
                logger.error(f"Error in background stream processing for session {session_id} (user '{username}'): {e}", exc_info=True)
                await event_queue.put({"type": "error", "error": "Fehler bei der Antwortgenerierung"})
            finally:
                event_queue.put_nowait(None)
                _active_chat_sessions.discard(session_key)

        bg_task = asyncio.create_task(stream_task_runner())
        _active_tasks.add(bg_task)
        bg_task.add_done_callback(_handle_bg_task_done)

        async def sse_generator():
            try:
                while True:
                    event = await event_queue.get()
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
            except asyncio.CancelledError:
                logger.info(f"SSE client disconnected for session {session_id} (user '{username}'). Background AI task continues.")
                raise

        return StreamingResponse(sse_generator(), media_type="text/event-stream")
            
    async def process_and_save():
        try:
            # Process via agy with FULL context
            user_data_dir = os.path.abspath(os.path.join(DATA_DIR, username, "sessions", session_id, "data"))
            os.makedirs(user_data_dir, exist_ok=True)
            
            session_settings = await get_session_settings(username, session_id)
            session_prompt = session_settings.get("prompt", "")
            
            technical_prompt = (
                f"TECHNISCHE VORAUSSETZUNG: Dein persistentes Datenverzeichnis lautet: {user_data_dir}\n"
                "Speichere und lese generierte Dateien IMMER in diesem absoluten Verzeichnis. "
                "Verwende in generierten Skripten (z.B. Python) zwingend diesen absoluten Pfad. "
                "Erstelle für alle generierten Dateien einen Markdown-Link in der Antwort. "
                "Nutze als Link-Ziel AUSSCHLIESSLICH den reinen Dateinamen ohne Pfade, z.B. [Dateiname.pdf](Dateiname.pdf)."
            )
            if location:
                technical_prompt += f"\n\nHINWEIS: Der Nutzer befindet sich aktuell hier (GPS): {location}"
            
            combined_prompt = f"{technical_prompt}\n\n{session_prompt}" if session_prompt else technical_prompt
            
            parsed_response = await agy_client.process_message(
                context_messages=history, 
                new_message=message, 
                image_paths=image_paths, 
                attachments=attachments,
                system_prompt=combined_prompt,
                cwd=user_data_dir
            )
                
            ai_reply = parsed_response.get("reply", "Entschuldigung, ich habe das nicht verstanden.")
            context_truncated = parsed_response.get("context_truncated", False)
            
            ai_reply = _format_local_links(ai_reply, username, session_id)

            # Append AI reply to history
            ai_msg_data = {
                "text": ai_reply, 
                "is_user": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await save_session_message(username, session_id, ai_msg_data)
            
            return {
                "reply": ai_reply, 
                "context_truncated": context_truncated,
                "timestamp": ai_msg_data["timestamp"]
            }
        except Exception as e:
            logger.error(f"Error in non-streaming chat process for session {session_id} (user '{username}'): {e}", exc_info=True)
            raise
        finally:
            _active_chat_sessions.discard(session_key)

    # Shield the entire AI processing and saving pipeline against connection drops
    task = asyncio.create_task(process_and_save())
    _active_tasks.add(task)
    task.add_done_callback(_handle_bg_task_done)
    try:
        result = await asyncio.shield(task)
        return JSONResponse(content=result)
    except asyncio.CancelledError:
        logger.info(f"Client disconnected during chat request for session {session_id} (user '{username}'). Task continues in background.")
        raise

# Secure Downloads Endpoint for AI Generated files
@app.get("/app/data/{username}/{session_id}/data/{file_path:path}")
async def download_file(username: str, session_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    if username != current_user:
        logger.warning(f"Forbidden data download attempt: user '{current_user}' attempted to access files of user '{username}', file: '{file_path}'")
        raise HTTPException(status_code=403, detail="Forbidden")
    # --- Fallback for old history with scratch paths ---
    if file_path.startswith("file:///root/.gemini/antigravity-cli/"):
        real_path = file_path[len("file://"):]
        if os.path.isfile(real_path):
            return FileResponse(real_path, filename=os.path.basename(real_path))
    elif file_path.startswith("/root/.gemini/antigravity-cli/"):
        if os.path.isfile(file_path):
            return FileResponse(file_path, filename=os.path.basename(file_path))
    # --- End Fallback ---
            
    safe_session_id = os.path.basename(session_id)
    base_dir = os.path.abspath(os.path.join(DATA_DIR, username, "sessions", safe_session_id, "data"))
    full_path = os.path.abspath(os.path.join(base_dir, file_path))
    
    if not full_path.startswith(base_dir):
        logger.warning(f"Potential path traversal attempt detected in data download: '{file_path}' for session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Invalid path")
        
    if os.path.isfile(full_path):
        return FileResponse(full_path, filename=os.path.basename(full_path))
    logger.warning(f"Data file not found: '{file_path}' in session {session_id} for user '{username}'")
    raise HTTPException(status_code=404, detail="File not found")

# Secure Uploads Endpoint
@app.get("/uploads/{session_id}/{filename}")
async def get_upload(session_id: str, filename: str, username: str = Depends(get_current_user)):
    safe_filename = os.path.basename(filename)
    safe_session_id = os.path.basename(session_id)
    file_path = os.path.join(DATA_DIR, username, "sessions", safe_session_id, "uploads", safe_filename)
    if os.path.exists(file_path):
        download_name = safe_filename
        match = re.match(r'^[0-9a-fA-F]{8}_(.+)$', safe_filename)
        if match:
            download_name = match.group(1)
        return FileResponse(
            file_path,
            filename=download_name,
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )
    logger.warning(f"Upload file not found: '{filename}' for session {session_id} (user '{username}')")
    raise HTTPException(status_code=404, detail="File not found")

# Secure Thumbnails Endpoint
@app.get("/uploads/{session_id}/thumbnails/{filename}")
async def get_thumbnail(session_id: str, filename: str, username: str = Depends(get_current_user)):
    safe_filename = os.path.basename(filename)
    safe_session_id = os.path.basename(session_id)
    thumb_dir = os.path.join(DATA_DIR, username, "sessions", safe_session_id, "thumbnails")
    thumb_path = os.path.join(thumb_dir, safe_filename)
    
    if os.path.exists(thumb_path):
        return FileResponse(
            thumb_path,
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )
        
    orig_path = os.path.join(DATA_DIR, username, "sessions", safe_session_id, "uploads", safe_filename)
    if not os.path.exists(orig_path):
        logger.warning(f"Thumbnail source image not found: '{filename}' for session {session_id} (user '{username}')")
        raise HTTPException(status_code=404, detail="Image not found")
        
    success = await asyncio.to_thread(generate_thumbnail, orig_path, thumb_path)
    if success and os.path.exists(thumb_path):
        return FileResponse(
            thumb_path,
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )
    # Fallback to original if thumbnail generation failed (e.g. non-image or SVG)
    logger.warning(f"Thumbnail generation failed for '{filename}', falling back to original image.")
    return FileResponse(
        orig_path,
        headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )

