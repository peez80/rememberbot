import json
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8019

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
async def test_auth_modal_not_flashing_on_initial_load():
    """Verify that #auth-modal starts hidden in the HTML to prevent a flash for logged-in users."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Mock authenticated status with 200ms delay to simulate network latency
        async def slow_auth(route):
            await asyncio.sleep(0.2)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='{"authenticated": true, "username": "testuser"}'
            )
        await page.route("**/api/auth/status", slow_auth)
        await page.route("**/api/sessions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": "sess-1", "title": "Test Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        
        # In the static DOM before/during auth check, auth-modal MUST NOT be flex/visible
        modal = page.locator("#auth-modal")
        is_visible = await modal.is_visible()
        assert not is_visible, "Auth modal was visible before authentication check completed (causes flash)!"

        await browser.close()


@pytest.mark.asyncio
async def test_sidebar_dom_preserved_on_session_switch():
    """Verify that switching sessions updates the active class WITHOUT destroying and rebuilding the sidebar DOM."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated": true, "username": "testuser"}'
        ))
        sessions_data = [
            {"id": "sess-1", "title": "Chat 1", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "sess-2", "title": "Chat 2", "created_at": "2026-01-01T00:00:00Z"}
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
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator(".session-item")).to_have_count(2)

        # Mark DOM node with a custom property
        await page.evaluate("""() => {
            const firstItem = document.querySelector('.session-item');
            if (firstItem) firstItem._custom_marker = "persisted_node";
        }""")

        # Trigger select session 2
        items = page.locator(".session-item")
        await items.nth(1).click()
        await page.wait_for_timeout(300)

        # Switch back to session 1
        await items.nth(0).click()
        await page.wait_for_timeout(300)

        # Check if the DOM node was preserved or wiped out
        has_marker = await page.evaluate("""() => {
            const firstItem = document.querySelector('.session-item');
            return firstItem ? firstItem._custom_marker === "persisted_node" : false;
        }""")
        assert has_marker, "Sidebar DOM elements were destroyed and recreated during session switch!"

        await browser.close()


@pytest.mark.asyncio
async def test_prompt_preserved_during_gps_and_visibilitychange():
    """Verify that a prompt submitted while GPS is slow is NOT wiped when visibilitychange fires."""
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
            body='[{"id": "sess-gps", "title": "GPS Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/sess-gps/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": "", "include_gps": true}'
        ))
        await page.route("**/api/sessions/sess-gps/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        # Slow chat response
        async def slow_chat(route):
            await asyncio.sleep(1.0)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Antwort mit Standort erhalten", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/sess-gps/chat", slow_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        # Mock geolocation with 1s delay
        await page.evaluate("""() => {
            navigator.geolocation.getCurrentPosition = (success, error, options) => {
                setTimeout(() => {
                    success({ coords: { latitude: 48.137, longitude: 11.576 } });
                }, 1000);
            };
        }""")

        # Submit a prompt
        await page.fill("#message-input", "Wichtiger Prompt mit GPS")
        await page.click("#send-btn")

        # User message should appear immediately
        user_msg = page.locator(".user-message:has-text('Wichtiger Prompt mit GPS')")
        await expect(user_msg).to_be_visible()

        # Simulate returning to tab while GPS is still pending
        await page.evaluate("""() => {
            Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });
            document.dispatchEvent(new Event('visibilitychange'));
        }""")

        # Verify message did NOT vanish
        await page.wait_for_timeout(500)
        assert await user_msg.is_visible(), "Prompt vanished when visibilitychange fired during GPS lookup!"

        # Wait for AI reply
        await expect(page.locator("text='Antwort mit Standort erhalten'")).to_be_visible(timeout=5000)
        assert await user_msg.is_visible(), "Prompt vanished after reply arrived!"

        await browser.close()


@pytest.mark.asyncio
async def test_image_upload_error_displayed_in_chat():
    """Verify that HTTP 400 upload errors display a clear error message in the chat."""
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
            body='[{"id": "sess-err", "title": "Error Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        # Return 400 error
        await page.route("**/api/sessions/sess-err/chat", lambda route: route.fulfill(
            status=400,
            content_type="application/json",
            body='{"error": "Maximal 5 Bilder erlaubt"}'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        await page.fill("#message-input", "Nachricht mit Fehler")
        await page.click("#send-btn")

        # Expect clear error message to appear in the chat
        await expect(page.locator("text='Maximal 5 Bilder erlaubt'")).to_be_visible(timeout=3000)

        await browser.close()


@pytest.mark.asyncio
async def test_inflight_select_session_does_not_wipe_new_submit():
    """Verify that an in-flight selectSession history fetch does not wipe a newly submitted message."""
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
            body='[{"id": "sess-race", "title": "Race Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        
        # Slow history route (500ms delay)
        history_calls = {"count": 0}
        async def slow_history(route):
            history_calls["count"] += 1
            await asyncio.sleep(0.5)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body='[]'
            )
        await page.route("**/api/sessions/*/history", slow_history)

        async def fast_chat(route):
            await asyncio.sleep(0.8)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Schnelle Antwort", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/*/chat", fast_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        # Submit message immediately while history fetch may still be settling
        await page.fill("#message-input", "Sofort gesendet")
        await page.click("#send-btn")

        user_msg = page.locator(".user-message:has-text('Sofort gesendet')")
        await expect(user_msg).to_be_visible()

        # Wait across the history fetch resolution window
        await page.wait_for_timeout(600)
        assert await user_msg.is_visible(), "User message was wiped by delayed selectSession history resolution!"

        await expect(page.locator("text='Schnelle Antwort'")).to_be_visible(timeout=3000)
        assert await user_msg.is_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_camera_capture_visibilitychange_submit_flow():
    """Verify that selecting a photo via file upload, simulating camera visibilitychange, and submitting works seamlessly."""
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
            body='[{"id": "sess-cam", "title": "Cam Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        chat_received = {}
        async def mock_chat(route):
            await asyncio.sleep(0.5)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Foto erfolgreich verarbeitet", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/sess-cam/chat", mock_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        # Set files on camera-upload
        import base64
        png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        
        await page.set_input_files("#camera-upload", {
            "name": "blob",
            "mimeType": "image/png",
            "buffer": png_bytes
        })

        # Simulate returning to tab from camera app (visibilitychange)
        await page.evaluate("""() => {
            Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });
            document.dispatchEvent(new Event('visibilitychange'));
        }""")

        # Preview should be visible
        await expect(page.locator("#image-preview-container .preview-item")).to_be_visible()

        # Send
        await page.click("#send-btn")

        # Check user message with image is visible
        user_msg = page.locator(".user-message")
        await expect(user_msg).to_be_visible()
        await expect(user_msg.locator("img.chat-image")).to_be_visible()

        # AI reply
        await expect(page.locator("text='Foto erfolgreich verarbeitet'")).to_be_visible(timeout=3000)

        await browser.close()


@pytest.mark.asyncio
async def test_history_messages_rendered_without_animation_jitter():
    """Verify that messages loaded from history have the history-message class to avoid animation re-triggers."""
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
            body='[{"id": "sess-hist", "title": "History Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        history_data = [
            {"text": "Alte Nachricht 1", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"text": "Alte Nachricht 2", "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
        ]
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(history_data)
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        messages = page.locator("#chat-container .message")
        await expect(messages).to_have_count(2)

        # Both must have history-message class
        for i in range(2):
            msg = messages.nth(i)
            class_str = await msg.get_attribute("class")
            assert "history-message" in class_str, f"Message {i} did not have history-message class: {class_str}"

        await browser.close()


@pytest.mark.asyncio
async def test_camera_upload_input_configuration():
    """Verify that camera input is optimized for single-shot camera intent on mobile (no multiple attribute)."""
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
            body='[{"id": "sess-cam-cfg", "title": "Cam Config", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        
        camera_input = page.locator("#camera-upload")
        has_multiple = await camera_input.evaluate("el => el.hasAttribute('multiple')")
        # Should not have multiple attribute to avoid Android OS camera intent memory errors
        assert not has_multiple, "Camera upload input should not have multiple attribute to prevent mobile OS memory crash!"

        await browser.close()


@pytest.mark.asyncio
async def test_client_image_compression_and_object_url_preview():
    """Verify that selected images in preview use Object URLs (not heavy base64 strings) and submit correctly."""
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
            body='[{"id": "sess-comp", "title": "Compression Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        async def mock_chat(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Komprimiertes Bild empfangen", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/*/chat", mock_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        import base64
        png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

        await page.set_input_files("#image-upload", {
            "name": "large_photo.png",
            "mimeType": "image/png",
            "buffer": png_bytes
        })

        preview_img = page.locator("#image-preview-container .preview-item img")
        await expect(preview_img).to_be_visible()

        # Check preview src starts with blob: (not data: which bloats DOM memory)
        src = await preview_img.get_attribute("src")
        assert src.startswith("blob:"), f"Preview image used non-blob src ({src[:30]}...), which bloats mobile memory!"

        await page.fill("#message-input", "Bild hochladen")
        await page.click("#send-btn")

        await expect(page.locator("text='Komprimiertes Bild empfangen'")).to_be_visible(timeout=5000)

        await browser.close()


@pytest.mark.asyncio
async def test_image_compression_fallback_for_empty_mime_type():
    """Verify that images with empty MIME type (common on some mobile cameras) are still compressed properly."""
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
            body='[{"id": "sess-empty-mime", "title": "Empty Mime Chat", "created_at": "2026-01-01T00:00:00Z"}]'
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))
        await page.route("**/api/sessions/*/history", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[]'
        ))

        async def mock_chat(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Bild ohne Mime verarbeitet", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/*/chat", mock_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        import base64
        png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

        # Simulate mobile file with empty mimeType and name "blob"
        await page.set_input_files("#camera-upload", {
            "name": "blob",
            "mimeType": "",
            "buffer": png_bytes
        })

        preview_img = page.locator("#image-preview-container .preview-item img")
        await expect(preview_img).to_be_visible()
        src = await preview_img.get_attribute("src")
        assert src.startswith("blob:"), f"Preview image should have blob: src even for empty mime type, got {src}"

        await page.click("#send-btn")
        await expect(page.locator("text='Bild ohne Mime verarbeitet'")).to_be_visible(timeout=5000)

        await browser.close()


@pytest.mark.asyncio
async def test_photo_message_persisted_across_chat_switch_during_ai_generation():
    """Verify that when a user sends a photo, switches chat immediately while AI is processing, the photo is still in history upon return."""
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
            body=json.dumps([
                {"id": "sess-a", "title": "Chat A (Foto)", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "sess-b", "title": "Chat B (Andere)", "created_at": "2026-01-01T00:01:00Z"}
            ])
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        # Track history dynamically
        histories = {
            "sess-a": [],
            "sess-b": []
        }

        async def route_history(route):
            url = route.request.url
            for sid in ["sess-a", "sess-b"]:
                if f"/api/sessions/{sid}/history" in url:
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(histories[sid]),
                        headers={"X-Is-Processing": "true" if sid == "sess-a" and len(histories[sid]) == 1 else "false"}
                    )
                    return
            await route.fulfill(status=200, content_type="application/json", body="[]")

        await page.route("**/api/sessions/*/history", route_history)

        # Slow chat route for Chat A (takes 5s)
        async def slow_chat(route):
            # Record user message in backend history immediately
            histories["sess-a"].append({
                "text": "Mein Foto [1 Bild(er) angehängt]",
                "is_user": True,
                "image_urls": ["/uploads/sess-a/photo1.jpg"],
                "images": [{"url": "/uploads/sess-a/photo1.jpg", "width": 100, "height": 100}],
                "timestamp": "2026-01-01T00:00:02Z"
            })
            await asyncio.sleep(3)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "Foto in Chat A erkannt", "timestamp": "2026-01-01T00:00:05Z"})
            )
        await page.route("**/api/sessions/sess-a/chat", slow_chat)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        # Select Chat A
        await page.click(".session-item:has-text('Chat A')")

        import base64
        png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

        await page.set_input_files("#camera-upload", {
            "name": "photo1.jpg",
            "mimeType": "image/jpeg",
            "buffer": png_bytes
        })

        await page.fill("#message-input", "Mein Foto")
        await page.click("#send-btn")

        # Verify photo is in chat container
        user_msg = page.locator("#chat-container .user-message")
        await expect(user_msg).to_be_visible()

        # Immediately switch to Chat B while AI is still generating
        await page.click(".session-item:has-text('Chat B')")
        await page.wait_for_timeout(300)

        # Now switch back to Chat A
        await page.click(".session-item:has-text('Chat A')")

        # Chat A MUST retain the user message and photo!
        user_msg_after_return = page.locator("#chat-container .user-message")
        await expect(user_msg_after_return).to_be_visible()
        await expect(user_msg_after_return.locator("img.chat-image")).to_be_visible()

        await browser.close()



