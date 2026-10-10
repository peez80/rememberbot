import os
import re
import asyncio
import logging
from typing import List
from fastapi import APIRouter, Response, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse

from app.core.tasks import supervisor, fire_and_forget
from app.core.config import (
    MAX_ZIP_UPLOAD_SIZE,
    AGY_DEFAULT_MODEL,
    AGY_DEFAULT_THINKING_EFFORT,
    MODEL_CATALOG,
    validate_model_and_effort,
    is_safe_session_id,
)
from app.models.chat import ChatMessage
from app.models.session import (
    SessionSettingsRequest,
    SessionTitleRequest,
    SessionCreateResponse,
    SessionImportResponse,
)
from app.services.auth_service import get_current_user
from app.services.session_service import session_service
from app.services.storage_service import storage_service
from app.services.agy_service import agy_service as agy_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse)
async def create_session_endpoint(username: str = Depends(get_current_user)):
    session_id = await session_service.create_session(username, "Neuer Chat")
    logger.info(f"User '{username}' created new session {session_id}")
    return {"id": session_id, "title": "Neuer Chat"}


@router.get("")
async def get_sessions_endpoint(username: str = Depends(get_current_user)):
    fire_and_forget(session_service.cleanup_deleted_sessions(username))
    return await session_service.get_sessions(username)


@router.get("/models/catalog")
async def get_models_catalog_endpoint():
    return {
        "default_model": AGY_DEFAULT_MODEL,
        "default_effort": AGY_DEFAULT_THINKING_EFFORT,
        "model_catalog": MODEL_CATALOG
    }


@router.get("/{session_id}/status")
async def get_session_status_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in status check: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Status check for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    is_processing = supervisor.is_session_active(username, session_id)
    return {"id": session_id, "is_processing": is_processing}


@router.get("/{session_id}/history", response_model=List[ChatMessage])
async def get_history_endpoint(session_id: str, response: Response, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in history check: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"History requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    history = await session_service.get_session_history(username, session_id)
    if storage_service.get_session_icon_path(username, session_id) is None:
        title = await session_service.get_session_title(username, session_id)
        if title and title != "Neuer Chat":
            user_ctx = None
            ai_ctx = None
            for msg in (history or []):
                is_user = msg.is_user if hasattr(msg, "is_user") else (msg.get("is_user") if isinstance(msg, dict) else False)
                text = msg.text if hasattr(msg, "text") else (msg.get("text", "") if isinstance(msg, dict) else "")
                if is_user and user_ctx is None:
                    user_ctx = text
                elif not is_user and ai_ctx is None:
                    ai_ctx = text
                if user_ctx and ai_ctx:
                    break
            target_path = storage_service.get_session_icon_target_path(username, session_id)
            fire_and_forget(agy_client.generate_chat_icon(
                title=title,
                output_path=target_path,
                user_context=user_ctx,
                ai_context=ai_ctx
            ))

    is_processing = supervisor.is_session_active(username, session_id)
    response.headers["X-Is-Processing"] = "true" if is_processing else "false"
    return history


@router.get("/{session_id}/icon")
async def get_session_icon(session_id: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in icon check: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    icon_path = storage_service.get_session_icon_path(username, session_id)
    if icon_path and os.path.exists(icon_path):
        return FileResponse(
            icon_path,
            media_type="image/svg+xml",
            headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-cache, must-revalidate"
            }
        )
    logger.warning(f"Icon not found for session {session_id} (user '{username}')")
    raise HTTPException(status_code=404, detail="Icon not found")


@router.delete("/{session_id}")
async def delete_session_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in delete request: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Delete requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    await session_service.delete_session(username, session_id)
    logger.info(f"User '{username}' deleted session {session_id}")
    return {"success": True}


@router.get("/{session_id}/settings")
async def get_settings_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in settings check: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Settings requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    return await session_service.get_session_settings(username, session_id)


@router.put("/{session_id}/settings")
async def update_settings_endpoint(session_id: str, req: SessionSettingsRequest, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in settings update: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Settings update requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    ok, err = validate_model_and_effort(req.model, req.thinking_effort)
    if not ok:
        logger.warning(f"Invalid settings for session {session_id} by user '{username}': {err}")
        raise HTTPException(status_code=422, detail=err)

    if req.model is not None or req.thinking_effort is not None:
        await session_service.update_session_settings(
            username,
            session_id,
            req.prompt,
            req.include_gps,
            req.model,
            req.thinking_effort
        )
    else:
        await session_service.update_session_settings(
            username,
            session_id,
            req.prompt,
            req.include_gps
        )
    logger.info(f"User '{username}' updated settings for session {session_id} (model='{req.model}', effort='{req.thinking_effort}')")
    return {"success": True}


@router.put("/{session_id}/title")
async def update_title_endpoint(session_id: str, req: SessionTitleRequest, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in title update: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Title update requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    await session_service.update_session_title(username, session_id, req.title)
    logger.info(f"User '{username}' updated title for session {session_id} to '{req.title}'")
    target_path = storage_service.get_session_icon_target_path(username, session_id)

    # Extract user and AI context from history if available
    user_ctx = None
    ai_ctx = None
    try:
        history = await session_service.get_session_history(username, session_id)
        for msg in (history or []):
            is_user = msg.is_user if hasattr(msg, "is_user") else (msg.get("is_user") if isinstance(msg, dict) else False)
            text = msg.text if hasattr(msg, "text") else (msg.get("text", "") if isinstance(msg, dict) else "")
            if is_user and user_ctx is None:
                user_ctx = text
            elif not is_user and ai_ctx is None:
                ai_ctx = text
            if user_ctx and ai_ctx:
                break
    except Exception as e:
        logger.warning(f"Could not load history for context during icon regeneration: {e}")

    fire_and_forget(agy_client.generate_chat_icon(
        req.title,
        target_path,
        user_context=user_ctx,
        ai_context=ai_ctx
    ))
    return {"success": True}


@router.get("/{session_id}/export")
async def export_session_endpoint(session_id: str, username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in export request: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Export requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        zip_bytes = await session_service.export_session_archive(username, session_id)
        title = await session_service.get_session_title(username, session_id)
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30] or "chat"
        filename = f"chat_{safe_title}_{session_id[:8]}.zip"

        logger.info(f"User '{username}' exported session {session_id} as '{filename}'")
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Cache-Control": "no-cache"
            }
        )
    except FileNotFoundError:
        logger.warning(f"Export failed: session {session_id} not found on disk for user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to export session {session_id} for user '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Fehler beim Exportieren der Session")


@router.post("/{session_id}/import", response_model=SessionImportResponse)
async def import_session_endpoint(session_id: str, file: UploadFile = File(...), username: str = Depends(get_current_user)):
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in import request: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Import requested for non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    if supervisor.is_session_active(username, session_id):
        logger.warning(f"Rejected import into active session {session_id} by user '{username}'")
        raise HTTPException(status_code=400, detail="Session wird gerade verarbeitet")

    try:
        # Bounded streaming read in 64KB chunks to prevent unbounded memory allocation
        CHUNK_SIZE = 64 * 1024
        total_read = 0
        chunks = []
        while chunk := await file.read(CHUNK_SIZE):
            total_read += len(chunk)
            if total_read > MAX_ZIP_UPLOAD_SIZE:
                logger.warning(f"Rejected import: archive exceeds limit for session {session_id} (user '{username}')")
                max_zip_mb = MAX_ZIP_UPLOAD_SIZE // (1024 * 1024)
                raise HTTPException(status_code=413, detail=f"ZIP-Archiv ist zu groß (maximal {max_zip_mb} MB erlaubt)")
            chunks.append(chunk)

        zip_bytes = b"".join(chunks)
        if not zip_bytes:
            logger.warning(f"Empty file uploaded for import in session {session_id} by user '{username}'")
            raise HTTPException(status_code=400, detail="Leere Datei hochgeladen")

        result = await session_service.import_session_archive(username, session_id, zip_bytes)
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
