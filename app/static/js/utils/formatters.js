/**
 * Formatting utilities for AI thoughts, download buttons, and markdown sanitization.
 */

export const formatThoughtBlocks = (rawText, isStreaming = false) => {
    let formatted = rawText || "";

    // Mask code blocks and inline code spans to prevent quoted tags from closing details early
    const codePlaceholders = [];
    const maskCode = (text) => {
        // Mask multiline code blocks ```...```
        let masked = text.replace(/```[\s\S]*?```/g, (match) => {
            const placeholder = `___CODE_BLOCK_${codePlaceholders.length}___`;
            codePlaceholders.push({ placeholder, original: match });
            return placeholder;
        });
        // Mask inline code spans `...`
        masked = masked.replace(/`[^`\n]+`/g, (match) => {
            const placeholder = `___INLINE_CODE_${codePlaceholders.length}___`;
            codePlaceholders.push({ placeholder, original: match });
            return placeholder;
        });
        return masked;
    };

    const unmaskCode = (text) => {
        let unmasked = text;
        for (let i = codePlaceholders.length - 1; i >= 0; i--) {
            unmasked = unmasked.replace(codePlaceholders[i].placeholder, codePlaceholders[i].original);
        }
        return unmasked;
    };

    const maskedText = maskCode(formatted);
    const normalizedText = normalizeMarkdownLinks(maskedText);

    // Closed thought/thinking blocks with backreference \1 to ensure matching tags
    // Tolerates optional whitespace inside tags e.g. <thinking > or </thinking >
    let processed = normalizedText.replace(/<\s*(thought|thinking|gedanken)\s*>([\s\S]*?)<\s*\/\s*\1\s*>/gi, (match, tag, content) => {
        return `<details class='ai-reasoning'><summary>Gedankengang der KI</summary><div class='reasoning-content'>\n${content.trim()}\n</div></details>\n`;
    });

    // Open unclosed thought/thinking block while streaming
    if (isStreaming && /<\s*(thought|thinking|gedanken)\s*>/i.test(processed)) {
        processed = processed.replace(/<\s*(thought|thinking|gedanken)\s*>([\s\S]*)$/gi, (match, tag, content) => {
            return `<details class='ai-reasoning' open><summary>Gedankengang der KI...</summary><div class='reasoning-content'>\n${content.trim()}\n</div></details>\n`;
        });
    }

    return unmaskCode(processed);
};

export const isPlaceholderFilename = (fileName) => {
    if (!fileName) return false;
    const clean = fileName.trim().toLowerCase();
    const stem = clean.substring(0, clean.lastIndexOf('.')) || clean;
    const placeholderStems = new Set(["dateiname", "filename", "beispiel", "example", "placeholder"]);
    const placeholderFull = new Set(["dateiname.pdf", "filename.pdf", "datei.ext", "dateiname.ext", "filename.ext"]);
    return placeholderFull.has(clean) || placeholderStems.has(stem);
};

export const normalizeMarkdownLinks = (text) => {
    if (!text) return "";
    return text.replace(/\[([^\]]+)\]\s+\(([^)]+)\)/g, '[$1]($2)');
};

export const enhanceMarkdownLinksAndImages = (container) => {
    if (!container) return;
    container.querySelectorAll("img").forEach(img => {
        img.loading = "lazy";
        img.decoding = "async";
    });
    container.querySelectorAll("a").forEach(a => {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const href = a.getAttribute("href") || "";
        if (href.startsWith("/app/data/") || href.startsWith("/uploads/")) {
            const fname = decodeURIComponent(href.split("/").pop());
            if (fname && !isPlaceholderFilename(fname)) {
                a.setAttribute("download", fname);
            }
        }
    });
};

export const attachDownloadButtons = (bubble, text) => {
    if (!bubble || !text) return;
    const pathRegex = /\/app\/data\/([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)\/data\/([^\s"'`<>()*\[\]]+)/g;
    let match;
    const downloadLinks = [];
    while ((match = pathRegex.exec(text)) !== null) {
        let linkPath = match[0];
        if (linkPath.endsWith('.') || linkPath.endsWith(',')) {
            linkPath = linkPath.slice(0, -1);
        }
        downloadLinks.push(linkPath);
    }

    const uniqueLinks = Array.from(new Set(downloadLinks));
    if (uniqueLinks.length > 0) {
        let downloadContainer = bubble.querySelector(".download-links-container");
        if (!downloadContainer) {
            downloadContainer = document.createElement("div");
            downloadContainer.className = "download-links-container";
            bubble.appendChild(downloadContainer);
        } else {
            downloadContainer.innerHTML = '';
        }

        uniqueLinks.forEach(linkPath => {
            const fileName = decodeURIComponent(linkPath.split('/').pop());
            if (isPlaceholderFilename(fileName)) {
                return;
            }
            const btn = document.createElement("a");
            btn.href = linkPath;
            btn.target = "_blank";
            btn.download = fileName;
            btn.className = "download-btn";
            
            const icon = document.createElement("i");
            icon.className = "ph-bold ph-download-simple";
            btn.appendChild(icon);
            btn.appendChild(document.createTextNode(" " + fileName));
            
            downloadContainer.appendChild(btn);
        });
    }
};

export const renderMarkdownContent = (targetElement, text, isStreaming = false) => {
    const formatted = formatThoughtBlocks(text, isStreaming);
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        const parsedHTML = marked.parse(formatted);
        targetElement.innerHTML = DOMPurify.sanitize(parsedHTML, {
            ADD_TAGS: ['details', 'summary'],
            ADD_ATTR: ['class', 'open']
        });
        targetElement.className = "markdown-body";
        enhanceMarkdownLinksAndImages(targetElement);
    } else {
        targetElement.textContent = formatted;
    }
};
