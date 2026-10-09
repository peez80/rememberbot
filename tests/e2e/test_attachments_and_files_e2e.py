import json
import base64
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8032

TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
SAMPLE_CSV = b"id,name,score\n1,Alice,100\n2,Bob,95"


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


async def setup_standard_routes(page, session_id, title="Test Chat", history=None):
    """Helper to register standard async route handlers."""
    if history is None:
        history = []

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
            body=json.dumps([{"id": session_id, "title": title, "created_at": "2026-01-01T00:00:00Z", "has_icon": False}])
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
            body=json.dumps(history)
        )
    await page.route("**/api/sessions/*/history", history_route)


@pytest.mark.asyncio
async def test_multi_file_upload_staging_and_preview_e2e():
    """Verify selecting multiple files (images + documents) renders previews in #image-preview-container."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await setup_standard_routes(page, "sess-upload-1", "Upload Chat")

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        preview_container = page.locator("#image-preview-container")
        await expect(preview_container).not_to_be_visible()

        # Select 2 images and 1 CSV file via #file-upload
        await page.set_input_files("#file-upload", [
            {"name": "diagram1.png", "mimeType": "image/png", "buffer": TINY_PNG},
            {"name": "diagram2.png", "mimeType": "image/png", "buffer": TINY_PNG},
            {"name": "test_data.csv", "mimeType": "text/csv", "buffer": SAMPLE_CSV}
        ])

        # Preview container must now be visible
        await expect(preview_container).to_be_visible()

        # Check 2 image previews
        image_previews = preview_container.locator(".preview-item img")
        await expect(image_previews).to_have_count(2)
        src1 = await image_previews.nth(0).get_attribute("src")
        src2 = await image_previews.nth(1).get_attribute("src")
        assert src1.startswith("blob:")
        assert src2.startswith("blob:")

        # Check 1 document card
        doc_card = preview_container.locator(".preview-file-card")
        await expect(doc_card).to_have_count(1)
        await expect(doc_card.locator(".preview-file-icon")).to_be_visible()
        await expect(doc_card.locator(".preview-file-name")).to_have_text("test_data.csv")
        await expect(doc_card.locator(".preview-file-size")).to_contain_text("B")

        await browser.close()


@pytest.mark.asyncio
async def test_remove_staged_file_before_send_e2e():
    """Verify removing a staged file from preview updates state and DOM before submission."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await setup_standard_routes(page, "sess-remove-1", "Remove Chat")

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        preview_container = page.locator("#image-preview-container")

        # Select 1 image and 1 CSV file
        await page.set_input_files("#file-upload", [
            {"name": "photo.png", "mimeType": "image/png", "buffer": TINY_PNG},
            {"name": "remove_me.csv", "mimeType": "text/csv", "buffer": SAMPLE_CSV}
        ])

        await expect(preview_container).to_be_visible()
        await expect(preview_container.locator(".preview-item")).to_have_count(1)
        await expect(preview_container.locator(".preview-file-card")).to_have_count(1)

        # Click remove button on the CSV file card
        remove_doc_btn = preview_container.locator(".preview-file-card .remove-image-btn")
        await remove_doc_btn.click()

        # The file card must be gone, image remains
        await expect(preview_container.locator(".preview-file-card")).to_have_count(0)
        await expect(preview_container.locator(".preview-item")).to_have_count(1)
        await expect(preview_container).to_be_visible()

        # Now remove the image
        remove_img_btn = preview_container.locator(".preview-item .remove-image-btn")
        await remove_img_btn.click()

        # Preview container is now empty and hidden
        await expect(preview_container).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_attachment_bubble_rendering_e2e():
    """Verify sending message with attachments renders image grid and document list in the bubble."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await setup_standard_routes(page, "sess-bubble-1", "Bubble Chat")

        # Mock SSE chat endpoint
        async def mock_chat(route):
            sse_body = (
                'data: {"type": "delta", "text": "Dateien empfangen und ausgewertet."}\n\n'
                'data: {"type": "done", "reply": "Dateien empfangen und ausgewertet.", "timestamp": "2026-01-01T00:00:05Z"}\n\n'
            )
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body
            )

        await page.route("**/api/sessions/sess-bubble-1/chat", mock_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Wait for session item to load and be active
        await expect(page.locator(".session-item")).to_have_count(1)

        # Attach 1 image and 1 CSV
        await page.set_input_files("#file-upload", [
            {"name": "screenshot.png", "mimeType": "image/png", "buffer": TINY_PNG},
            {"name": "daten.csv", "mimeType": "text/csv", "buffer": SAMPLE_CSV}
        ])

        # Type message and submit
        await page.fill("#message-input", "Hier ist das Dokumenten-Paket")
        await page.click("#send-btn")

        # Verify user message bubble
        user_message = page.locator(".user-message")
        await expect(user_message).to_be_visible(timeout=5000)
        await expect(user_message).to_contain_text("Hier ist das Dokumenten-Paket")
        await expect(user_message).to_contain_text("[1 Bild(er), 1 Datei(en) angehängt]")

        # Verify rendered image grid in user bubble
        img = user_message.locator(".chat-images-grid .chat-image")
        await expect(img).to_be_visible()

        # Verify rendered attachment card in user bubble
        att_item = user_message.locator(".chat-attachments-list .chat-attachment-item")
        await expect(att_item).to_be_visible()
        await expect(att_item.locator(".chat-attachment-name")).to_have_text("daten.csv")
        await expect(att_item.locator(".chat-attachment-size")).to_contain_text("B")
        await expect(att_item.locator(".chat-attachment-download")).to_be_visible()

        # Verify preview container is cleared
        preview_container = page.locator("#image-preview-container")
        await expect(preview_container).not_to_be_visible()

        # Verify AI reply appears
        await expect(page.locator(".ai-message")).to_contain_text("Dateien empfangen und ausgewertet.")

        await browser.close()


@pytest.mark.asyncio
async def test_download_buttons_for_ai_generated_files_e2e():
    """Verify AI generated file links create .download-btn with download attribute and filter placeholders."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        ai_response_text = (
            "Ich habe den Bericht generiert.\n\n"
            "Download: /app/data/testuser/sess-dl-1/data/jahresbericht.pdf und "
            "[daten_export.xlsx](/app/data/testuser/sess-dl-1/data/daten_export.xlsx)\n\n"
            "Beispiel: [Dateiname.pdf](Dateiname.pdf) ist nur ein Platzhalter."
        )

        history_data = [
            {"text": "Bitte erstelle den Jahresbericht", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"text": ai_response_text, "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
        ]

        await setup_standard_routes(page, "sess-dl-1", "Download Chat", history=history_data)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)

        ai_bubble = page.locator(".ai-message .message-bubble")
        await expect(ai_bubble).to_be_visible()

        # 1. Verify download container exists
        dl_container = ai_bubble.locator(".download-links-container")
        await expect(dl_container).to_be_visible()

        # 2. Verify .download-btn for jahresbericht.pdf
        pdf_btn = dl_container.locator(".download-btn:has-text('jahresbericht.pdf')")
        await expect(pdf_btn).to_be_visible()
        assert await pdf_btn.get_attribute("download") == "jahresbericht.pdf"
        assert await pdf_btn.get_attribute("href") == "/app/data/testuser/sess-dl-1/data/jahresbericht.pdf"

        # 3. Verify .download-btn for daten_export.xlsx
        xlsx_btn = dl_container.locator(".download-btn:has-text('daten_export.xlsx')")
        await expect(xlsx_btn).to_be_visible()
        assert await xlsx_btn.get_attribute("download") == "daten_export.xlsx"

        # 4. Verify placeholder Dateiname.pdf does NOT generate a download-btn
        placeholder_btn = dl_container.locator(".download-btn:has-text('Dateiname.pdf')")
        await expect(placeholder_btn).to_have_count(0)

        # 5. Verify inline markdown link for daten_export.xlsx has download attribute and target="_blank"
        inline_link = ai_bubble.locator("a:has-text('daten_export.xlsx')").first
        await expect(inline_link).to_be_visible()
        assert await inline_link.get_attribute("download") == "daten_export.xlsx"
        assert await inline_link.get_attribute("target") == "_blank"

        await browser.close()


@pytest.mark.asyncio
async def test_max_files_limit_alert_e2e():
    """Verify selecting more than 10 files triggers browser alert and rejects addition."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await setup_standard_routes(page, "sess-limit-1", "Limit Chat")

        dialog_messages = []
        async def handle_alert(dialog):
            dialog_messages.append(dialog.message)
            await dialog.accept()
        page.on("dialog", handle_alert)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        # Attempt to upload 11 files
        eleven_files = [
            {"name": f"doc_{i}.csv", "mimeType": "text/csv", "buffer": SAMPLE_CSV}
            for i in range(11)
        ]
        await page.set_input_files("#file-upload", eleven_files)

        # Verify browser alert was shown with exact message
        assert any("maximal 10 dateien" in msg.lower() for msg in dialog_messages)

        # Verify preview container remains hidden
        preview_container = page.locator("#image-preview-container")
        await expect(preview_container).not_to_be_visible()

        await browser.close()
