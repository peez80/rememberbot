import os
import re
import asyncio
import logging
from typing import List
from fastapi import APIRouter, Request, Response, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import MAX_UPLOADS_PER_MESSAGE, is_safe_session_id
from app.core.tasks import supervisor
from app.services.auth_service import get_current_user
from app.services.session_service import session_service
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["chat"])


@router.post("/{session_id}/chat")
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
    if not is_safe_session_id(session_id):
        logger.warning(f"Invalid session_id in chat request: '{session_id}' by user '{username}'")
        raise HTTPException(status_code=400, detail="Ungültige Sitzungs-ID")

    exists = await session_service.check_session_exists(username, session_id)
    if not exists:
        logger.warning(f"Chat request sent to non-existent session {session_id} by user '{username}'")
        raise HTTPException(status_code=404, detail="Session not found")

    supervisor.register_session(username, session_id)

    valid_uploads = [f for f in (files + images) if f.filename]
    if len(valid_uploads) > MAX_UPLOADS_PER_MESSAGE:
        supervisor.unregister_session(username, session_id)
        logger.warning(f"Rejected chat request: {len(valid_uploads)} files uploaded (max {MAX_UPLOADS_PER_MESSAGE}) for session {session_id} by '{username}'")
        return JSONResponse(status_code=400, content={"error": f"Maximal {MAX_UPLOADS_PER_MESSAGE} Dateien erlaubt"})

    display_msg = message
    image_paths = []
    image_urls = []
    images_data = []
    files_data = []
    attachments = []

    try:
        if valid_uploads:
            upload_meta = await session_service.save_user_attachments(username, session_id, valid_uploads)
            image_paths = upload_meta["image_paths"]
            image_urls = upload_meta["image_urls"]
            images_data = upload_meta["images_data"]
            files_data = upload_meta["files_data"]
            attachments = upload_meta["attachments"]

            num_images = sum(1 for f in files_data if f.get("is_image"))
            num_docs = sum(1 for f in files_data if not f.get("is_image"))
            display_msg = chat_service.format_display_message(message, num_images, num_docs)
            logger.info(f"User '{username}' uploaded {len(valid_uploads)} file(s) for session {session_id}")
    except ValueError as ve:
        supervisor.unregister_session(username, session_id)
        logger.warning(f"Rejected upload for session {session_id} by '{username}': {ve}")
        return JSONResponse(status_code=413, content={"error": str(ve)})
    except Exception as e:
        supervisor.unregister_session(username, session_id)
        logger.error(f"Failed to process/save file upload for session {session_id} (user '{username}'): {e}", exc_info=True)
        raise

    is_stream = stream.lower() in ("true", "1")

    if is_stream:
        logger.info(f"Starting SSE chat stream for session {session_id} (user '{username}')")
        return StreamingResponse(
            chat_service.stream_chat_generator(
                username=username,
                session_id=session_id,
                message=message,
                location=location,
                valid_uploads=valid_uploads,
                image_paths=image_paths,
                image_urls=image_urls,
                images_data=images_data,
                files_data=files_data,
                attachments=attachments,
                display_msg=display_msg
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # Non-streaming mode
    async def process_and_save():
        try:
            return await chat_service.process_chat(
                username=username,
                session_id=session_id,
                message=message,
                location=location,
                valid_uploads=valid_uploads,
                image_paths=image_paths,
                image_urls=image_urls,
                images_data=images_data,
                files_data=files_data,
                attachments=attachments,
                display_msg=display_msg
            )
        except Exception as e:
            logger.error(f"Error in non-streaming chat process for session {session_id} (user '{username}'): {e}", exc_info=True)
            raise
        finally:
            supervisor.unregister_session(username, session_id)

    task = supervisor.create_task(process_and_save())
    try:
        result = await asyncio.shield(task)
        return JSONResponse(content=result)
    except asyncio.CancelledError:
        logger.info(f"Client disconnected during chat request for session {session_id} (user '{username}'). Task continues in background.")
        raise
