/**
 * Chat view component for rendering messages, reasoning blocks, file cards, and scroll behavior.
 */

import { getFileIconClass, formatFileSize } from '../utils/dom.js';
import { formatThoughtBlocks, attachDownloadButtons } from '../utils/formatters.js';
import { state } from '../state.js';

export const getChatContainer = () => document.getElementById("chat-container");
export const getScrollToBottomBtn = () => document.getElementById("scroll-to-bottom-btn");

export const checkScrollPosition = () => {
    const chatContainer = getChatContainer();
    const scrollToBottomBtn = getScrollToBottomBtn();
    if (!chatContainer || !scrollToBottomBtn) return;
    const threshold = 50;
    const isAtBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight <= threshold;
    if (isAtBottom) {
        scrollToBottomBtn.classList.remove("visible");
    } else {
        scrollToBottomBtn.classList.add("visible");
    }
};

export const scrollToBottom = (smooth = false) => {
    const chatContainer = getChatContainer();
    const scrollToBottomBtn = getScrollToBottomBtn();
    if (!chatContainer) return;
    chatContainer.scrollTo({
        top: chatContainer.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
    });
    if (scrollToBottomBtn) {
        scrollToBottomBtn.classList.remove("visible");
    }
};

export const handleChatScroll = () => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    checkScrollPosition();

    if (chatContainer.scrollTop < 100 && state.currentRenderStartIndex > 0 && !state.isPrependingMessages) {
        state.isPrependingMessages = true;
        const nextStartIndex = Math.max(0, state.currentRenderStartIndex - state.MESSAGE_BATCH_SIZE);
        const olderMessages = state.currentSessionHistory.slice(nextStartIndex, state.currentRenderStartIndex);
        
        if (olderMessages.length > 0) {
            const fragment = document.createDocumentFragment();
            olderMessages.forEach(msg => {
                const msgFiles = msg.files || [];
                const msgImages = (msg.images || msg.image_urls || []).length > 0 
                    ? (msg.images || msg.image_urls) 
                    : msgFiles.filter(f => f.is_image);
                const msgDiv = createMessageElement(msg.text, msg.is_user, msgImages, msg.timestamp, true, true, false, msgFiles);
                fragment.appendChild(msgDiv);
            });

            const oldScrollHeight = chatContainer.scrollHeight;
            chatContainer.prepend(fragment);
            const newScrollHeight = chatContainer.scrollHeight;
            chatContainer.scrollTop += (newScrollHeight - oldScrollHeight);

            state.currentRenderStartIndex = nextStartIndex;
        }
        state.isPrependingMessages = false;
    }
};

export const createMessageElement = (text, isUser, imagesData = [], timestampStr = null, isHistory = false, skipScroll = false, smoothScroll = false, filesData = []) => {
    const chatContainer = getChatContainer();
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${isUser ? "user-message" : "ai-message"} ${isHistory ? "history-message" : "new-message"}`;

    if (timestampStr) {
        const timeDiv = document.createElement("div");
        timeDiv.className = "message-timestamp";
        const date = new Date(timestampStr);
        timeDiv.textContent = date.toLocaleDateString() + ', ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' Uhr';
        msgDiv.appendChild(timeDiv);
    }

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    if (text) {
        const textDiv = document.createElement("div");
        const formatted = isUser ? text : formatThoughtBlocks(text, false);

        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const parsedHTML = marked.parse(formatted);
            textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, { ADD_TAGS: ['details', 'summary'], ADD_ATTR: ['class', 'open'] });
            textDiv.className = "markdown-body";
            textDiv.querySelectorAll("img").forEach(img => {
                img.loading = "lazy";
                img.decoding = "async";
            });
        } else {
            textDiv.textContent = formatted;
        }

        bubble.appendChild(textDiv);
    }

    if (imagesData && imagesData.length > 0) {
        const gridDiv = document.createElement("div");
        gridDiv.className = "chat-images-grid";
        imagesData.forEach(imgData => {
            let originalUrl = '';
            let hasDimensions = false;
            let width = null, height = null;
            
            if (typeof imgData === 'string') {
                originalUrl = imgData;
            } else if (imgData && imgData.url) {
                originalUrl = imgData.url;
                if (imgData.width && imgData.height) {
                    width = imgData.width;
                    height = imgData.height;
                    hasDimensions = true;
                }
            } else {
                return;
            }
            
            let thumbUrl = originalUrl;
            const uploadMatch = originalUrl.match(/^\/uploads\/([^/]+)\/(.+)$/);
            if (uploadMatch && !originalUrl.includes('/thumbnails/')) {
                thumbUrl = `/uploads/${uploadMatch[1]}/thumbnails/${uploadMatch[2]}`;
            }
            
            const link = document.createElement("a");
            link.href = originalUrl;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.className = "chat-image-link";
            link.title = "Bild in neuem Tab öffnen";
            
            const img = document.createElement("img");
            img.src = thumbUrl;
            if (hasDimensions) {
                img.width = width;
                img.height = height;
            }
            img.alt = "Angehängtes Bild";
            img.className = "chat-image";
            img.loading = "lazy";
            img.decoding = "async";

            let initialHeight = 0;
            img.onload = () => {
                if (img.dataset.loaded) return;
                img.dataset.loaded = "true";
                
                if (hasDimensions) return;

                const newHeight = img.offsetHeight;
                const deltaHeight = newHeight - initialHeight;
                const threshold = 150;
                const canScroll = chatContainer.scrollHeight > chatContainer.clientHeight;
                const isNearBottom = canScroll && (chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight <= threshold);

                if (isNearBottom) {
                    scrollToBottom(skipScroll ? false : smoothScroll);
                } else if (img.offsetTop < chatContainer.scrollTop && deltaHeight > 0) {
                    chatContainer.scrollTop += deltaHeight;
                }
            };
            link.appendChild(img);
            gridDiv.appendChild(link);
        });
        bubble.appendChild(gridDiv);
    }

    const nonImageFiles = (filesData || []).filter(f => f && !f.is_image);
    if (nonImageFiles.length > 0) {
        const attList = document.createElement("div");
        attList.className = "chat-attachments-list";
        nonImageFiles.forEach(f => {
            const card = document.createElement("a");
            card.className = "chat-attachment-item";
            card.href = f.url || "#";
            card.target = "_blank";
            card.rel = "noopener noreferrer";
            card.title = `${f.name || 'Datei'} herunterladen`;

            const icon = document.createElement("i");
            icon.className = `ph-bold ${getFileIconClass(f.name || "")} chat-attachment-icon`;

            const info = document.createElement("div");
            info.className = "chat-attachment-info";

            const title = document.createElement("span");
            title.className = "chat-attachment-name";
            title.textContent = f.name || "Datei";

            const size = document.createElement("span");
            size.className = "chat-attachment-size";
            size.textContent = formatFileSize(f.size);

            info.appendChild(title);
            info.appendChild(size);

            const dlIcon = document.createElement("i");
            dlIcon.className = "ph-bold ph-download-simple chat-attachment-download";

            card.appendChild(icon);
            card.appendChild(info);
            card.appendChild(dlIcon);
            attList.appendChild(card);
        });
        bubble.appendChild(attList);
    }

    if (!isUser && text) {
        attachDownloadButtons(bubble, text);
    }

    msgDiv.appendChild(bubble);
    return msgDiv;
};

export const appendMessage = (text, isUser, imagesData = [], timestampStr = null, skipScroll = false, smoothScroll = false, isHistory = false, filesData = []) => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    const msgDiv = createMessageElement(text, isUser, imagesData, timestampStr, isHistory, skipScroll, smoothScroll, filesData);
    chatContainer.appendChild(msgDiv);
    
    if (!skipScroll) {
        scrollToBottom(smoothScroll);
    }
};

export const appendErrorMessage = (errorText) => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    const msgDiv = document.createElement("div");
    msgDiv.className = "message ai-message error-message new-message";
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = errorText;
    msgDiv.appendChild(bubble);
    chatContainer.appendChild(msgDiv);
    scrollToBottom(true);
};

export const showInitialGreeting = () => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    chatContainer.innerHTML = '';
    const msgDiv = document.createElement("div");
    msgDiv.id = "initial-greeting";
    msgDiv.className = "message ai-message history-message";
    msgDiv.innerHTML = `<div class="message-bubble">Hallo, wie geht es dir heute?</div>`;
    chatContainer.appendChild(msgDiv);
};

export const showTypingIndicator = () => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    if (document.getElementById("typing-indicator")) return;

    const typingDiv = document.createElement("div");
    typingDiv.className = "message ai-message typing-container";
    typingDiv.id = "typing-indicator";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble typing-indicator";
    bubble.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

    typingDiv.appendChild(bubble);
    chatContainer.appendChild(typingDiv);
    scrollToBottom(true);
};

export const removeTypingIndicator = () => {
    const indicator = document.getElementById("typing-indicator");
    if (indicator) {
        indicator.remove();
    }
};
