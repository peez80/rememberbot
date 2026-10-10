/**
 * Modals component for auth and system prompt / settings dialogues.
 */

import { state } from '../state.js';
import { formatFileSize } from '../utils/dom.js';

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
        exportSessionBtn.disabled = false;
    }
    if (importSessionBtn) {
        const isNewChat = (!state.currentSessionHistory || state.currentSessionHistory.length === 0);
        importSessionBtn.style.display = isNewChat ? "inline-flex" : "none";
    }
    if (importStatusText) {
        importStatusText.style.display = "none";
        importStatusText.textContent = "";
    }
    const settingsErrorBanner = document.getElementById("settings-error-banner");
    if (settingsErrorBanner) {
        settingsErrorBanner.style.display = "none";
        settingsErrorBanner.textContent = "";
    }
    
    const modal = getSystemPromptModal();
    if (modal) modal.style.display = "flex";
};

export const closeSystemPromptModal = () => {
    const modal = getSystemPromptModal();
    if (modal) modal.style.display = "none";
};

export const getExportModal = () => document.getElementById("export-modal");
export const getExportModalTitle = () => document.getElementById("export-modal-title");
export const getExportStatusSpinner = () => document.getElementById("export-status-spinner");
export const getExportStatusMessage = () => document.getElementById("export-status-message");
export const getExportStatusDetail = () => document.getElementById("export-status-detail");
export const getExportCancelBtn = () => document.getElementById("export-cancel-btn");

export const openExportModal = () => {
    const modal = getExportModal();
    const title = getExportModalTitle();
    const spinner = getExportStatusSpinner();
    const msg = getExportStatusMessage();
    const detail = getExportStatusDetail();
    const cancelBtn = getExportCancelBtn();

    if (title) title.innerHTML = '<i class="ph-bold ph-download-simple"></i> Chat exportieren';
    if (spinner) spinner.style.display = "block";
    if (msg) {
        msg.textContent = "ZIP-Archiv wird vorbereitet...";
        msg.classList.remove("export-status-error");
    }
    if (detail) {
        detail.textContent = "Dies kann bei umfangreichen Chats und Bildern einen Moment dauern.";
        detail.style.display = "block";
    }
    if (cancelBtn) {
        cancelBtn.textContent = "Abbrechen";
        cancelBtn.classList.remove("primary-btn");
        cancelBtn.classList.add("secondary-btn");
    }
    if (modal) modal.style.display = "flex";
};

export const closeExportModal = () => {
    const modal = getExportModal();
    if (modal) modal.style.display = "none";
};

export const updateExportModalStatus = ({ title, message, detail, isError = false, showSpinner = true, buttonText = "Abbrechen" }) => {
    const titleEl = getExportModalTitle();
    const spinnerEl = getExportStatusSpinner();
    const msgEl = getExportStatusMessage();
    const detailEl = getExportStatusDetail();
    const btnEl = getExportCancelBtn();

    if (title && titleEl) titleEl.innerHTML = title;
    if (spinnerEl) spinnerEl.style.display = showSpinner ? "block" : "none";
    if (msgEl && message !== undefined) {
        msgEl.textContent = message;
        if (isError) {
            msgEl.classList.add("export-status-error");
        } else {
            msgEl.classList.remove("export-status-error");
        }
    }
    if (detailEl) {
        if (detail) {
            detailEl.textContent = detail;
            detailEl.style.display = "block";
        } else {
            detailEl.style.display = "none";
        }
    }
    if (btnEl && buttonText) {
        btnEl.textContent = buttonText;
    }
};

export const getImportModal = () => document.getElementById("import-modal");
export const getImportCancelBtn = () => document.getElementById("import-cancel-btn");
export const getImportFileInfo = () => document.getElementById("import-modal-file-info");
export const getImportErrorBanner = () => document.getElementById("import-modal-error-banner");
export const getImportModalTitle = () => document.getElementById("import-modal-title");

export const setImportStepStatus = (stepKey, state, statusText) => {
    const stepEl = document.getElementById(`import-step-${stepKey}`);
    const iconEl = document.getElementById(`import-step-${stepKey}-icon`);
    const statusEl = document.getElementById(`import-step-${stepKey}-status`);

    if (!stepEl || !iconEl || !statusEl) return;

    if (state === 'waiting') {
        stepEl.className = 'import-step-item';
        iconEl.innerHTML = '<i class="ph-bold ph-circle" style="color: var(--text-muted);"></i>';
        if (statusText) statusEl.textContent = statusText;
        statusEl.style.color = 'var(--text-muted)';
    } else if (state === 'active') {
        stepEl.className = 'import-step-item active';
        iconEl.innerHTML = '<i class="ph-bold ph-spinner ph-spin" style="color: var(--primary-color);"></i>';
        if (statusText) statusEl.textContent = statusText;
        statusEl.style.color = 'var(--primary-color)';
    } else if (state === 'done') {
        stepEl.className = 'import-step-item done';
        iconEl.innerHTML = '<i class="ph-bold ph-check-circle" style="color: #10b981;"></i>';
        if (statusText) statusEl.textContent = statusText;
        statusEl.style.color = '#10b981';
    } else if (state === 'error') {
        stepEl.className = 'import-step-item error';
        iconEl.innerHTML = '<i class="ph-bold ph-warning-circle" style="color: #ef4444;"></i>';
        if (statusText) statusEl.textContent = statusText;
        statusEl.style.color = '#ef4444';
    }
};

export const openImportModal = (fileName, fileSize) => {
    const modal = getImportModal();
    const title = getImportModalTitle();
    const fileInfo = getImportFileInfo();
    const errorBanner = getImportErrorBanner();
    const cancelBtn = getImportCancelBtn();

    if (title) title.innerHTML = '<i class="ph-bold ph-upload-simple"></i> Chat importieren';
    if (fileInfo && fileName) {
        fileInfo.textContent = fileSize ? `${fileName} (${formatFileSize(fileSize)})` : fileName;
    }
    if (errorBanner) {
        errorBanner.style.display = 'none';
        errorBanner.textContent = '';
    }
    if (cancelBtn) {
        cancelBtn.textContent = 'Abbrechen';
        cancelBtn.classList.remove('primary-btn');
        cancelBtn.classList.add('secondary-btn');
    }

    setImportStepStatus('upload', 'waiting', 'Warten...');
    setImportStepStatus('verify', 'waiting', 'Warten...');
    setImportStepStatus('restore', 'waiting', 'Warten...');
    setImportStepStatus('finalize', 'waiting', 'Warten...');

    if (modal) modal.style.display = 'flex';
};

export const setImportModalError = (errorMessage) => {
    const errorBanner = getImportErrorBanner();
    const cancelBtn = getImportCancelBtn();
    if (errorBanner) {
        errorBanner.style.display = 'block';
        errorBanner.textContent = errorMessage;
    }
    if (cancelBtn) {
        cancelBtn.textContent = 'Schließen';
    }
};

export const closeImportModal = () => {
    const modal = getImportModal();
    if (modal) modal.style.display = 'none';
};


