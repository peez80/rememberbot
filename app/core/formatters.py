import re
import urllib.parse
import logging

logger = logging.getLogger(__name__)

def format_thought_blocks(text: str, is_streaming: bool = False) -> str:
    """
    Convert <thinking>...</thinking> (and legacy <thought>) blocks into collapsible <details> HTML elements.
    Supports unclosed streaming thought tags gracefully.
    Masks code blocks and inline code spans to prevent quoted tags from prematurely closing blocks.
    """
    if not text:
        return ""

    code_placeholders = []

    def mask_code_block(match):
        placeholder = f"___CODE_BLOCK_{len(code_placeholders)}___"
        code_placeholders.append((placeholder, match.group(0)))
        return placeholder

    def mask_inline_code(match):
        placeholder = f"___INLINE_CODE_{len(code_placeholders)}___"
        code_placeholders.append((placeholder, match.group(0)))
        return placeholder

    # 1. Mask fenced multiline code blocks ```...```
    masked_text = re.sub(r'```[\s\S]*?```', mask_code_block, text)
    # 2. Mask inline code spans `...`
    masked_text = re.sub(r'`[^`\n]+`', mask_inline_code, masked_text)

    def replace_closed_thought(match):
        content = match.group(2).strip()
        return (
            "<details class='ai-reasoning'>\n"
            "  <summary>Gedankengang der KI</summary>\n"
            "  <div class='reasoning-content'>\n"
            f"{content}\n"
            "  </div>\n"
            "</details>\n"
        )

    # Match closed tags with backreference \1 to enforce matching opening and closing tag names
    # Tolerates optional whitespace inside tags e.g. <thinking > or </thinking >
    formatted = re.sub(
        r'<\s*(thought|thinking|gedanken)\s*>(.*?)<\s*/\s*\1\s*>',
        replace_closed_thought,
        masked_text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # If streaming and an open tag exists without its matching closing tag
    if is_streaming and re.search(r'<\s*(thought|thinking|gedanken)\s*>', formatted, flags=re.IGNORECASE):
        def replace_open_thought(match):
            content = match.group(2).strip()
            return (
                "<details class='ai-reasoning' open>\n"
                "  <summary>Gedankengang der KI...</summary>\n"
                "  <div class='reasoning-content'>\n"
                f"{content}\n"
                "  </div>\n"
                "</details>\n"
            )
        formatted = re.sub(
            r'<\s*(thought|thinking|gedanken)\s*>(.*)$',
            replace_open_thought,
            formatted,
            flags=re.DOTALL | re.IGNORECASE
        )

    # Restore placeholders
    for placeholder, original in reversed(code_placeholders):
        formatted = formatted.replace(placeholder, original)

    return formatted.strip()


def format_local_links(text: str, username: str, session_id: str) -> str:
    """
    Rewrite raw file and internal storage links to application download endpoints.
    """
    if not text:
        return ""

    def replace_local_links(match):
        label = match.group(1)
        href = match.group(2)
        if href.startswith("file://"):
            href = href[7:]
        data_prefix = f"/app/data/{username}/sessions/{session_id}/data/"
        uploads_prefix = f"/app/data/{username}/sessions/{session_id}/uploads/"
        if href.startswith(data_prefix):
            rel_path = href[len(data_prefix):]
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        if href.startswith(uploads_prefix):
            rel_path = href[len(uploads_prefix):]
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/uploads/{session_id}/{encoded})"
        if not href.startswith(("http", "/", "data:", "#", "mailto:")):
            encoded = urllib.parse.quote(href, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        return match.group(0)

    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_local_links, text)


def sanitize_svg(svg_content: str | bytes) -> str:
    """
    Sanitizes SVG content by removing <script> tags, <foreignObject>, inline event handlers,
    and javascript: URI schemes to prevent Stored XSS.
    """
    if isinstance(svg_content, bytes):
        svg_text = svg_content.decode("utf-8", errors="replace")
    else:
        svg_text = str(svg_content)

    # Remove script tags and their content
    svg_text = re.sub(r'<script\b[^>]*>([\s\S]*?)<\/script>', '', svg_text, flags=re.IGNORECASE)
    svg_text = re.sub(r'<script\b[^>]*\/?>', '', svg_text, flags=re.IGNORECASE)

    # Remove foreignObject tags and their content
    svg_text = re.sub(r'<foreignObject\b[^>]*>([\s\S]*?)<\/foreignObject>', '', svg_text, flags=re.IGNORECASE)

    # Remove event handlers (e.g., onload=..., onclick=..., onerror=...)
    svg_text = re.sub(r'\bon\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', '', svg_text, flags=re.IGNORECASE)

    # Remove javascript: pseudo-protocol in attributes
    svg_text = re.sub(
        r'(href|xlink:href)\s*=\s*(?:"\s*javascript:[^"]*"|\'\s*javascript:[^\']*\'|javascript:[^\s>]+)',
        '',
        svg_text,
        flags=re.IGNORECASE
    )

    return svg_text.strip()
