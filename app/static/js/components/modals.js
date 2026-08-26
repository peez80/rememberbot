/**
 * Modals component for auth and system prompt / settings dialogues.
 */

import { state } from '../state.js';

export const getAuthModal = () => document.getElementById("auth-modal");
export const getSystemPromptModal = () => document.getElementById("system-prompt-modal");
export const getUserBadge = () => document.getElementById("user-badge");

export const updateUserBadge = (username) => {
    const badge = getUserBadge();
    if (badge && username) {
        badge.style.display = "flex";
        badge.textContent = username.charAt(0);
        badge.title = `Angemeldet als: ${username}`;
    } else if (badge) {
        badge.style.display = "none";
    }
};

export const openAuthModal = () => {
    const modal = getAuthModal();
    if (modal) modal.style.display = "flex";
    updateUserBadge(null);
};

export const closeAuthModal = () => {
    const modal = getAuthModal();
    if (modal) modal.style.display = "none";
};

export const openSystemPromptModal = () => {
    if (!state.currentSessionId) return;
    const session = state.lastSessions?.find(s => s.id === state.currentSessionId);
    if (session) {
        const titleInput = document.getElementById("chat-title-input");
        if (titleInput) titleInput.value = session.title || "";
    }

    const exportSessionBtn = document.getElementById("export-session-btn");
    const importSessionBtn = document.getElementById("import-session-btn");
    const importStatusText = document.getElementById("import-status-text");

    if (exportSessionBtn) {
        exportSessionBtn.style.display = "inline-flex";
    }
    if (importSessionBtn) {
        const isNewChat = (!state.currentSessionHistory || state.currentSessionHistory.length === 0);
        importSessionBtn.style.display = isNewChat ? "inline-flex" : "none";
    }
    if (importStatusText) {
        importStatusText.style.display = "none";
        importStatusText.textContent = "";
    }
    
    const modal = getSystemPromptModal();
    if (modal) modal.style.display = "flex";
};

export const closeSystemPromptModal = () => {
    const modal = getSystemPromptModal();
    if (modal) modal.style.display = "none";
};
