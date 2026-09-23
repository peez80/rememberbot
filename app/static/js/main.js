/**
 * Main application orchestrator for RememberBot.
 */

import { state, setCurrentSessionId } from './state.js';
import { isImageFile } from './utils/dom.js';
import { formatThoughtBlocks, attachDownloadButtons } from './utils/formatters.js';
import * as api from './api/client.js';
import { readSSEStream } from './api/sse.js';
import * as sidebarView from './components/sidebar_view.js';
import * as chatView from './components/chat_view.js';
import * as inputBar from './components/input_bar.js';
import * as modals from './components/modals.js';

document.addEventListener("DOMContentLoaded", () => {
    // Configure marked for chat-style breaks
    if (typeof marked !== 'undefined') {
        marked.use({ breaks: true });
    }

    const chatContainer = chatView.getChatContainer();
    const chatForm = document.getElementById("chat-form");
    const messageInput = inputBar.getMessageInput();
    const fileUpload = document.getElementById("file-upload");
    const imageUpload = document.getElementById("image-upload");
    const cameraUpload = document.getElementById("camera-upload");
    const contextWarning = document.getElementById("context-warning");

    const sidebar = document.getElementById("sidebar");
    const menuBtn = document.getElementById("menu-btn");
    const closeSidebarBtn = document.getElementById("close-sidebar-btn");
    const newChatBtn = document.getElementById("new-chat-btn");

    const authForm = document.getElementById("auth-form");
    const loginUsernameInput = document.getElementById("login-username");
    const loginPasswordInput = document.getElementById("login-password");
    const verifyBtn = document.getElementById("verify-btn");
    const logoutBtn = document.getElementById("logout-btn");

    const systemPromptBtn = document.getElementById("system-prompt-btn");
    const systemPromptForm = document.getElementById("system-prompt-form");
    const systemPromptInput = document.getElementById("system-prompt-input");
    const chatModelSelect = document.getElementById("chat-model-select");
    const chatThinkingEffortSelect = document.getElementById("chat-thinking-effort-select");
    const settingsErrorBanner = document.getElementById("settings-error-banner");
    const sessionModelIndicator = document.getElementById("session-model-indicator");
    const gpsSettingInput = document.getElementById("gps-setting-input");
    const closePromptBtn = document.getElementById("close-prompt-btn");
    const savePromptBtn = document.getElementById("save-prompt-btn");
    const exportSessionBtn = document.getElementById("export-session-btn");
    const importSessionBtn = document.getElementById("import-session-btn");
    const importSessionInput = document.getElementById("import-session-input");
    const importStatusText = document.getElementById("import-status-text");

    let modelCatalog = null;

    const ensureModelCatalogLoaded = async () => {
        if (modelCatalog) return;
        try {
            const catRes = await api.getModelsCatalog();
            if (catRes.ok) {
                const catData = await catRes.json();
                modelCatalog = catData.model_catalog;
                if (chatModelSelect && chatModelSelect.options.length <= 1) {
                    chatModelSelect.innerHTML = '<option value="">Standard (Host / Server-Default)</option>';
                    Object.entries(modelCatalog).forEach(([key, spec]) => {
                        if (key !== "default") {
                            const opt = document.createElement("option");
                            opt.value = key;
                            opt.textContent = spec.label || key;
                            chatModelSelect.appendChild(opt);
                        }
                    });
                }
            }
        } catch (e) {
            console.error("Failed to load model catalog", e);
        }
    };

    const updateEffortOptionsForModel = (selectedModel) => {
        if (!chatThinkingEffortSelect) return;
        const modelKey = selectedModel || "default";
        const spec = modelCatalog ? modelCatalog[modelKey] : null;
        const supportsThinking = spec ? (spec.supports_thinking !== false) : true;
        const allowed = spec ? (spec.allowed_efforts || []) : ["low", "high"];

        if (!supportsThinking) {
            chatThinkingEffortSelect.disabled = true;
            chatThinkingEffortSelect.value = "";
            Array.from(chatThinkingEffortSelect.options).forEach(opt => {
                opt.disabled = true;
            });
            return;
        }

        chatThinkingEffortSelect.disabled = false;
        Array.from(chatThinkingEffortSelect.options).forEach(opt => {
            const val = opt.value;
            if (!val) {
                opt.disabled = false;
                opt.text = "Standard / Automatisch";
            } else {
                const isAllowed = allowed.includes(val);
                opt.disabled = !isAllowed;
                if (!isAllowed) {
                    if (!opt.text.includes("(nicht unterstützt)")) {
                        opt.text = opt.text.replace(" (nicht verfügbar)", "").replace(" (nicht unterstützt)", "") + " (nicht unterstützt)";
                    }
                } else {
                    opt.text = opt.text.replace(" (nicht verfügbar)", "").replace(" (nicht unterstützt)", "");
                }
            }
        });

        const currentEffort = chatThinkingEffortSelect.value;
        if (currentEffort && !allowed.includes(currentEffort)) {
            chatThinkingEffortSelect.value = "";
        }
    };

    const updateHeaderModelIndicator = (model, effort) => {
        if (!sessionModelIndicator) return;
        if (!model && !effort) {
            sessionModelIndicator.style.display = "none";
            sessionModelIndicator.textContent = "";
            return;
        }

        const modelSpec = modelCatalog && model ? modelCatalog[model] : null;
        const modelLabel = modelSpec ? modelSpec.label : (model || "Standard");

        let effortLabel = "";
        if (effort === "low") effortLabel = " · Niedriges Thinking";
        else if (effort === "medium") effortLabel = " · Mittleres Thinking";
        else if (effort === "high") effortLabel = " · Hohes Thinking";

        sessionModelIndicator.textContent = `${modelLabel}${effortLabel}`;
        sessionModelIndicator.style.display = "block";
    };

    if (chatModelSelect) {
        chatModelSelect.addEventListener("change", () => {
            if (settingsErrorBanner) settingsErrorBanner.style.display = "none";
            updateEffortOptionsForModel(chatModelSelect.value);
        });
    }

    // 401 Handler
    const handleAuthError = () => {
        setCurrentSessionId(null);
        if (chatContainer) chatContainer.innerHTML = '';
        const sessionList = document.getElementById("session-list");
        if (sessionList) sessionList.innerHTML = '';
        modals.openAuthModal();
    };
    api.setAuthErrorHandler(handleAuthError);

    // Sidebar toggling
    if (menuBtn) menuBtn.addEventListener("click", sidebarView.toggleSidebar);
    if (closeSidebarBtn) closeSidebarBtn.addEventListener("click", sidebarView.toggleSidebar);

    // Chat scroll listener
    if (chatContainer) {
        chatContainer.addEventListener("scroll", chatView.handleChatScroll);
    }

    const scrollToBottomBtn = chatView.getScrollToBottomBtn();
    if (scrollToBottomBtn) {
        scrollToBottomBtn.addEventListener("click", () => {
            chatView.scrollToBottom(true);
        });
    }

    // Input handlers
    inputBar.setupInputAutoResize();
    if (fileUpload) fileUpload.addEventListener("change", (e) => inputBar.handleFileSelection(e, imageUpload, cameraUpload));
    if (imageUpload) imageUpload.addEventListener("change", (e) => inputBar.handleFileSelection(e, fileUpload, cameraUpload));
    if (cameraUpload) cameraUpload.addEventListener("change", (e) => inputBar.handleFileSelection(e, fileUpload, imageUpload));

    if (chatContainer && chatForm) {
        inputBar.setupDragAndDrop([chatContainer, chatForm]);
    }
    inputBar.setupPaste();

    // Background session polling
    const stopPollingSession = (sessionId) => {
        if (state.activePollTimers.has(sessionId)) {
            clearInterval(state.activePollTimers.get(sessionId));
            state.activePollTimers.delete(sessionId);
        }
    };

    const startPollingSession = (sessionId) => {
        if (state.activePollTimers.has(sessionId)) return;

        const timerId = setInterval(async () => {
            try {
                const res = await api.getSessionStatus(sessionId);
                if (!res.ok) {
                    stopPollingSession(sessionId);
                    return;
                }
                const data = await res.json();
                if (!data.is_processing) {
                    stopPollingSession(sessionId);
                    if (state.currentSessionId === sessionId && state.activeSubmittingSessionId !== sessionId) {
                        await selectSession(sessionId);
                    }
                    const sessions = await api.getSessions();
                    sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);
                }
            } catch (err) {
                console.error("Polling error for session", sessionId, err);
            }
        }, 1000);

        state.activePollTimers.set(sessionId, timerId);
    };

    // Select session
    const selectSession = async (sessionId, forceReload = false) => {
        const isSwitchingSession = (state.currentSessionId !== sessionId);
        if (!forceReload && !isSwitchingSession && state.activeSubmittingSessionId === sessionId) {
            return;
        }
        const requestId = ++state.selectSessionCounter;
        setCurrentSessionId(sessionId);
        if (contextWarning) contextWarning.style.display = "none";
        sidebarView.updateActiveSessionHighlight(sessionId);

        if (window.innerWidth <= 768 && sidebar) {
            sidebar.classList.remove("open");
        }

        if (systemPromptBtn) systemPromptBtn.disabled = false;

        const session = state.lastSessions?.find(s => s.id === sessionId);
        if (session) {
            const titleEl = document.getElementById('header-chat-title');
            if (titleEl) titleEl.textContent = session.title;
            const iconImg = document.getElementById('header-chat-icon');
            const defaultIcon = document.getElementById('header-default-icon');
            
            if (session.has_icon && iconImg && defaultIcon) {
                iconImg.src = `/api/sessions/${session.id}/icon?t=${Date.now()}`;
                iconImg.style.display = 'block';
                defaultIcon.style.display = 'none';
            } else if (iconImg && defaultIcon) {
                iconImg.style.display = 'none';
                defaultIcon.style.display = 'block';
            }
        }

        try {
            const [promptRes, response] = await Promise.all([
                api.getSessionSettings(sessionId),
                api.getSessionHistory(sessionId)
            ]);

            if (requestId !== state.selectSessionCounter) return;
            if (state.currentSessionId !== sessionId) return;

            if (promptRes.ok) {
                const promptData = await promptRes.json();
                if (state.currentSessionId === sessionId) {
                    if (systemPromptInput) systemPromptInput.value = promptData.prompt || "";
                    state.currentSessionGpsEnabled = promptData.include_gps || false;
                    if (gpsSettingInput) {
                        gpsSettingInput.checked = state.currentSessionGpsEnabled;
                    }
                    await ensureModelCatalogLoaded();
                    if (chatModelSelect) {
                        chatModelSelect.value = promptData.model || "";
                    }
                    if (chatThinkingEffortSelect) {
                        chatThinkingEffortSelect.value = promptData.thinking_effort || "";
                    }
                    updateEffortOptionsForModel(promptData.model);
                    updateHeaderModelIndicator(promptData.model, promptData.thinking_effort);
                }
            }

            const isProcessing = response.headers.get("X-Is-Processing") === "true";
            const history = await response.json();

            if (requestId !== state.selectSessionCounter) return;
            if (state.currentSessionId !== sessionId) return;

            if (chatContainer) chatContainer.innerHTML = '';
            state.currentSessionHistory = history || [];
            if (state.currentSessionHistory.length > 0) {
                state.currentRenderStartIndex = Math.max(0, state.currentSessionHistory.length - state.MESSAGE_BATCH_SIZE);
                const initialBatch = state.currentSessionHistory.slice(state.currentRenderStartIndex);
                initialBatch.forEach(msg => {
                    const msgFiles = msg.files || [];
                    const msgImages = (msg.images || msg.image_urls || []).length > 0 
                        ? (msg.images || msg.image_urls) 
                        : msgFiles.filter(f => f.is_image);
                    chatView.appendMessage(msg.text, msg.is_user, msgImages, msg.timestamp, true, false, true, msgFiles);
                });
                chatView.scrollToBottom(false);
            } else if (!isProcessing && state.activeSubmittingSessionId !== sessionId) {
                state.currentRenderStartIndex = 0;
                chatView.showInitialGreeting();
            }

            if (isProcessing || state.activeSubmittingSessionId === sessionId) {
                chatView.showTypingIndicator();
                startPollingSession(sessionId);
            } else {
                chatView.removeTypingIndicator();
                stopPollingSession(sessionId);
            }
        } catch (error) {
            console.error("Failed to load history", error);
        }
    };

    const deleteSessionPrompt = async (session) => {
        if (confirm('Möchtest du diesen Chat wirklich löschen?')) {
            try {
                const res = await api.deleteSession(session.id);
                if (res.ok) {
                    if (state.currentSessionId === session.id) {
                        setCurrentSessionId(null);
                        if (chatContainer) chatContainer.innerHTML = '';
                    }
                    await loadSessions();
                } else {
                    alert("Fehler beim Löschen des Chats.");
                }
            } catch (err) {
                console.error("Error deleting session", err);
            }
        }
    };

    const createNewSession = async () => {
        try {
            const data = await api.createSession();
            setCurrentSessionId(data.id);
            await loadSessions();
        } catch (err) {
            console.error("Error creating session", err);
        }
    };

    if (newChatBtn) newChatBtn.addEventListener("click", createNewSession);

    const loadSessions = async () => {
        try {
            const sessions = await api.getSessions();
            if (!sessions || sessions.length === 0) {
                await createNewSession();
                return;
            }

            sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);

            if (!state.currentSessionId || !sessions.find(s => s.id === state.currentSessionId)) {
                selectSession(sessions[0].id);
            } else {
                selectSession(state.currentSessionId);
            }
        } catch (err) {
            console.error("Failed to load sessions", err);
        }
    };

    // Chat form submission
    if (chatForm) {
        chatForm.addEventListener("submit", async (e) => {
            e.preventDefault();

            if (!state.currentSessionId) {
                alert("Fehler: Keine aktive Sitzung.");
                return;
            }

            const text = messageInput ? messageInput.value.trim() : "";
            if (!text && state.selectedFiles.length === 0) return;

            const submittedSessionId = state.currentSessionId;
            state.activeSubmittingSessionId = submittedSessionId;
            ++state.selectSessionCounter;

            if (contextWarning) contextWarning.style.display = "none";
            
            const filesToUpload = [...state.selectedFiles];
            const localImages = [];
            const localNonImages = [];

            filesToUpload.forEach(f => {
                if (isImageFile(f)) {
                    localImages.push(URL.createObjectURL(f));
                } else {
                    localNonImages.push({
                        name: f.name,
                        size: f.size,
                        is_image: false,
                        url: '#'
                    });
                }
            });

            if (messageInput) {
                messageInput.value = "";
                messageInput.style.height = "auto";
                messageInput.style.overflowY = "hidden";
            }
            state.selectedFiles = [];
            inputBar.updatePreviewUI();

            chatView.showTypingIndicator();
            
            let locationStr = "";
            if (state.currentSessionGpsEnabled) {
                try {
                    const position = await new Promise((resolve, reject) => {
                        navigator.geolocation.getCurrentPosition(resolve, reject, {
                            enableHighAccuracy: false,
                            timeout: 10000,
                            maximumAge: 60000
                        });
                    });
                    locationStr = `Lat: ${position.coords.latitude}, Lon: ${position.coords.longitude}`;
                } catch (err) {
                    console.warn("GPS failed", err);
                    locationStr = "Standort konnte nicht ermittelt werden.";
                }
            }

            let displayMsg = text;
            const numImg = filesToUpload.filter(isImageFile).length;
            const numDoc = filesToUpload.length - numImg;
            if (numImg > 0 && numDoc > 0) {
                displayMsg += displayMsg ? ` [${numImg} Bild(er), ${numDoc} Datei(en) angehängt]` : `[${numImg} Bild(er), ${numDoc} Datei(en) gesendet]`;
            } else if (numImg > 0) {
                displayMsg += displayMsg ? ` [${numImg} Bild(er) angehängt]` : `[${numImg} Bild(er) gesendet]`;
            } else if (numDoc > 0) {
                displayMsg += displayMsg ? ` [${numDoc} Datei(en) angehängt]` : `[${numDoc} Datei(en) gesendet]`;
            }

            chatView.removeTypingIndicator();

            const greetingEl = document.getElementById("initial-greeting");
            if (greetingEl) greetingEl.remove();

            const now = new Date().toISOString();
            chatView.appendMessage(displayMsg, true, localImages, now, false, true, false, localNonImages);
            state.currentSessionHistory.push({
                text: displayMsg,
                is_user: true,
                images: localImages,
                files: localNonImages,
                timestamp: now
            });

            const formData = new FormData();
            formData.append("message", text);
            formData.append("stream", "true");
            filesToUpload.forEach(file => {
                formData.append("files", file);
            });
            if (locationStr) {
                formData.append("location", locationStr);
            }

            chatView.showTypingIndicator();

            try {
                const response = await api.sendChatMessage(submittedSessionId, formData);

                if (!response.ok) {
                    chatView.removeTypingIndicator();
                    let errorMsg = "Fehler beim Senden der Nachricht.";
                    try {
                        const errData = await response.json();
                        if (errData.error || errData.detail) {
                            errorMsg = errData.error || errData.detail;
                        }
                    } catch (_) {}
                    if (state.currentSessionId === submittedSessionId) {
                        chatView.appendErrorMessage(errorMsg);
                    }
                    return;
                }

                const contentType = response.headers.get("content-type") || "";

                if (contentType.includes("text/event-stream")) {
                    let accumulatedText = "";
                    let aiMsgDiv = null;
                    let textDiv = null;
                    let bubbleDiv = null;

                    await readSSEStream(response, {
                        onDelta: (event) => {
                            if (state.currentSessionId === submittedSessionId) {
                                chatView.removeTypingIndicator();
                                if (!aiMsgDiv) {
                                    aiMsgDiv = document.createElement("div");
                                    aiMsgDiv.className = "message ai-message streaming new-message";
                                    bubbleDiv = document.createElement("div");
                                    bubbleDiv.className = "message-bubble";
                                    textDiv = document.createElement("div");
                                    textDiv.className = "markdown-body";
                                    bubbleDiv.appendChild(textDiv);
                                    aiMsgDiv.appendChild(bubbleDiv);
                                    if (chatContainer) chatContainer.appendChild(aiMsgDiv);
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

                                chatView.scrollToBottom(false);
                            } else {
                                accumulatedText += event.text;
                            }
                        },
                        onDone: (event) => {
                            chatView.removeTypingIndicator();
                            if (aiMsgDiv) {
                                aiMsgDiv.classList.remove("streaming");
                            }
                            if (state.currentSessionId === submittedSessionId) {
                                if (!aiMsgDiv) {
                                    chatView.appendMessage(event.reply || accumulatedText, false, [], event.timestamp, false, true, false);
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
                                state.currentSessionHistory.push({
                                    text: event.reply || accumulatedText,
                                    is_user: false,
                                    images: [],
                                    timestamp: event.timestamp || new Date().toISOString()
                                });
                                if (event.context_truncated && contextWarning) {
                                    contextWarning.style.display = "flex";
                                }
                            }
                        },
                        onError: (event) => {
                            chatView.removeTypingIndicator();
                            if (aiMsgDiv) aiMsgDiv.remove();
                            if (state.currentSessionId === submittedSessionId) {
                                chatView.appendErrorMessage(event.error || "Fehler bei der Antwortgenerierung.");
                            }
                        }
                    });

                    chatView.removeTypingIndicator();
                    if (aiMsgDiv) aiMsgDiv.classList.remove("streaming");

                    const sessions = await api.getSessions();
                    sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);

                } else {
                    const data = await response.json();
                    chatView.removeTypingIndicator();

                    if (state.currentSessionId !== submittedSessionId) return;

                    chatView.appendMessage(data.reply, false, [], data.timestamp, false, true, false);
                    state.currentSessionHistory.push({
                        text: data.reply,
                        is_user: false,
                        images: [],
                        timestamp: data.timestamp || new Date().toISOString()
                    });

                    if (data.context_truncated && contextWarning) {
                        contextWarning.style.display = "flex";
                    }

                    const sessions = await api.getSessions();
                    state.lastSessions = sessions;
                    sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);

                    const curSess = sessions.find(s => s.id === submittedSessionId);
                    if (curSess && !curSess.has_icon) {
                        setTimeout(async () => {
                            if (state.currentSessionId === submittedSessionId) {
                                await loadSessions();
                                const refreshedSession = state.lastSessions?.find(s => s.id === submittedSessionId);
                                if (refreshedSession && refreshedSession.has_icon) {
                                    const iconImg = document.getElementById('header-chat-icon');
                                    const defaultIcon = document.getElementById('header-default-icon');
                                    if (iconImg && defaultIcon) {
                                        iconImg.src = `/api/sessions/${submittedSessionId}/icon?t=${Date.now()}`;
                                        iconImg.style.display = 'block';
                                        defaultIcon.style.display = 'none';
                                    }
                                }
                            }
                        }, 3000);
                    }
                }

            } catch (error) {
                chatView.removeTypingIndicator();
                if (state.currentSessionId === submittedSessionId) {
                    chatView.appendErrorMessage("Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.");
                }
                console.error("Error calling chat API", error);
            } finally {
                if (state.activeSubmittingSessionId === submittedSessionId) {
                    state.activeSubmittingSessionId = null;
                }
            }
        });
    }

    // System prompt modal events
    if (systemPromptBtn) systemPromptBtn.addEventListener("click", modals.openSystemPromptModal);
    if (closePromptBtn) closePromptBtn.addEventListener("click", modals.closeSystemPromptModal);

    if (exportSessionBtn) {
        exportSessionBtn.addEventListener("click", () => {
            if (!state.currentSessionId) return;
            const downloadUrl = `/api/sessions/${state.currentSessionId}/export`;
            const link = document.createElement("a");
            link.href = downloadUrl;
            link.setAttribute("download", "");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }

    if (importSessionBtn && importSessionInput) {
        importSessionBtn.addEventListener("click", () => {
            importSessionInput.value = "";
            importSessionInput.click();
        });

        importSessionInput.addEventListener("change", async (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file || !state.currentSessionId) return;

            importSessionBtn.disabled = true;
            if (importStatusText) {
                importStatusText.style.display = "block";
                importStatusText.style.color = "var(--text-muted)";
                importStatusText.textContent = "Importiere Chat-Archiv...";
            }

            try {
                const response = await api.importSessionArchive(state.currentSessionId, file);

                if (response.ok) {
                    modals.closeSystemPromptModal();
                    await loadSessions();
                    await selectSession(state.currentSessionId, true);
                } else {
                    let errMsg = "Fehler beim Importieren des Chats.";
                    try {
                        const errData = await response.json();
                        if (errData.detail || errData.error) {
                            errMsg = errData.detail || errData.error;
                        }
                    } catch (_) {}
                    if (importStatusText) {
                        importStatusText.textContent = errMsg;
                        importStatusText.style.color = "var(--danger-color, #ef4444)";
                    }
                    alert(errMsg);
                }
            } catch (err) {
                console.error("Error importing session", err);
                if (importStatusText) {
                    importStatusText.textContent = "Verbindungsfehler beim Importieren.";
                    importStatusText.style.color = "var(--danger-color, #ef4444)";
                }
                alert("Verbindungsfehler beim Importieren.");
            } finally {
                importSessionBtn.disabled = false;
                importSessionInput.value = "";
            }
        });
    }

    if (systemPromptForm) {
        systemPromptForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!state.currentSessionId) return;

            const promptText = systemPromptInput ? systemPromptInput.value.trim() : "";
            const includeGps = gpsSettingInput ? gpsSettingInput.checked : false;
            const modelVal = chatModelSelect ? (chatModelSelect.value || null) : null;
            const effortVal = (chatThinkingEffortSelect && !chatThinkingEffortSelect.disabled) ? (chatThinkingEffortSelect.value || null) : null;
            const titleInput = document.getElementById("chat-title-input");
            const titleText = titleInput ? titleInput.value.trim() : "";
            
            if (savePromptBtn) {
                savePromptBtn.disabled = true;
                savePromptBtn.textContent = "Wird gespeichert...";
            }
            if (settingsErrorBanner) {
                settingsErrorBanner.style.display = "none";
                settingsErrorBanner.textContent = "";
            }

            try {
                const promptPromise = api.updateSessionSettings(state.currentSessionId, {
                    prompt: promptText,
                    include_gps: includeGps,
                    model: modelVal,
                    thinking_effort: effortVal
                });
                const session = state.lastSessions?.find(s => s.id === state.currentSessionId);
                let titlePromise = null;
                if (titleText && session && session.title !== titleText) {
                    titlePromise = api.updateSessionTitle(state.currentSessionId, titleText);
                }

                const responses = await Promise.all([promptPromise, ...(titlePromise ? [titlePromise] : [])]);
                const settingsRes = responses[0];
                const allOk = responses.every(res => res.ok);

                if (allOk) {
                    state.currentSessionGpsEnabled = includeGps;
                    updateHeaderModelIndicator(modelVal, effortVal);
                    modals.closeSystemPromptModal();
                    if (titlePromise) {
                        await loadSessions();
                    }
                } else {
                    let errMsg = "Fehler beim Speichern der Einstellungen.";
                    try {
                        const errJson = await settingsRes.json();
                        if (errJson && errJson.detail) errMsg = errJson.detail;
                    } catch (_) {}
                    if (settingsErrorBanner) {
                        settingsErrorBanner.textContent = errMsg;
                        settingsErrorBanner.style.display = "block";
                    } else {
                        alert(errMsg);
                    }
                }
            } catch (err) {
                console.error("Error saving settings", err);
                if (settingsErrorBanner) {
                    settingsErrorBanner.textContent = "Verbindungsfehler beim Speichern.";
                    settingsErrorBanner.style.display = "block";
                } else {
                    alert("Verbindungsfehler beim Speichern.");
                }
            } finally {
                if (savePromptBtn) {
                    savePromptBtn.disabled = false;
                    savePromptBtn.textContent = "Speichern";
                }
            }
        });
    }

    // Auth Form submission
    if (authForm) {
        authForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const username = loginUsernameInput.value.trim();
            const password = loginPasswordInput.value;
            if (!username || !password) return;

            if (verifyBtn) {
                verifyBtn.disabled = true;
                verifyBtn.textContent = "Wird verifiziert...";
            }

            try {
                const res = await api.login(username, password);

                if (res.ok) {
                    const data = await res.json();
                    if (data.success) {
                        modals.closeAuthModal();
                        loginPasswordInput.value = "";
                        modals.updateUserBadge(username);
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
                if (verifyBtn) {
                    verifyBtn.disabled = false;
                    verifyBtn.textContent = "Anmelden";
                }
            }
        });
    }

    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            if (confirm("Möchtest du dich wirklich abmelden?")) {
                try {
                    await api.logout();
                    handleAuthError();
                } catch (err) {
                    console.error("Error logging out", err);
                }
            }
        });
    }

    // Visibility change sync
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible" && state.currentSessionId && state.activeSubmittingSessionId !== state.currentSessionId) {
            selectSession(state.currentSessionId);
        }
    });

    // Initial Auth Check
    (async () => {
        try {
            const data = await api.checkAuthStatus();
            if (!data.authenticated) {
                modals.openAuthModal();
            } else {
                modals.closeAuthModal();
                modals.updateUserBadge(data.username);
                loadSessions();
            }
        } catch (err) {
            console.error("Error checking auth status", err);
        }
    })();
});
