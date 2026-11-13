/**
 * Shared state for the RememberBot frontend application.
 */

export const state = {
    selectedFiles: [],
    currentSessionId: localStorage.getItem("currentSessionId"),
    currentSessionGpsEnabled: false,
    activeSubmittingSessionId: null,
    activeSubmissionsBySession: new Map(),
    activeStreamAbortController: null,
    streamWasHidden: false,
    recoveryWakeListeners: new Set(),
    recoveryResetRequested: false,
    pendingRecoverySessionId: null,
    currentSessionHistory: [],
    currentRenderStartIndex: 0,
    isPrependingMessages: false,
    selectSessionCounter: 0,
    activeSelectSessionPromise: null,
    activeSelectSessionId: null,
    lastSessions: [],
    activePollTimers: new Map(),
    activeIconPollTimers: new Map(),
    MESSAGE_BATCH_SIZE: 20,
    authConfig: null,
    pendingShortcutAction: null,
    shortcutSetupActive: false,
    shortcutErrorNotice: null
};

const PENDING_SHORTCUT_STORAGE_KEY = "rememberbot_pending_shortcut";
const PENDING_SHORTCUT_TTL_MS = 5 * 60 * 1000;

export function savePendingShortcut(action) {
    if (!action || !action.sessionId || !action.prompt) return;
    const payload = {
        sessionId: action.sessionId,
        prompt: action.prompt,
        autosend: Boolean(action.autosend),
        title: action.title || "",
        expiresAt: Date.now() + PENDING_SHORTCUT_TTL_MS
    };
    state.pendingShortcutAction = payload;
    try {
        localStorage.setItem(PENDING_SHORTCUT_STORAGE_KEY, JSON.stringify(payload));
    } catch (_) {}
}

export function peekPendingShortcut() {
    let payload = state.pendingShortcutAction;

    if (!payload) {
        try {
            const raw = localStorage.getItem(PENDING_SHORTCUT_STORAGE_KEY);
            if (raw) {
                payload = JSON.parse(raw);
            }
        } catch (_) {}
    }

    if (!payload || !payload.sessionId || !payload.prompt) {
        return null;
    }
    if (payload.expiresAt && Date.now() > payload.expiresAt) {
        return null;
    }
    return payload;
}

export function consumePendingShortcut() {
    const payload = peekPendingShortcut();
    state.pendingShortcutAction = null;

    try {
        localStorage.removeItem(PENDING_SHORTCUT_STORAGE_KEY);
    } catch (_) {}

    return payload;
}

export function setCurrentSessionId(id) {
    state.currentSessionId = id;
    if (id) {
        localStorage.setItem("currentSessionId", id);
    } else {
        localStorage.removeItem("currentSessionId");
    }
}
