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
    authConfig: null
};

export function setCurrentSessionId(id) {
    state.currentSessionId = id;
    if (id) {
        localStorage.setItem("currentSessionId", id);
    } else {
        localStorage.removeItem("currentSessionId");
    }
}
