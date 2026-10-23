import asyncio
import json
import pytest
import threading
import time
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8055


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
async def test_chat_switch_shows_loading_animation_until_history_loaded():
    """Verify that selecting another chat immediately displays the loading overlay,
    and only hides it after the chat history has finished loading."""
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
                {"id": "sess-alpha", "title": "Chat Alpha", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "sess-beta", "title": "Chat Beta", "created_at": "2026-01-01T01:00:00Z"}
            ])
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        # sess-alpha returns immediately
        # sess-beta has an artificial delay of 600ms
        async def handle_history(route):
            url = route.request.url
            if "sess-alpha" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([
                        {"text": "Nachricht in Chat Alpha", "is_user": False, "images": [], "timestamp": "2026-01-01T00:01:00Z"}
                    ])
                )
            elif "sess-beta" in url:
                await asyncio.sleep(0.6)
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([
                        {"text": "Nachricht in Chat Beta", "is_user": False, "images": [], "timestamp": "2026-01-01T01:01:00Z"}
                    ])
                )
            else:
                await route.fulfill(status=200, content_type="application/json", body="[]")

        await page.route("**/api/sessions/*/history", handle_history)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("#chat-container")).to_be_visible()

        # Chat Alpha should be rendered first
        await expect(page.locator("text='Nachricht in Chat Alpha'")).to_be_visible()

        # Loading overlay should not be visible when Chat Alpha is loaded
        loading_overlay = page.locator("#chat-loading-overlay")
        await expect(loading_overlay).not_to_be_visible()

        # Click on Chat Beta
        await page.click(".session-item:has-text('Chat Beta')")

        # Loading animation MUST be visible immediately while Chat Beta is loading!
        await expect(loading_overlay).to_be_visible()
        await expect(loading_overlay.locator(".chat-loading-spinner")).to_be_visible()
        await expect(loading_overlay).to_contain_text("Chat wird geladen...")

        # Wait for Chat Beta history resolution
        await expect(page.locator("text='Nachricht in Chat Beta'")).to_be_visible(timeout=3000)

        # Once loaded, loading overlay must be hidden!
        await expect(loading_overlay).not_to_be_visible()

        await browser.close()


@pytest.mark.asyncio
async def test_rapid_chat_switch_maintains_loading_until_latest_selected():
    """Verify that rapidly clicking between chats keeps the loading animation visible
    until the latest selected chat is fully rendered, ignoring previous stale responses."""
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
                {"id": "sess-one", "title": "Chat Eins", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "sess-two", "title": "Chat Zwei", "created_at": "2026-01-01T01:00:00Z"},
                {"id": "sess-three", "title": "Chat Drei", "created_at": "2026-01-01T02:00:00Z"}
            ])
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        async def handle_history(route):
            url = route.request.url
            if "sess-one" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([{"text": "Erster Chat Inhalt", "is_user": False, "images": [], "timestamp": "2026-01-01T00:01:00Z"}])
                )
            elif "sess-two" in url:
                await asyncio.sleep(0.5)
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([{"text": "Zweiter Chat Inhalt", "is_user": False, "images": [], "timestamp": "2026-01-01T01:01:00Z"}])
                )
            elif "sess-three" in url:
                await asyncio.sleep(0.8)
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([{"text": "Dritter Chat Inhalt", "is_user": False, "images": [], "timestamp": "2026-01-01T02:01:00Z"}])
                )
            else:
                await route.fulfill(status=200, content_type="application/json", body="[]")

        await page.route("**/api/sessions/*/history", handle_history)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("text='Erster Chat Inhalt'")).to_be_visible()

        loading_overlay = page.locator("#chat-loading-overlay")
        await expect(loading_overlay).not_to_be_visible()

        # Click Chat Zwei, then rapidly click Chat Drei
        await page.click(".session-item:has-text('Chat Zwei')")
        await expect(loading_overlay).to_be_visible()

        await page.wait_for_timeout(100)
        await page.click(".session-item:has-text('Chat Drei')")
        await expect(loading_overlay).to_be_visible()

        # Chat Zwei finishes first around t=500ms, but overlay must STAY visible because Chat Drei is still loading!
        await page.wait_for_timeout(550)
        await expect(loading_overlay).to_be_visible()

        # Finally Chat Drei finishes around t=900ms
        await expect(page.locator("text='Dritter Chat Inhalt'")).to_be_visible(timeout=3000)
        await expect(loading_overlay).not_to_be_visible()
        # Stale content from Chat Zwei should NOT be rendered
        assert await page.locator("text='Zweiter Chat Inhalt'").count() == 0

        await browser.close()


@pytest.mark.asyncio
async def test_background_polling_does_not_show_loading_overlay():
    """Verify that background polling (syncing session status for the current active chat)
    does not pop up the loading overlay and disturb user reading."""
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
                {"id": "sess-poll", "title": "Poll Chat", "created_at": "2026-01-01T00:00:00Z"}
            ])
        ))
        await page.route("**/api/sessions/*/settings", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"prompt": ""}'
        ))

        history_count = 0
        async def handle_history(route):
            nonlocal history_count
            history_count += 1
            if history_count == 1:
                # Initially processing
                await route.fulfill(
                    status=200,
                    headers={"X-Is-Processing": "true"},
                    content_type="application/json",
                    body=json.dumps([{"text": "Erste Nachricht", "is_user": True, "images": [], "timestamp": "2026-01-01T00:00:00Z"}])
                )
            else:
                await route.fulfill(
                    status=200,
                    headers={"X-Is-Processing": "false"},
                    content_type="application/json",
                    body=json.dumps([
                        {"text": "Erste Nachricht", "is_user": True, "images": [], "timestamp": "2026-01-01T00:00:00Z"},
                        {"text": "Fertige KI-Antwort", "is_user": False, "images": [], "timestamp": "2026-01-01T00:00:05Z"}
                    ])
                )

        await page.route("**/api/sessions/*/history", handle_history)

        status_count = 0
        async def handle_status(route):
            nonlocal status_count
            status_count += 1
            if status_count >= 2:
                await route.fulfill(status=200, content_type="application/json", body='{"is_processing": false}')
            else:
                await route.fulfill(status=200, content_type="application/json", body='{"is_processing": true}')

        await page.route("**/api/sessions/*/status", handle_status)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")
        await expect(page.locator("text='Erste Nachricht'")).to_be_visible()

        loading_overlay = page.locator("#chat-loading-overlay")
        # Overlay should not be visible
        await expect(loading_overlay).not_to_be_visible()

        # Wait for background poll to resolve the finished answer
        await expect(page.locator("text='Fertige KI-Antwort'")).to_be_visible(timeout=3000)

        # Loading overlay MUST have remained hidden throughout the background update
        await expect(loading_overlay).not_to_be_visible()

        await browser.close()

