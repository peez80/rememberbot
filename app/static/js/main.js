/**
 * Main application orchestrator for RememberBot.
 */

import { state, setCurrentSessionId } from './state.js';
import { isImageFile } from './utils/dom.js';
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
    const sidebarBackdrop = document.getElementById("sidebar-backdrop");
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
    const settingsErrorBanner = document.getElementById("settings-error-banner");
    const sessionModelIndicator = document.getElementById("session-model-indicator");
    const gpsSettingInput = document.getElementById("gps-setting-input");
    const closePromptBtn = document.getElementById("close-prompt-btn");
    const savePromptBtn = document.getElementById("save-prompt-btn");
    const exportSessionBtn = document.getElementById("export-session-btn");
    const exportCancelBtn = document.getElementById("export-cancel-btn");
    const importSessionBtn = document.getElementById("import-session-btn");
    const importCancelBtn = document.getElementById("import-cancel-btn");
    const importSessionInput = document.getElementById("import-session-input");
    const importStatusText = document.getElementById("import-status-text");

    let activeExportAbortController = null;
    let activeImportAbortController = null;
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

    const updateHeaderModelIndicator = (model) => {
        if (!sessionModelIndicator) return;
        if (!model) {
            sessionModelIndicator.style.display = "none";
            sessionModelIndicator.textContent = "";
            return;
        }

        const modelSpec = modelCatalog && model ? modelCatalog[model] : null;
        const modelLabel = modelSpec ? modelSpec.label : model;

        sessionModelIndicator.textContent = modelLabel;
        sessionModelIndicator.style.display = "block";
    };

    if (chatModelSelect) {
        chatModelSelect.addEventListener("change", () => {
            if (settingsErrorBanner) settingsErrorBanner.style.display = "none";
        });
    }

    const updateAuthModalView = (authConfig) => {
        const authForm = document.getElementById("auth-form");
        const oauthContainer = document.getElementById("oauth-login-container");
        const oauthLabel = document.getElementById("oauth-login-label");
        if (authConfig && authConfig.oauth_configured) {
            if (authForm) authForm.style.display = "none";
            if (oauthContainer) {
                oauthContainer.style.display = "block";
                if (oauthLabel && authConfig.provider_name) {
                    oauthLabel.textContent = `Mit ${authConfig.provider_name} anmelden`;
                }
            }
        } else {
            if (authForm) authForm.style.display = "flex";
            if (oauthContainer) oauthContainer.style.display = "none";
        }
    };

    // 401 Handler
    const handleAuthError = async () => {
        setCurrentSessionId(null);
        if (chatContainer) chatContainer.innerHTML = '';
        const sessionList = document.getElementById("session-list");
        if (sessionList) sessionList.innerHTML = '';

        if (state.authConfig) {
            updateAuthModalView(state.authConfig);
        } else {
            try {
                const data = await api.checkAuthStatus();
                state.authConfig = data;
                updateAuthModalView(data);
            } catch (_) {}
        }
        modals.openAuthModal();
    };
    api.setAuthErrorHandler(handleAuthError);

    // Sidebar toggling and gestures
    if (menuBtn) menuBtn.addEventListener("click", sidebarView.toggleSidebar);
    if (closeSidebarBtn) closeSidebarBtn.addEventListener("click", sidebarView.toggleSidebar);
    if (sidebarBackdrop) sidebarBackdrop.addEventListener("click", sidebarView.closeSidebar);
    sidebarView.initSidebarSwipeGestures();

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

    const notifyRecoveryWake = () => {
        state.recoveryResetRequested = true;
        if (state.recoveryWakeListeners) {
            state.recoveryWakeListeners.forEach(resolve => resolve());
            state.recoveryWakeListeners.clear();
        }
    };

    const waitForVisibleOrDelay = (delayMs) => new Promise(resolve => {
        if (document.visibilityState === "hidden") {
            state.recoveryWakeListeners.add(resolve);
            return;
        }
        let timer = null;
        const wake = () => {
            if (timer) clearTimeout(timer);
            state.recoveryWakeListeners.delete(wake);
            resolve();
        };
        state.recoveryWakeListeners.add(wake);
        timer = setTimeout(wake, delayMs);
    });

    const fetchWithTimeout = async (requestFn, timeoutMs = 1200) => {
        const controller = new AbortController();
        let timer = null;
        try {
            timer = setTimeout(() => controller.abort(), timeoutMs);
            return await requestFn(controller.signal);
        } finally {
            if (timer) clearTimeout(timer);
        }
    };

    // Background session polling
    const stopPollingSession = (sessionId) => {
        if (state.activePollTimers.has(sessionId)) {
            clearInterval(state.activePollTimers.get(sessionId));
            state.activePollTimers.delete(sessionId);
        }
    };

    const updateHeaderSessionInfo = (sessionId) => {
        if (state.currentSessionId !== sessionId) return;
        const session = state.lastSessions?.find(s => s.id === sessionId);
        if (!session) return;
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
    };

    const stopPollingSessionIcon = (sessionId) => {
        if (state.activeIconPollTimers.has(sessionId)) {
            clearInterval(state.activeIconPollTimers.get(sessionId));
            state.activeIconPollTimers.delete(sessionId);
        }
    };

    const startPollingSessionIcon = (sessionId, { expectNewIcon = false } = {}) => {
        stopPollingSessionIcon(sessionId);

        let ticks = 0;
        const maxTicks = 120;
        let sawGenerating = false;

        const checkIconStatus = async () => {
            if (document.visibilityState === "hidden") return;
            ticks++;
            if (ticks > maxTicks) {
                stopPollingSessionIcon(sessionId);
                return;
            }

            try {
                const res = await api.getSessionStatus(sessionId);
                if (!res.ok) {
                    if (res.status === 404) {
                        stopPollingSessionIcon(sessionId);
                    }
                    return;
                }
                const data = await res.json();
                if (data.is_generating_icon) {
                    sawGenerating = true;
                    return;
                }

                const shouldRefresh = (!expectNewIcon && data.has_icon) ||
                                      (expectNewIcon && (sawGenerating || ticks >= 2) && data.has_icon);

                if (shouldRefresh) {
                    stopPollingSessionIcon(sessionId);
                    const sessions = await api.getSessions();
                    state.lastSessions = sessions;
                    sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);
                    if (state.currentSessionId === sessionId) {
                        updateHeaderSessionInfo(sessionId);
                    }
                } else if (!data.is_generating_icon && !data.has_icon && ticks >= 4) {
                    stopPollingSessionIcon(sessionId);
                }
            } catch (err) {
                console.warn("Icon polling error for session", sessionId, err);
            }
        };

        const timerId = setInterval(checkIconStatus, 1000);
        state.activeIconPollTimers.set(sessionId, timerId);
        setTimeout(checkIconStatus, 150);
    };

    const startPollingSession = (sessionId) => {
        if (state.activePollTimers.has(sessionId)) return;

        const checkStatus = async () => {
            if (document.visibilityState === "hidden") return;
            try {
                const res = await api.getSessionStatus(sessionId);
                if (!res.ok) {
                    if (res.status === 404) {
                        stopPollingSession(sessionId);
                    }
                    return;
                }
                const data = await res.json();
                if (data.is_processing) {
                    if (state.currentSessionId === sessionId) {
                        const hasIndicator = document.getElementById("typing-indicator");
                        const hasStreaming = document.querySelector(".message.streaming");
                        if (!hasIndicator && !hasStreaming) {
                            chatView.showTypingIndicator();
                        }
                    }
                } else {
                    if (state.currentSessionId === sessionId && state.activeSubmittingSessionId !== sessionId) {
                        const loaded = await selectSession(sessionId, true);
                        if (!loaded) return;
                    }
                    stopPollingSession(sessionId);
                    const sessions = await api.getSessions();
                    sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);
                }
            } catch (err) {
                console.error("Polling error for session", sessionId, err);
            }
        };

        const timerId = setInterval(checkStatus, 500);
        state.activePollTimers.set(sessionId, timerId);
    };

    const handleRemoveQueued = async (messageId, msgElement) => {
        try {
            if (msgElement) {
                msgElement._wasRemovedByUser = true;
                if (msgElement._abortController) {
                    try {
                        msgElement._abortController.abort();
                    } catch (_) {}
                }
                msgElement.remove();
            }
            const idx = state.currentSessionHistory.findIndex(m => m.id === messageId);
            if (idx !== -1) {
                state.currentSessionHistory.splice(idx, 1);
            }

            const ensureActiveIndicator = () => {
                const stillBusy = (state.activeSubmissionsBySession.get(state.currentSessionId) || 0) > 0 || state.activeSubmittingSessionId === state.currentSessionId;
                if (stillBusy) {
                    const hasIndicator = document.getElementById("typing-indicator");
                    const hasStreaming = document.querySelector(".message.streaming");
                    if (!hasIndicator && !hasStreaming) {
                        chatView.showTypingIndicator();
                    }
                }
            };
            ensureActiveIndicator();

            const res = await api.deleteQueuedMessage(state.currentSessionId, messageId);
            if (!res.ok && res.status === 409) {
                if (msgElement) {
                    msgElement._wasRemovedByUser = false;
                    chatView.markMessageProcessing(msgElement);
                }
            }
            ensureActiveIndicator();
        } catch (err) {
            console.error("Failed to delete queued message:", err);
        }
    };

    const applySessionHistoryToView = (sessionId, history, isProcessing) => {
        if (state.currentSessionId !== sessionId) return false;
        if (state.pendingRecoverySessionId === sessionId) {
            state.pendingRecoverySessionId = null;
        }

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
                chatView.appendMessage(
                    msg.text,
                    msg.is_user,
                    msgImages,
                    msg.timestamp,
                    true,
                    false,
                    true,
                    msgFiles,
                    msg.id,
                    msg.status,
                    handleRemoveQueued
                );
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
        return true;
    };

    // Select session
    const selectSession = async (sessionId, forceReload = false) => {
        const isSwitchingSession = (state.currentSessionId !== sessionId);
        if (!forceReload && !isSwitchingSession && state.activeSubmittingSessionId === sessionId) {
            return false;
        }

        if (!forceReload && !isSwitchingSession && state.activeSelectSessionPromise && state.activeSelectSessionId === sessionId && state.currentSessionId === sessionId) {
            return state.activeSelectSessionPromise;
        }

        const requestId = ++state.selectSessionCounter;
        setCurrentSessionId(sessionId);
        if (contextWarning) contextWarning.style.display = "none";
        sidebarView.updateActiveSessionHighlight(sessionId);

        if (window.innerWidth <= 768) {
            sidebarView.closeSidebar();
        }

        if (systemPromptBtn) systemPromptBtn.disabled = false;

        const session = state.lastSessions?.find(s => s.id === sessionId);
        updateHeaderSessionInfo(sessionId);
        if (session && !session.has_icon && session.title && session.title !== "Neuer Chat") {
            startPollingSessionIcon(sessionId, { expectNewIcon: false });
        }

        const shouldShowLoading = isSwitchingSession || !chatContainer || chatContainer.children.length === 0;
        if (shouldShowLoading) {
            chatView.showChatLoading();
        }

        const executeSelect = async () => {
            try {
                // Fetch settings in parallel without blocking history rendering
                api.getSessionSettings(sessionId).then(async (promptRes) => {
                    if (requestId !== state.selectSessionCounter || state.currentSessionId !== sessionId) return;
                    if (promptRes && promptRes.ok) {
                        try {
                            const promptData = await promptRes.json();
                            if (state.currentSessionId === sessionId) {
                                if (systemPromptInput) systemPromptInput.value = promptData.prompt || "";
                                state.currentSessionGpsEnabled = promptData.include_gps || false;
                                if (gpsSettingInput) {
                                    gpsSettingInput.checked = state.currentSessionGpsEnabled;
                                }
                                await ensureModelCatalogLoaded();
                                if (chatModelSelect) {
                                    const desiredModel = promptData.model || "";
                                    chatModelSelect.value = desiredModel;
                                    if (chatModelSelect.value !== desiredModel) {
                                        chatModelSelect.value = "";
                                    }
                                }
                                updateHeaderModelIndicator(promptData.model);
                            }
                        } catch (_) {}
                    }
                }).catch(() => {});

                const historyRes = await api.getSessionHistory(sessionId);

                if (requestId !== state.selectSessionCounter) return false;
                if (state.currentSessionId !== sessionId) return false;
                if (!historyRes || !historyRes.ok) {
                    if (requestId === state.selectSessionCounter) {
                        chatView.hideChatLoading();
                        chatView.appendErrorMessage("Fehler beim Laden des Chatverlaufs.");
                    }
                    return false;
                }

                const isProcessing = historyRes.headers.get("X-Is-Processing") === "true";
                const history = await historyRes.json();

                if (requestId !== state.selectSessionCounter) return false;
                if (state.currentSessionId !== sessionId) return false;

                applySessionHistoryToView(sessionId, history, isProcessing);
                return true;
            } catch (error) {
                console.error("Failed to load history", error);
                if (requestId === state.selectSessionCounter) {
                    chatView.hideChatLoading();
                    chatView.appendErrorMessage("Fehler beim Laden des Chatverlaufs.");
                }
                return false;
            } finally {
                if (state.activeSelectSessionId === sessionId) {
                    state.activeSelectSessionPromise = null;
                    state.activeSelectSessionId = null;
                }
                if (requestId === state.selectSessionCounter) {
                    chatView.hideChatLoading();
                }
            }
        };

        const selectPromise = executeSelect();
        state.activeSelectSessionPromise = selectPromise;
        state.activeSelectSessionId = sessionId;
        return selectPromise;
    };

    const syncSessionWithRetry = async (sessionId, forceReload = false) => {
        const delays = [80, 180, 350, 600];
        for (let i = 0; i <= delays.length; i++) {
            if (state.currentSessionId !== sessionId) return false;
            const ok = await selectSession(sessionId, forceReload);
            if (ok) return true;
            if (i < delays.length) {
                await waitForVisibleOrDelay(delays[i]);
            }
        }
        return false;
    };

    const recoverInterruptedChat = async (sessionId, baselineHistoryCount, expectedUserText = "") => {
        const backoffs = [80, 180, 350, 600, 900, 1200, 1500];
        let attempt = 0;

        while (attempt < (state.streamWasHidden ? 8 : 3)) {
            if (document.visibilityState === "hidden") {
                state.streamWasHidden = true;
                await waitForVisibleOrDelay(0);
            }
            if (state.recoveryResetRequested) {
                state.recoveryResetRequested = false;
                attempt = 0;
            }
            attempt++;

            try {
                const statusRes = await fetchWithTimeout((sig) => api.getSessionStatus(sessionId, { signal: sig }));
                if (statusRes.status === 404) {
                    return false;
                }
                if (!statusRes.ok) {
                    throw new Error(`Status check failed with ${statusRes.status}`);
                }
                const statusData = await statusRes.json();
                if (statusData.is_processing) {
                    if (state.activeSubmittingSessionId === sessionId) {
                        state.activeSubmittingSessionId = null;
                    }
                    if (state.currentSessionId === sessionId) {
                        await syncSessionWithRetry(sessionId, true);
                    } else {
                        startPollingSession(sessionId);
                    }
                    return true;
                }

                const histRes = await fetchWithTimeout((sig) => api.getSessionHistory(sessionId, { signal: sig }));
                if (!histRes.ok) {
                    throw new Error(`History check failed with ${histRes.status}`);
                }
                const isProcessing = histRes.headers.get("X-Is-Processing") === "true";
                const history = await histRes.json();
                const lastMsg = Array.isArray(history) && history.length > 0 ? history[history.length - 1] : null;
                const prevMsg = Array.isArray(history) && history.length > 1 ? history[history.length - 2] : null;
                const hasServerProgress = Array.isArray(history) && (
                    history.length > baselineHistoryCount ||
                    Boolean(expectedUserText && lastMsg && !lastMsg.is_user && prevMsg && prevMsg.is_user && prevMsg.text === expectedUserText)
                );
                if (hasServerProgress) {
                    if (state.activeSubmittingSessionId === sessionId) {
                        state.activeSubmittingSessionId = null;
                    }
                    if (state.currentSessionId === sessionId) {
                        applySessionHistoryToView(sessionId, history, isProcessing);
                        api.getSessionSettings(sessionId).catch(() => {});
                    }
                    try {
                        const sessions = await api.getSessions();
                        state.lastSessions = sessions;
                        sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);
                    } catch (_) {}
                    return true;
                }
            } catch (err) {
                const maxAttempts = state.streamWasHidden ? 8 : 3;
                if (attempt >= maxAttempts && document.visibilityState !== "hidden" && !state.recoveryResetRequested) {
                    console.warn("Could not recover interrupted chat session", sessionId, err);
                }
            }

            const maxAttempts = state.streamWasHidden ? 8 : 3;
            if (attempt < maxAttempts || document.visibilityState === "hidden" || state.recoveryResetRequested) {
                const delayMs = backoffs[Math.min(attempt - 1, backoffs.length - 1)];
                await waitForVisibleOrDelay(delayMs);
            }
        }
        return false;
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
            const isBusy = (state.activeSubmissionsBySession.get(submittedSessionId) || 0) > 0 || state.activeSubmittingSessionId === submittedSessionId;
            const activeCount = (state.activeSubmissionsBySession.get(submittedSessionId) || 0) + 1;
            state.activeSubmissionsBySession.set(submittedSessionId, activeCount);
            state.activeSubmittingSessionId = submittedSessionId;
            ++state.selectSessionCounter;

            startPollingSession(submittedSessionId);

            if (contextWarning) contextWarning.style.display = "none";
            chatView.hideChatLoading();
            
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

            if (!isBusy) {
                chatView.showTypingIndicator();
            }
            
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

            if (!isBusy) {
                chatView.removeTypingIndicator();
            }

            const greetingEl = document.getElementById("initial-greeting");
            if (greetingEl) greetingEl.remove();

            const baselineHistoryCount = state.currentSessionHistory.length;
            const now = new Date().toISOString();
            const clientMessageId = "msg-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

            const userMsgDiv = chatView.appendMessage(
                displayMsg,
                true,
                localImages,
                now,
                false,
                true,
                false,
                localNonImages,
                clientMessageId,
                isBusy ? "queued" : null,
                handleRemoveQueued
            );

            state.currentSessionHistory.push({
                id: clientMessageId,
                text: displayMsg,
                is_user: true,
                status: isBusy ? "queued" : null,
                images: localImages,
                files: localNonImages,
                timestamp: now
            });

            const formData = new FormData();
            formData.append("message", text);
            formData.append("message_id", clientMessageId);
            formData.append("stream", "true");
            filesToUpload.forEach(file => {
                formData.append("files", file);
            });
            if (locationStr) {
                formData.append("location", locationStr);
            }

            if (!isBusy) {
                chatView.showTypingIndicator(userMsgDiv);
            }

            const streamAbortController = new AbortController();
            userMsgDiv._abortController = streamAbortController;
            if (!isBusy) {
                state.activeStreamAbortController = streamAbortController;
            }
            state.streamWasHidden = (document.visibilityState === "hidden");

            try {
                const response = await api.sendChatMessage(submittedSessionId, formData, {
                    signal: streamAbortController.signal
                });

                if (!response.ok) {
                    if (state.currentSessionHistory.length > baselineHistoryCount) {
                        state.currentSessionHistory.length = baselineHistoryCount;
                    }
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
                    let streamController = null;
                    let streamDisconnected = false;
                    let streamDisconnectError = null;

                    await readSSEStream(response, {
                        onQueued: (event) => {
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            const msgId = event.message_id || clientMessageId;
                            if (userMsgDiv) {
                                userMsgDiv.dataset.messageId = msgId;
                                if (!userMsgDiv.classList.contains("queued-message")) {
                                    userMsgDiv.classList.add("queued-message");
                                }
                                if (!userMsgDiv.querySelector(".message-queued-bar")) {
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
                                    removeBtn.addEventListener("click", (e) => {
                                        e.stopPropagation();
                                        const currentId = userMsgDiv.dataset.messageId || msgId;
                                        handleRemoveQueued(currentId, userMsgDiv);
                                    });

                                    bar.appendChild(badge);
                                    bar.appendChild(removeBtn);
                                    userMsgDiv.appendChild(bar);
                                }
                            }
                        },
                        onProcessing: (event) => {
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            state.activeStreamAbortController = streamAbortController;
                            chatView.markMessageProcessing(userMsgDiv);
                            if (state.currentSessionId === submittedSessionId) {
                                chatView.showTypingIndicator(userMsgDiv);
                            }
                        },
                        onDelta: (event) => {
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            if (state.currentSessionId === submittedSessionId) {
                                if (!streamController) {
                                    streamController = chatView.initStreamingMessage(userMsgDiv);
                                }
                                accumulatedText += event.text;
                                chatView.updateStreamingMessage(streamController, accumulatedText);
                            } else {
                                accumulatedText += event.text;
                            }
                        },
                        onDone: (event) => {
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            if (state.currentSessionId === submittedSessionId) {
                                if (!streamController) {
                                    chatView.appendMessage(event.reply || accumulatedText, false, [], event.timestamp, false, true, false, [], null, null, null, userMsgDiv);
                                } else {
                                    chatView.finalizeStreamingMessage(streamController, event.reply || accumulatedText);
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
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            chatView.removeStreamingMessage(streamController);
                            streamController = null;
                            if (state.currentSessionId === submittedSessionId) {
                                chatView.appendErrorMessage(event.error || "Fehler bei der Antwortgenerierung.");
                            }
                        },
                        onDisconnect: (err) => {
                            if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                            streamDisconnected = true;
                            streamDisconnectError = err;
                        }
                    });

                    if (userMsgDiv && userMsgDiv._wasRemovedByUser) {
                        return;
                    }

                    if (streamDisconnected) {
                        chatView.removeStreamingMessage(streamController);
                        streamController = null;
                        throw streamDisconnectError || new Error("SSE stream disconnected");
                    }

                    if (!userMsgDiv?._wasRemovedByUser) {
                        chatView.removeTypingIndicator();
                        if (streamController && streamController.aiMsgDiv) {
                            streamController.aiMsgDiv.classList.remove("streaming");
                        }
                    }

                    try {
                        const sessions = await api.getSessions();
                        state.lastSessions = sessions;
                        sidebarView.renderSessionList(sessions, selectSession, deleteSessionPrompt);
                        if (state.currentSessionId === submittedSessionId) {
                            updateHeaderSessionInfo(submittedSessionId);
                        }
                        const curSess = sessions.find(s => s.id === submittedSessionId);
                        if (baselineHistoryCount === 0 || !curSess?.has_icon) {
                            startPollingSessionIcon(submittedSessionId, { expectNewIcon: false });
                        }
                    } catch (err) {
                        console.warn("Failed to refresh sessions after stream", err);
                    }

                } else {
                    const data = await response.json();
                    if (userMsgDiv && userMsgDiv._wasRemovedByUser) return;
                    chatView.removeTypingIndicator();

                    if (state.currentSessionId !== submittedSessionId) return;

                    chatView.appendMessage(data.reply, false, [], data.timestamp, false, true, false, [], null, null, null, userMsgDiv);
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
                    if (state.currentSessionId === submittedSessionId) {
                        updateHeaderSessionInfo(submittedSessionId);
                    }

                    const curSess = sessions.find(s => s.id === submittedSessionId);
                    if (baselineHistoryCount === 0 || !curSess?.has_icon) {
                        startPollingSessionIcon(submittedSessionId, { expectNewIcon: false });
                    }
                }

            } catch (error) {
                if (userMsgDiv && userMsgDiv._wasRemovedByUser) {
                    return;
                }
                if (state.activeStreamAbortController === streamAbortController) {
                    state.activeStreamAbortController = null;
                }
                state.recoveryResetRequested = false;
                const recovered = await recoverInterruptedChat(submittedSessionId, baselineHistoryCount, displayMsg);
                if (!recovered) {
                    if (state.currentSessionHistory.length > baselineHistoryCount) {
                        state.currentSessionHistory.length = baselineHistoryCount;
                    }
                    state.pendingRecoverySessionId = submittedSessionId;
                    chatView.removeTypingIndicator();
                    if (state.currentSessionId === submittedSessionId) {
                        chatView.appendErrorMessage("Es gab einen Verbindungsfehler. Bitte versuche es später noch einmal.");
                    }
                    console.error("Error calling chat API", error);
                }
            } finally {
                if (state.activeStreamAbortController === streamAbortController) {
                    state.activeStreamAbortController = null;
                }
                state.streamWasHidden = false;
                const count = Math.max(0, (state.activeSubmissionsBySession.get(submittedSessionId) || 1) - 1);
                if (count === 0) {
                    state.activeSubmissionsBySession.delete(submittedSessionId);
                    if (state.activeSubmittingSessionId === submittedSessionId) {
                        state.activeSubmittingSessionId = null;
                    }
                } else {
                    state.activeSubmissionsBySession.set(submittedSessionId, count);
                    if (state.currentSessionId === submittedSessionId) {
                        const hasIndicator = document.getElementById("typing-indicator");
                        const hasStreaming = document.querySelector(".message.streaming");
                        if (!hasIndicator && !hasStreaming) {
                            chatView.showTypingIndicator();
                        }
                    }
                }
            }
        });
    }

    // System prompt modal events
    if (systemPromptBtn) systemPromptBtn.addEventListener("click", modals.openSystemPromptModal);
    if (closePromptBtn) closePromptBtn.addEventListener("click", modals.closeSystemPromptModal);

    if (exportCancelBtn) {
        exportCancelBtn.addEventListener("click", () => {
            if (activeExportAbortController) {
                activeExportAbortController.abort();
                activeExportAbortController = null;
            }
            modals.closeExportModal();
            if (exportSessionBtn) exportSessionBtn.disabled = false;
        });
    }

    if (exportSessionBtn) {
        exportSessionBtn.addEventListener("click", async () => {
            if (!state.currentSessionId || exportSessionBtn.disabled) return;
            exportSessionBtn.disabled = true;
            activeExportAbortController = new AbortController();
            modals.openExportModal();

            try {
                const { blob, filename } = await api.exportSessionArchive(state.currentSessionId, activeExportAbortController.signal);

                modals.updateExportModalStatus({
                    title: '<i class="ph-bold ph-check-circle" style="color: #10b981;"></i> Download gestartet',
                    message: 'Der Download beginnt jetzt...',
                    detail: '',
                    isError: false,
                    showSpinner: false
                });

                const blobUrl = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = blobUrl;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);

                setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
                setTimeout(() => {
                    modals.closeExportModal();
                    if (exportSessionBtn) exportSessionBtn.disabled = false;
                }, 500);
            } catch (err) {
                if (err.name === "AbortError") {
                    return;
                }
                console.error("Session export error:", err);
                modals.updateExportModalStatus({
                    title: '<i class="ph-bold ph-warning-circle" style="color: #ef4444;"></i> Export fehlgeschlagen',
                    message: err.message || "Fehler beim Vorbereiten des Archivs",
                    detail: "Bitte versuche es erneut.",
                    isError: true,
                    showSpinner: false,
                    buttonText: "Schließen"
                });
                if (exportSessionBtn) exportSessionBtn.disabled = false;
            } finally {
                activeExportAbortController = null;
            }
        });
    }

    if (importCancelBtn) {
        importCancelBtn.addEventListener("click", () => {
            if (activeImportAbortController) {
                activeImportAbortController.abort();
                activeImportAbortController = null;
            }
            modals.closeImportModal();
            if (importSessionBtn) importSessionBtn.disabled = false;
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

            // Check size limit: 2000MB (matching backend MAX_ZIP_UPLOAD_SIZE = 2000 * 1024 * 1024)
            if (file.size > 2000 * 1024 * 1024) {
                modals.openImportModal(file.name, file.size);
                modals.setImportStepStatus("upload", "error", "Datei zu groß (max. 2000 MB)");
                modals.setImportModalError("Das ausgewählte ZIP-Archiv überschreitet die Maximalgröße von 2000 MB.");
                importSessionInput.value = "";
                return;
            }

            importSessionBtn.disabled = true;
            activeImportAbortController = new AbortController();
            modals.openImportModal(file.name, file.size);

            modals.setImportStepStatus("upload", "active", "Wird hochgeladen (0%)...");

            try {
                await api.importSessionArchive(state.currentSessionId, file, {
                    signal: activeImportAbortController.signal,
                    onUploadProgress: (pct) => {
                        if (pct < 100) {
                            modals.setImportStepStatus("upload", "active", `Wird hochgeladen (${pct}%)...`);
                        } else {
                            modals.setImportStepStatus("upload", "done", "Archiv übertragen (100%)");
                            modals.setImportStepStatus("verify", "active", "Integrität & Sicherheit prüfen...");
                        }
                    }
                });

                modals.setImportStepStatus("upload", "done", "Archiv übertragen");
                modals.setImportStepStatus("verify", "done", "Archiv geprüft & entpackt");
                modals.setImportStepStatus("restore", "done", "Historie & Medien wiederhergestellt");

                modals.setImportStepStatus("finalize", "active", "Chat wird geladen...");

                await loadSessions();
                await selectSession(state.currentSessionId, true);

                modals.setImportStepStatus("finalize", "done", "Chat bereit");

                const titleEl = modals.getImportModalTitle();
                if (titleEl) {
                    titleEl.innerHTML = '<i class="ph-bold ph-check-circle" style="color: #10b981;"></i> Import erfolgreich!';
                }

                setTimeout(() => {
                    modals.closeImportModal();
                    modals.closeSystemPromptModal();
                    if (importSessionBtn) importSessionBtn.disabled = false;
                }, 600);
            } catch (err) {
                if (err.name === "AbortError") {
                    return;
                }
                console.error("Error importing session:", err);
                const uploadStep = document.getElementById("import-step-upload");
                if (uploadStep && uploadStep.classList.contains("active")) {
                    modals.setImportStepStatus("upload", "error", "Upload fehlgeschlagen");
                } else {
                    modals.setImportStepStatus("verify", "error", "Prüfung fehlgeschlagen");
                }
                modals.setImportModalError(err.message || "Fehler beim Importieren des Chats.");
                if (importSessionBtn) importSessionBtn.disabled = false;
            } finally {
                activeImportAbortController = null;
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
                    thinking_effort: null
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
                    updateHeaderModelIndicator(modelVal);
                    modals.closeSystemPromptModal();
                    if (titlePromise) {
                        await loadSessions();
                        startPollingSessionIcon(state.currentSessionId, { expectNewIcon: true });
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

    const handleForegroundWakeup = () => {
        if (document.visibilityState === "hidden" || !state.currentSessionId) {
            return;
        }
        if (state.streamWasHidden && state.activeStreamAbortController) {
            state.activeStreamAbortController.abort();
            notifyRecoveryWake();
        } else if (state.activeSubmittingSessionId === state.currentSessionId) {
            state.streamWasHidden = true;
            notifyRecoveryWake();
        } else {
            syncSessionWithRetry(state.currentSessionId, Boolean(state.pendingRecoverySessionId));
        }
    };

    const markStreamHidden = () => {
        if (state.activeStreamAbortController || state.activeSubmittingSessionId) {
            state.streamWasHidden = true;
        }
    };

    // Visibility change and network reconnect sync
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
            markStreamHidden();
            return;
        }
        handleForegroundWakeup();
    });

    window.addEventListener("pagehide", markStreamHidden);
    window.addEventListener("blur", markStreamHidden);

    window.addEventListener("pageshow", (event) => {
        if (event.persisted || document.visibilityState === "visible") {
            handleForegroundWakeup();
        }
    });

    window.addEventListener("focus", () => {
        if (document.visibilityState === "visible") {
            handleForegroundWakeup();
        }
    });

    window.addEventListener("online", () => {
        handleForegroundWakeup();
    });

    // Initial Auth Check and Error Handling
    (async () => {
        const urlParams = new URLSearchParams(window.location.search);
        const errorParam = urlParams.get("error");
        if (errorParam) {
            const errorBanner = document.getElementById("auth-error-banner");
            if (errorBanner) {
                let errorMsg = "Fehler bei der Anmeldung.";
                if (errorParam === "oauth_access_denied" || errorParam === "access_denied") {
                    errorMsg = "Anmeldung abgebrochen: Zugriff am Identity-Provider verweigert.";
                } else if (errorParam === "state_mismatch") {
                    errorMsg = "Sicherheitsfehler: Die Sitzung ist ungültig oder abgelaufen. Bitte erneut versuchen.";
                } else if (errorParam === "oauth_failed") {
                    errorMsg = "Fehler bei der Authentifizierung am Identity-Provider.";
                }
                errorBanner.textContent = errorMsg;
                errorBanner.style.display = "block";
            }
            window.history.replaceState({}, document.title, window.location.pathname);
        }

        try {
            const data = await api.checkAuthStatus();
            state.authConfig = data;
            updateAuthModalView(data);

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
