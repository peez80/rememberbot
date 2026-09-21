import os
import io
import re
import json
import uuid
import time
import zipfile
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.core.config import (
    DATA_DIR,
    MAX_ZIP_FILES_COUNT,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    resolve_session_model_and_effort,
)
from app.core.formatters import sanitize_svg
from app.services.storage_service import StorageService, storage_service as default_storage_service

logger = logging.getLogger(__name__)

class SessionService:
    def __init__(self, storage_service: StorageService = default_storage_service):
        self.storage = storage_service

    async def check_session_exists(self, username: str, session_id: str) -> bool:
        return await asyncio.to_thread(self.storage.session_exists, username, session_id)

    def _sync_create_session(self, username: str, title: str) -> str:
        self.storage.init_user_storage(username)
        session_id = uuid.uuid4().hex
        self.storage.init_session_storage(username, session_id)
        filepath = self.storage.get_session_filepath(username, session_id)

        session_data = {
            "id": session_id,
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "history": [],
            "system_prompt": "",
            "include_gps": False,
            "agy_conversation_id": None
        }

        try:
            self.storage.atomic_write_json(filepath, session_data, indent=2)
        except Exception as e:
            logger.error(f"Failed to create session file {filepath} for user '{username}': {e}", exc_info=True)
            raise

        return session_id

    async def create_session(self, username: str, title: str = "Neuer Chat") -> str:
        return await asyncio.to_thread(self._sync_create_session, username, title)

    def _sync_get_sessions(self, username: str) -> list:
        sessions_dir = os.path.join(self.storage.data_dir, username, "sessions")
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
                            has_icon = self.storage.get_session_icon_path(username, session_id) is not None
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

    async def get_sessions(self, username: str) -> list:
        return await asyncio.to_thread(self._sync_get_sessions, username)

    def _sync_get_session_history(self, username: str, session_id: str) -> list:
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            return []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("history", [])
        except Exception as e:
            logger.error(f"Failed to read session history from {filepath} for user '{username}': {e}", exc_info=True)
            return []

    async def get_session_history(self, username: str, session_id: str) -> list:
        async with self.storage.session_locks[session_id]:
            return await asyncio.to_thread(self._sync_get_session_history, username, session_id)

    def _sync_save_session_message(self, username: str, session_id: str, message: dict):
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            logger.warning(f"Cannot save message: session file {filepath} does not exist for user '{username}'")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["history"].append(message)
            self.storage.atomic_write_json(filepath, data, indent=2)
        except Exception as e:
            logger.error(f"Failed to save message to session {session_id} for user '{username}': {e}", exc_info=True)

    async def save_session_message(self, username: str, session_id: str, message: dict):
        async with self.storage.session_locks[session_id]:
            await asyncio.to_thread(self._sync_save_session_message, username, session_id, message)

    def _sync_update_session_title(self, username: str, session_id: str, new_title: str):
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            logger.warning(f"Cannot update title: session file {filepath} does not exist for user '{username}'")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["title"] = new_title
            self.storage.atomic_write_json(filepath, data, indent=2)
        except Exception as e:
            logger.error(f"Failed to update title for session {session_id} (user '{username}'): {e}", exc_info=True)

    async def update_session_title(self, username: str, session_id: str, new_title: str):
        async with self.storage.session_locks[session_id]:
            await asyncio.to_thread(self._sync_update_session_title, username, session_id, new_title)

    def _sync_get_session_title(self, username: str, session_id: str) -> str:
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            return "Chat"
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("title", "Chat")
        except Exception as e:
            logger.warning(f"Failed to read title from {filepath} for user '{username}': {e}")
            return "Chat"

    async def get_session_title(self, username: str, session_id: str) -> str:
        async with self.storage.session_locks[session_id]:
            return await asyncio.to_thread(self._sync_get_session_title, username, session_id)

    def _sync_get_session_conversation_id(self, username: str, session_id: str) -> Optional[str]:
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("agy_conversation_id")
        except Exception as e:
            logger.error(f"Failed to read agy_conversation_id from {filepath} for user '{username}': {e}", exc_info=True)
            return None

    async def get_session_conversation_id(self, username: str, session_id: str) -> Optional[str]:
        async with self.storage.session_locks[session_id]:
            return await asyncio.to_thread(self._sync_get_session_conversation_id, username, session_id)

    def _sync_set_session_conversation_id(self, username: str, session_id: str, conv_id: Optional[str]):
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            logger.warning(f"Cannot set conversation_id: session file {filepath} does not exist for user '{username}'")
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["agy_conversation_id"] = conv_id
            self.storage.atomic_write_json(filepath, data, indent=2)
        except Exception as e:
            logger.error(f"Failed to save agy_conversation_id to {filepath} for user '{username}': {e}", exc_info=True)

    async def set_session_conversation_id(self, username: str, session_id: str, conv_id: Optional[str]):
        async with self.storage.session_locks[session_id]:
            await asyncio.to_thread(self._sync_set_session_conversation_id, username, session_id, conv_id)


    def _sync_delete_session(self, username: str, session_id: str):
        filepath = self.storage.get_session_filepath(username, session_id)
        session_dir = os.path.dirname(filepath)
        if os.path.exists(session_dir):
            parent_dir = os.path.dirname(session_dir)
            new_dir = os.path.join(parent_dir, f"DELETED_{int(time.time())}_{os.path.basename(session_dir)}")
            try:
                os.rename(session_dir, new_dir)
            except OSError as e:
                logger.error(f"Failed to rename/delete session directory {session_dir} to {new_dir}: {e}", exc_info=True)

    async def delete_session(self, username: str, session_id: str):
        async with self.storage.session_locks[session_id]:
            await asyncio.to_thread(self._sync_delete_session, username, session_id)

    def _sync_get_session_settings(self, username: str, session_id: str) -> dict:
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            eff_model, eff_effort = resolve_session_model_and_effort(None, None)
            return {"prompt": "", "include_gps": False, "model": eff_model, "thinking_effort": eff_effort}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                eff_model, eff_effort = resolve_session_model_and_effort(data.get("model"), data.get("thinking_effort"))
                return {
                    "prompt": data.get("system_prompt", ""),
                    "include_gps": data.get("include_gps", False),
                    "model": eff_model,
                    "thinking_effort": eff_effort
                }
        except Exception as e:
            logger.warning(f"Failed to load settings from {filepath} for user '{username}': {e}", exc_info=True)
            eff_model, eff_effort = resolve_session_model_and_effort(None, None)
            return {"prompt": "", "include_gps": False, "model": eff_model, "thinking_effort": eff_effort}

    async def get_session_settings(self, username: str, session_id: str) -> dict:
        async with self.storage.session_locks[session_id]:
            return await asyncio.to_thread(self._sync_get_session_settings, username, session_id)

    def _sync_update_session_settings(self, username: str, session_id: str, prompt: str, include_gps: bool, model: Optional[str] = None, thinking_effort: Optional[str] = None):
        filepath = self.storage.get_session_filepath(username, session_id)
        if not os.path.exists(filepath):
            logger.warning(f"Cannot update settings: session file {filepath} does not exist for user '{username}'")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["system_prompt"] = prompt
            data["include_gps"] = include_gps
            data["model"] = model
            data["thinking_effort"] = thinking_effort
            self.storage.atomic_write_json(filepath, data, indent=2)
        except Exception as e:
            logger.error(f"Failed to update session settings in {filepath} for user '{username}': {e}", exc_info=True)

    async def update_session_settings(self, username: str, session_id: str, prompt: str, include_gps: bool, model: Optional[str] = None, thinking_effort: Optional[str] = None):
        async with self.storage.session_locks[session_id]:
            await asyncio.to_thread(self._sync_update_session_settings, username, session_id, prompt, include_gps, model, thinking_effort)

    def _sync_export_session_zip(self, username: str, session_id: str) -> bytes:
        safe_session_id = os.path.basename(session_id)
        session_dir = os.path.join(self.storage.data_dir, username, "sessions", safe_session_id)
        session_json_path = os.path.join(session_dir, "session.json")

        if not os.path.isfile(session_json_path):
            logger.warning(f"Export failed: session file {session_json_path} does not exist for user '{username}'")
            raise FileNotFoundError(f"Session {session_id} not found")

        buf = io.BytesIO()
        try:
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(session_json_path, arcname="session.json")

                icon_path = os.path.join(session_dir, "icon.svg")
                if os.path.isfile(icon_path):
                    zf.write(icon_path, arcname="icon.svg")

                uploads_dir = os.path.join(session_dir, "uploads")
                if os.path.isdir(uploads_dir):
                    for root, _, files in os.walk(uploads_dir):
                        for fname in files:
                            full_path = os.path.join(root, fname)
                            rel_path = os.path.relpath(full_path, session_dir)
                            arcname = rel_path.replace(os.sep, "/")
                            zf.write(full_path, arcname=arcname)

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

    async def export_session_archive(self, username: str, session_id: str) -> bytes:
        async with self.storage.session_locks[session_id]:
            return await asyncio.to_thread(self._sync_export_session_zip, username, session_id)

    def _sync_import_session_zip(self, username: str, target_session_id: str, zip_bytes: bytes) -> dict:
        if not zip_bytes or not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            logger.warning(f"Import failed: uploaded file is not a valid zip archive for user '{username}'")
            raise ValueError("Ungültiges oder leeres ZIP-Archiv")

        safe_target_id = os.path.basename(target_session_id)
        target_dir = os.path.join(self.storage.data_dir, username, "sessions", safe_target_id)
        self.storage.init_user_storage(username)
        self.storage.init_session_storage(username, safe_target_id)

        target_uploads_dir = os.path.join(target_dir, "uploads")
        target_data_dir = os.path.join(target_dir, "data")
        target_thumbnails_dir = os.path.join(target_dir, "thumbnails")

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

                if len(infolist) > MAX_ZIP_FILES_COUNT:
                    logger.warning(f"Rejected import: archive contains {len(infolist)} files (max {MAX_ZIP_FILES_COUNT})")
                    raise ValueError(f"Zu viele Dateien im ZIP-Archiv (maximal {MAX_ZIP_FILES_COUNT})")

                total_uncompressed = sum(info.file_size for info in infolist)
                if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                    logger.warning(f"Rejected import: total uncompressed size exceeds limit")
                    raise ValueError(f"Gesamtgröße der entpackten Dateien überschreitet das Limit von {MAX_ZIP_UNCOMPRESSED_BYTES // (1024*1024)} MB")

                for info in infolist:
                    norm_name = os.path.normpath(info.filename).replace("\\", "/")
                    if norm_name.startswith("/") or ".." in norm_name.split("/"):
                        logger.warning(f"ZipSlip attempt or invalid path in archive: '{info.filename}' (user '{username}')")
                        raise ValueError(f"Ungültiger Pfad im ZIP-Archiv: {info.filename}")

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

                    if "text" in msg_copy and isinstance(msg_copy["text"], str):
                        text = msg_copy["text"]
                        if old_session_id:
                            text = text.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                        text = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', text)
                        text = re.sub(r'/app/data/[^/]+/(?:sessions/)?[a-zA-Z0-9_-]+/data/', f'/app/data/{username}/{safe_target_id}/data/', text)
                        msg_copy["text"] = text

                    if "image_urls" in msg_copy and isinstance(msg_copy["image_urls"], list):
                        new_img_urls = []
                        for u in msg_copy["image_urls"]:
                            if isinstance(u, str):
                                if old_session_id:
                                    u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                                u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                            new_img_urls.append(u)
                        msg_copy["image_urls"] = new_img_urls

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

                    if "files" in msg_copy and isinstance(msg_copy["files"], list):
                        new_files = []
                        for f_meta in msg_copy["files"]:
                            if isinstance(f_meta, dict):
                                f_dict = dict(f_meta)
                                fname = os.path.basename(f_dict.get("path") or f_dict.get("name") or "")
                                if not fname and "url" in f_dict:
                                    fname = os.path.basename(f_dict["url"])

                                if "url" in f_dict and isinstance(f_dict["url"], str):
                                    u = f_dict["url"]
                                    if old_session_id:
                                        u = u.replace(f"/uploads/{old_session_id}/", f"/uploads/{safe_target_id}/")
                                    u = re.sub(r'/uploads/[a-zA-Z0-9_-]+/', f'/uploads/{safe_target_id}/', u)
                                    f_dict["url"] = u

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
                self.storage.atomic_write_json(target_json_path, new_session_data, indent=2)

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

    async def import_session_archive(self, username: str, target_session_id: str, zip_bytes: bytes) -> dict:
        async with self.storage.session_locks[target_session_id]:
            return await asyncio.to_thread(self._sync_import_session_zip, username, target_session_id, zip_bytes)


# Global instance
session_service = SessionService()
