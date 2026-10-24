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


def test_sanitize_svg_advanced_vectors():
    malicious = (
        '<svg>'
        '<script>/* evil */ alert(1);</script>'
        '<SCRIPT SRC="https://evil.com/xss.js"></SCRIPT>'
        '<foreignObject width="100" height="100"><body xmlns="http://www.w3.org/1999/xhtml"><div>evil</div></body></foreignObject>'
        '<a xlink:href="javascript:alert(2)"><text>Link</text></a>'
        '<a href="javascript:alert(3)"><text>Link2</text></a>'
        '<circle cx="50" cy="50" r="40" onclick="alert(4)" onerror="alert(5)"/>'
        '</svg>'
    )
    clean = sanitize_svg(malicious)
    assert "<script" not in clean.lower()
    assert "<foreignobject" not in clean.lower()
    assert "xlink:href" not in clean
    assert "javascript:" not in clean
    assert "onclick=" not in clean
    assert "onerror=" not in clean
    assert "<svg>" in clean
    assert "<circle cx=\"50\" cy=\"50\" r=\"40\" />" in clean or "<circle" in clean



def test_format_thinking_blocks_case_insensitive_and_mismatched():
    raw1 = "Antwort 1.\n<Thinking>\nGroßes T\n</Thinking>\nEnde 1."
    formatted1 = format_thought_blocks(raw1, is_streaming=False)
    assert "<details class='ai-reasoning'>" in formatted1
    assert "Großes T" in formatted1

    # Mismatched tags should not be converted to details
    raw2 = "Text vor Tag.\n<thought>\nUngültige Mischung\n</thinking>\nText danach."
    formatted2 = format_thought_blocks(raw2, is_streaming=False)
    assert "<details" not in formatted2
    assert "<thought>" in formatted2
    assert "</thinking>" in formatted2


def test_format_thinking_streaming_with_quoted_tags():
    raw_stream = (
        "<thinking>\n"
        "Regeln beachten:\n"
        "- Gedanken in `<thinking>` und `</thinking>` Tags am Anfang.\n"
        "Noch im Denkprozess..."
    )
    formatted = format_thought_blocks(raw_stream, is_streaming=True)
    assert "<details class='ai-reasoning' open>" in formatted
    assert "<summary>Gedankengang der KI...</summary>" in formatted
    assert "`<thinking>` und `</thinking>` Tags am Anfang" in formatted
    assert "Noch im Denkprozess..." in formatted


def test_format_local_links_relative_and_dot_slash():
    username = "bob"
    session_id = "sess_456"
    text = "Hier ist [daten.csv](daten.csv) und [bericht.pdf](./bericht.pdf) und [unterordner](sub/file.txt)"
    result = format_local_links(text, username, session_id)
    assert f"[daten.csv](/app/data/{username}/{session_id}/data/daten.csv)" in result
    assert f"[bericht.pdf](/app/data/{username}/{session_id}/data/bericht.pdf)" in result
    assert "./" not in result
    assert f"[unterordner](/app/data/{username}/{session_id}/data/sub/file.txt)" in result


def test_format_local_links_raw_container_path():
    username = "bob"
    session_id = "sess_456"
    raw_path = f"/app/data/{username}/sessions/{session_id}/data/export.csv"
    text = f"Die Datei liegt unter {raw_path} zur Abholung bereit."
    result = format_local_links(text, username, session_id)
    expected_link = f"/app/data/{username}/{session_id}/data/export.csv"
    assert expected_link in result
    assert f"/app/data/{username}/sessions/{session_id}/data/" not in result


def test_format_local_links_auto_links_existing_files(tmp_path):
    username = "alice"
    session_id = "sess_789"
    user_data_dir = tmp_path / username / "sessions" / session_id / "data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    (user_data_dir / "tabelle.csv").write_text("a,b,c\n1,2,3")
    (user_data_dir / "chat_context_abcdef12.txt").write_text("old history")
    (user_data_dir / ".hidden_file").write_text("hidden")

    text = "Ich habe die Datei `tabelle.csv` erstellt. chat_context_abcdef12.txt ist intern."
    result = format_local_links(text, username, session_id, user_data_dir=str(user_data_dir))
    assert f"/app/data/{username}/{session_id}/data/tabelle.csv" in result
    assert f"/app/data/{username}/{session_id}/data/chat_context_abcdef12.txt" not in result
    assert f"/app/data/{username}/{session_id}/data/.hidden_file" not in result


def test_format_local_links_whitespace_variations():
    username = "peez"
    session_id = "sess_123"
    text = (
        "Download: [daten.csv] (daten.csv) und [bericht.pdf]  (./bericht.pdf) "
        f"und [diary.json] (/app/data/{username}/sessions/{session_id}/data/diary.json)"
    )
    result = format_local_links(text, username, session_id)
    assert f"[daten.csv](/app/data/{username}/{session_id}/data/daten.csv)" in result
    assert f"[bericht.pdf](/app/data/{username}/{session_id}/data/bericht.pdf)" in result
    assert f"[diary.json](/app/data/{username}/{session_id}/data/diary.json)" in result
    assert "] (" not in result
    assert "]  (" not in result


def test_format_local_links_ignores_placeholders():
    username = "peez"
    session_id = "sess_123"
    text = (
        "Hier ist deine Datei [tabelle.csv](tabelle.csv). "
        "Beispiel: [Dateiname.pdf](Dateiname.pdf) oder [dateiname.ext](dateiname.ext) oder [filename.pdf](filename.pdf)."
    )
    result = format_local_links(text, username, session_id)
    assert f"[tabelle.csv](/app/data/{username}/{session_id}/data/tabelle.csv)" in result
    assert f"/app/data/{username}/{session_id}/data/Dateiname.pdf" not in result
    assert f"/app/data/{username}/{session_id}/data/dateiname.ext" not in result
    assert f"/app/data/{username}/{session_id}/data/filename.pdf" not in result
    assert "[Dateiname.pdf](Dateiname.pdf)" in result
