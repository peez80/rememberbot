import pytest
from app.core.formatters import (
    format_thought_blocks,
    format_local_links,
    sanitize_svg,
)

def test_format_thought_blocks_closed():
    raw = "Here is an answer.\n<thought>\nStep 1: Check facts\nStep 2: Conclude\n</thought>\nFinal conclusion."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "<summary>Gedankengang der KI</summary>" in formatted
    assert "<div class='reasoning-content'>" in formatted
    assert "Step 1: Check facts" in formatted
    assert "Final conclusion." in formatted
    assert "<thought>" not in formatted
    assert "</thought>" not in formatted

def test_format_thought_blocks_streaming_open():
    raw = "Starting response...\n<thought>\nThinking in progress..."
    formatted = format_thought_blocks(raw, is_streaming=True)
    assert "<details class='ai-reasoning' open>" in formatted
    assert "<summary>Gedankengang der KI...</summary>" in formatted
    assert "Thinking in progress..." in formatted

def test_format_thought_blocks_with_quoted_tags():
    raw = (
        "<thinking>\n"
        "Check: `<thinking>` and `</thinking>` tags at start.\n"
        "Actual internal thought.\n"
        "</thinking>\n"
        "User answer."
    )
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "`<thinking>` and `</thinking>` tags at start." in formatted
    assert "Actual internal thought." in formatted
    parts = formatted.split("</details>")
    assert len(parts) == 2
    assert "tags at start" not in parts[1]
    assert parts[1].strip() == "User answer."

def test_format_thought_blocks_whitespace_in_tag():
    raw = "Start.\n<thinking >\nContent.\n</thinking >\nEnd."
    formatted = format_thought_blocks(raw, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted
    assert "Content." in formatted
    assert "End." in formatted


def test_format_local_links_data_and_uploads():
    username = "alice"
    session_id = "sess123"
    text = (
        "See [report.pdf](/app/data/alice/sessions/sess123/data/report.pdf) and "
        "[photo.jpg](/app/data/alice/sessions/sess123/uploads/photo.jpg) and "
        "[raw_file.csv](sub/raw_file.csv) and [external](https://example.com)."
    )
    result = format_local_links(text, username, session_id)
    assert "[report.pdf](/app/data/alice/sess123/data/report.pdf)" in result
    assert "[photo.jpg](/uploads/sess123/photo.jpg)" in result
    assert "[raw_file.csv](/app/data/alice/sess123/data/sub/raw_file.csv)" in result
    assert "[external](https://example.com)" in result

def test_sanitize_svg():
    evil_svg = '<svg onload="alert(1)"><script>alert("xss")</script><foreignObject>evil</foreignObject><a href="javascript:alert(2)"><text>Test</text></a></svg>'
    clean_svg = sanitize_svg(evil_svg)
    assert "<script" not in clean_svg
    assert "onload=" not in clean_svg
    assert "<foreignObject" not in clean_svg
    assert "javascript:" not in clean_svg
    assert "<svg" in clean_svg
    assert "<text>Test</text>" in clean_svg
