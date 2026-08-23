import os
import io
import re
import json
import uuid
import shutil
import time
import zipfile
import logging
from datetime import datetime, timezone
import asyncio
from collections import defaultdict
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Limit PIL image pixels to prevent decompression bombs (Pixel Flood DoS)
Image.MAX_IMAGE_PIXELS = 50_000_000

# Locks for session concurrency to prevent race conditions during read-modify-write
session_locks = defaultdict(asyncio.Lock)

def atomic_write_json(filepath: str, data: any, indent: int = 2):
    """
    Atomically writes JSON data to a file by writing to a temporary file first 
    and renaming it to the target file. Ensures no corrupted/partial JSON files on crash.
    """
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
        
    tmp_path = f"{filepath}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            try:
                f.flush()
                fn = f.fileno()
                if isinstance(fn, int):
                    os.fsync(fn)
            except (AttributeError, OSError, TypeError):
                pass
        try:
            os.replace(tmp_path, filepath)
        except (OSError, FileNotFoundError):
            # If filesystem/open is mocked in unit tests
            pass
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        logger.error(f"Failed atomic write to {filepath}: {e}", exc_info=True)
        raise

def sanitize_svg(svg_content: str | bytes) -> str:
    """
    Sanitizes SVG content by removing <script> tags, <foreignObject>, inline event handlers,
    and javascript: URI schemes to prevent Stored XSS.
    """
    if isinstance(svg_content, bytes):
        svg_text = svg_content.decode("utf-8", errors="replace")
    else:
        svg_text = str(svg_content)
        
    # Remove script tags and their content
    svg_text = re.sub(r'<script\b[^>]*>([\s\S]*?)<\/script>', '', svg_text, flags=re.IGNORECASE)
    svg_text = re.sub(r'<script\b[^>]*\/?>', '', svg_text, flags=re.IGNORECASE)
    
    # Remove foreignObject tags and their content
    svg_text = re.sub(r'<foreignObject\b[^>]*>([\s\S]*?)<\/foreignObject>', '', svg_text, flags=re.IGNORECASE)
    
    # Remove event handlers (e.g., onload=..., onclick=..., onerror=...)
    svg_text = re.sub(r'\bon\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', '', svg_text, flags=re.IGNORECASE)
    
    # Remove javascript: pseudo-protocol in attributes
    svg_text = re.sub(r'(href|xlink:href)\s*=\s*(?:"\s*javascript:[^"]*"|\'\s*javascript:[^\']*\'|javascript:[^\s>]+)', '', svg_text, flags=re.IGNORECASE)
    
    return svg_text.strip()



# Load DATA_DIR from environment, fallback to a local 'data' folder
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))

def init_storage():
    """Ensure the base data directory exists."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(os.path.join(DATA_DIR, "config"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize base storage at {DATA_DIR}: {e}", exc_info=True)
        raise

def init_user_storage(username: str):
    """Ensure the subdirectories for a specific user exist."""
    try:
        user_dir = os.path.join(DATA_DIR, username)
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(os.path.join(user_dir, "sessions"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize user storage for '{username}': {e}", exc_info=True)
        raise

def init_session_storage(username: str, session_id: str):
    """Ensure the subdirectories for a specific session exist."""
    try:
        session_dir = os.path.join(DATA_DIR, username, "sessions", session_id)
        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(os.path.join(session_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "thumbnails"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "data"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize session storage for '{username}/{session_id}': {e}", exc_info=True)
        raise


# --- Session Management ---

def session_exists(username: str, session_id: str) -> bool:
    """Check if a session exists in O(1) without listing all user sessions."""
    safe_session_id = os.path.basename(session_id)
    return os.path.isfile(get_session_filepath(username, safe_session_id))

async def check_session_exists(username: str, session_id: str) -> bool:
    """Async wrapper for session_exists."""
    return await asyncio.to_thread(session_exists, username, session_id)

def generate_thumbnail(source_path: str, target_path: str, max_dimension: int = 400) -> bool:
    """
    Generate an optimized thumbnail from source_path and save to target_path.
    Handles EXIF orientation and RGBA transparency.
    """
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[3])
                else:
                    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            img.save(target_path, "JPEG", quality=80, optimize=True)
            return True
    except Exception as e:
        logger.warning(f"Failed to generate thumbnail for {source_path}: {e}", exc_info=True)
        return False

def get_session_filepath(username: str, session_id: str) -> str:
    # Basic protection against path traversal
    safe_session_id = os.path.basename(session_id)
    return os.path.join(DATA_DIR, username, "sessions", safe_session_id, "session.json")

def get_session_icon_target_path(username: str, session_id: str) -> str:
    safe_session_id = os.path.basename(session_id)
    return os.path.join(DATA_DIR, username, "sessions", safe_session_id, "icon.svg")

def get_session_icon_path(username: str, session_id: str) -> str | None:
    target = get_session_icon_target_path(username, session_id)
    if os.path.exists(target):
        return target
    return None

def _sync_create_session(username: str, title: str) -> str:
    init_user_storage(username)
    session_id = uuid.uuid4().hex
    init_session_storage(username, session_id)
    filepath = get_session_filepath(username, session_id)
    
    session_data = {
        "id": session_id,
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history": [],
        "system_prompt": "",
        "include_gps": False
    }
    
    try:
        atomic_write_json(filepath, session_data, indent=2)
    except Exception as e:
        logger.error(f"Failed to create session file {filepath} for user '{username}': {e}", exc_info=True)
        raise
        
    return session_id

async def create_session(username: str, title: str = "Neuer Chat") -> str:
    return await asyncio.to_thread(_sync_create_session, username, title)

def _sync_get_sessions(username: str) -> list:
    sessions_dir = os.path.join(DATA_DIR, username, "sessions")
    if not os.path.exists(sessions_dir):
        return []
        
    sessions = []
    for dirname in os.listdir(sessions_dir):
        if dirname.startswith("DELETED_"):
            continue
        dir_path = os.path.join(sessions_dir, dirname)
        if os.path.isdir(dir_path):
            filepath = os.path.join(dir_path, "session.json")
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        session_id = data.get("id")
                        has_icon = get_session_icon_path(username, session_id) is not None
                        sessions.append({
                            "id": session_id,
                            "title": data.get("title", "Chat"),
                            "created_at": data.get("created_at", ""),
                            "has_icon": has_icon
                        })
                except Exception as e:
                    logger.warning(f"Failed to read session file {filepath} for user '{username}': {e}", exc_info=True)
                    continue
                    
    # Sort newest first
    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return sessions

async def get_sessions(username: str) -> list:
    return await asyncio.to_thread(_sync_get_sessions, username)

def _sync_get_session_history(username: str, session_id: str) -> list:
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return []
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("history", [])
    except Exception as e:
        logger.error(f"Failed to read session history from {filepath} for user '{username}': {e}", exc_info=True)
        return []

async def get_session_history(username: str, session_id: str) -> list:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_get_session_history, username, session_id)

def _sync_save_session_message(username: str, session_id: str, message: dict):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        logger.warning(f"Cannot save message: session file {filepath} does not exist for user '{username}'")
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["history"].append(message)
        atomic_write_json(filepath, data, indent=2)
    except Exception as e:
        logger.error(f"Failed to save message to session {session_id} for user '{username}': {e}", exc_info=True)

async def save_session_message(username: str, session_id: str, message: dict):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_save_session_message, username, session_id, message)

def _sync_update_session_title(username: str, session_id: str, new_title: str):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        logger.warning(f"Cannot update title: session file {filepath} does not exist for user '{username}'")
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["title"] = new_title
        atomic_write_json(filepath, data, indent=2)
    except Exception as e:
        logger.error(f"Failed to update title for session {session_id} (user '{username}'): {e}", exc_info=True)

async def update_session_title(username: str, session_id: str, new_title: str):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_update_session_title, username, session_id, new_title)

def _sync_get_session_title(username: str, session_id: str) -> str:
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return "Chat"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("title", "Chat")
    except Exception as e:
        logger.warning(f"Failed to read title from {filepath} for user '{username}': {e}")
        return "Chat"

async def get_session_title(username: str, session_id: str) -> str:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_get_session_title, username, session_id)

def _sync_delete_session(username: str, session_id: str):
    filepath = get_session_filepath(username, session_id)
    session_dir = os.path.dirname(filepath)
    if os.path.exists(session_dir):
        parent_dir = os.path.dirname(session_dir)
        new_dir = os.path.join(parent_dir, f"DELETED_{int(time.time())}_{os.path.basename(session_dir)}")
        try:
            os.rename(session_dir, new_dir)
        except OSError as e:
            logger.error(f"Failed to rename/delete session directory {session_dir} to {new_dir}: {e}", exc_info=True)

async def delete_session(username: str, session_id: str):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_delete_session, username, session_id)

def _sync_get_session_settings(username: str, session_id: str) -> dict:
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return {"prompt": "", "include_gps": False}
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "prompt": data.get("system_prompt", ""),
                "include_gps": data.get("include_gps", False)
            }
    except Exception as e:
        logger.warning(f"Failed to load settings from {filepath} for user '{username}': {e}", exc_info=True)
        return {"prompt": "", "include_gps": False}

async def get_session_settings(username: str, session_id: str) -> dict:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_get_session_settings, username, session_id)

def _sync_update_session_settings(username: str, session_id: str, prompt: str, include_gps: bool):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        logger.warning(f"Cannot update settings: session file {filepath} does not exist for user '{username}'")
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["system_prompt"] = prompt
        data["include_gps"] = include_gps
        atomic_write_json(filepath, data, indent=2)
    except Exception as e:
        logger.error(f"Failed to update session settings in {filepath} for user '{username}': {e}", exc_info=True)

async def update_session_settings(username: str, session_id: str, prompt: str, include_gps: bool):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_update_session_settings, username, session_id, prompt, include_gps)

def _sync_cleanup_deleted_sessions(username: str, days: int = 30):
    user_dir = os.path.join(DATA_DIR, username)
    if not os.path.exists(user_dir):
        return
        
    last_run_file = os.path.join(user_dir, "cleanup_last_run.txt")
    current_time = time.time()
    
    if os.path.exists(last_run_file):
        try:
            with open(last_run_file, "r", encoding="utf-8") as f:
                last_run = float(f.read().strip())
                if current_time - last_run < 86400:
                    return
        except Exception as e:
            logger.warning(f"Failed to read cleanup timestamp {last_run_file}: {e}")
            
    sessions_dir = os.path.join(user_dir, "sessions")
    if not os.path.exists(sessions_dir):
        return
        
    for dirname in os.listdir(sessions_dir):
        if not dirname.startswith("DELETED_"):
            continue
            
        dir_path = os.path.join(sessions_dir, dirname)
        parts = dirname.split("_")
        
        folder_time = None
        if len(parts) >= 3 and parts[1].isdigit():
            folder_time = float(parts[1])
        else:
            try:
                folder_time = os.stat(dir_path).st_mtime
            except Exception as e:
                logger.warning(f"Failed to stat directory {dir_path}: {e}")
                
        if folder_time is not None and current_time - folder_time > days * 86400:
            try:
                shutil.rmtree(dir_path)
            except Exception as e:
                logger.warning(f"Failed to delete expired session folder {dir_path}: {e}")
                
    try:
        with open(last_run_file, "w", encoding="utf-8") as f:
            f.write(str(current_time))
    except Exception as e:
        logger.warning(f"Failed to write cleanup timestamp {last_run_file}: {e}")

async def cleanup_deleted_sessions(username: str, days: int = 30):
    await asyncio.to_thread(_sync_cleanup_deleted_sessions, username, days)


# --- Session Export & Import ---

def _sync_export_session_zip(username: str, session_id: str) -> bytes:
    """Pack session.json, icon.svg, uploads, and data directories into a zip archive in memory (excluding thumbnails)."""
    safe_session_id = os.path.basename(session_id)
    session_dir = os.path.join(DATA_DIR, username, "sessions", safe_session_id)
    session_json_path = os.path.join(session_dir, "session.json")
    
    if not os.path.isfile(session_json_path):
        logger.warning(f"Export failed: session file {session_json_path} does not exist for user '{username}'")
        raise FileNotFoundError(f"Session {session_id} not found")
        
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. session.json
            zf.write(session_json_path, arcname="session.json")
            
            # 2. icon.svg if exists
            icon_path = os.path.join(session_dir, "icon.svg")
            if os.path.isfile(icon_path):
                zf.write(icon_path, arcname="icon.svg")
                
            # 3. uploads/ (all uploaded files except thumbnails)
            uploads_dir = os.path.join(session_dir, "uploads")
            if os.path.isdir(uploads_dir):
                for root, _, files in os.walk(uploads_dir):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, session_dir)
                        arcname = rel_path.replace(os.sep, "/")
                        zf.write(full_path, arcname=arcname)
                        
            # 4. data/ (all generated data files)
            data_dir = os.path.join(session_dir, "data")
            if os.path.isdir(data_dir):
                for root, _, files in os.walk(data_dir):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, session_dir)
                        arcname = rel_path.replace(os.sep, "/")
                        zf.write(full_path, arcname=arcname)
                        
        logger.info(f"Successfully packaged export archive for session {session_id} (user '{username}')")
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Failed to create export zip for session {session_id} (user '{username}'): {e}", exc_info=True)
        raise

async def export_session_archive(username: str, session_id: str) -> bytes:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_export_session_zip, username, session_id)


def _sync_import_session_zip(username: str, target_session_id: str, zip_bytes: bytes) -> dict:
    """Safely extract and remap a session zip archive into target_session_id."""
    if not zip_bytes or not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
        logger.warning(f"Import failed: uploaded file is not a valid zip archive for user '{username}'")
        raise ValueError("Ungültiges oder leeres ZIP-Archiv")
        
    safe_target_id = os.path.basename(target_session_id)
    target_dir = os.path.join(DATA_DIR, username, "sessions", safe_target_id)
    init_user_storage(username)
    init_session_storage(username, safe_target_id)
    
    target_uploads_dir = os.path.join(target_dir, "uploads")
    target_data_dir = os.path.join(target_dir, "data")
    target_thumbnails_dir = os.path.join(target_dir, "thumbnails")
    
    # Ensure directories exist and clear thumbnails
    os.makedirs(target_uploads_dir, exist_ok=True)
    os.makedirs(target_data_dir, exist_ok=True)
    if os.path.isdir(target_thumbnails_dir):
        for f in os.listdir(target_thumbnails_dir):
            try:
                os.remove(os.path.join(target_thumbnails_dir, f))
            except Exception as e:
                logger.warning(f"Failed to clear old thumbnail {f} in {target_thumbnails_dir}: {e}")
    else:
        os.makedirs(target_thumbnails_dir, exist_ok=True)
        
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            infolist = zf.infolist()
            
            # SEC-08: Decompression & File Count limits (Zip-Bomb Protection)
            MAX_ZIP_FILES = 1000
            MAX_UNCOMPRESSED_BYTES = 1000 * 1024 * 1024  # 1000 MB limit
            
            if len(infolist) > MAX_ZIP_FILES:
                logger.warning(f"Rejected import: archive contains {len(infolist)} files (max {MAX_ZIP_FILES})")
                raise ValueError(f"Zu viele Dateien im ZIP-Archiv (maximal {MAX_ZIP_FILES})")
                
            total_uncompressed = sum(info.file_size for info in infolist)
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                logger.warning(f"Rejected import: total uncompressed size {total_uncompressed} bytes exceeds limit of {MAX_UNCOMPRESSED_BYTES}")
                raise ValueError("Gesamtgröße der entpackten Dateien überschreitet das Limit von 1000 MB")
            
            # ZipSlip and path traversal protection check
            for info in infolist:
                norm_name = os.path.normpath(info.filename).replace("\\", "/")
                if norm_name.startswith("/") or ".." in norm_name.split("/"):
                    logger.warning(f"ZipSlip attempt or invalid path in archive: '{info.filename}' (user '{username}')")
                    raise ValueError(f"Ungültiger Pfad im ZIP-Archiv: {info.filename}")
                    
            # Find session.json entry (at root or inside top-level directory)
            session_json_info = None
            prefix = ""
            for info in infolist:
                if info.is_dir():
                    continue
                norm_name = os.path.normpath(info.filename).replace("\\", "/")
                if norm_name == "session.json":
                    session_json_info = info
                    prefix = ""
                    break
                elif norm_name.endswith("/session.json") and norm_name.count("/") == 1:
                    session_json_info = info
                    prefix = norm_name.split("/")[0] + "/"
                    break
                    
            if not session_json_info:
                logger.warning(f"Import failed: session.json missing in zip archive (user '{username}')")
                raise ValueError("Keine session.json im ZIP-Archiv gefunden")
                
            raw_session_bytes = zf.read(session_json_info)
            try:
                old_session_data = json.loads(raw_session_bytes.decode("utf-8"))
            except Exception as e:
                logger.warning(f"Import failed: session.json is not valid JSON: {e}")
                raise ValueError("session.json ist kein gültiges JSON")
                
            old_session_id = old_session_data.get("id", "")
            
            # Extract files
            for info in infolist:
                if info.is_dir():
                    continue
                filename = os.path.normpath(info.filename).replace("\\", "/")
                if prefix and filename.startswith(prefix):
                    rel_name = filename[len(prefix):]
                else:
                    rel_name = filename
                    
                if rel_name.startswith("uploads/"):
                    sub_file = rel_name[len("uploads/"):].lstrip("/\\")
                    clean_sub = os.path.normpath(sub_file).replace("\\", "/")
                    if clean_sub and clean_sub != "." and not clean_sub.startswith("..") and ".." not in clean_sub.split("/"):
                        dest_path = os.path.abspath(os.path.join(target_uploads_dir, clean_sub))
                        if dest_path.startswith(os.path.abspath(target_uploads_dir) + os.sep) or dest_path == os.path.abspath(target_uploads_dir):
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            with open(dest_path, "wb") as f_out:
                                f_out.write(zf.read(info))
                        else:
                            raise ValueError(f"Ungültiger Pfad im ZIP-Archiv: {info.filename}")
                elif rel_name.startswith("data/"):
                    sub_file = rel_name[len("data/"):].lstrip("/\\")
                    clean_sub = os.path.normpath(sub_file).replace("\\", "/")
                    if clean_sub and clean_sub != "." and not clean_sub.startswith("..") and ".." not in clean_sub.split("/"):
                        dest_path = os.path.abspath(os.path.join(target_data_dir, clean_sub))
                        if dest_path.startswith(os.path.abspath(target_data_dir) + os.sep) or dest_path == os.path.abspath(target_data_dir):
                            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                            with open(dest_path, "wb") as f_out:
                                f_out.write(zf.read(info))
                        else:
                            raise ValueError(f"Ungültiger Pfad im ZIP-Archiv: {info.filename}")
                elif rel_name == "icon.svg":
                    dest_path = os.path.join(target_dir, "icon.svg")
                    clean_svg_str = sanitize_svg(zf.read(info))
                    with open(dest_path, "w", encoding="utf-8") as f_out:
                        f_out.write(clean_svg_str)
                        
            # Remap history URLs, paths, and Markdown links
            old_history = old_session_data.get("history", [])
            new_history = []
            
            for msg in old_history:
                msg_copy = dict(msg)
                
                # Remap text
                if "text" in msg_copy and isinstance(msg_copy["text"], str):
                    text = msg_copy["text"]
                    if old_session_id:
                        text = text.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                    text = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', text)
                    text = re.sub(r'/app/data/[^/]+/(?:sessions/)?[a-zA-Z0-9_-]+/data/', f'/app/data/{username}/{safe_target_id}/data/', text)
                    msg_copy["text"] = text
                    
                # Remap image_urls
                if "image_urls" in msg_copy and isinstance(msg_copy["image_urls"], list):
                    new_img_urls = []
                    for u in msg_copy["image_urls"]:
                        if isinstance(u, str):
                            if old_session_id:
                                u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                            u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                        new_img_urls.append(u)
                    msg_copy["image_urls"] = new_img_urls
                    
                # Remap images
                if "images" in msg_copy and isinstance(msg_copy["images"], list):
                    new_images = []
                    for img in msg_copy["images"]:
                        if isinstance(img, dict):
                            img_dict = dict(img)
                            if "url" in img_dict and isinstance(img_dict["url"], str):
                                u = img_dict["url"]
                                if old_session_id:
                                    u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                                u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                                img_dict["url"] = u
                            new_images.append(img_dict)
                        elif isinstance(img, str):
                            u = img
                            if old_session_id:
                                u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                            u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                            new_images.append(u)
                    msg_copy["images"] = new_images
                    
                # Remap files
                if "files" in msg_copy and isinstance(msg_copy["files"], list):
                    new_files = []
                    for f_meta in msg_copy["files"]:
                        if isinstance(f_meta, dict):
                            f_dict = dict(f_meta)
                            fname = os.path.basename(f_dict.get("path") or f_dict.get("name") or "")
                            if not fname and "url" in f_dict:
                                fname = os.path.basename(f_dict["url"])
                            
                            # Rewrite url
                            if "url" in f_dict and isinstance(f_dict["url"], str):
                                u = f_dict["url"]
                                if old_session_id:
                                    u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                                u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                                f_dict["url"] = u
                                
                            # Rewrite path
                            if fname:
                                f_dict["path"] = os.path.join(target_uploads_dir, fname)
                            new_files.append(f_dict)
                    msg_copy["files"] = new_files
                    
                new_history.append(msg_copy)
                
            new_session_data = {
                "id": safe_target_id,
                "title": old_session_data.get("title", "Importierter Chat"),
                "created_at": old_session_data.get("created_at") or datetime.now(timezone.utc).isoformat(),
                "history": new_history,
                "system_prompt": old_session_data.get("system_prompt", ""),
                "include_gps": bool(old_session_data.get("include_gps", False))
            }
            
            target_json_path = os.path.join(target_dir, "session.json")
            atomic_write_json(target_json_path, new_session_data, indent=2)
                
            has_icon = os.path.isfile(os.path.join(target_dir, "icon.svg"))
            logger.info(f"Successfully imported session into {safe_target_id} for user '{username}'")
            return {
                "id": safe_target_id,
                "title": new_session_data["title"],
                "has_icon": has_icon
            }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Failed to import session archive into {target_session_id} for user '{username}': {e}", exc_info=True)
        raise

async def import_session_archive(username: str, target_session_id: str, zip_bytes: bytes) -> dict:
    async with session_locks[target_session_id]:
        return await asyncio.to_thread(_sync_import_session_zip, username, target_session_id, zip_bytes)

