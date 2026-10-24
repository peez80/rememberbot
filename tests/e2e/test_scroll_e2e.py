import json
import re
import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8008


@pytest.fixture(scope="module", autouse=True)
def run_test_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    time.sleep(1)  # wait for server to start
    yield
    server.should_exit = True


@pytest.mark.asyncio
async def test_scroll_to_bottom_button_e2e():
    """Playwright E2E test verifying floating scroll button behavior."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-1/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Fill chat-container with 30 message items to force scrolling
        await page.evaluate("""() => {
            const container = document.getElementById('chat-container');
            container.innerHTML = '';
            for (let i = 0; i < 30; i++) {
                const div = document.createElement('div');
                div.className = 'message ai-message';
                div.innerHTML = `<div class="message-bubble" style="padding: 20px;">Message ${i}</div>`;
                container.appendChild(div);
            }
        }""")

        scroll_btn = page.locator("#scroll-to-bottom-btn")

        # 1. Scrolled to bottom initially: button should NOT have class 'visible'
        await page.evaluate("""() => {
            const c = document.getElementById('chat-container');
            c.scrollTop = c.scrollHeight;
            c.dispatchEvent(new Event('scroll'));
        }""")
        await expect(scroll_btn).not_to_have_class(re.compile(r"visible"))

        # 2. Scroll up to top: button MUST have class 'visible'
        await page.evaluate("""() => {
            const c = document.getElementById('chat-container');
            c.scrollTop = 0;
            c.dispatchEvent(new Event('scroll'));
        }""")
        await expect(scroll_btn).to_have_class(re.compile(r"visible"))

        # 3. Click button: scroll back to bottom
        await scroll_btn.click()

        # 4. Verify button becomes hidden again after scrolling to bottom
        await expect(scroll_btn).not_to_have_class(re.compile(r"visible"))

        # 5. Verify scrolled to bottom
        is_at_bottom = await page.wait_for_function("""() => {
            const c = document.getElementById('chat-container');
            return Math.abs(c.scrollHeight - c.scrollTop - c.clientHeight) <= 50;
        }""")
        assert is_at_bottom

        await browser.close()


@pytest.mark.asyncio
async def test_image_loading_preserves_scroll_position_e2e():
    """Verify that images loading higher up in history do not force scroll to bottom when user is scrolled up."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        # Provide history with an image at message 0 and many text messages following it
        history_data = [
            {
                "text": "First message with image",
                "is_user": True,
                "image_urls": ["data:image/svg+xml;charset=utf-8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='200'></svg>"],
                "timestamp": "2026-01-01T00:00:00Z"
            }
        ]
        for i in range(50):
            history_data.append({
                "text": f"Message {i} content text line that takes up vertical space in chat container. Adding extra text to ensure vertical overflow.",
                "is_user": False,
                "image_urls": [],
                "timestamp": "2026-01-01T00:01:00Z"
            })

        await page.route("**/api/sessions/sess-1/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/sess-1/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(history_data)
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Wait for async history fetch to finish rendering messages
        await page.wait_for_selector(".message")

        # Scroll up to middle of chat (e.g., scrollTop = 200)
        await page.evaluate("""() => {
            const c = document.getElementById('chat-container');
            c.scrollTop = 200;
        }""")

        # Trigger onload event of an image higher up in history
        await page.evaluate("""() => {
            const img = document.querySelector('.chat-image');
            if (img) {
                // Simulate image load event
                const loadEvent = new Event('load');
                img.dispatchEvent(loadEvent);
            }
        }""")

        # Check scroll position: User should NOT have been scrolled to the bottom
        scroll_info = await page.evaluate("""() => {
            const c = document.getElementById('chat-container');
            return {
                scrollTop: c.scrollTop,
                scrollHeight: c.scrollHeight,
                clientHeight: c.clientHeight,
                isNearBottom: (c.scrollHeight > c.clientHeight) && (Math.abs(c.scrollHeight - c.scrollTop - c.clientHeight) <= 100)
            };
        }""")

        # User was at scrollTop = 200, so after image load while scrolled up, user should NOT be forced to the bottom
        assert not scroll_info["isNearBottom"], f"User was forced to bottom! scrollTop={scroll_info['scrollTop']}, scrollHeight={scroll_info['scrollHeight']}, clientHeight={scroll_info['clientHeight']}"
        assert scroll_info["scrollTop"] >= 200, f"scrollTop decreased unexpectedly! scrollTop={scroll_info['scrollTop']}"

        await browser.close()


@pytest.mark.asyncio
async def test_progressive_message_batching_on_scroll_top_e2e():
    """Verify that older messages (>20) are progressively prepended into the DOM when scrolling to the top."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-batch", "title": "Batch Test Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))

        # Generate 35 messages (0 to 34)
        history_35 = []
        for i in range(35):
            history_35.append({
                "text": f"Batch Message {i:02d} with extra padding to ensure height",
                "is_user": (i % 2 == 0),
                "image_urls": [],
                "timestamp": f"2026-01-01T{i:02d}:00:00Z"
            })

        await page.route("**/api/sessions/sess-batch/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/sess-batch/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(history_35)
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Wait for messages to render
        await page.wait_for_selector(".message")

        # Initial render should only render the latest 20 messages (indices 15..34)
        initial_count = await page.evaluate("() => document.querySelectorAll('#chat-container .message').length")
        assert initial_count == 20

        # Oldest message 00 should not yet be in DOM
        has_msg_00 = await page.evaluate("() => document.body.innerText.includes('Batch Message 00')")
        assert not has_msg_00

        # Scroll to top to trigger progressive prepending
        await page.evaluate("""() => {
            const c = document.getElementById('chat-container');
            c.scrollTop = 0;
            c.dispatchEvent(new Event('scroll'));
        }""")

        # Wait for older messages to be prepended into the DOM
        await page.wait_for_function("() => document.querySelectorAll('#chat-container .message').length === 35")

        total_count = await page.evaluate("() => document.querySelectorAll('#chat-container .message').length")
        assert total_count == 35

        # Now Message 00 must be in DOM
        has_msg_00_now = await page.evaluate("() => document.body.innerText.includes('Batch Message 00')")
        assert has_msg_00_now

        await browser.close()


