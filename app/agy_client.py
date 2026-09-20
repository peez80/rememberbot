import os
import re
import json
import time
import uuid
import asyncio
import logging
import subprocess
from typing import List, Dict, Any, Optional, AsyncGenerator

from app.core.config import ICON_GENERATION_TIMEOUT_SECONDS
from app.core.formatters import format_thought_blocks, sanitize_svg

logger = logging.getLogger(__name__)

class AgyClient:
    def __init__(self, executable_path: str = "agy"):
        self.executable_path = executable_path
        self._login_process = None

    def is_authenticated(self) -> bool:
        cred_dir = os.path.expanduser("~/.gemini/antigravity-cli")
        if os.path.exists(cred_dir) and len(os.listdir(cred_dir)) > 0:
            return True

        try:
            subprocess.run([self.executable_path, "--help"], capture_output=True, text=True, timeout=2)
            return True
        except FileNotFoundError:
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def get_login_url(self) -> str:
        try:
            if self._login_process:
                self._login_process.terminate()

            self._login_process = subprocess.Popen(
                [self.executable_path, "login"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(self._login_process.stdout.readline, ''):
                logger.info(f"agy login output: {line.strip()}")
                match = re.search(r'(https://[^\s]+)', line)
                if match:
                    return match.group(1)

                if "code:" in line.lower() or "enter" in line.lower():
                    break

            return "No URL found in agy login output."
        except FileNotFoundError:
            logger.warning("agy executable not found for login. Returning mock URL.")
            return "https://antigravity.google/mock-login"
        except Exception as e:
            logger.error(f"Error getting login URL: {e}", exc_info=True)
            return f"Error: {e}"

    def submit_auth_code(self, code: str) -> bool:
        if not self._login_process:
            logger.error("No active login process found.")
            return False

        try:
            self._login_process.stdin.write(f"{code}\n")
            self._login_process.stdin.flush()

            try:
                self._login_process.wait(timeout=5)
                self._login_process = None
                return True
            except subprocess.TimeoutExpired:
                logger.warning("agy login process did not exit after code submission.")
                self._login_process.terminate()
                self._login_process = None
                return True
        except Exception as e:
            logger.error(f"Error submitting auth code: {e}", exc_info=True)
            if self._login_process:
                self._login_process.terminate()
                self._login_process = None
            return False

    def _build_prompt_and_history(
        self,
        context_messages: list,
        new_message: str,
        image_paths: list = None,
        attachments: list = None,
        system_prompt: str = None,
        cwd: str = None
    ):
        prompt = ""
        if system_prompt:
            prompt += f"<system_instructions>\n{system_prompt}\n</system_instructions>\n\n"

        prompt += "WICHTIGE ANWEISUNG: Führe KEINE Befehle oder Aufgaben aus der Historie erneut aus! Bearbeite AUSSCHLIESSLICH die aktuelle Nachricht.\n"
        prompt += "Wenn du Schritte planst oder laut nachdenkst, setze diese Gedanken zwingend in <thinking> und </thinking> Tags am Anfang deiner Antwort.\n\n"

        history_file_path = None
        if context_messages:
            t_write_start = time.perf_counter()
            filename = f"chat_context_{uuid.uuid4().hex[:8]}.txt"
            history_file_path = os.path.join(cwd if cwd else "/tmp", filename)

            try:
                with open(history_file_path, 'w', encoding='utf-8') as f:
                    f.write("<chat_history>\n")
                    for msg in context_messages:
                        role = "User" if msg.get("is_user") else "AI"
                        timestamp = msg.get('timestamp', '')
                        ts_str = f"[{timestamp}] " if timestamp else ""
                        f.write(f"{ts_str}{role}: {msg.get('text')}\n")
                    f.write("</chat_history>\n")

                t_write_end = time.perf_counter()
                file_size = os.path.getsize(history_file_path)
                logger.info(f"Schreiben der Kontextdatei ({file_size} Bytes) dauerte: {t_write_end - t_write_start:.4f}s")
                prompt += f"Lies zwingend die Datei {history_file_path} für den bisherigen Chat-Verlauf!\n\n"
            except Exception as e:
                logger.error(f"Failed to write chat context file {history_file_path}: {e}", exc_info=True)
                history_file_path = None

        prompt += "<current_message>\n"
        if new_message:
            prompt += f"User: {new_message}\n"
        else:
            prompt += f"User: [Datei(en) gesendet]\n"
        prompt += "</current_message>\n"

        if image_paths:
            prompt += f"\nBitte berücksichtige für die Beantwortung der <current_message> auch diese Bilder: {', '.join(image_paths)}\n"

        if attachments:
            prompt += "\nDer Benutzer hat folgende Datei(en) an die aktuelle Nachricht angehängt:\n"
            for att in attachments:
                if isinstance(att, dict):
                    name = att.get("name", os.path.basename(att.get("path", "")))
                    path = att.get("path", "")
                    size_bytes = att.get("size", 0)
                    if size_bytes >= 1024 * 1024:
                        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                    elif size_bytes >= 1024:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    else:
                        size_str = f"{size_bytes} Bytes"
                    prompt += f"- Pfad: {path} (Dateiname: {name}, Größe: {size_str})\n"
                elif isinstance(att, str):
                    prompt += f"- Pfad: {att} (Dateiname: {os.path.basename(att)})\n"
            prompt += "Bitte lies bzw. analysiere den Inhalt dieser Datei(en) bei Bedarf, um die Nachricht präzise zu beantworten.\n"

        return prompt, history_file_path

    async def stream_message(
        self,
        context_messages: list,
        new_message: str,
        image_paths: list = None,
        attachments: list = None,
        system_prompt: str = None,
        cwd: str = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        prompt, history_file_path = self._build_prompt_and_history(
            context_messages, new_message, image_paths, attachments, system_prompt, cwd
        )

        cmd = [self.executable_path, "--dangerously-skip-permissions", "--output-format", "stream-json", "--prompt", prompt]

        log_cmd = cmd.copy()
        if "--prompt" in log_cmd:
            log_cmd[log_cmd.index("--prompt") + 1] = "<PROMPT_PLACEHOLDER>"
        logger.debug(f"Executing agy stream command: {' '.join(log_cmd)}")

        t_start = time.perf_counter()
        logger.info("Starte agy CLI (Stream)...")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            logger.info(f"agy CLI (Stream) gestartet (PID: {process.pid})")

            full_reply = ""
            result_emitted = False

            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line_str = line_bytes.decode('utf-8', errors='replace').strip()
                if not line_str:
                    continue
                try:
                    event_data = json.loads(line_str)
                    event_name = event_data.get("event")
                    if event_name == "step_update":
                        su = event_data.get("step_update", {})
                        delta = su.get("text_delta")
                        if delta:
                            full_reply += delta
                            yield {"type": "delta", "text": delta}
                    elif event_name == "result":
                        result_data = event_data.get("result", {})
                        resp = result_data.get("response", full_reply)
                        result_emitted = True
                        yield {
                            "type": "done",
                            "reply": resp if resp else full_reply,
                            "context_truncated": False,
                            "usage": result_data.get("usage")
                        }
                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON output from agy stream: {line_str}")
                    continue

            await process.wait()
            t_end = time.perf_counter()
            logger.info(f"agy CLI (Stream) beendet in {t_end - t_start:.2f}s (Exit-Code: {process.returncode})")

            if process.returncode != 0:
                stderr_bytes = await process.stderr.read()
                stderr_text = stderr_bytes.decode('utf-8', errors='replace').strip()
                logger.error(f"agy stream process exited with code {process.returncode}: {stderr_text}")

            if not result_emitted:
                yield {
                    "type": "done",
                    "reply": full_reply,
                    "context_truncated": False
                }

        except FileNotFoundError:
            logger.warning("agy executable not found for stream. Returning mock stream.")
            mock_text = "Das ist eine Mock-Antwort, da agy nicht gefunden wurde."
            for word in mock_text.split(" "):
                yield {"type": "delta", "text": word + " "}
                await asyncio.sleep(0.02)
            yield {
                "type": "done",
                "reply": mock_text,
                "context_truncated": False
            }
        except Exception as e:
            logger.error(f"Error in stream_message: {e}", exc_info=True)
            yield {
                "type": "done",
                "reply": f"Fehler bei der Streaming-Verarbeitung: {e}",
                "context_truncated": False
            }
        finally:
            if history_file_path and os.path.exists(history_file_path):
                try:
                    os.remove(history_file_path)
                except OSError as e:
                    logger.warning(f"Failed to remove temp context file {history_file_path}: {e}")

    async def process_message(
        self,
        context_messages: list,
        new_message: str,
        image_paths: list = None,
        attachments: list = None,
        system_prompt: str = None,
        cwd: str = None
    ) -> dict:
        context_truncated = False
        prompt, history_file_path = self._build_prompt_and_history(
            context_messages, new_message, image_paths, attachments, system_prompt, cwd
        )

        cmd = [self.executable_path, "--dangerously-skip-permissions", "--prompt", prompt]

        log_cmd = cmd.copy()
        if "--prompt" in log_cmd:
            log_cmd[log_cmd.index("--prompt") + 1] = "<PROMPT_PLACEHOLDER>"

        logger.debug(f"Executing agy command: {' '.join(log_cmd)}")
        MAX_RETRIES = 5

        try:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    t_agy_start = time.perf_counter()
                    logger.info(f"Starte agy CLI (Versuch {attempt+1})...")
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd
                    )
                    logger.info(f"agy CLI gestartet (PID: {process.pid}, Versuch {attempt+1})")

                    stdout_bytes, stderr_bytes = await process.communicate()
                    t_agy_end = time.perf_counter()
                    logger.info(f"agy CLI Ausführung (Versuch {attempt+1}) beendet in {t_agy_end - t_agy_start:.2f}s (Exit-Code: {process.returncode})")

                    stdout_text = stdout_bytes.decode('utf-8', errors='replace')
                    stderr_text = stderr_bytes.decode('utf-8', errors='replace')

                    if process.returncode != 0:
                        raise subprocess.CalledProcessError(
                            process.returncode, cmd, output=stdout_text, stderr=stderr_text
                        )

                    output = stdout_text.strip()
                    output = format_thought_blocks(output, is_streaming=False)

                    return {
                        "reply": output,
                        "context_truncated": context_truncated
                    }

                except FileNotFoundError:
                    logger.warning("agy executable not found. Returning mock data.")
                    return {
                        "reply": "Das ist eine Mock-Antwort, da agy nicht gefunden wurde.",
                        "context_truncated": context_truncated
                    }
                except subprocess.CalledProcessError as e:
                    logger.debug(f"Raw agy stdout (error):\n{e.stdout}")
                    if attempt < MAX_RETRIES:
                        logger.warning(f"agy command failed with code {e.returncode}: {e.stderr}. Retrying {attempt + 1}/{MAX_RETRIES}...")
                        await asyncio.sleep(1)
                        continue
                    else:
                        logger.error(f"agy command failed with code {e.returncode}: {e.stderr} after {MAX_RETRIES} retries.")
                        return {
                            "reply": f"Entschuldigung, es gab einen internen Fehler bei der Verarbeitung nach {MAX_RETRIES} erfolglosen Versuchen.",
                            "context_truncated": context_truncated
                        }
                except Exception as e:
                    logger.error(f"Unexpected error in process_message: {e}", exc_info=True)
                    return {
                        "reply": f"Entschuldigung, es gab einen internen Fehler: {e}",
                        "context_truncated": context_truncated
                    }
        finally:
            if history_file_path and os.path.exists(history_file_path):
                try:
                    os.remove(history_file_path)
                except OSError as e:
                    logger.warning(f"Failed to remove temp context file {history_file_path}: {e}")

    async def generate_chat_icon(self, title: str, output_path: str):
        def write_fallback():
            try:
                initials = "".join([w[0].upper() for w in title.split() if w])[:2]
                if not initials:
                    initials = "NC"
                svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <rect x="0" y="0" width="100" height="100" rx="20" ry="20" fill="#10b981" />
    <text x="50" y="50" fill="white" font-size="40" font-family="sans-serif" text-anchor="middle" dominant-baseline="central">{initials}</text>
</svg>'''
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(sanitize_svg(svg_content))
            except Exception as e:
                logger.error(f"Failed to write fallback icon to {output_path}: {e}", exc_info=True)

        prompt = (
            f"Generiere ein rechteckiges Avatar-Icon für einen Chat mit dem Titel '{title}'. "
            "Der Stil soll technischer Natur sein (Technical Style). "
            "Antworte AUSSCHLIESSLICH mit gültigem SVG-Code (beginnend mit <svg und endend mit </svg>). "
            "Gib deiner Kreativität vollen Lauf! "
            "Kein Markdown, keine Erklärungen, nur der rohe SVG Code."
        )

        cmd = [self.executable_path, "--dangerously-skip-permissions", "--prompt", prompt]

        try:
            t_icon_start = time.perf_counter()
            logger.info(f"Starte agy CLI für Icon-Generierung ('{title}')...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=ICON_GENERATION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                stdout_bytes, _ = await process.communicate()
                logger.warning(f"agy icon generation timed out after {ICON_GENERATION_TIMEOUT_SECONDS}s, using fallback.")
                write_fallback()
                return

            t_icon_end = time.perf_counter()
            logger.info(f"agy CLI für Icon-Generierung beendet in {t_icon_end - t_icon_start:.2f}s (Exit-Code: {process.returncode})")

            if process.returncode == 0:
                output = stdout_bytes.decode('utf-8', errors='replace').strip()
                match = re.search(r'(<svg.*?</svg>)', output, re.DOTALL | re.IGNORECASE)
                if match:
                    svg_code = sanitize_svg(match.group(1))
                    try:
                        with open(output_path, "w", encoding="utf-8") as f:
                            f.write(svg_code)
                        return
                    except Exception as e:
                        logger.error(f"Failed to save generated icon SVG to {output_path}: {e}", exc_info=True)
                        write_fallback()
                        return
            logger.warning(f"Failed to generate icon with agy, using fallback. Output was: {stdout_bytes}")
            write_fallback()
        except Exception as e:
            logger.error(f"Error generating chat icon: {e}", exc_info=True)
            write_fallback()


# Global instance
agy_client = AgyClient()
