import os
import io
import json
import uuid
import time
import shutil
import logging
import asyncio
from collections import defaultdict
from typing import Dict, Any, Optional
from PIL import Image, ImageOps

from app.core.config import DATA_DIR
from app.core.formatters import sanitize_svg

logger = logging.getLogger(__name__)

# Limit PIL image pixels to prevent decompression bombs (Pixel Flood DoS)
Image.MAX_IMAGE_PIXELS = 50_000_000

class StorageService:
    def __init__(self, data_dir: Optional[str] = None):
        self._custom_data_dir = data_dir
        self.session_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def data_dir(self) -> str:
        if self._custom_data_dir is not None:
            return self._custom_data_dir
        try:
            import sys
            storage_mod = sys.modules.get("app.storage")
            if storage_mod and hasattr(storage_mod, "DATA_DIR"):
                val = storage_mod.DATA_DIR
                if str(val) != str(DATA_DIR):
                    return str(val)
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "DATA_DIR"):
                val = main_mod.DATA_DIR
                if str(val) != str(DATA_DIR):
                    return str(val)
            if storage_mod and hasattr(storage_mod, "DATA_DIR"):
                return str(storage_mod.DATA_DIR)
            if main_mod and hasattr(main_mod, "DATA_DIR"):
                return str(main_mod.DATA_DIR)
        except Exception:
            pass
        return DATA_DIR

    def init_storage(self):
        """Ensure the base data directory and config directory exist."""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            os.makedirs(os.path.join(self.data_dir, "config"), exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to initialize base storage at {self.data_dir}: {e}", exc_info=True)
            raise

    def init_user_storage(self, username: str):
        """Ensure the subdirectories for a specific user exist."""
        try:
            user_dir = os.path.join(self.data_dir, username)
            os.makedirs(user_dir, exist_ok=True)
            os.makedirs(os.path.join(user_dir, "sessions"), exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to initialize user storage for '{username}': {e}", exc_info=True)
            raise

    def init_session_storage(self, username: str, session_id: str):
        """Ensure the subdirectories for a specific session exist."""
        try:
            session_dir = os.path.join(self.data_dir, username, "sessions", session_id)
            os.makedirs(session_dir, exist_ok=True)
            os.makedirs(os.path.join(session_dir, "uploads"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "thumbnails"), exist_ok=True)
            os.makedirs(os.path.join(session_dir, "data"), exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to initialize session storage for '{username}/{session_id}': {e}", exc_info=True)
            raise

    def atomic_write_json(self, filepath: str, data: Any, indent: int = 2):
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
                pass
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            logger.error(f"Failed atomic write to {filepath}: {e}", exc_info=True)
            raise

    def generate_thumbnail(self, source_path: str, target_path: str, max_dimension: int = 400) -> bool:
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

    def get_session_filepath(self, username: str, session_id: str) -> str:
        safe_session_id = os.path.basename(session_id)
        return os.path.join(self.data_dir, username, "sessions", safe_session_id, "session.json")

    def get_session_icon_target_path(self, username: str, session_id: str) -> str:
        safe_session_id = os.path.basename(session_id)
        return os.path.join(self.data_dir, username, "sessions", safe_session_id, "icon.svg")

    def get_session_icon_path(self, username: str, session_id: str) -> Optional[str]:
        target = self.get_session_icon_target_path(username, session_id)
        if os.path.exists(target):
            return target
        return None

    def session_exists(self, username: str, session_id: str) -> bool:
        safe_session_id = os.path.basename(session_id)
        return os.path.isfile(self.get_session_filepath(username, safe_session_id))

    def cleanup_deleted_sessions(self, username: str, days: int = 30):
        user_dir = os.path.join(self.data_dir, username)
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


# Global storage service instance
storage_service = StorageService()
