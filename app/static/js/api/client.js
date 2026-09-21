/**
 * API client for interacting with RememberBot backend routes.
 */

let onAuthErrorHandler = null;

export const setAuthErrorHandler = (handler) => {
    onAuthErrorHandler = handler;
};

const originalFetch = window.fetch;

export const apiFetch = async (url, options = {}) => {
    const response = await originalFetch(url, options);
    if (response.status === 401 && !url.includes('/api/auth/status') && !url.includes('/api/auth/login') && !url.includes('/models/catalog')) {
        if (onAuthErrorHandler) {
            onAuthErrorHandler();
        }
    }
    return response;
};

// Also wrap window.fetch globally for backward compatibility
window.fetch = apiFetch;

export const checkAuthStatus = async () => {
    const res = await originalFetch("/api/auth/status");
    return res.json();
};

export const login = async (username, password) => {
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    return originalFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString()
    });
};

export const logout = async () => {
    return originalFetch("/api/auth/logout", { method: "POST" });
};

export const getSessions = async () => {
    const res = await apiFetch("/api/sessions");
    if (!res.ok) throw new Error("Failed to fetch sessions");
    return res.json();
};

export const createSession = async () => {
    const res = await apiFetch("/api/sessions", { method: "POST" });
    if (!res.ok) throw new Error("Failed to create session");
    return res.json();
};

export const deleteSession = async (sessionId) => {
    return apiFetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
};

export const getSessionSettings = async (sessionId) => {
    return apiFetch(`/api/sessions/${sessionId}/settings`);
};

export const getModelsCatalog = async () => {
    return apiFetch(`/api/sessions/models/catalog`);
};

export const getSessionHistory = async (sessionId) => {
    return apiFetch(`/api/sessions/${sessionId}/history`);
};

export const getSessionStatus = async (sessionId) => {
    return apiFetch(`/api/sessions/${sessionId}/status`);
};

export const updateSessionSettings = async (sessionId, { prompt, include_gps, model, thinking_effort }) => {
    return apiFetch(`/api/sessions/${sessionId}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, include_gps, model, thinking_effort })
    });
};

export const updateSessionTitle = async (sessionId, title) => {
    return apiFetch(`/api/sessions/${sessionId}/title`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title })
    });
};

export const importSessionArchive = async (sessionId, file) => {
    const formData = new FormData();
    formData.append("file", file);

    return apiFetch(`/api/sessions/${sessionId}/import`, {
        method: "POST",
        body: formData
    });
};

export const sendChatMessage = async (sessionId, formData) => {
    return apiFetch(`/api/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: {
            "Accept": "text/event-stream, application/json"
        },
        body: formData
    });
};
