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
    const closePromptBtn = document.getElementById("close-prompt-btn");
    const savePromptBtn = document.getElementById("save-prompt-btn");

    let selectedImageFiles = [];
    let currentSessionId = localStorage.getItem("currentSessionId");

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


    // Append a message to the chat
    const appendMessage = (text, isUser, imagesData = [], timestampStr = null, skipScroll = false, smoothScroll = false) => {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${isUser ? "user-message" : "ai-message"}`;

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

            if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                const parsedHTML = marked.parse(text);
                textDiv.innerHTML = DOMPurify.sanitize(parsedHTML, { ADD_TAGS: ['details', 'summary'], ADD_ATTR: ['class'] });
                textDiv.className = "markdown-body";
                textDiv.querySelectorAll("img").forEach(img => {
                    img.loading = "lazy";
                    img.decoding = "async";
                });
            } else {
                textDiv.textContent = text;
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
                const downloadContainer = document.createElement("div");
                downloadContainer.className = "download-links-container";

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

                bubble.appendChild(downloadContainer);
            }
        }

        msgDiv.appendChild(bubble);
        chatContainer.appendChild(msgDiv);
        
        if (!skipScroll) {
            scrollToBottom(smoothScroll);
        }
    };

    // Show initial greeting
    const showInitialGreeting = () => {
        chatContainer.innerHTML = '';
        const msgDiv = document.createElement("div");
        msgDiv.className = "message ai-message";
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

    // Update preview UI
    const updatePreviewUI = () => {
        imagePreviewContainer.innerHTML = '';
        if (selectedImageFiles.length > 0) {
            imagePreviewContainer.style.display = "flex";
            selectedImageFiles.forEach((file, index) => {
                const reader = new FileReader();
                reader.onload = (event) => {
                    const itemDiv = document.createElement("div");
                    itemDiv.className = "preview-item";

                    const img = document.createElement("img");
                    img.src = event.target.result;

                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "remove-image-btn";
                    btn.innerHTML = '<i class="ph-bold ph-x"></i>';
                    btn.title = "Bild entfernen";
                    btn.onclick = () => {
                        selectedImageFiles.splice(index, 1);
                        updatePreviewUI();
                    };

                    itemDiv.appendChild(img);
                    itemDiv.appendChild(btn);
                    imagePreviewContainer.appendChild(itemDiv);
                };
                reader.readAsDataURL(file);
            });
        } else {
            imagePreviewContainer.style.display = "none";
        }
    };

    // Handle Image Selection
    const handleImageSelection = (e, otherInputToClear) => {
        if (e.target.files && e.target.files.length > 0) {
            const newFiles = Array.from(e.target.files);

            if (selectedImageFiles.length + newFiles.length > 5) {
                alert("Du kannst maximal 5 Bilder auf einmal senden.");
            } else {
                selectedImageFiles = [...selectedImageFiles, ...newFiles];
            }

            otherInputToClear.value = "";
            e.target.value = "";
            updatePreviewUI();
            messageInput.focus();
        }
    };

    imageUpload.addEventListener("change", (e) => handleImageSelection(e, cameraUpload));
    cameraUpload.addEventListener("change", (e) => handleImageSelection(e, imageUpload));

    // --- Session Management ---

    const selectSession = async (sessionId) => {
        currentSessionId = sessionId;
        localStorage.setItem("currentSessionId", sessionId);
        contextWarning.style.display = "none";
        renderSessionList(window.lastSessions || []);

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
            // Fetch system prompt
            const promptRes = await fetch(`/api/sessions/${sessionId}/prompt`);
            if (promptRes.ok) {
                const promptData = await promptRes.json();
                if (currentSessionId === sessionId) {
                    systemPromptInput.value = promptData.prompt || "";
                }
            }

            const response = await fetch(`/api/sessions/${sessionId}/history`);
            const history = await response.json();

            if (currentSessionId !== sessionId) return;

            chatContainer.innerHTML = '';
            if (history && history.length > 0) {
                history.forEach(msg => {
                    appendMessage(msg.text, msg.is_user, msg.images || msg.image_urls || [], msg.timestamp, true, false);
                });
                scrollToBottom(false);
            } else {
                showInitialGreeting();
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

        // Display user message
        let displayMsg = text;
        let localImageUrls = [];
        if (selectedImageFiles.length > 0) {
            displayMsg += displayMsg ? ` [${selectedImageFiles.length} Bild(er) angehängt]` : `[${selectedImageFiles.length} Bild(er) gesendet]`;
            localImageUrls = selectedImageFiles.map(f => URL.createObjectURL(f));
        }

        // Remove initial greeting if it's the first message
        if (chatContainer.children.length === 1 && chatContainer.firstElementChild.innerText.includes("Hallo! Was hast du heute gegessen")) {
            chatContainer.innerHTML = '';
        }

        const now = new Date().toISOString();
        appendMessage(displayMsg, true, localImageUrls, now, false, true);

        // Prepare form data
        const formData = new FormData();
        formData.append("message", text);
        selectedImageFiles.forEach(file => {
            formData.append("images", file);
        });

        // Reset input
        messageInput.value = "";
        messageInput.style.height = "auto";
        messageInput.style.overflowY = "hidden";
        selectedImageFiles = [];
        updatePreviewUI();

        showTypingIndicator();
        contextWarning.style.display = "none";

        const submittedSessionId = currentSessionId;

        try {
            const response = await fetch(`/api/sessions/${submittedSessionId}/chat`, {
                method: "POST",
                body: formData
            });
            const data = await response.json();

            removeTypingIndicator();

            if (currentSessionId !== submittedSessionId) return;

            appendMessage(data.reply, false, [], data.timestamp, false, true);

            if (data.context_truncated) {
                contextWarning.style.display = "flex";
            }

            // Reload sessions in case the title changed
            const sessionsRes = await fetch("/api/sessions");
            const sessionsData = await sessionsRes.json();
            renderSessionList(sessionsData);

        } catch (error) {
            removeTypingIndicator();
            appendMessage("Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.", false);
            console.error("Error calling chat API", error);
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
        const titleText = document.getElementById("chat-title-input").value.trim();
        savePromptBtn.disabled = true;
        savePromptBtn.textContent = "Wird gespeichert...";

        try {
            const promptRes = fetch(`/api/sessions/${currentSessionId}/prompt`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: promptText })
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

    // Init
    checkAuthStatus();
});
