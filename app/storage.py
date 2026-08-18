import os
import json
import uuid
import shutil
import time
import logging
from datetime import datetime, timezone
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)

# Locks for session concurrency to prevent race conditions during read-modify-write
session_locks = defaultdict(asyncio.Lock)


# Load DATA_DIR from environment, fallback to a local 'data' folder
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))

def init_storage():
    """Ensure the base data directory exists."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "config"), exist_ok=True)

def init_user_storage(username: str):
    """Ensure the subdirectories for a specific user exist."""
    user_dir = os.path.join(DATA_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "sessions"), exist_ok=True)

def init_session_storage(username: str, session_id: str):
    """Ensure the subdirectories for a specific session exist."""
    session_dir = os.path.join(DATA_DIR, username, "sessions", session_id)
    os.makedirs(session_dir, exist_ok=True)
    os.makedirs(os.path.join(session_dir, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(session_dir, "data"), exist_ok=True)


# --- Session Management ---

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
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)
        
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
                except Exception:
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
    except Exception:
        return []

async def get_session_history(username: str, session_id: str) -> list:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_get_session_history, username, session_id)

def _sync_save_session_message(username: str, session_id: str, message: dict):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["history"].append(message)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

async def save_session_message(username: str, session_id: str, message: dict):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_save_session_message, username, session_id, message)

def _sync_update_session_title(username: str, session_id: str, new_title: str):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["title"] = new_title
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

async def update_session_title(username: str, session_id: str, new_title: str):
    async with session_locks[session_id]:
        await asyncio.to_thread(_sync_update_session_title, username, session_id, new_title)

def _sync_delete_session(username: str, session_id: str):
    filepath = get_session_filepath(username, session_id)
    session_dir = os.path.dirname(filepath)
    if os.path.exists(session_dir):
        parent_dir = os.path.dirname(session_dir)
        new_dir = os.path.join(parent_dir, f"DELETED_{int(time.time())}_{os.path.basename(session_dir)}")
        try:
            os.rename(session_dir, new_dir)
        except OSError:
            pass

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
    except Exception:
        return {"prompt": "", "include_gps": False}

async def get_session_settings(username: str, session_id: str) -> dict:
    async with session_locks[session_id]:
        return await asyncio.to_thread(_sync_get_session_settings, username, session_id)

def _sync_update_session_settings(username: str, session_id: str, prompt: str, include_gps: bool):
    filepath = get_session_filepath(username, session_id)
    if not os.path.exists(filepath):
        return
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["system_prompt"] = prompt
        data["include_gps"] = include_gps
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

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
        except Exception:
            pass
            
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
            except Exception:
                pass
                
        if folder_time is not None and current_time - folder_time > days * 86400:
            try:
                shutil.rmtree(dir_path)
            except Exception:
                pass
                
    try:
        with open(last_run_file, "w", encoding="utf-8") as f:
            f.write(str(current_time))
    except Exception:
        pass

async def cleanup_deleted_sessions(username: str, days: int = 30):
    await asyncio.to_thread(_sync_cleanup_deleted_sessions, username, days)
