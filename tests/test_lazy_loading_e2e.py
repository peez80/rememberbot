import json
import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8009


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
async def test_chat_images_have_lazy_loading_attributes_e2e():
    """Playwright E2E test verifying that chat history images (grid & markdown) have loading='lazy' and decoding='async'."""
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
            body='[{"id": "sess-lazy-1", "title": "Lazy Loading Test", "created_at": "2026-01-01T00:00:00Z"}]'
        ))

        history_data = [
            {
                "text": "User message with attached images",
                "is_user": True,
                "image_urls": ["/uploads/sess-lazy-1/test1.png", "/uploads/sess-lazy-1/test2.png"],
                "timestamp": "2026-01-01T00:00:00Z"
            },
            {
                "text": "AI response with inline markdown image ![sample image](/uploads/sess-lazy-1/sample.png)",
                "is_user": False,
                "image_urls": [],
                "timestamp": "2026-01-01T00:01:00Z"
            }
        ]

        await page.route("**/api/sessions/sess-lazy-1/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/sess-lazy-1/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(history_data)
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        # Remove auth modal explicitly if present
        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        chat_container = page.locator("#chat-container")
        await expect(chat_container).to_be_visible()

        # Wait for messages to be rendered
        await page.wait_for_selector(".message")

        # 1. Check attached chat images in grid
        grid_imgs = page.locator(".chat-images-grid img")
        grid_count = await grid_imgs.count()
        assert grid_count == 2, f"Expected 2 attached images, got {grid_count}"

        for i in range(grid_count):
            img = grid_imgs.nth(i)
            loading_attr = await img.get_attribute("loading")
            decoding_attr = await img.get_attribute("decoding")
            assert loading_attr == "lazy", f"Grid img {i} has loading='{loading_attr}', expected 'lazy'"
            assert decoding_attr == "async", f"Grid img {i} has decoding='{decoding_attr}', expected 'async'"

        # 2. Check inline markdown images
        markdown_imgs = page.locator(".markdown-body img")
        md_count = await markdown_imgs.count()
        assert md_count >= 1, f"Expected at least 1 markdown image, got {md_count}"

        for i in range(md_count):
            img = markdown_imgs.nth(i)
            loading_attr = await img.get_attribute("loading")
            decoding_attr = await img.get_attribute("decoding")
            assert loading_attr == "lazy", f"Markdown img {i} has loading='{loading_attr}', expected 'lazy'"
            assert decoding_attr == "async", f"Markdown img {i} has decoding='{decoding_attr}', expected 'async'"

        await browser.close()
