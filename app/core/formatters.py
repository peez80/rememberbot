import os
import re
import urllib.parse
import logging
from typing import Optional

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


def is_placeholder_filename(filename: str) -> bool:
    if not filename:
        return False
    clean = filename.strip().lower()
    base = os.path.basename(clean)
    stem = os.path.splitext(base)[0]
    placeholder_stems = {"dateiname", "filename", "beispiel", "example", "placeholder"}
    placeholder_full = {"dateiname.pdf", "filename.pdf", "datei.ext", "dateiname.ext", "filename.ext"}
    return base in placeholder_full or stem in placeholder_stems


def format_local_links(text: str, username: str, session_id: str, user_data_dir: Optional[str] = None) -> str:
    """
    Rewrite raw file and internal storage links to application download endpoints.
    Optionally scans user_data_dir for mentioned existing files to auto-link them.
    Ignores placeholder filenames from prompts or documentation (e.g. dateiname.pdf).
    """
    if not text:
        return ""

    def replace_local_links(match):
        label = match.group(1).strip()
        href = match.group(2).strip()
        if is_placeholder_filename(href) or is_placeholder_filename(label):
            return f"[{label}]({href})"
        if href.startswith("file://"):
            href = href[7:]
        data_prefix = f"/app/data/{username}/sessions/{session_id}/data/"
        uploads_prefix = f"/app/data/{username}/sessions/{session_id}/uploads/"
        if href.startswith(data_prefix):
            rel_path = href[len(data_prefix):]
            if is_placeholder_filename(rel_path):
                return f"[{label}]({rel_path})"
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        if href.startswith(uploads_prefix):
            rel_path = href[len(uploads_prefix):]
            if is_placeholder_filename(rel_path):
                return f"[{label}]({rel_path})"
            encoded = urllib.parse.quote(rel_path, safe='/')
            return f"[{label}](/uploads/{session_id}/{encoded})"
        if not href.startswith(("http", "/", "data:", "#", "mailto:")):
            clean_href = href[2:] if href.startswith("./") else href
            if is_placeholder_filename(clean_href):
                return f"[{label}]({href})"
            encoded = urllib.parse.quote(clean_href, safe='/')
            return f"[{label}](/app/data/{username}/{session_id}/data/{encoded})"
        return f"[{label}]({href})"

    # 0. Pre-normalize markdown links with whitespace between brackets and parentheses
    text = re.sub(r'\[([^\]]+)\]\s+\(([^)]+)\)', r'[\1](\2)', text)

    # 1. Transform markdown links [label](href) (tolerating optional whitespace)
    formatted = re.sub(r'\[([^\]]+)\]\s*\(([^)]+)\)', replace_local_links, text)

    # 2. Rewrite raw container storage paths (e.g. /app/data/{username}/sessions/{session_id}/data/...)
    raw_storage_pattern = rf'(?:file://)?/app/data/{re.escape(username)}/sessions/{re.escape(session_id)}/data/([^\s"`\'<>()*\[\]]+)'
    def replace_raw_storage(m):
        raw_fname = m.group(1)
        if is_placeholder_filename(raw_fname):
            return m.group(0)
        return rf'/app/data/{username}/{session_id}/data/{raw_fname}'
    formatted = re.sub(raw_storage_pattern, replace_raw_storage, formatted)

    # 3. Fallback auto-linking: If user_data_dir exists, find mentioned files that are not yet linked
    if user_data_dir and os.path.isdir(user_data_dir):
        try:
            for entry in os.scandir(user_data_dir):
                if entry.is_file():
                    fname = entry.name
                    # Ignore hidden files, temporary context files, or session internals
                    if fname.startswith(".") or fname.startswith("chat_context_"):
                        continue
                    download_url = f"/app/data/{username}/{session_id}/data/{urllib.parse.quote(fname, safe='/')}"
                    # If this file is not already linked with its download endpoint in the text
                    if download_url not in formatted:
                        # Check if file is mentioned as code `fname`
                        code_pattern = rf'`{re.escape(fname)}`'
                        if re.search(code_pattern, formatted):
                            formatted = re.sub(code_pattern, f'[`{fname}`]({download_url})', formatted)
                        else:
                            # Plain text mention (word boundary)
                            word_pattern = rf'(?<!/)(?<!\[)(?<!\()\b{re.escape(fname)}\b(?!\))(?![^<]*>)'
                            if re.search(word_pattern, formatted):
                                formatted = re.sub(word_pattern, f'[{fname}]({download_url})', formatted, count=1)
        except Exception as e:
            logger.warning(f"Error scanning user_data_dir '{user_data_dir}' for auto-linking files: {e}", exc_info=True)

    return formatted


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
