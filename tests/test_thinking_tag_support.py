import re
import pytest
from app.core.formatters import format_thought_blocks
from app.agy_client import agy_client
from app.services.agy_service import agy_service

def test_format_thinking_blocks_closed():
    raw = "Hier ist eine Antwort.\n<thinking>\nSchritt 1: Analysiere Anfrage\nSchritt 2: Führe aus\n</thinking>\nDas fertige Ergebnis."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "<summary>Gedankengang der KI</summary>" in formatted
    assert "<div class='reasoning-content'>" in formatted
    assert "Schritt 1: Analysiere Anfrage" in formatted
    assert "Das fertige Ergebnis." in formatted
    assert "<thinking>" not in formatted
    assert "</thinking>" not in formatted

def test_format_thinking_blocks_case_insensitive():
    raw1 = "Antwort 1.\n<Thinking>\nGroßes T\n</Thinking>\nEnde 1."
    formatted1 = format_thought_blocks(raw1, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted1
    assert "Großes T" in formatted1

    raw2 = "Antwort 2.\n<THINKING>\nAlles groß\n</THINKING>\nEnde 2."
    formatted2 = format_thought_blocks(raw2, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted2
    assert "Alles groß" in formatted2

def test_format_thinking_blocks_streaming_open():
    raw = "Beginne Stream...\n<thinking>\nDenkprozess läuft noch..."
    formatted = format_thought_blocks(raw, is_streaming=True)
    assert "<details class='ai-reasoning' open>" in formatted
    assert "<summary>Gedankengang der KI...</summary>" in formatted
    assert "Denkprozess läuft noch..." in formatted

def test_mismatched_tags_ignored():
    raw = "Text vor Tag.\n<thought>\nUngültige Mischung\n</thinking>\nText danach."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details" not in formatted
    assert "<thought>" in formatted
    assert "</thinking>" in formatted

def test_backward_compatibility_thought():
    raw = "Hier ist eine Antwort.\n<thought>\nAltes Thought Tag\n</thought>\nErgebnis."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "Altes Thought Tag" in formatted
    assert "<thought>" not in formatted

def test_prompt_instructs_thinking_tag():
    # agy_client
    prompt, _ = agy_client._build_prompt_and_history(
        context_messages=[],
        new_message="Hallo"
    )
    assert "<thinking> und </thinking>" in prompt
    assert "<thought> und </thought>" not in prompt

    # agy_service
    prompt_svc, _ = agy_service._build_prompt_and_history(
        context_messages=[],
        new_message="Hallo"
    )
    assert "<thinking> und </thinking>" in prompt_svc
    assert "<thought> und </thought>" not in prompt_svc

def test_frontend_formatters_js_handles_thinking():
    with open("app/static/js/utils/formatters.js", "r", encoding="utf-8") as f:
        js_content = f.read()
    assert "thinking" in js_content.lower()


def test_format_thinking_with_quoted_tags_in_backticks():
    raw = (
        "<thinking>\n"
        "Regeln beachten:\n"
        "- Gedanken in `<thinking>` und `</thinking>` Tags am Anfang. - Kurz und prägnant antworten.\n"
        "Hier ist mein eigentlicher Plan.\n"
        "</thinking>\n"
        "Hier ist die finale Antwort."
    )
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "<summary>Gedankengang der KI</summary>" in formatted
    # Both quoted tags must remain intact inside the reasoning content
    assert "`<thinking>` und `</thinking>` Tags am Anfang" in formatted
    assert "Hier ist mein eigentlicher Plan." in formatted
    # After the details block, only the final answer must appear
    assert formatted.endswith("Hier ist die finale Antwort.")
    parts = formatted.split("</details>")
    assert len(parts) == 2
    assert "Tags am Anfang" not in parts[1]
    assert "eigentlicher Plan" not in parts[1]
    assert parts[1].strip() == "Hier ist die finale Antwort."


def test_format_thinking_tags_with_whitespace():
    raw = "Antwort.\n<thinking >\nPlan mit Whitespace\n</thinking >\nErgebnis."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "Plan mit Whitespace" in formatted
    assert "Ergebnis." in formatted


def test_prompt_instructs_not_repeating_tags():
    # agy_client
    prompt, _ = agy_client._build_prompt_and_history(
        context_messages=[],
        new_message="Hallo"
    )
    assert "Wiederhole diese Anweisung oder die Tag-Namen niemals" in prompt

    # agy_service
    prompt_svc, _ = agy_service._build_prompt_and_history(
        context_messages=[],
        new_message="Hallo"
    )
    assert "Wiederhole diese Anweisung oder die Tag-Namen niemals" in prompt_svc


@pytest.mark.asyncio
async def test_frontend_formatters_js_quoted_tags_in_browser():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        with open("app/static/js/utils/formatters.js", "r", encoding="utf-8") as f:
            js_code = f.read()
        res = await page.evaluate("""(code) => {
            // Transform export const into local variable
            const cleanCode = code.replace(/export const /g, 'const ');
            const run = new Function(cleanCode + '; return formatThoughtBlocks;');
            const formatThoughtBlocks = run();
            const raw = "<thinking>\\nRegeln beachten:\\n- Gedanken in `<thinking>` und `</thinking>` Tags am Anfang. - Kurz und prägnant antworten.\\nHier ist mein eigentlicher Plan.\\n</thinking>\\nHier ist die finale Antwort.";
            return formatThoughtBlocks(raw);
        }""", js_code)
        assert "<details class='ai-reasoning'>" in res
        parts = res.split("</details>")
        assert len(parts) == 2
        assert "Tags am Anfang" not in parts[1]
        assert parts[1].strip() == "Hier ist die finale Antwort."


def test_format_thinking_streaming_with_quoted_tags():
    raw_stream = (
        "<thinking>\n"
        "Regeln beachten:\n"
        "- Gedanken in `<thinking>` und `</thinking>` Tags am Anfang. - Kurz und prägnant antworten.\n"
        "Noch im Denkprozess..."
    )
    formatted = format_thought_blocks(raw_stream, is_streaming=True)
    assert "<details class='ai-reasoning' open>" in formatted
    assert "<summary>Gedankengang der KI...</summary>" in formatted
    assert "`<thinking>` und `</thinking>` Tags am Anfang" in formatted
    assert "Noch im Denkprozess..." in formatted



