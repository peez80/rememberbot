import json
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8034


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


@pytest.mark.asyncio
async def test_tab_close_during_processing_and_resume_e2e():
    """Verify closing the browser tab while AI generates, and cleanly resuming on a new tab."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        session_id = "sess-resume-1"
        session_state = {
            "processing": True,
            "completed": False,
            "history": [
                {"text": "Berechne eine komplexe Simulation", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"}
            ]
        }

        async def setup_routes(target_page):
            async def auth_route(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"authenticated": true, "username": "testuser"}'
                )
            await target_page.route("**/api/auth/status", auth_route)

            async def sessions_route(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([{"id": session_id, "title": "Simulation Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": False}])
                )
            await target_page.route("**/api/sessions", sessions_route)

            async def settings_route(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"prompt": "", "include_gps": false}'
                )
            await target_page.route("**/api/sessions/*/settings", settings_route)

            async def history_route(route):
                headers = {"X-Is-Processing": "true" if session_state["processing"] else "false"}
                await route.fulfill(
                    status=200,
                    headers=headers,
                    content_type="application/json",
                    body=json.dumps(session_state["history"])
                )
            await target_page.route("**/api/sessions/*/history", history_route)

            async def status_route(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": session_id, "is_processing": session_state["processing"]})
                )
            await target_page.route("**/api/sessions/*/status", status_route)

        await setup_routes(page)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)

        # Typing indicator must be visible because processing is True
        typing_indicator = page.locator("#typing-indicator")
        await expect(typing_indicator).to_be_visible(timeout=5000)

        # User closes the browser tab entirely while processing
        await page.close()

        # Simulate background task completing and saving AI answer
        session_state["processing"] = False
        session_state["completed"] = True
        session_state["history"].append({
            "text": "Simulation erfolgreich abgeschlossen. Alle Parameter liegen im optimalen Bereich.",
            "is_user": False,
            "timestamp": "2026-01-01T00:00:08Z"
        })

        # User opens a brand new tab / window
        new_page = await browser.new_page()
        await setup_routes(new_page)

        await new_page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await new_page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(new_page.locator(".session-item")).to_have_count(1)

        # Typing indicator must NOT be visible anymore
        await expect(new_page.locator("#typing-indicator")).not_to_be_visible()

        # Both user prompt and complete AI answer must be restored in the chat container
        chat_container = new_page.locator("#chat-container")
        await expect(chat_container).to_contain_text("Berechne eine komplexe Simulation")
        await expect(chat_container).to_contain_text("Simulation erfolgreich abgeschlossen. Alle Parameter liegen im optimalen Bereich.")

        # Ensure no duplicates
        user_messages = new_page.locator(".user-message")
        ai_messages = new_page.locator(".ai-message")
        await expect(user_messages).to_have_count(1)
        await expect(ai_messages).to_have_count(1)

        await new_page.close()
        await browser.close()


@pytest.mark.asyncio
async def test_thinking_box_styling_and_contrast_e2e():
    """Verify that .ai-reasoning thinking box has proper CSS styling, contrast, and interactive toggling."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        ai_thinking_text = (
            "<thinking>\n"
            "Schritt 1: Initialisiere Analyse.\n"
            "Schritt 2: Validiere Hypothese.\n"
            "</thinking>\n"
            "Das Ergebnis steht fest."
        )

        history_data = [
            {"text": "Erkläre deine Überlegung", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"text": ai_thinking_text, "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
        ]

        async def auth_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"authenticated": true, "username": "testuser"}'
            )
        await page.route("**/api/auth/status", auth_route)

        async def sessions_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([{"id": "sess-think-style", "title": "Thinking Style Chat", "created_at": "2026-01-01T00:00:00Z", "has_icon": False}])
            )
        await page.route("**/api/sessions", sessions_route)

        async def settings_route(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"prompt": "", "include_gps": false}'
            )
        await page.route("**/api/sessions/*/settings", settings_route)

        async def history_route(route):
            await route.fulfill(
                status=200,
                headers={"X-Is-Processing": "false"},
                content_type="application/json",
                body=json.dumps(history_data)
            )
        await page.route("**/api/sessions/*/history", history_route)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)

        reasoning_box = page.locator(".ai-message details.ai-reasoning")
        await expect(reasoning_box).to_be_visible()

        # 1. Computed style assertions for CSS visibility and styling
        styles = await reasoning_box.evaluate("""(el) => {
            const computed = window.getComputedStyle(el);
            return {
                display: computed.display,
                borderRadius: computed.borderRadius,
                borderWidth: computed.borderWidth,
                cursor: window.getComputedStyle(el.querySelector('summary')).cursor
            };
        }""")

        assert styles["display"] == "block", f"Expected display block, got {styles['display']}"
        assert styles["borderRadius"] != "0px", "Thinking box should have rounded border"
        assert styles["cursor"] == "pointer", "Summary should have pointer cursor"

        # 2. Initially closed for completed message
        assert await reasoning_box.get_attribute("open") is None

        # 3. Click summary to open
        summary = reasoning_box.locator("summary")
        await summary.click()
        await expect(reasoning_box).to_have_attribute("open", "")

        content = reasoning_box.locator(".reasoning-content")
        await expect(content).to_be_visible()
        await expect(content).to_contain_text("Schritt 1: Initialisiere Analyse.")
        await expect(content).to_contain_text("Schritt 2: Validiere Hypothese.")

        # 4. Click summary again to close
        await summary.click()
        assert await reasoning_box.get_attribute("open") is None

        # 5. Final answer is clearly visible
        await expect(page.locator(".ai-message")).to_contain_text("Das Ergebnis steht fest.")

        await browser.close()
