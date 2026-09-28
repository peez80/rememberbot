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
from typing import Optional, List, Dict, Any
from PIL import Image, ImageOps

from app.core.config import DATA_DIR, resolve_session_model_and_effort
from app.core.formatters import sanitize_svg
from app.services.storage_service import storage_service, StorageService
from app.services.session_service import session_service, SessionService

logger = logging.getLogger(__name__)

# Concurrency locks - canonical shared instance from storage_service
session_locks = storage_service.session_locks

# Primitives from storage_service
init_storage = storage_service.init_storage
init_user_storage = storage_service.init_user_storage
init_session_storage = storage_service.init_session_storage
atomic_write_json = storage_service.atomic_write_json
generate_thumbnail = storage_service.generate_thumbnail
get_session_filepath = storage_service.get_session_filepath
get_session_icon_target_path = storage_service.get_session_icon_target_path
get_session_icon_path = storage_service.get_session_icon_path
session_exists = storage_service.session_exists

# Async methods from session_service
check_session_exists = session_service.check_session_exists
create_session = session_service.create_session
get_sessions = session_service.get_sessions
get_session_history = session_service.get_session_history
save_session_message = session_service.save_session_message
update_session_title = session_service.update_session_title
get_session_title = session_service.get_session_title
delete_session = session_service.delete_session
get_session_settings = session_service.get_session_settings
update_session_settings = session_service.update_session_settings
export_session_archive = session_service.export_session_archive
import_session_archive = session_service.import_session_archive

# Synchronous helpers for direct callers / unit tests
_sync_create_session = session_service._sync_create_session
_sync_get_sessions = session_service._sync_get_sessions
_sync_get_session_history = session_service._sync_get_session_history
_sync_save_session_message = session_service._sync_save_session_message
_sync_update_session_title = session_service._sync_update_session_title
_sync_get_session_title = session_service._sync_get_session_title
_sync_delete_session = session_service._sync_delete_session
_sync_get_session_settings = session_service._sync_get_session_settings
_sync_update_session_settings = session_service._sync_update_session_settings
_sync_export_session_zip = session_service._sync_export_session_zip
_sync_import_session_zip = session_service._sync_import_session_zip

# Cleanup operations
async def cleanup_deleted_sessions(username: str, days: int = 30):
    await asyncio.to_thread(storage_service.cleanup_deleted_sessions, username, days)

_sync_cleanup_deleted_sessions = storage_service.cleanup_deleted_sessions
