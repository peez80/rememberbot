/**
 * Shared state for the RememberBot frontend application.
 */

export const state = {
    selectedFiles: [],
    currentSessionId: localStorage.getItem("currentSessionId"),
    currentSessionGpsEnabled: false,
    activeSubmittingSessionId: null,
    currentSessionHistory: [],
    currentRenderStartIndex: 0,
    isPrependingMessages: false,
    selectSessionCounter: 0,
    lastSessions: [],
    activePollTimers: new Map(),
    MESSAGE_BATCH_SIZE: 20
};

export function setCurrentSessionId(id) {
    state.currentSessionId = id;
    if (id) {
        localStorage.setItem("currentSessionId", id);
    } else {
        localStorage.removeItem("currentSessionId");
    }
}
