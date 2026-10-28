/**
 * Chat view component for rendering messages, reasoning blocks, file cards, and scroll behavior.
 */

import { getFileIconClass, formatFileSize } from '../utils/dom.js';
import { formatThoughtBlocks, attachDownloadButtons, enhanceMarkdownLinksAndImages } from '../utils/formatters.js';
import { state } from '../state.js';

export const isSafeUrl = (url) => {
    if (!url || typeof url !== 'string') return false;
    const trimmed = url.trim().toLowerCase();
    return (trimmed.startsWith('/') && !trimmed.startsWith('//')) ||
           trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('blob:');
};

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
                const msgDiv = createMessageElement(msg.text, msg.is_user, msgImages, msg.timestamp, true, true, false, msgFiles, msg.id, msg.status);
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

export const createMessageElement = (text, isUser, imagesData = [], timestampStr = null, isHistory = false, skipScroll = false, smoothScroll = false, filesData = [], messageId = null, status = null, onRemoveQueued = null) => {
    const chatContainer = getChatContainer();
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${isUser ? "user-message" : "ai-message"} ${isHistory ? "history-message" : "new-message"}${status === "queued" ? " queued-message" : ""}`;
    if (messageId) {
        msgDiv.dataset.messageId = messageId;
    }

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
            enhanceMarkdownLinksAndImages(textDiv);
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
            link.href = isSafeUrl(originalUrl) ? originalUrl : '#';
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
            card.href = isSafeUrl(f.url) ? f.url : "#";
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

    if (status === "queued") {
        const bar = document.createElement("div");
        bar.className = "message-queued-bar";

        const badge = document.createElement("span");
        badge.className = "queued-badge";
        badge.innerHTML = '<i class="ph-bold ph-clock"></i> Wartend';

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-queued-btn";
        removeBtn.title = "Wartende Nachricht entfernen";
        removeBtn.setAttribute("aria-label", "Entfernen");
        removeBtn.innerHTML = '<i class="ph-bold ph-x"></i>';
        if (onRemoveQueued) {
            removeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                const currentId = msgDiv.dataset.messageId || messageId;
                if (currentId) {
                    onRemoveQueued(currentId, msgDiv);
                }
            });
        }

        bar.appendChild(badge);
        bar.appendChild(removeBtn);
        msgDiv.appendChild(bar);
    }

    msgDiv.appendChild(bubble);
    return msgDiv;
};

export const markMessageProcessing = (msgDiv) => {
    if (!msgDiv) return;
    msgDiv.classList.remove("queued-message");
    const bar = msgDiv.querySelector(".message-queued-bar");
    if (bar) bar.remove();
};

export const appendMessage = (text, isUser, imagesData = [], timestampStr = null, skipScroll = false, smoothScroll = false, isHistory = false, filesData = [], messageId = null, status = null, onRemoveQueued = null, anchorElement = null) => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return null;
    const msgDiv = createMessageElement(text, isUser, imagesData, timestampStr, isHistory, skipScroll, smoothScroll, filesData, messageId, status, onRemoveQueued);
    if (anchorElement && anchorElement.parentNode === chatContainer) {
        anchorElement.insertAdjacentElement('afterend', msgDiv);
    } else {
        chatContainer.appendChild(msgDiv);
    }
    
    if (!skipScroll) {
        scrollToBottom(smoothScroll);
    }
    return msgDiv;
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

export const showTypingIndicator = (anchorElement = null) => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return;
    removeTypingIndicator();

    const typingDiv = document.createElement("div");
    typingDiv.className = "message ai-message typing-container";
    typingDiv.id = "typing-indicator";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble typing-indicator";
    bubble.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

    typingDiv.appendChild(bubble);
    if (anchorElement && anchorElement.parentNode === chatContainer) {
        anchorElement.insertAdjacentElement('afterend', typingDiv);
    } else {
        chatContainer.appendChild(typingDiv);
    }
    scrollToBottom(true);
};

export const removeTypingIndicator = () => {
    const indicator = document.getElementById("typing-indicator");
    if (indicator) {
        indicator.remove();
    }
};

export const initStreamingMessage = (anchorElement = null) => {
    const chatContainer = getChatContainer();
    if (!chatContainer) return null;

    removeTypingIndicator();

    const aiMsgDiv = document.createElement("div");
    aiMsgDiv.className = "message ai-message streaming new-message";

    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "message-bubble";

    const textDiv = document.createElement("div");
    textDiv.className = "markdown-body";

    // Track manually toggled details across innerHTML re-renders
    const manuallyOpened = new Set();
    textDiv.addEventListener('click', (e) => {
        const summary = e.target.closest('details.ai-reasoning summary');
        if (summary) {
            const details = summary.closest('details.ai-reasoning');
            const allDetails = Array.from(textDiv.querySelectorAll('details.ai-reasoning'));
            const idx = allDetails.indexOf(details);
            setTimeout(() => {
                if (details && details.open) {
                    manuallyOpened.add(idx);
                } else if (details) {
                    manuallyOpened.delete(idx);
                }
            }, 0);
        }
    });

    bubbleDiv.appendChild(textDiv);
    aiMsgDiv.appendChild(bubbleDiv);
    if (anchorElement && anchorElement.parentNode === chatContainer) {
        anchorElement.insertAdjacentElement('afterend', aiMsgDiv);
    } else {
        chatContainer.appendChild(aiMsgDiv);
    }

    return {
        aiMsgDiv,
        bubbleDiv,
        textDiv,
        manuallyOpened
    };
};

export const updateStreamingMessage = (controller, accumulatedText) => {
    if (!controller || !controller.textDiv) return;
    const formatted = formatThoughtBlocks(accumulatedText, true);

    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        const parsedHTML = marked.parse(formatted);
        controller.textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, {
            ADD_TAGS: ['details', 'summary'],
            ADD_ATTR: ['class', 'open']
        });

        // Restore user-toggled open states if thought block has closed
        const hasClosedThought = /<\s*\/\s*(thought|thinking|gedanken)\s*>/i.test(accumulatedText);
        if (hasClosedThought && controller.manuallyOpened) {
            const allDetails = controller.textDiv.querySelectorAll("details.ai-reasoning");
            allDetails.forEach((d, idx) => {
                d.open = controller.manuallyOpened.has(idx);
            });
        }

        enhanceMarkdownLinksAndImages(controller.textDiv);
    } else {
        controller.textDiv.textContent = formatted;
    }

    scrollToBottom(false);
};

export const finalizeStreamingMessage = (controller, replyText) => {
    removeTypingIndicator();
    if (!controller) return;

    if (controller.aiMsgDiv) {
        controller.aiMsgDiv.classList.remove("streaming");
    }

    const finalFormatted = formatThoughtBlocks(replyText, false);
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        const parsedHTML = marked.parse(finalFormatted);
        controller.textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, {
            ADD_TAGS: ['details', 'summary'],
            ADD_ATTR: ['class', 'open']
        });

        if (controller.manuallyOpened) {
            const allDetails = controller.textDiv.querySelectorAll("details.ai-reasoning");
            allDetails.forEach((d, idx) => {
                d.open = controller.manuallyOpened.has(idx);
            });
        }

        enhanceMarkdownLinksAndImages(controller.textDiv);
    } else {
        controller.textDiv.textContent = finalFormatted;
    }

    if (controller.bubbleDiv) {
        attachDownloadButtons(controller.bubbleDiv, replyText);
    }
};

export const removeStreamingMessage = (controller) => {
    removeTypingIndicator();
    if (controller && controller.aiMsgDiv) {
        controller.aiMsgDiv.remove();
    }
};

export const getChatLoadingOverlay = () => document.getElementById("chat-loading-overlay");

export const showChatLoading = () => {
    const overlay = getChatLoadingOverlay();
    if (overlay) {
        overlay.classList.add("visible");
        overlay.style.display = "flex";
    }
};

export const hideChatLoading = () => {
    const overlay = getChatLoadingOverlay();
    if (overlay) {
        overlay.classList.remove("visible");
        overlay.style.display = "none";
    }
};
