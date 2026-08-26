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
from typing import Optional, List, Dict, Any
from PIL import Image, ImageOps

from app.core.config import DATA_DIR
from app.core.formatters import sanitize_svg

logger = logging.getLogger(__name__)

# Limit PIL image pixels
Image.MAX_IMAGE_PIXELS = 50_000_000

# Concurrency locks
session_locks = defaultdict(asyncio.Lock)

def atomic_write_json(filepath: str, data: Any, indent: int = 2):
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
            pass
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        logger.error(f"Failed atomic write to {filepath}: {e}", exc_info=True)
        raise

def init_storage():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(os.path.join(DATA_DIR, "config"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize base storage at {DATA_DIR}: {e}", exc_info=True)
        raise

def init_user_storage(username: str):
    try:
        user_dir = os.path.join(DATA_DIR, username)
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(os.path.join(user_dir, "sessions"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize user storage for '{username}': {e}", exc_info=True)
        raise

def init_session_storage(username: str, session_id: str):
    try:
        session_dir = os.path.join(DATA_DIR, username, "sessions", session_id)
        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(os.path.join(session_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "thumbnails"), exist_ok=True)
        os.makedirs(os.path.join(session_dir, "data"), exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to initialize session storage for '{username}/{session_id}': {e}", exc_info=True)
        raise

def generate_thumbnail(source_path: str, target_path: str, max_dimension: int = 400) -> bool:
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
    safe_session_id = os.path.basename(session_id)
    return os.path.join(DATA_DIR, username, "sessions", safe_session_id, "session.json")

def get_session_icon_target_path(username: str, session_id: str) -> str:
    safe_session_id = os.path.basename(session_id)
    return os.path.join(DATA_DIR, username, "sessions", safe_session_id, "icon.svg")

def get_session_icon_path(username: str, session_id: str) -> Optional[str]:
    target = get_session_icon_target_path(username, session_id)
    if os.path.exists(target):
        return target
    return None

def session_exists(username: str, session_id: str) -> bool:
    safe_session_id = os.path.basename(session_id)
    return os.path.isfile(get_session_filepath(username, safe_session_id))

async def check_session_exists(username: str, session_id: str) -> bool:
    return await asyncio.to_thread(session_exists, username, session_id)

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

def _sync_export_session_zip(username: str, session_id: str) -> bytes:
    from app.services.session_service import session_service
    return session_service._sync_export_session_zip(username, session_id)

async def export_session_archive(username: str, session_id: str) -> bytes:
    from app.services.session_service import session_service
    return await session_service.export_session_archive(username, session_id)

def _sync_import_session_zip(username: str, target_session_id: str, zip_bytes: bytes) -> dict:
    from app.services.session_service import session_service
    return session_service._sync_import_session_zip(username, target_session_id, zip_bytes)

async def import_session_archive(username: str, target_session_id: str, zip_bytes: bytes) -> dict:
    from app.services.session_service import session_service
    return await session_service.import_session_archive(username, target_session_id, zip_bytes)
