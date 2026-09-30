import json
import pytest
import asyncio
import threading
import time
import uvicorn
from unittest.mock import patch, AsyncMock
from playwright.async_api import async_playwright, expect

from app.main import app, get_current_user

SERVER_PORT = 8016

@pytest.fixture(scope="module", autouse=True)
def run_test_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    time.sleep(1)
    yield
    server.should_exit = True


def mock_auth():
    app.dependency_overrides[get_current_user] = lambda: "testuser"

def clear_mock_auth():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.fixture(autouse=True)
def run_around_tests():
    mock_auth()
    yield
    clear_mock_auth()


@pytest.mark.asyncio
async def test_streaming_ui_progressive_rendering_e2e():
    """Verify that the frontend receives streaming tokens and progressively renders markdown."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        # Mock Sessions
        sessions_data = [
            {"id": "sess-live", "title": "Live Chat", "created_at": "2026-01-01T00:00:00Z"}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-live", "is_processing": false}'
        ))

        # Mock SSE Streaming chat endpoint
        async def sse_chat(route):
            # Send SSE payload
            sse_body = (
                'data: {"type": "delta", "text": "**Hallo** "}\n\n'
                'data: {"type": "delta", "text": "aus dem *Stream*!"}\n\n'
                'data: {"type": "done", "reply": "**Hallo** aus dem *Stream*!", "timestamp": "2026-01-01T00:00:05Z"}\n\n'
            )
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-live/chat", sse_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Type message and send
        await page.fill("#message-input", "Stream bitte")
        await page.click("#send-btn")

        # Verify that the AI message bubble appears with the rendered markdown
        ai_message = page.locator(".ai-message:has-text('Hallo aus dem Stream!')")
        await expect(ai_message).to_be_visible(timeout=5000)

        # Verify bold and italic tags rendered via markdown
        bold_elem = page.locator(".ai-message strong:has-text('Hallo')")
        italic_elem = page.locator(".ai-message em:has-text('Stream')")
        await expect(bold_elem).to_be_visible()
        await expect(italic_elem).to_be_visible()

        # Typing indicator must be gone
        await expect(page.locator("#typing-indicator")).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_streaming_thinking_block_e2e():
    """Verify that SSE stream with <thinking> tags renders collapsible .ai-reasoning block."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        # Mock Sessions
        sessions_data = [
            {"id": "sess-thinking", "title": "Thinking Chat", "created_at": "2026-01-01T00:00:00Z"}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body='[]'
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id": "sess-thinking", "is_processing": false}'
        ))

        # Mock SSE Streaming chat endpoint with thinking tags
        async def sse_thinking_chat(route):
            sse_body = (
                'data: {"type": "delta", "text": "<thinking>\\nSchritt 1: Berechne etwas\\n"}\n\n'
                'data: {"type": "delta", "text": "</thinking>\\nDas ist das finale Ergebnis!"}\n\n'
                'data: {"type": "done", "reply": "<thinking>\\nSchritt 1: Berechne etwas\\n</thinking>\\nDas ist das finale Ergebnis!", "timestamp": "2026-01-01T00:00:05Z"}\n\n'
            )
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-thinking/chat", sse_thinking_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Type message and send
        await page.fill("#message-input", "Erkläre mir was")
        await page.click("#send-btn")

        # Verify details.ai-reasoning appears
        reasoning_box = page.locator(".ai-message details.ai-reasoning")
        await expect(reasoning_box).to_be_visible(timeout=5000)

        # Summary text is visible
        summary = reasoning_box.locator("summary")
        await expect(summary).to_have_text("Gedankengang der KI")

        # Click summary to toggle open
        await summary.click()
        await expect(reasoning_box).to_have_attribute("open", "")
        await expect(reasoning_box.locator(".reasoning-content")).to_contain_text("Schritt 1: Berechne etwas")

        # Final answer is visible in the bubble
        ai_message = page.locator(".ai-message")
        await expect(ai_message).to_contain_text("Das ist das finale Ergebnis!")

        await browser.close()


@pytest.mark.asyncio
async def test_thinking_box_persists_on_session_switch_and_history_e2e():
    """Verify that .ai-reasoning thinking box persists across session switching and reloads."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock Auth
        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))

        # Mock Sessions: s1 and s2
        sessions_data = [
            {"id": "sess-alpha", "title": "Alpha Chat", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "sess-beta", "title": "Beta Chat", "created_at": "2026-01-01T00:00:01Z"}
        ]
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(sessions_data)
        ))

        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        await page.route("**/api/sessions/sess-alpha/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body=json.dumps([
                {
                    "text": "<thinking>Alpha interne Gedanken</thinking>Antwort in Alpha",
                    "is_user": False,
                    "timestamp": "2026-01-01T00:00:02Z"
                }
            ])
        ))

        await page.route("**/api/sessions/sess-beta/history", lambda route: route.fulfill(
            status=200,
            headers={"X-Is-Processing": "false"},
            content_type="application/json",
            body=json.dumps([
                {
                    "text": "Einfacher Text ohne Gedanken in Beta",
                    "is_user": False,
                    "timestamp": "2026-01-01T00:00:03Z"
                }
            ])
        ))

        await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"is_processing": false}'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Select Alpha Chat
        alpha_item = page.locator(".session-item:has-text('Alpha Chat')")
        await alpha_item.click()

        # Verify details.ai-reasoning is rendered in Alpha Chat
        alpha_box = page.locator(".ai-message details.ai-reasoning")
        await expect(alpha_box).to_be_visible(timeout=5000)
        await expect(alpha_box.locator("summary")).to_have_text("Gedankengang der KI")

        # Open and check content
        await alpha_box.locator("summary").click()
        await expect(alpha_box).to_have_attribute("open", "")
        await expect(alpha_box.locator(".reasoning-content")).to_contain_text("Alpha interne Gedanken")

        # Switch to Beta Chat
        beta_item = page.locator(".session-item:has-text('Beta Chat')")
        await beta_item.click()

        # In Beta Chat, verify simple text and NO details.ai-reasoning
        await expect(page.locator(".ai-message:has-text('Einfacher Text ohne Gedanken in Beta')")).to_be_visible(timeout=5000)
        await expect(page.locator(".ai-message details.ai-reasoning")).to_have_count(0)

        # Switch back to Alpha Chat
        await alpha_item.click()

        # In Alpha Chat, verify details.ai-reasoning is STILL PRESENT in the DOM
        reopened_box = page.locator(".ai-message details.ai-reasoning")
        await expect(reopened_box).to_be_visible(timeout=5000)
        await expect(reopened_box.locator("summary")).to_have_text("Gedankengang der KI")
        await reopened_box.locator("summary").click()
        await expect(reopened_box.locator(".reasoning-content")).to_contain_text("Alpha interne Gedanken")

        # Reload page and verify it remains present
        await page.reload()
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")
        await alpha_item.click()
        await expect(page.locator(".ai-message details.ai-reasoning")).to_be_visible(timeout=5000)

        await browser.close()


@pytest.mark.asyncio
async def test_streaming_thinking_mid_stream_click_e2e():
    """Verify that clicking .ai-reasoning during active streaming keeps it open across subsequent tokens."""
    from app.services.session_service import session_service
    from app.services.agy_service import AGYService

    # Setup session in backend
    session_id = await session_service.create_session("testuser", "Mid Stream Chat")

    async def slow_stream(*args, **kwargs):
        yield {"type": "delta", "text": "<thinking>\nSchritt 1: Analysiere\n"}
        await asyncio.sleep(0.4)
        yield {"type": "delta", "text": "</thinking>\nAntwort Teil 1. "}
        await asyncio.sleep(0.6)
        yield {"type": "delta", "text": "Antwort Teil 2. "}
        await asyncio.sleep(0.6)
        yield {"type": "delta", "text": "Antwort Teil 3."}
        await asyncio.sleep(0.3)
        yield {
            "type": "done",
            "reply": "<thinking>\nSchritt 1: Analysiere\n</thinking>\nAntwort Teil 1. Antwort Teil 2. Antwort Teil 3.",
            "timestamp": "2026-01-01T00:00:05Z"
        }

    try:
        with patch.object(AGYService, "stream_message", side_effect=slow_stream), \
             patch.object(AGYService, "generate_chat_icon", new=AsyncMock()):
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # Mock Auth
                await page.route("**/api/auth/status", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"authenticated": true, "username": "testuser"}'
                ))

                # Mock Sessions list to contain exactly our created session
                sessions_data = [
                    {"id": session_id, "title": "Mid Stream Chat", "created_at": "2026-01-01T00:00:00Z"}
                ]
                await page.route("**/api/sessions", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(sessions_data)
                ))

                await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"prompt": ""}'
                ))

                await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
                    status=200,
                    headers={"X-Is-Processing": "false"},
                    content_type="application/json",
                    body='[]'
                ))

                await page.route("**/api/sessions/*/status", lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": session_id, "is_processing": False})
                ))

                await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
                await page.evaluate("""() => {
                    const modal = document.getElementById('auth-modal');
                    if (modal) modal.remove();
                }""")

                # Wait for session item and select it
                sess_item = page.locator(".session-item:has-text('Mid Stream Chat')")
                await expect(sess_item).to_be_visible(timeout=5000)
                await sess_item.click()

                # Fill and send message
                await page.fill("#message-input", "Erkläre mir das")
                await page.click("#send-btn")

                # Wait for thinking box to appear
                box = page.locator(".ai-message details.ai-reasoning")
                await expect(box).to_be_visible(timeout=5000)

                # Wait until "Antwort Teil 1." appears in the message (box has auto-closed at </thinking>)
                await expect(page.locator(".ai-message")).to_contain_text("Antwort Teil 1.", timeout=5000)

                # User clicks summary WHILE stream is still active
                await box.locator("summary").click()

                # Verify it is open
                await expect(box).to_have_attribute("open", "", timeout=1000)

                # Wait for Teil 2 and Teil 3 to stream in
                await expect(page.locator(".ai-message")).to_contain_text("Antwort Teil 3.", timeout=5000)

                # The box must STILL be open!
                await expect(box).to_have_attribute("open", "")
                await expect(box.locator(".reasoning-content")).to_contain_text("Schritt 1: Analysiere")

                # Wait for streaming class to be removed (finalization)
                await expect(page.locator(".ai-message.streaming")).to_have_count(0, timeout=5000)

                # After finalization, the box MUST STILL BE OPEN!
                await expect(box).to_have_attribute("open", "")

                await browser.close()
    finally:
        await session_service.delete_session("testuser", session_id)
