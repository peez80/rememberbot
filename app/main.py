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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

import logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)

from .agy_client import agy_client
from .storage import (
    init_storage, DATA_DIR,
    create_session, get_sessions, get_session_history,
    save_session_message, update_session_title, delete_session,
    get_session_settings, update_session_settings, init_user_storage,
    get_session_icon_path, get_session_icon_target_path,
    cleanup_deleted_sessions
)

app = FastAPI(title="RememberBot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage on startup
init_storage()

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(static_dir, "favicon.png"))

# --- Authentication & Sessions ---

def get_valid_users():
    users_file = os.path.join(DATA_DIR, "config", "users.json")
    if os.path.exists(users_file):
        try:
            with open(users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
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
        except Exception:
            ACTIVE_SESSIONS = {}

def save_auth_sessions():
    try:
        with open(AUTH_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(ACTIVE_SESSIONS, f)
    except Exception:
        pass

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

def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

# --- Endpoints ---

class ChatMessage(BaseModel):
    text: str
    is_user: bool
    image_urls: List[str] = []
    images: Optional[List[dict]] = None
    timestamp: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open(os.path.join(static_dir, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

# Auth Endpoints
@app.post("/api/auth/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
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
        return {"success": True}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_token]
        save_auth_sessions()
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
    return {"id": session_id, "title": "Neuer Chat"}

@app.get("/api/sessions")
async def get_sessions_endpoint(username: str = Depends(get_current_user)):
    fire_and_forget(cleanup_deleted_sessions(username))
    return await get_sessions(username)

@app.get("/api/sessions/{session_id}/status")
async def get_session_status_endpoint(session_id: str, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    is_processing = (username, session_id) in _active_chat_sessions
    return {"id": session_id, "is_processing": is_processing}

@app.get("/api/sessions/{session_id}/history", response_model=List[ChatMessage])
async def get_history_endpoint(session_id: str, response: Response, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    history = await get_session_history(username, session_id)
    if get_session_icon_path(username, session_id) is None:
        sessions = await get_sessions(username)
        session_metadata = next((s for s in sessions if s["id"] == session_id), None)
        if session_metadata and session_metadata.get("title") != "Neuer Chat":
            target_path = get_session_icon_target_path(username, session_id)
            fire_and_forget(agy_client.generate_chat_icon(session_metadata["title"], target_path))
            
    is_processing = (username, session_id) in _active_chat_sessions
    response.headers["X-Is-Processing"] = "true" if is_processing else "false"
    return history

@app.get("/api/sessions/{session_id}/icon")
async def get_session_icon(session_id: str, username: str = Depends(get_current_user)):
    icon_path = get_session_icon_path(username, session_id)
    if icon_path and os.path.exists(icon_path):
        return FileResponse(icon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Icon not found")

@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    await delete_session(username, session_id)
    return {"success": True}

class SessionSettingsRequest(BaseModel):
    prompt: str
    include_gps: bool = False

@app.get("/api/sessions/{session_id}/settings")
async def get_settings_endpoint(session_id: str, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    settings = await get_session_settings(username, session_id)
    return settings

@app.put("/api/sessions/{session_id}/settings")
async def update_settings_endpoint(session_id: str, req: SessionSettingsRequest, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    await update_session_settings(username, session_id, req.prompt, req.include_gps)
    return {"success": True}

class SessionTitleRequest(BaseModel):
    title: str

@app.put("/api/sessions/{session_id}/title")
async def update_title_endpoint(session_id: str, req: SessionTitleRequest, username: str = Depends(get_current_user)):
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")
        
    await update_session_title(username, session_id, req.title)
    target_path = get_session_icon_target_path(username, session_id)
    fire_and_forget(agy_client.generate_chat_icon(req.title, target_path))
    return {"success": True}

@app.post("/api/sessions/{session_id}/chat")
async def chat_endpoint(
    session_id: str,
    request: Request,
    message: str = Form(""),
    location: str = Form(""),
    stream: str = Form("false"),
    images: List[UploadFile] = File([]),
    username: str = Depends(get_current_user)
):
    # Verify session exists
    sessions = await get_sessions(username)
    session_metadata = next((s for s in sessions if s["id"] == session_id), None)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    session_key = (username, session_id)
    _active_chat_sessions.add(session_key)

    valid_images = [img for img in images if img.filename]
    if len(valid_images) > 5:
        _active_chat_sessions.discard(session_key)
        return JSONResponse(status_code=400, content={"error": "Maximal 5 Bilder erlaubt"})
        
    display_msg = message
    image_paths = []
    image_urls = []
    images_data = []
    
    try:
        if valid_images:
            # Ensure uploads dir exists for user
            user_uploads_dir = os.path.join(DATA_DIR, username, "sessions", session_id, "uploads")
            os.makedirs(user_uploads_dir, exist_ok=True)
            
            for img in valid_images:
                # Save uploaded image permanently
                ext = os.path.splitext(img.filename)[1].lower() if img.filename else ""
                if not ext or ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
                    ext = ".jpg"
                filename = f"{uuid.uuid4().hex}{ext}"
                img_path = os.path.join(user_uploads_dir, filename)
                
                contents = await img.read()
                
                width, height = 0, 0
                try:
                    with Image.open(io.BytesIO(contents)) as pil_img:
                        width, height = pil_img.size
                except Exception as e:
                    logging.warning(f"Could not read image dimensions: {e}")

                with open(img_path, "wb") as f:
                    f.write(contents)
                    
                image_paths.append(img_path)
                url = f"/uploads/{session_id}/{filename}"
                image_urls.append(url)
                images_data.append({"url": url, "width": width, "height": height})
                
            if not display_msg:
                display_msg = f"[{len(valid_images)} Bild(er) gesendet]"
            else:
                display_msg += f" [{len(valid_images)} Bild(er) angehängt]"
    except Exception:
        _active_chat_sessions.discard(session_key)
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
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await save_session_message(username, session_id, user_msg_data)

    # Auto-rename if this is the first message and title is default
    if is_first_message and session_metadata.get("title") == "Neuer Chat":
        title_source = message if message else "Foto-Notiz"
        new_title = (title_source[:27] + "...") if len(title_source) > 30 else title_source
        await update_session_title(username, session_id, new_title)
        target_path = get_session_icon_target_path(username, session_id)
        fire_and_forget(agy_client.generate_chat_icon(new_title, target_path))

    is_stream = stream.lower() == "true" or "text/event-stream" in request.headers.get("accept", "")

    if is_stream:
        async def sse_generator():
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
                    system_prompt=combined_prompt,
                    cwd=user_data_dir
                ):
                    if event.get("type") == "delta":
                        text_chunk = event.get("text", "")
                        full_reply += text_chunk
                        yield f"data: {json.dumps({'type': 'delta', 'text': text_chunk})}\n\n"
                    elif event.get("type") == "done":
                        full_reply = event.get("reply", full_reply)
                        context_truncated = event.get("context_truncated", False)

                # --- Fix local file links ---
                def replace_local_links(match):
                    text = match.group(1)
                    href = match.group(2)
                    if href.startswith("file://"):
                        href = href[7:]
                    data_prefix = f"/app/data/{username}/sessions/{session_id}/data/"
                    uploads_prefix = f"/app/data/{username}/sessions/{session_id}/uploads/"
                    if href.startswith(data_prefix):
                        rel_path = href[len(data_prefix):]
                        encoded = urllib.parse.quote(rel_path, safe='/')
                        return f"[{text}](/app/data/{username}/{session_id}/data/{encoded})"
                    if href.startswith(uploads_prefix):
                        rel_path = href[len(uploads_prefix):]
                        encoded = urllib.parse.quote(rel_path, safe='/')
                        return f"[{text}](/uploads/{session_id}/{encoded})"
                    if not href.startswith(("http", "/", "data:", "#", "mailto:")):
                        encoded = urllib.parse.quote(href, safe='/')
                        return f"[{text}](/app/data/{username}/{session_id}/data/{encoded})"
                    return match.group(0)

                full_reply = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_local_links, full_reply)

                # Format thoughts if needed for final history storage
                def replace_thought(match):
                    content = match.group(1).strip()
                    return f"<details class='ai-reasoning'>\n  <summary>Gedankengang der KI</summary>\n  <div class='reasoning-content'>\n{content}\n  </div>\n</details>\n"
                
                saved_reply = re.sub(r'<thought>(.*?)</thought>', replace_thought, full_reply, flags=re.DOTALL).strip()
                if not saved_reply:
                    saved_reply = full_reply

                ai_msg_data = {
                    "text": saved_reply, 
                    "is_user": False,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await asyncio.shield(save_session_message(username, session_id, ai_msg_data))

                yield f"data: {json.dumps({'type': 'done', 'reply': saved_reply, 'context_truncated': context_truncated, 'timestamp': ai_msg_data['timestamp']})}\n\n"
            except Exception as e:
                logging.error(f"Error in SSE stream: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': 'Fehler bei der Antwortgenerierung'})}\n\n"
            finally:
                _active_chat_sessions.discard(session_key)

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
                system_prompt=combined_prompt,
                cwd=user_data_dir
            )
                
            ai_reply = parsed_response.get("reply", "Entschuldigung, ich habe das nicht verstanden.")
            context_truncated = parsed_response.get("context_truncated", False)
            
            # --- Fix local file links ---
            def replace_local_links(match):
                text = match.group(1)
                href = match.group(2)
                
                # Bereinige file:// Präfixe
                if href.startswith("file://"):
                    href = href[7:]
                    
                data_prefix = f"/app/data/{username}/sessions/{session_id}/data/"
                uploads_prefix = f"/app/data/{username}/sessions/{session_id}/uploads/"
                
                # Korrigiere KI-generierte absolute Pfade in die korrekten API-Download-Routen
                if href.startswith(data_prefix):
                    rel_path = href[len(data_prefix):]
                    encoded = urllib.parse.quote(rel_path, safe='/')
                    return f"[{text}](/app/data/{username}/{session_id}/data/{encoded})"
                    
                if href.startswith(uploads_prefix):
                    rel_path = href[len(uploads_prefix):]
                    encoded = urllib.parse.quote(rel_path, safe='/')
                    return f"[{text}](/uploads/{session_id}/{encoded})"
                    
                # Wenn die KI (korrekterweise) nur den Dateinamen zurückgibt
                if not href.startswith(("http", "/", "data:", "#", "mailto:")):
                    encoded = urllib.parse.quote(href, safe='/')
                    return f"[{text}](/app/data/{username}/{session_id}/data/{encoded})"
                    
                return match.group(0)

            ai_reply = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_local_links, ai_reply)
            # --- End fix ---

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
        finally:
            _active_chat_sessions.discard(session_key)

    # Shield the entire AI processing and saving pipeline against connection drops
    task = asyncio.create_task(process_and_save())
    try:
        result = await asyncio.shield(task)
        return JSONResponse(content=result)
    except asyncio.CancelledError:
        # If the client disconnected, FastAPI cancels this endpoint request.
        # But `asyncio.shield` ensures `task` continues running in the background.
        # We raise the exception to let FastAPI cleanup properly.
        raise

# Secure Downloads Endpoint for AI Generated files
@app.get("/app/data/{username}/{session_id}/data/{file_path:path}")
async def download_file(username: str, session_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    if username != current_user:
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
        raise HTTPException(status_code=400, detail="Invalid path")
        
    if os.path.isfile(full_path):
        return FileResponse(full_path, filename=os.path.basename(full_path))
    raise HTTPException(status_code=404, detail="File not found")

# Secure Uploads Endpoint
@app.get("/uploads/{session_id}/{filename}")
async def get_upload(session_id: str, filename: str, username: str = Depends(get_current_user)):
    safe_filename = os.path.basename(filename)
    safe_session_id = os.path.basename(session_id)
    file_path = os.path.join(DATA_DIR, username, "sessions", safe_session_id, "uploads", safe_filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")
