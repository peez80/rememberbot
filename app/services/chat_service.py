import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple

from app.core.formatters import format_local_links
from app.core.tasks import supervisor, fire_and_forget
from app.services.storage_service import StorageService, storage_service as default_storage_service
from app.services.session_service import SessionService, session_service as default_session_service
from app.services.agy_service import AGYService, agy_service as default_agy_service

# Alias for backwards compatibility with tests
agy_client = default_agy_service

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

    @property
    def _agy(self):
        import sys
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "agy_client"):
            from unittest.mock import MagicMock, AsyncMock
            if isinstance(main_mod.agy_client, (MagicMock, AsyncMock)):
                return main_mod.agy_client
        return self.agy_service

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

    def _build_session_system_prompt(self, username: str, session_id: str, settings: dict, location: Optional[str] = None) -> Tuple[str, str]:
        user_data_dir = os.path.abspath(os.path.join(self.storage_service.data_dir, username, "sessions", session_id, "data"))
        os.makedirs(user_data_dir, exist_ok=True)

        technical_prompt = (
            f"TECHNISCHE VORAUSSETZUNG: Dein persistentes Datenverzeichnis lautet: {user_data_dir}\n"
            "Speichere und lese generierte Dateien IMMER in diesem absoluten Verzeichnis. "
            "Verwende in generierten Skripten (z.B. Python) zwingend diesen absoluten Pfad. "
            "Erstelle für alle generierten Dateien einen Markdown-Link in der Antwort. "
            "Nutze als Link-Ziel AUSSCHLIESSLICH den reinen Dateinamen ohne Pfade (z.B. `[datei.ext](datei.ext)`). "
            "Setze kein Leerzeichen zwischen die eckigen und runden Klammern. "
            "Gib niemals Platzhalter, Beispiele oder Formatierungshinweise in deiner Antwort an den Nutzer aus."
        )

        include_gps = settings.get("include_gps", False)
        if include_gps and location:
            technical_prompt += f"\n\nStandort des Nutzers: {location}"

        session_prompt = settings.get("prompt", "")
        combined_prompt = f"{technical_prompt}\n\n{session_prompt}".strip() if session_prompt else technical_prompt
        return combined_prompt, user_data_dir

    async def _handle_first_message_title(self, username: str, session_id: str, is_first_message: bool, message: str, valid_uploads: list):
        if is_first_message:
            auto_title = message[:30].strip() if message else (
                f"{len(valid_uploads)} Datei(en)" if valid_uploads else "Neuer Chat"
            )
            if not auto_title:
                auto_title = "Neuer Chat"
            await self.session_service.update_session_title(username, session_id, auto_title)

    async def _prepare_chat_turn(
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
        await self.session_service.save_session_message(username, session_id, user_msg_data)

        # Auto-title on first message
        await self._handle_first_message_title(username, session_id, is_first_message, message, valid_uploads)

        # Settings
        settings = await self.session_service.get_session_settings(username, session_id)
        system_prompt, cwd = self._build_session_system_prompt(username, session_id, settings, location)
        model = settings.get("model")
        thinking_effort = settings.get("thinking_effort")

        stored_conv_id = await self.session_service.get_session_conversation_id(username, session_id)
        has_conv_exists = hasattr(self._agy, "conversation_exists")

        if stored_conv_id:
            if not has_conv_exists or self._agy.conversation_exists(stored_conv_id):
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

        return {
            "history": history,
            "is_first_message": is_first_message,
            "system_prompt": system_prompt,
            "cwd": cwd,
            "conversation_id": conversation_id,
            "stored_conv_id": stored_conv_id,
            "model": model,
            "thinking_effort": thinking_effort,
        }

    async def _finalize_chat_turn(
        self,
        username: str,
        session_id: str,
        raw_reply: str,
        cwd: str,
        is_first_message: bool,
        user_message: str
    ) -> dict:
        ai_reply = format_local_links(raw_reply, username, session_id, user_data_dir=cwd).strip()
        timestamp = datetime.now(timezone.utc).isoformat()
        ai_msg_data = {
            "text": ai_reply,
            "is_user": False,
            "timestamp": timestamp
        }
        await self.session_service.save_session_message(username, session_id, ai_msg_data)

        if is_first_message:
            target_path = self.storage_service.get_session_icon_target_path(username, session_id)
            title = await self.session_service.get_session_title(username, session_id)
            fire_and_forget(self._agy.generate_chat_icon(
                title=title or "Neuer Chat",
                output_path=target_path,
                user_context=user_message[:600],
                ai_context=ai_reply[:600]
            ))

        return {
            "reply": ai_reply,
            "timestamp": timestamp
        }

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
        prep = await self._prepare_chat_turn(
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

        result = await self._agy.process_message(
            context_messages=prep["history"],
            new_message=message,
            image_paths=image_paths or [],
            attachments=attachments or [],
            system_prompt=prep["system_prompt"],
            cwd=prep["cwd"],
            conversation_id=prep["conversation_id"],
            model=prep["model"],
            thinking_effort=prep["thinking_effort"]
        )

        finalized = await self._finalize_chat_turn(
            username=username,
            session_id=session_id,
            raw_reply=result.get("reply", ""),
            cwd=prep["cwd"],
            is_first_message=prep["is_first_message"],
            user_message=message
        )

        return {
            "reply": finalized["reply"],
            "context_truncated": result.get("context_truncated", False),
            "timestamp": finalized["timestamp"]
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
        prep = await self._prepare_chat_turn(
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

        queue = asyncio.Queue()

        async def background_stream_consumer():
            full_raw_reply = ""
            done_saved = False
            current_conv_id = prep["conversation_id"]
            try:
                async for event in self._agy.stream_message(
                    context_messages=prep["history"],
                    new_message=message,
                    image_paths=image_paths or [],
                    attachments=attachments or [],
                    system_prompt=prep["system_prompt"],
                    cwd=prep["cwd"],
                    conversation_id=prep["conversation_id"],
                    model=prep["model"],
                    thinking_effort=prep["thinking_effort"]
                ):
                    event_type = event.get("type")
                    if event_type == "init":
                        new_conv_id = event.get("conversation_id")
                        if new_conv_id and new_conv_id != current_conv_id:
                            current_conv_id = new_conv_id
                            prefix = "[CONVERSATION SEEDING] Captured new agy conversation" if not prep["stored_conv_id"] else "Captured updated agy conversation"
                            logger.info("%s '%s' for session %s (user '%s'). Persisting to session storage.", prefix, new_conv_id, session_id, username)
                            await self.session_service.set_session_conversation_id(username, session_id, new_conv_id)
                    elif event_type == "delta":
                        text_chunk = event.get("text", "")
                        full_raw_reply += text_chunk
                        await queue.put({"type": "delta", "text": text_chunk})
                    elif event_type == "done":
                        raw_reply = event.get("reply", full_raw_reply)
                        finalized = await self._finalize_chat_turn(
                            username=username,
                            session_id=session_id,
                            raw_reply=raw_reply,
                            cwd=prep["cwd"],
                            is_first_message=prep["is_first_message"],
                            user_message=message
                        )
                        done_saved = True
                        await queue.put({
                            "type": "done",
                            "reply": finalized["reply"],
                            "context_truncated": event.get("context_truncated", False),
                            "timestamp": finalized["timestamp"]
                        })
                        break

                if not done_saved:
                    finalized = await self._finalize_chat_turn(
                        username=username,
                        session_id=session_id,
                        raw_reply=full_raw_reply,
                        cwd=prep["cwd"],
                        is_first_message=prep["is_first_message"],
                        user_message=message
                    )
                    await queue.put({
                        "type": "done",
                        "reply": finalized["reply"],
                        "context_truncated": False,
                        "timestamp": finalized["timestamp"]
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

