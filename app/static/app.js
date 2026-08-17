document.addEventListener("DOMContentLoaded", () => {
    // Configure marked for chat-style breaks
    if (typeof marked !== 'undefined') {
        marked.use({ breaks: true });
    }

    const chatContainer = document.getElementById("chat-container");
    const chatForm = document.getElementById("chat-form");
    const messageInput = document.getElementById("message-input");
    const imageUpload = document.getElementById("image-upload");
    const cameraUpload = document.getElementById("camera-upload");
    const imagePreviewContainer = document.getElementById("image-preview-container");
    const removeImageBtn = document.getElementById("remove-image-btn");
    const contextWarning = document.getElementById("context-warning");

    // Sidebar elements
    const sidebar = document.getElementById("sidebar");
    const menuBtn = document.getElementById("menu-btn");
    const closeSidebarBtn = document.getElementById("close-sidebar-btn");
    const sessionList = document.getElementById("session-list");
    const newChatBtn = document.getElementById("new-chat-btn");

    // Auth Modal elements
    const authModal = document.getElementById("auth-modal");
    const authForm = document.getElementById("auth-form");
    const loginUsernameInput = document.getElementById("login-username");
    const loginPasswordInput = document.getElementById("login-password");
    const verifyBtn = document.getElementById("verify-btn");
    const logoutBtn = document.getElementById("logout-btn");
    const userBadge = document.getElementById("user-badge");

    // System Prompt elements
    const systemPromptBtn = document.getElementById("system-prompt-btn");
    const systemPromptModal = document.getElementById("system-prompt-modal");
    const systemPromptForm = document.getElementById("system-prompt-form");
    const systemPromptInput = document.getElementById("system-prompt-input");
    const gpsSettingInput = document.getElementById("gps-setting-input");
    const closePromptBtn = document.getElementById("close-prompt-btn");
    const savePromptBtn = document.getElementById("save-prompt-btn");

    let selectedImageFiles = [];
    let currentSessionId = localStorage.getItem("currentSessionId");
    let currentSessionGpsEnabled = false;
    let activeSubmittingSessionId = null;

    const scrollToBottomBtn = document.getElementById("scroll-to-bottom-btn");

    // Toggle Sidebar Mobile
    const toggleSidebar = () => {
        sidebar.classList.toggle("open");
    };
    menuBtn.addEventListener("click", toggleSidebar);
    closeSidebarBtn.addEventListener("click", toggleSidebar);

    // Check scroll position to toggle scroll-to-bottom button
    const checkScrollPosition = () => {
        if (!scrollToBottomBtn) return;
        const threshold = 50;
        const isAtBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight <= threshold;
        if (isAtBottom) {
            scrollToBottomBtn.classList.remove("visible");
        } else {
            scrollToBottomBtn.classList.add("visible");
        }
    };

    chatContainer.addEventListener("scroll", checkScrollPosition);

    // Scroll to bottom
    const scrollToBottom = (smooth = false) => {
        chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: smooth ? 'smooth' : 'auto'
        });
        if (scrollToBottomBtn) {
            scrollToBottomBtn.classList.remove("visible");
        }
    };

    if (scrollToBottomBtn) {
        scrollToBottomBtn.addEventListener("click", () => {
            scrollToBottom(true);
        });
    }


    // Helper to format streaming / regular text with thought tags
    const formatThoughtBlocks = (rawText, isStreaming = false) => {
        let formatted = rawText;
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

    const attachDownloadButtons = (bubble, text) => {
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
                btn.innerHTML = `<i class="ph-bold ph-download-simple"></i> ${fileName}`;
                downloadContainer.appendChild(btn);
            });
        }
    };

    // Append a message to the chat
    const appendMessage = (text, isUser, imagesData = [], timestampStr = null, skipScroll = false, smoothScroll = false, isHistory = false) => {
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
                const img = document.createElement("img");
                let hasDimensions = false;
                
                if (typeof imgData === 'string') {
                    img.src = imgData;
                } else if (imgData && imgData.url) {
                    img.src = imgData.url;
                    if (imgData.width && imgData.height) {
                        img.width = imgData.width;
                        img.height = imgData.height;
                        hasDimensions = true;
                    }
                } else {
                    return;
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
                        // Keep pinned to bottom if user is reading at the bottom
                        scrollToBottom(skipScroll ? false : smoothScroll);
                    } else if (img.offsetTop < chatContainer.scrollTop && deltaHeight > 0) {
                        // Image loaded above current viewport: adjust scrollTop by height gain to preserve view position
                        chatContainer.scrollTop += deltaHeight;
                    }
                };
                gridDiv.appendChild(img);
            });
            bubble.appendChild(gridDiv);
        }

        if (!isUser && text) {
            attachDownloadButtons(bubble, text);
        }

        msgDiv.appendChild(bubble);
        chatContainer.appendChild(msgDiv);
        
        if (!skipScroll) {
            scrollToBottom(smoothScroll);
        }
    };

    // Append error message to the chat
    const appendErrorMessage = (errorText) => {
        const msgDiv = document.createElement("div");
        msgDiv.className = "message ai-message error-message new-message";
        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.textContent = errorText;
        msgDiv.appendChild(bubble);
        chatContainer.appendChild(msgDiv);
        scrollToBottom(true);
    };

    // Show initial greeting
    const showInitialGreeting = () => {
        chatContainer.innerHTML = '';
        const msgDiv = document.createElement("div");
        msgDiv.id = "initial-greeting";
        msgDiv.className = "message ai-message history-message";
        msgDiv.innerHTML = `<div class="message-bubble">Hallo, wie geht es dir heute?</div>`;
        chatContainer.appendChild(msgDiv);
    };

    // Show typing indicator
    const showTypingIndicator = () => {
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

    // Remove typing indicator
    const removeTypingIndicator = () => {
        const indicator = document.getElementById("typing-indicator");
        if (indicator) {
            indicator.remove();
        }
    };

    // Client-side image compression & optimization to prevent mobile OOM
    const compressImage = async (file, maxDimension = 1920, quality = 0.85) => {
        const isImage = (file.type && file.type.startsWith("image/")) ||
                        (file.name && /\.(jpe?g|png|webp|gif|bmp|heic|heif)$/i.test(file.name)) ||
                        file.name === "blob" ||
                        !file.type;
        if (!isImage) return file;

        return new Promise((resolve) => {
            let settled = false;
            const timeoutId = setTimeout(() => {
                if (!settled) {
                    settled = true;
                    try { URL.revokeObjectURL(url); } catch (_) {}
                    resolve(file);
                }
            }, 3000);

            const img = new Image();
            let url = "";
            try {
                url = URL.createObjectURL(file);
            } catch (_) {
                clearTimeout(timeoutId);
                resolve(file);
                return;
            }

            img.onload = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timeoutId);
                try { URL.revokeObjectURL(url); } catch (_) {}
                
                try {
                    let { width, height } = img;
                    if (width <= maxDimension && height <= maxDimension && file.size < 1024 * 1024) {
                        resolve(file);
                        return;
                    }

                    if (width > maxDimension || height > maxDimension) {
                        if (width > height) {
                            height = Math.round((height * maxDimension) / width);
                            width = maxDimension;
                        } else {
                            width = Math.round((width * maxDimension) / height);
                            height = maxDimension;
                        }
                    }

                    const canvas = document.createElement("canvas");
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext("2d");
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob(
                        (blob) => {
                            if (blob) {
                                const originalName = file.name || "photo.jpg";
                                const newFileName = originalName.replace(/\.[^/.]+$/, "") + ".jpg";
                                const compressedFile = new File([blob], newFileName, {
                                    type: "image/jpeg",
                                    lastModified: Date.now()
                                });
                                resolve(compressedFile);
                            } else {
                                resolve(file);
                            }
                        },
                        "image/jpeg",
                        quality
                    );
                } catch (e) {
                    resolve(file);
                }
            };

            img.onerror = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timeoutId);
                try { URL.revokeObjectURL(url); } catch (_) {}
                resolve(file);
            };

            img.src = url;
        });
    };

    // Update preview UI using memory-efficient Object URLs
    const updatePreviewUI = () => {
        imagePreviewContainer.innerHTML = '';
        if (selectedImageFiles.length > 0) {
            imagePreviewContainer.style.display = "flex";
            selectedImageFiles.forEach((file, index) => {
                const itemDiv = document.createElement("div");
                itemDiv.className = "preview-item";

                const img = document.createElement("img");
                const blobUrl = URL.createObjectURL(file);
                img.src = blobUrl;
                img.alt = "Vorschau";

                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "remove-image-btn";
                btn.innerHTML = '<i class="ph-bold ph-x"></i>';
                btn.title = "Bild entfernen";
                btn.onclick = () => {
                    URL.revokeObjectURL(blobUrl);
                    selectedImageFiles.splice(index, 1);
                    updatePreviewUI();
                };

                itemDiv.appendChild(img);
                itemDiv.appendChild(btn);
                imagePreviewContainer.appendChild(itemDiv);
            });
        } else {
            imagePreviewContainer.style.display = "none";
        }
    };

    // Handle Image Selection with instant preview and async background compression
    const handleImageSelection = async (e, otherInputToClear) => {
        if (e.target.files && e.target.files.length > 0) {
            const rawFiles = Array.from(e.target.files);

            if (selectedImageFiles.length + rawFiles.length > 5) {
                alert("Du kannst maximal 5 Bilder auf einmal senden.");
                otherInputToClear.value = "";
                e.target.value = "";
                return;
            }

            const startIndex = selectedImageFiles.length;
            selectedImageFiles = [...selectedImageFiles, ...rawFiles];
            otherInputToClear.value = "";
            e.target.value = "";
            updatePreviewUI();
            messageInput.focus();

            try {
                const compressedFiles = await Promise.all(rawFiles.map(f => compressImage(f)));
                for (let i = 0; i < compressedFiles.length; i++) {
                    if (selectedImageFiles[startIndex + i] === rawFiles[i]) {
                        selectedImageFiles[startIndex + i] = compressedFiles[i];
                    }
                }
            } catch (err) {
                console.warn("Async compression error, keeping raw files", err);
            }
        }
    };

    imageUpload.addEventListener("change", (e) => handleImageSelection(e, cameraUpload));
    cameraUpload.addEventListener("change", (e) => handleImageSelection(e, imageUpload));

    // --- Polling for Active Background Processing ---
    const activePollTimers = new Map();

    const stopPollingSession = (sessionId) => {
        if (activePollTimers.has(sessionId)) {
            clearInterval(activePollTimers.get(sessionId));
            activePollTimers.delete(sessionId);
        }
    };

    const startPollingSession = (sessionId) => {
        if (activePollTimers.has(sessionId)) return;

        const timerId = setInterval(async () => {
            try {
                const res = await fetch(`/api/sessions/${sessionId}/status`);
                if (!res.ok) {
                    stopPollingSession(sessionId);
                    return;
                }
                const data = await res.json();
                if (!data.is_processing) {
                    stopPollingSession(sessionId);
                    if (currentSessionId === sessionId && activeSubmittingSessionId !== sessionId) {
                        await selectSession(sessionId);
                    }
                    const sessionsRes = await fetch("/api/sessions");
                    if (sessionsRes.ok) {
                        const sessionsData = await sessionsRes.json();
                        renderSessionList(sessionsData);
                    }
                }
            } catch (err) {
                console.error("Polling error for session", sessionId, err);
            }
        }, 1000);

        activePollTimers.set(sessionId, timerId);
    };

    // --- Session Management ---

    const updateActiveSessionHighlight = (activeId) => {
        document.querySelectorAll('.session-item').forEach(el => {
            el.classList.toggle('active', el.dataset.sessionId === activeId);
        });
    };

    let selectSessionCounter = 0;

    const selectSession = async (sessionId, forceReload = false) => {
        const isSwitchingSession = (currentSessionId !== sessionId);
        if (!forceReload && !isSwitchingSession && activeSubmittingSessionId === sessionId) {
            return;
        }
        const requestId = ++selectSessionCounter;
        currentSessionId = sessionId;
        localStorage.setItem("currentSessionId", sessionId);
        contextWarning.style.display = "none";
        updateActiveSessionHighlight(sessionId);

        // Hide sidebar on mobile after selection
        if (window.innerWidth <= 768) {
            sidebar.classList.remove("open");
        }

        // Enable system prompt button
        systemPromptBtn.disabled = false;

        const session = window.lastSessions?.find(s => s.id === sessionId);
        if (session) {
            document.getElementById('header-chat-title').textContent = session.title;
            const iconImg = document.getElementById('header-chat-icon');
            const defaultIcon = document.getElementById('header-default-icon');
            
            if (session.has_icon) {
                iconImg.src = `/api/sessions/${session.id}/icon?t=${Date.now()}`;
                iconImg.style.display = 'block';
                defaultIcon.style.display = 'none';
            } else {
                iconImg.style.display = 'none';
                defaultIcon.style.display = 'block';
            }
        }

        try {
            const [promptRes, response] = await Promise.all([
                fetch(`/api/sessions/${sessionId}/settings`),
                fetch(`/api/sessions/${sessionId}/history`)
            ]);

            if (requestId !== selectSessionCounter) return;
            if (currentSessionId !== sessionId) return;

            if (promptRes.ok) {
                const promptData = await promptRes.json();
                if (currentSessionId === sessionId) {
                    systemPromptInput.value = promptData.prompt || "";
                    currentSessionGpsEnabled = promptData.include_gps || false;
                    if (gpsSettingInput) {
                        gpsSettingInput.checked = currentSessionGpsEnabled;
                    }
                }
            }

            const isProcessing = response.headers.get("X-Is-Processing") === "true";
            const history = await response.json();

            if (requestId !== selectSessionCounter) return;
            if (currentSessionId !== sessionId) return;

            chatContainer.innerHTML = '';
            if (history && history.length > 0) {
                history.forEach(msg => {
                    appendMessage(msg.text, msg.is_user, msg.images || msg.image_urls || [], msg.timestamp, true, false, true);
                });
                scrollToBottom(false);
            } else if (!isProcessing && activeSubmittingSessionId !== sessionId) {
                showInitialGreeting();
            }

            if (isProcessing || activeSubmittingSessionId === sessionId) {
                showTypingIndicator();
                startPollingSession(sessionId);
            } else {
                removeTypingIndicator();
                stopPollingSession(sessionId);
            }
        } catch (error) {
            console.error("Failed to load history", error);
        }
    };

    const createNewSession = async () => {
        try {
            const res = await fetch("/api/sessions", { method: "POST" });
            const data = await res.json();

            currentSessionId = data.id;
            localStorage.setItem("currentSessionId", data.id);

            await loadSessions();
        } catch (err) {
            console.error("Error creating session", err);
        }
    };

    newChatBtn.addEventListener("click", createNewSession);

    const renderSessionList = (sessions) => {
        window.lastSessions = sessions;
        sessionList.innerHTML = '';
        sessions.forEach(session => {
            const div = document.createElement("div");
            div.className = `session-item ${session.id === currentSessionId ? "active" : ""}`;
            div.dataset.sessionId = session.id;

            // Format date slightly
            let dateStr = session.created_at;
            if (dateStr) {
                const d = new Date(dateStr);
                dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            }

            const iconHtml = session.has_icon 
                ? `<img class="session-list-icon" src="/api/sessions/${session.id}/icon?t=${new Date(session.created_at || Date.now()).getTime()}">`
                : `<i class="ph-fill ph-robot session-list-icon"></i>`;

            div.innerHTML = `
                ${iconHtml}
                <div class="session-info">
                    <div class="session-date">${dateStr || "Neu"}</div>
                    <div class="session-title">${session.title}</div>
                </div>
                <button class="icon-button danger delete-btn" title="Chat löschen">
                    <i class="ph-bold ph-trash"></i>
                </button>
            `;

            // Handle session selection
            div.addEventListener("click", () => selectSession(session.id));

            // Handle deletion
            const deleteBtn = div.querySelector('.delete-btn');
            deleteBtn.addEventListener('click', async (e) => {
                e.stopPropagation(); // prevent selecting the session
                if (confirm('Möchtest du diesen Chat wirklich löschen?')) {
                    try {
                        const res = await fetch(`/api/sessions/${session.id}`, { method: 'DELETE' });
                        if (res.ok) {
                            if (currentSessionId === session.id) {
                                currentSessionId = null;
                                localStorage.removeItem("currentSessionId");
                                chatContainer.innerHTML = '';
                            }
                            await loadSessions();
                        } else {
                            alert("Fehler beim Löschen des Chats.");
                        }
                    } catch (err) {
                        console.error("Error deleting session", err);
                    }
                }
            });

            sessionList.appendChild(div);
        });
    };

    const loadSessions = async () => {
        try {
            const res = await fetch("/api/sessions");
            const sessions = await res.json();

            if (!sessions || sessions.length === 0) {
                await createNewSession();
                return;
            }

            renderSessionList(sessions);

            // If currentSessionId not in list or not set, select the first one
            if (!currentSessionId || !sessions.find(s => s.id === currentSessionId)) {
                selectSession(sessions[0].id);
            } else {
                selectSession(currentSessionId);
            }
        } catch (err) {
            console.error("Failed to load sessions", err);
        }
    };

    // Textarea auto-resize and keyboard logic
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.scrollHeight > 150) {
            this.style.overflowY = 'auto';
        } else {
            this.style.overflowY = 'hidden';
        }
    });

    messageInput.addEventListener('keydown', function(e) {
        const isMobile = window.innerWidth <= 768 || /Mobi|Android/i.test(navigator.userAgent);
        
        if (e.key === 'Enter') {
            if (!isMobile) {
                if (!e.shiftKey) {
                    e.preventDefault();
                    document.getElementById('send-btn').click();
                }
            }
        }
    });

    // Handle form submission
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        if (!currentSessionId) {
            alert("Fehler: Keine aktive Sitzung.");
            return;
        }

        const text = messageInput.value.trim();
        if (!text && selectedImageFiles.length === 0) return;

        const submittedSessionId = currentSessionId;
        activeSubmittingSessionId = submittedSessionId; // Lock immediately to protect DOM
        ++selectSessionCounter; // Invalidate any in-flight selectSession history fetches that started before submit

        // Hide warning and show UI feedback immediately
        contextWarning.style.display = "none";
        
        // Grab local urls before we clear selectedImageFiles
        let localImageUrls = [];
        if (selectedImageFiles.length > 0) {
            localImageUrls = selectedImageFiles.map(f => URL.createObjectURL(f));
        }

        const filesToUpload = [...selectedImageFiles];

        // Reset input immediately for responsiveness
        messageInput.value = "";
        messageInput.style.height = "auto";
        messageInput.style.overflowY = "hidden";
        selectedImageFiles = [];
        updatePreviewUI();

        // Show typing indicator while we possibly fetch GPS
        showTypingIndicator();
        
        let locationStr = "";
        if (currentSessionGpsEnabled) {
            try {
                const position = await new Promise((resolve, reject) => {
                    navigator.geolocation.getCurrentPosition(resolve, reject, {
                        enableHighAccuracy: false, // Better compatibility on Android if true isn't strictly needed
                        timeout: 10000, // 10s max wait time
                        maximumAge: 60000 // allow up to 1-minute old cached location
                    });
                });
                locationStr = `Lat: ${position.coords.latitude}, Lon: ${position.coords.longitude}`;
            } catch (err) {
                console.warn("GPS failed", err);
                locationStr = "Standort konnte nicht ermittelt werden.";
            }
        }

        // Build display message
        let displayMsg = text;
        if (filesToUpload.length > 0) {
            displayMsg += displayMsg ? ` [${filesToUpload.length} Bild(er) angehängt]` : `[${filesToUpload.length} Bild(er) gesendet]`;
        }

        // Remove the early typing indicator so we can append the user message
        removeTypingIndicator();

        // Remove initial greeting if it exists
        const greetingEl = document.getElementById("initial-greeting");
        if (greetingEl) {
            greetingEl.remove();
        }

        const now = new Date().toISOString();
        appendMessage(displayMsg, true, localImageUrls, now, false, true, false);

        // Prepare form data
        const formData = new FormData();
        formData.append("message", text);
        formData.append("stream", "true");
        filesToUpload.forEach(file => {
            formData.append("images", file);
        });
        if (locationStr) {
            formData.append("location", locationStr);
        }

        // Show typing indicator again for the actual API request
        showTypingIndicator();

        try {
            const response = await fetch(`/api/sessions/${submittedSessionId}/chat`, {
                method: "POST",
                headers: {
                    "Accept": "text/event-stream, application/json"
                },
                body: formData
            });

            if (!response.ok) {
                removeTypingIndicator();
                let errorMsg = "Fehler beim Senden der Nachricht.";
                try {
                    const errData = await response.json();
                    if (errData.error || errData.detail) {
                        errorMsg = errData.error || errData.detail;
                    }
                } catch (_) {}
                if (currentSessionId === submittedSessionId) {
                    appendErrorMessage(errorMsg);
                }
                return;
            }

            const contentType = response.headers.get("content-type") || "";

            if (contentType.includes("text/event-stream")) {
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let accumulatedText = "";
                let sseBuffer = "";
                let aiMsgDiv = null;
                let textDiv = null;
                let bubbleDiv = null;

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    sseBuffer += decoder.decode(value, { stream: true });
                    const lines = sseBuffer.split("\n");
                    sseBuffer = lines.pop(); // keep partial line remainder

                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (trimmed.startsWith("data: ")) {
                            try {
                                const event = JSON.parse(trimmed.slice(6));
                                if (event.type === "delta") {
                                    if (currentSessionId === submittedSessionId) {
                                        removeTypingIndicator();
                                        if (!aiMsgDiv) {
                                            aiMsgDiv = document.createElement("div");
                                            aiMsgDiv.className = "message ai-message streaming new-message";
                                            bubbleDiv = document.createElement("div");
                                            bubbleDiv.className = "message-bubble";
                                            textDiv = document.createElement("div");
                                            textDiv.className = "markdown-body";
                                            bubbleDiv.appendChild(textDiv);
                                            aiMsgDiv.appendChild(bubbleDiv);
                                            chatContainer.appendChild(aiMsgDiv);
                                        }

                                        accumulatedText += event.text;
                                        const formatted = formatThoughtBlocks(accumulatedText, true);

                                        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                                            const parsedHTML = marked.parse(formatted);
                                            textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, { ADD_TAGS: ['details', 'summary'], ADD_ATTR: ['class', 'open'] });
                                            textDiv.querySelectorAll("img").forEach(img => {
                                                img.loading = "lazy";
                                                img.decoding = "async";
                                            });
                                        } else {
                                            textDiv.textContent = formatted;
                                        }

                                        scrollToBottom(false);
                                    } else {
                                        accumulatedText += event.text;
                                    }
                                } else if (event.type === "done") {
                                    removeTypingIndicator();
                                    if (aiMsgDiv) {
                                        aiMsgDiv.classList.remove("streaming");
                                    }
                                    if (currentSessionId === submittedSessionId) {
                                        if (!aiMsgDiv) {
                                            appendMessage(event.reply || accumulatedText, false, [], event.timestamp, false, true, false);
                                        } else {
                                            const finalFormatted = formatThoughtBlocks(event.reply || accumulatedText, false);
                                            if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                                                const parsedHTML = marked.parse(finalFormatted);
                                                textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, { ADD_TAGS: ['details', 'summary'], ADD_ATTR: ['class', 'open'] });
                                                textDiv.querySelectorAll("img").forEach(img => {
                                                    img.loading = "lazy";
                                                    img.decoding = "async";
                                                });
                                            } else {
                                                textDiv.textContent = finalFormatted;
                                            }
                                            attachDownloadButtons(bubbleDiv, event.reply || accumulatedText);
                                        }
                                        if (event.context_truncated) {
                                            contextWarning.style.display = "flex";
                                        }
                                    }
                                } else if (event.type === "error") {
                                    removeTypingIndicator();
                                    if (aiMsgDiv) {
                                        aiMsgDiv.remove();
                                    }
                                    if (currentSessionId === submittedSessionId) {
                                        appendErrorMessage(event.error || "Fehler bei der Antwortgenerierung.");
                                    }
                                }
                            } catch (e) {
                                console.warn("Error parsing SSE event:", e, trimmed);
                            }
                        }
                    }
                }

                removeTypingIndicator();
                if (aiMsgDiv) {
                    aiMsgDiv.classList.remove("streaming");
                }

                // Reload sessions in case the title changed
                const sessionsRes = await fetch("/api/sessions");
                if (sessionsRes.ok) {
                    const sessionsData = await sessionsRes.json();
                    renderSessionList(sessionsData);
                }

            } else {
                const data = await response.json();
                removeTypingIndicator();

                if (currentSessionId !== submittedSessionId) return;

                appendMessage(data.reply, false, [], data.timestamp, false, true, false);

                if (data.context_truncated) {
                    contextWarning.style.display = "flex";
                }

                // Reload sessions in case the title changed
                const sessionsRes = await fetch("/api/sessions");
                if (sessionsRes.ok) {
                    const sessionsData = await sessionsRes.json();
                    renderSessionList(sessionsData);
                }
            }

        } catch (error) {
            removeTypingIndicator();
            if (currentSessionId === submittedSessionId) {
                appendErrorMessage("Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.");
            }
            console.error("Error calling chat API", error);
        } finally {
            if (activeSubmittingSessionId === submittedSessionId) {
                activeSubmittingSessionId = null;
            }
        }
    });

    // --- System Prompt Flow ---
    systemPromptBtn.addEventListener("click", () => {
        if (!currentSessionId) return;
        
        const session = window.lastSessions?.find(s => s.id === currentSessionId);
        if (session) {
            document.getElementById("chat-title-input").value = session.title || "";
        }
        
        systemPromptModal.style.display = "flex";
    });

    closePromptBtn.addEventListener("click", () => {
        systemPromptModal.style.display = "none";
    });

    systemPromptForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!currentSessionId) return;

        const promptText = systemPromptInput.value.trim();
        const includeGps = gpsSettingInput ? gpsSettingInput.checked : false;
        const titleText = document.getElementById("chat-title-input").value.trim();
        savePromptBtn.disabled = true;
        savePromptBtn.textContent = "Wird gespeichert...";

        try {
            const promptRes = fetch(`/api/sessions/${currentSessionId}/settings`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: promptText, include_gps: includeGps })
            });

            const session = window.lastSessions?.find(s => s.id === currentSessionId);
            let titleRes = null;
            if (titleText && session && session.title !== titleText) {
                titleRes = fetch(`/api/sessions/${currentSessionId}/title`, {
                     method: "PUT",
                     headers: { "Content-Type": "application/json" },
                     body: JSON.stringify({ title: titleText })
                });
            }

            const responses = await Promise.all([promptRes, ...(titleRes ? [titleRes] : [])]);
            const allOk = responses.every(res => res.ok);

            if (allOk) {
                currentSessionGpsEnabled = includeGps;
                systemPromptModal.style.display = "none";
                if (titleRes) {
                    await loadSessions();
                }
            } else {
                alert("Fehler beim Speichern der Einstellungen.");
            }
        } catch (err) {
            console.error("Error saving settings", err);
            alert("Verbindungsfehler beim Speichern.");
        } finally {
            savePromptBtn.disabled = false;
            savePromptBtn.textContent = "Speichern";
        }
    });

    // --- Global 401 Handler ---
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
        const response = await originalFetch.apply(this, args);
        if (response.status === 401 && !args[0].includes('/api/auth/status') && !args[0].includes('/api/auth/login')) {
            handleAuthError();
        }
        return response;
    };

    const handleAuthError = () => {
        currentSessionId = null;
        localStorage.removeItem("currentSessionId");
        chatContainer.innerHTML = '';
        sessionList.innerHTML = '';
        authModal.style.display = "flex";
        updateUserBadge(null);
    };

    // --- Auth Flow ---
    const updateUserBadge = (username) => {
        if (userBadge && username) {
            userBadge.style.display = "flex";
            userBadge.textContent = username.charAt(0);
            userBadge.title = `Angemeldet als: ${username}`;
        } else if (userBadge) {
            userBadge.style.display = "none";
        }
    };

    const checkAuthStatus = async () => {
        try {
            const res = await originalFetch("/api/auth/status");
            const data = await res.json();
            if (!data.authenticated) {
                authModal.style.display = "flex";
                updateUserBadge(null);
            } else {
                authModal.style.display = "none";
                updateUserBadge(data.username);
                loadSessions();
            }
        } catch (err) {
            console.error("Error checking auth status", err);
        }
    };

    authForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = loginUsernameInput.value.trim();
        const password = loginPasswordInput.value;
        if (!username || !password) return;

        verifyBtn.disabled = true;
        verifyBtn.textContent = "Wird verifiziert...";

        try {
            const formData = new URLSearchParams();
            formData.append("username", username);
            formData.append("password", password);

            const res = await originalFetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: formData.toString()
            });

            if (res.ok) {
                const data = await res.json();
                if (data.success) {
                    authModal.style.display = "none";
                    loginPasswordInput.value = ""; // clear password
                    updateUserBadge(username);
                    loadSessions();
                } else {
                    alert("Login fehlgeschlagen. Bitte überprüfe deine Daten.");
                }
            } else {
                alert("Login fehlgeschlagen. Bitte überprüfe deine Daten.");
            }
        } catch (err) {
            console.error("Error logging in", err);
            alert("Ein Fehler ist aufgetreten.");
        } finally {
            verifyBtn.disabled = false;
            verifyBtn.textContent = "Anmelden";
        }
    });

    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            if (confirm("Möchtest du dich wirklich abmelden?")) {
                try {
                    await originalFetch("/api/auth/logout", { method: "POST" });
                    handleAuthError();
                } catch (err) {
                    console.error("Error logging out", err);
                }
            }
        });
    }

    // Reload session on visibility change to recover from suspended state disconnects
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible" && currentSessionId && activeSubmittingSessionId !== currentSessionId) {
            selectSession(currentSessionId);
        }
    });

    // Init
    checkAuthStatus();
});
