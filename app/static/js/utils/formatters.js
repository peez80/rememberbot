/**
 * Formatting utilities for AI thoughts, download buttons, and markdown sanitization.
 */

export const formatThoughtBlocks = (rawText, isStreaming = false) => {
    let formatted = rawText || "";
    // Closed thought blocks
    formatted = formatted.replace(/<thought>([\s\S]*?)<\/thought>/g, (match, content) => {
        return `<details class='ai-reasoning'><summary>Gedankengang der KI</summary><div class='reasoning-content'>\n${content.trim()}\n</div></details>\n`;
    });
    // Open unclosed thought block while streaming
    if (isStreaming && formatted.includes('<thought>')) {
        formatted = formatted.replace(/<thought>([\s\S]*)$/g, (match, content) => {
            return `<details class='ai-reasoning' open><summary>Gedankengang der KI...</summary><div class='reasoning-content'>\n${content.trim()}\n</div></details>\n`;
        });
    }
    return formatted;
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
            const btn = document.createElement("a");
            btn.href = linkPath;
            btn.target = "_blank";
            const fileName = decodeURIComponent(linkPath.split('/').pop());
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
        targetElement.querySelectorAll("img").forEach(img => {
            img.loading = "lazy";
            img.decoding = "async";
        });
    } else {
        targetElement.textContent = formatted;
    }
};
