import json
import pytest
import threading
import time
import asyncio
import uvicorn
from app.main import app
from playwright.async_api import async_playwright, expect

SERVER_PORT = 8033


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


async def setup_standard_routes(page, session_id, title="Markdown Chat", history=None):
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
async def test_rich_markdown_rendering_in_chat_e2e():
    """Verify that marked.js correctly parses all standard Markdown elements into DOM nodes."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        markdown_payload = (
            "# Haupttitel\n\n"
            "## Untertitel\n\n"
            "### Zwischenabschnitt\n\n"
            "Normaler Text mit **fettem Text** und *kursivem Text*.\n\n"
            "- Punkt Alpha\n"
            "- Punkt Beta\n\n"
            "1. Erster Schritt\n"
            "2. Zweiter Schritt\n\n"
            "> Ein wichtiges Zitat im Blockquote.\n\n"
            "```python\n"
            "def calculate(x, y):\n"
            "    return x * y\n"
            "```\n\n"
            "Hier ist `inline_function()` im Fließtext.\n\n"
            "| Produkt | Preis | Status |\n"
            "| :--- | :--- | :--- |\n"
            "| RememberBot | Kostenlos | Aktiv |\n"
            "| Premium | 10 EUR | Beta |\n"
        )

        history_data = [
            {"text": "Erstelle eine strukturierte Übersicht", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"text": markdown_payload, "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
        ]

        await setup_standard_routes(page, "sess-md-1", "Markdown Chat", history=history_data)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)

        md_body = page.locator(".ai-message .markdown-body")
        await expect(md_body).to_be_visible()

        # 1. Headings
        await expect(md_body.locator("h1")).to_have_text("Haupttitel")
        await expect(md_body.locator("h2")).to_have_text("Untertitel")
        await expect(md_body.locator("h3")).to_have_text("Zwischenabschnitt")

        # 2. Bold & Italic
        await expect(md_body.locator("strong")).to_have_text("fettem Text")
        await expect(md_body.locator("em")).to_have_text("kursivem Text")

        # 3. Lists
        ul_items = md_body.locator("ul li")
        await expect(ul_items).to_have_count(2)
        await expect(ul_items.nth(0)).to_have_text("Punkt Alpha")
        await expect(ul_items.nth(1)).to_have_text("Punkt Beta")

        ol_items = md_body.locator("ol li")
        await expect(ol_items).to_have_count(2)
        await expect(ol_items.nth(0)).to_have_text("Erster Schritt")
        await expect(ol_items.nth(1)).to_have_text("Zweiter Schritt")

        # 4. Blockquote
        await expect(md_body.locator("blockquote")).to_contain_text("Ein wichtiges Zitat im Blockquote.")

        # 5. Code block & Inline code
        code_block = md_body.locator("pre code")
        await expect(code_block).to_be_visible()
        await expect(code_block).to_contain_text("def calculate(x, y):")

        inline_code = md_body.locator("p code")
        await expect(inline_code).to_have_text("inline_function()")

        # 6. Table
        table = md_body.locator("table")
        await expect(table).to_be_visible()
        headers = table.locator("th")
        await expect(headers).to_have_count(3)
        await expect(headers.nth(0)).to_have_text("Produkt")
        await expect(headers.nth(1)).to_have_text("Preis")
        await expect(headers.nth(2)).to_have_text("Status")

        rows = table.locator("tbody tr")
        await expect(rows).to_have_count(2)
        await expect(rows.nth(0).locator("td").nth(0)).to_have_text("RememberBot")

        await browser.close()


@pytest.mark.asyncio
async def test_dompurify_xss_protection_e2e():
    """Verify DOMPurify sanitizes malicious scripts, attributes and javascript: URLs in rendered messages."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        xss_payload = (
            "Gefahr im Verzug:\n"
            "<script>window.__xss_flag = 'EXPLOITED_SCRIPT';</script>\n"
            '<img src="invalid_path.jpg" onerror="window.__xss_flag = \'EXPLOITED_IMG\';" />\n'
            '<a id="xss-link" href="javascript:window.__xss_flag = \'EXPLOITED_A\';">Klick mich</a>\n'
            '<svg><set onbegin="window.__xss_flag = \'EXPLOITED_SVG\';" attributeName="x"/></svg>\n'
            '<iframe src="javascript:alert(1)"></iframe>'
        )

        history_data = [
            {"text": "Führe XSS Test aus", "is_user": True, "timestamp": "2026-01-01T00:00:00Z"},
            {"text": xss_payload, "is_user": False, "timestamp": "2026-01-01T00:00:05Z"}
        ]

        await setup_standard_routes(page, "sess-xss-1", "Security Chat", history=history_data)

        await page.goto(f"http://127.0.0.1:{SERVER_PORT}")

        await page.evaluate("""() => {
            const modal = document.getElementById('auth-modal');
            if (modal) modal.remove();
        }""")

        await expect(page.locator(".session-item")).to_have_count(1)

        md_body = page.locator(".ai-message .markdown-body")
        await expect(md_body).to_be_visible()

        # Wait 500ms to allow any rogue script or image onerror to fire if not sanitized
        await page.wait_for_timeout(500)

        # 1. Verify window.__xss_flag was never created or set
        xss_flag = await page.evaluate("() => window.__xss_flag")
        assert xss_flag is None, f"XSS payload executed in browser! Flag: {xss_flag}"

        # 2. Verify script tags are stripped
        assert await md_body.locator("script").count() == 0

        # 3. Verify iframe tags are stripped
        assert await md_body.locator("iframe").count() == 0

        # 4. Verify javascript: href was removed or neutralized by DOMPurify
        link = md_body.locator("#xss-link")
        if await link.count() > 0:
            href = await link.get_attribute("href")
            assert not href or not href.lower().startswith("javascript:"), f"Malicious javascript: URL not stripped: {href}"

        # 5. Verify onerror attribute is not present on img
        img = md_body.locator("img")
        if await img.count() > 0:
            onerror = await img.first.get_attribute("onerror")
            assert onerror is None, f"Malicious onerror attribute not stripped: {onerror}"

        await browser.close()
