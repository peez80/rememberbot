import os
import re
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from app.core.config import is_safe_session_id
from app.services.auth_service import get_current_user
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

@router.get("/app/data/{username}/{session_id}/data/{file_path:path}")
async def download_file(username: str, session_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    if username != current_user:
        logger.warning(f"Forbidden data download attempt: user '{current_user}' attempted to access files of user '{username}', file: '{file_path}'")
        raise HTTPException(status_code=403, detail="Forbidden")

    if not is_safe_session_id(session_id):
        logger.warning(f"Potential path traversal attempt detected in data download: invalid session_id '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Invalid path")

    safe_session_id = os.path.basename(session_id)
    base_dir = os.path.abspath(os.path.join(storage_service.data_dir, username, "sessions", safe_session_id, "data"))
    clean_file_path = os.path.normpath(file_path.lstrip("/\\"))
    full_path = os.path.abspath(os.path.join(base_dir, clean_file_path))

    if not (full_path.startswith(base_dir + os.sep) or full_path == base_dir) or os.path.commonpath([base_dir, full_path]) != base_dir:
        logger.warning(f"Potential path traversal attempt detected in data download: '{file_path}' for session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Invalid path")

    if os.path.isfile(full_path):
        return FileResponse(
            full_path,
            filename=os.path.basename(full_path),
            headers={
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-cache, must-revalidate"
            }
        )
    logger.warning(f"Data file not found: '{file_path}' in session {session_id} for user '{username}'")
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/uploads/{session_id}/{filename}")
async def get_upload(session_id: str, filename: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in upload request: '{session_id}' (user '{username}')")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename in (".", ".."):
        logger.warning(f"Invalid filename in upload request: '{filename}' (user '{username}')")
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname")

    file_path = storage_service.get_upload_filepath(username, session_id, filename)
    upload_dir = os.path.realpath(storage_service.get_upload_dir(username, session_id))
    real_file_path = os.path.realpath(file_path)

    if not (real_file_path.startswith(upload_dir + os.sep) or real_file_path == upload_dir) or os.path.commonpath([upload_dir, real_file_path]) != upload_dir:
        logger.warning(f"Path traversal detected in upload request: '{filename}' for session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname")

    if os.path.exists(file_path):
        download_name = safe_filename
        match = re.match(r'^[0-9a-fA-F]{8}_(.+)$', safe_filename)
        if match:
            download_name = match.group(1)

        return FileResponse(
            file_path,
            filename=download_name,
            headers={
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "public, max-age=31536000, immutable"
            }
        )
    logger.warning(f"Upload file not found: '{filename}' for session {session_id} (user '{username}')")
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/uploads/{session_id}/thumbnails/{filename}")
async def get_thumbnail(session_id: str, filename: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in thumbnail request: '{session_id}' (user '{username}')")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename in (".", ".."):
        logger.warning(f"Invalid filename in thumbnail request: '{filename}' (user '{username}')")
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname")

    thumb_dir = os.path.realpath(storage_service.get_thumbnail_dir(username, session_id))
    thumb_path = storage_service.get_thumbnail_filepath(username, session_id, filename)
    real_thumb_path = os.path.realpath(thumb_path)

    if not (real_thumb_path.startswith(thumb_dir + os.sep) or real_thumb_path == thumb_dir) or os.path.commonpath([thumb_dir, real_thumb_path]) != thumb_dir:
        logger.warning(f"Path traversal detected in thumbnail request: '{filename}' for session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname")

    if os.path.exists(thumb_path):
        return FileResponse(
            thumb_path,
            headers={
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "public, max-age=31536000, immutable"
            }
        )

    orig_path = storage_service.get_upload_filepath(username, session_id, filename)
    if not os.path.exists(orig_path):
        logger.warning(f"Thumbnail source image not found: '{filename}' for session {session_id} (user '{username}')")
        raise HTTPException(status_code=404, detail="Image not found")

    success = await asyncio.to_thread(storage_service.generate_thumbnail, orig_path, thumb_path)
    if success and os.path.exists(thumb_path):
        return FileResponse(
            thumb_path,
            headers={
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "public, max-age=31536000, immutable"
            }
        )
    # Fallback to original if thumbnail generation failed (e.g. non-image or SVG)
    logger.warning(f"Thumbnail generation failed for '{filename}', falling back to original image.")
    return FileResponse(
        orig_path,
        filename=os.path.basename(orig_path),
        headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable"
        }
    )
