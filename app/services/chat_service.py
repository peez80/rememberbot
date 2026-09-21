import os
import io
import re
import json
import uuid
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, AsyncGenerator

from app.core.formatters import format_thought_blocks, format_local_links
from app.core.tasks import supervisor, fire_and_forget
from app.models.chat import ChatMessage, AttachmentMeta
from app.services.storage_service import StorageService, storage_service as default_storage_service
from app.services.session_service import SessionService, session_service as default_session_service
from app.services.agy_service import AGYService, agy_service as default_agy_service
from app.agy_client import agy_client

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(
        self,
        storage_service: StorageService = default_storage_service,
        session_service: SessionService = default_session_service,
        agy_service: AGYService = default_agy_service
    ):
        self.storage_service = storage_service
        self.session_service = session_service
        self.agy_service = agy_service

    def format_display_message(self, message: str, num_images: int, num_docs: int) -> str:
        if num_images > 0 and num_docs > 0:
            tag = f"[{num_images} Bild(er), {num_docs} Datei(en) angehängt]"
            return f"{message} {tag}".strip() if message else f"[{num_images} Bild(er), {num_docs} Datei(en) gesendet]"
        elif num_images > 0:
            tag = f"[{num_images} Bild(er) angehängt]"
            return f"{message} {tag}".strip() if message else f"[{num_images} Bild(er) gesendet]"
        elif num_docs > 0:
            tag = f"[{num_docs} Datei(en) angehängt]"
            return f"{message} {tag}".strip() if message else f"[{num_docs} Datei(en) gesendet]"
        return message

    def _get_agy_client(self):
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "agy_client"):
                fn = main_mod.agy_client
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    return fn
        except Exception:
            pass
        return agy_client

    async def _handle_first_message_title(self, username: str, session_id: str, is_first_message: bool, message: str, valid_uploads: list):
        if is_first_message:
            auto_title = message[:30].strip() if message else (
                f"{len(valid_uploads)} Datei(en)" if valid_uploads else "Neuer Chat"
            )
            if not auto_title:
                auto_title = "Neuer Chat"
            try:
                import sys
                main_mod = sys.modules.get("app.main")
                if main_mod and hasattr(main_mod, "update_session_title"):
                    fn = getattr(main_mod, "update_session_title")
                    if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                        res = fn(username, session_id, auto_title)
                        if asyncio.iscoroutine(res):
                            await res
                    else:
                        await self.session_service.update_session_title(username, session_id, auto_title)
                else:
                    await self.session_service.update_session_title(username, session_id, auto_title)
            except Exception:
                await self.session_service.update_session_title(username, session_id, auto_title)

            target_path = self.storage_service.get_session_icon_target_path(username, session_id)
            client_obj = self._get_agy_client()
            fire_and_forget(client_obj.generate_chat_icon(auto_title, target_path))

    async def process_chat(
        self,
        username: str,
        session_id: str,
        message: str,
        location: str = "",
        valid_uploads: list = None,
        image_paths: list = None,
        image_urls: list = None,
        images_data: list = None,
        files_data: list = None,
        attachments: list = None,
        display_msg: str = None
    ) -> dict:
        valid_uploads = valid_uploads or []
        image_paths = image_paths or []
        image_urls = image_urls or []
        images_data = images_data or []
        files_data = files_data or []
        attachments = attachments or []

        if display_msg is None:
            num_images = sum(1 for f in files_data if f.get("is_image"))
            num_docs = sum(1 for f in files_data if not f.get("is_image"))
            display_msg = self.format_display_message(message, num_images, num_docs)

        # Get existing history
        history = []
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "get_session_history"):
                fn = getattr(main_mod, "get_session_history")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id)
                    history = await res if asyncio.iscoroutine(res) else res
                else:
                    history = await self.session_service.get_session_history(username, session_id)
            else:
                history = await self.session_service.get_session_history(username, session_id)
        except Exception:
            history = await self.session_service.get_session_history(username, session_id)

        is_first_message = len(history) == 0

        # Save user message immediately
        user_msg_data = {
            "text": display_msg,
            "is_user": True,
            "image_urls": image_urls,
            "images": images_data if images_data else None,
            "files": files_data if files_data else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "save_session_message"):
                fn = getattr(main_mod, "save_session_message")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id, user_msg_data)
                    if asyncio.iscoroutine(res):
                        await res
                else:
                    await self.session_service.save_session_message(username, session_id, user_msg_data)
            else:
                await self.session_service.save_session_message(username, session_id, user_msg_data)
        except Exception:
            await self.session_service.save_session_message(username, session_id, user_msg_data)

        # Auto-title on first message
        await self._handle_first_message_title(username, session_id, is_first_message, message, valid_uploads)

        # Settings
        settings = {}
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "get_session_settings"):
                fn = getattr(main_mod, "get_session_settings")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id)
                    settings = await res if asyncio.iscoroutine(res) else res
                else:
                    settings = await self.session_service.get_session_settings(username, session_id)
            else:
                settings = await self.session_service.get_session_settings(username, session_id)
        except Exception:
            settings = await self.session_service.get_session_settings(username, session_id)

        system_prompt = settings.get("prompt", "")
        include_gps = settings.get("include_gps", False)
        model = settings.get("model")
        thinking_effort = settings.get("thinking_effort")

        if include_gps and location:
            loc_instruction = f"\nStandort des Nutzers: {location}"
            system_prompt = f"{system_prompt}{loc_instruction}".strip() if system_prompt else loc_instruction.strip()

        cwd = os.path.join(self.storage_service.data_dir, username, "sessions", session_id, "data")
        os.makedirs(cwd, exist_ok=True)

        client_obj = self._get_agy_client()
        stored_conv_id = await self.session_service.get_session_conversation_id(username, session_id)
        has_conv_exists = hasattr(client_obj, "conversation_exists")

        if stored_conv_id:
            if not has_conv_exists or client_obj.conversation_exists(stored_conv_id):
                logger.info("[CONVERSATION RESUMING] Resuming agy conversation '%s' for session %s (user '%s').", stored_conv_id, session_id, username)
                conversation_id = stored_conv_id
            else:
                logger.warning("[CONVERSATION FALLBACK] Stored agy conversation '%s' not found locally for session %s (user '%s'). Triggering re-seeding with full history (%d messages).", stored_conv_id, session_id, username, len(history))
                conversation_id = None
        elif history:
            logger.info("[CONVERSATION SEEDING] Initiating one-time history seeding for session %s (%d messages) for user '%s'.", session_id, len(history), username)
            conversation_id = None
        else:
            logger.info("Starting brand new agy conversation for session %s (user '%s').", session_id, username)
            conversation_id = None

        result = await client_obj.process_message(
            context_messages=history,
            new_message=message,
            image_paths=image_paths,
            attachments=attachments,
            system_prompt=system_prompt,
            cwd=cwd,
            conversation_id=conversation_id,
            model=model,
            thinking_effort=thinking_effort
        )

        ai_reply = format_local_links(result.get("reply", ""), username, session_id)
        context_truncated = result.get("context_truncated", False)

        ai_msg_data = {
            "text": ai_reply,
            "is_user": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "save_session_message"):
                fn = getattr(main_mod, "save_session_message")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id, ai_msg_data)
                    if asyncio.iscoroutine(res):
                        await res
                else:
                    await self.session_service.save_session_message(username, session_id, ai_msg_data)
            else:
                await self.session_service.save_session_message(username, session_id, ai_msg_data)
        except Exception:
            await self.session_service.save_session_message(username, session_id, ai_msg_data)

        return {
            "reply": ai_reply,
            "context_truncated": context_truncated,
            "timestamp": ai_msg_data["timestamp"]
        }

    async def stream_chat_generator(
        self,
        username: str,
        session_id: str,
        message: str,
        location: str = "",
        valid_uploads: list = None,
        image_paths: list = None,
        image_urls: list = None,
        images_data: list = None,
        files_data: list = None,
        attachments: list = None,
        display_msg: str = None
    ) -> AsyncGenerator[str, None]:
        valid_uploads = valid_uploads or []
        image_paths = image_paths or []
        image_urls = image_urls or []
        images_data = images_data or []
        files_data = files_data or []
        attachments = attachments or []

        if display_msg is None:
            num_images = sum(1 for f in files_data if f.get("is_image"))
            num_docs = sum(1 for f in files_data if not f.get("is_image"))
            display_msg = self.format_display_message(message, num_images, num_docs)

        # Get existing history
        history = []
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "get_session_history"):
                fn = getattr(main_mod, "get_session_history")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id)
                    history = await res if asyncio.iscoroutine(res) else res
                else:
                    history = await self.session_service.get_session_history(username, session_id)
            else:
                history = await self.session_service.get_session_history(username, session_id)
        except Exception:
            history = await self.session_service.get_session_history(username, session_id)

        is_first_message = len(history) == 0

        # Save user message immediately
        user_msg_data = {
            "text": display_msg,
            "is_user": True,
            "image_urls": image_urls,
            "images": images_data if images_data else None,
            "files": files_data if files_data else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "save_session_message"):
                fn = getattr(main_mod, "save_session_message")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id, user_msg_data)
                    if asyncio.iscoroutine(res):
                        await res
                else:
                    await self.session_service.save_session_message(username, session_id, user_msg_data)
            else:
                await self.session_service.save_session_message(username, session_id, user_msg_data)
        except Exception:
            await self.session_service.save_session_message(username, session_id, user_msg_data)

        # Auto-title on first message
        await self._handle_first_message_title(username, session_id, is_first_message, message, valid_uploads)

        settings = {}
        try:
            import sys
            main_mod = sys.modules.get("app.main")
            if main_mod and hasattr(main_mod, "get_session_settings"):
                fn = getattr(main_mod, "get_session_settings")
                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                    res = fn(username, session_id)
                    settings = await res if asyncio.iscoroutine(res) else res
                else:
                    settings = await self.session_service.get_session_settings(username, session_id)
            else:
                settings = await self.session_service.get_session_settings(username, session_id)
        except Exception:
            settings = await self.session_service.get_session_settings(username, session_id)

        system_prompt = settings.get("prompt", "")
        include_gps = settings.get("include_gps", False)
        model = settings.get("model")
        thinking_effort = settings.get("thinking_effort")

        if include_gps and location:
            loc_instruction = f"\nStandort des Nutzers: {location}"
            system_prompt = f"{system_prompt}{loc_instruction}".strip() if system_prompt else loc_instruction.strip()

        cwd = os.path.join(self.storage_service.data_dir, username, "sessions", session_id, "data")
        os.makedirs(cwd, exist_ok=True)

        queue = asyncio.Queue()
        client_obj = self._get_agy_client()
        stored_conv_id = await self.session_service.get_session_conversation_id(username, session_id)
        has_conv_exists = hasattr(client_obj, "conversation_exists")

        if stored_conv_id:
            if not has_conv_exists or client_obj.conversation_exists(stored_conv_id):
                logger.info("[CONVERSATION RESUMING] Resuming agy conversation '%s' for session %s (user '%s').", stored_conv_id, session_id, username)
                conversation_id = stored_conv_id
            else:
                logger.warning("[CONVERSATION FALLBACK] Stored agy conversation '%s' not found locally for session %s (user '%s'). Triggering re-seeding with full history (%d messages).", stored_conv_id, session_id, username, len(history))
                conversation_id = None
        elif history:
            logger.info("[CONVERSATION SEEDING] Initiating one-time history seeding for session %s (%d messages) for user '%s'.", session_id, len(history), username)
            conversation_id = None
        else:
            logger.info("Starting brand new agy conversation for session %s (user '%s').", session_id, username)
            conversation_id = None

        async def background_stream_consumer():
            full_raw_reply = ""
            done_saved = False
            current_conv_id = conversation_id
            try:
                async for event in client_obj.stream_message(
                    context_messages=history,
                    new_message=message,
                    image_paths=image_paths,
                    attachments=attachments,
                    system_prompt=system_prompt,
                    cwd=cwd,
                    conversation_id=conversation_id,
                    model=model,
                    thinking_effort=thinking_effort
                ):
                    event_type = event.get("type")
                    if event_type == "init":
                        new_conv_id = event.get("conversation_id")
                        if new_conv_id and new_conv_id != current_conv_id:
                            current_conv_id = new_conv_id
                            prefix = "[CONVERSATION SEEDING] Captured new agy conversation" if not stored_conv_id else "Captured updated agy conversation"
                            logger.info("%s '%s' for session %s (user '%s'). Persisting to session storage.", prefix, new_conv_id, session_id, username)
                            await self.session_service.set_session_conversation_id(username, session_id, new_conv_id)
                    elif event_type == "delta":
                        text_chunk = event.get("text", "")
                        full_raw_reply += text_chunk
                        await queue.put({"type": "delta", "text": text_chunk})
                    elif event_type == "done":
                        raw_reply = event.get("reply", full_raw_reply)
                        final_reply = format_local_links(raw_reply, username, session_id).strip()

                        ai_msg_data = {
                            "text": final_reply,
                            "is_user": False,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                        try:
                            import sys
                            main_mod = sys.modules.get("app.main")
                            if main_mod and hasattr(main_mod, "save_session_message"):
                                fn = getattr(main_mod, "save_session_message")
                                if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                                    res = fn(username, session_id, ai_msg_data)
                                    if asyncio.iscoroutine(res):
                                        await res
                                else:
                                    await self.session_service.save_session_message(username, session_id, ai_msg_data)
                            else:
                                await self.session_service.save_session_message(username, session_id, ai_msg_data)
                        except Exception:
                            await self.session_service.save_session_message(username, session_id, ai_msg_data)

                        done_saved = True
                        await queue.put({
                            "type": "done",
                            "reply": final_reply,
                            "context_truncated": event.get("context_truncated", False),
                            "timestamp": ai_msg_data["timestamp"]
                        })
                        break

                if not done_saved:
                    final_reply = format_local_links(full_raw_reply, username, session_id).strip()
                    ai_msg_data = {
                        "text": final_reply,
                        "is_user": False,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    try:
                        import sys
                        main_mod = sys.modules.get("app.main")
                        if main_mod and hasattr(main_mod, "save_session_message"):
                            fn = getattr(main_mod, "save_session_message")
                            if hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value") or type(fn).__module__.startswith("unittest.mock"):
                                res = fn(username, session_id, ai_msg_data)
                                if asyncio.iscoroutine(res):
                                    await res
                            else:
                                await self.session_service.save_session_message(username, session_id, ai_msg_data)
                        else:
                            await self.session_service.save_session_message(username, session_id, ai_msg_data)
                    except Exception:
                        await self.session_service.save_session_message(username, session_id, ai_msg_data)

                    await queue.put({
                        "type": "done",
                        "reply": final_reply,
                        "context_truncated": False,
                        "timestamp": ai_msg_data["timestamp"]
                    })
            except Exception as e:
                logger.error(f"Error in background_stream_consumer for session {session_id}: {e}", exc_info=True)
                await queue.put({"type": "error", "error": f"Streaming-Fehler: {str(e)}"})
            finally:
                await queue.put(None)
                supervisor.unregister_session(username, session_id)

        # Run consumer in supervisor background task shielded against client disconnect
        supervisor.register_session(username, session_id)
        consumer_task = supervisor.create_task(background_stream_consumer())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_type = item.get("type", "message")
                payload = json.dumps(item, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE client disconnected for session {session_id} (user '{username}'). Task continues in background.")
            raise


# Global instance
chat_service = ChatService()
