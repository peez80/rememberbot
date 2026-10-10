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

export const importSessionArchive = async (sessionId, file, { onUploadProgress, signal } = {}) => {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `/api/sessions/${sessionId}/import`);

        if (signal) {
            if (signal.aborted) {
                const err = new Error("Import abgebrochen");
                err.name = "AbortError";
                return reject(err);
            }
            signal.addEventListener("abort", () => {
                xhr.abort();
                const err = new Error("Import abgebrochen");
                err.name = "AbortError";
                reject(err);
            });
        }

        if (xhr.upload && onUploadProgress) {
            xhr.upload.addEventListener("progress", (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    onUploadProgress(pct);
                }
            });
        }

        xhr.onload = () => {
            if (xhr.status === 401 && onAuthErrorHandler) {
                onAuthErrorHandler();
            }
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    resolve(data);
                } catch (_) {
                    resolve({ success: true });
                }
            } else {
                let detail = "Fehler beim Importieren des Chats.";
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (data && (data.detail || data.error)) {
                        detail = data.detail || data.error;
                    }
                } catch (_) {}
                reject(new Error(detail));
            }
        };

        xhr.onerror = () => reject(new Error("Verbindungsfehler beim Importieren des Archivs."));
        xhr.onabort = () => {
            const err = new Error("Import abgebrochen");
            err.name = "AbortError";
            reject(err);
        };

        const formData = new FormData();
        formData.append("file", file);
        xhr.send(formData);
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

export const exportSessionArchive = async (sessionId, signal) => {
    const res = await apiFetch(`/api/sessions/${sessionId}/export`, { signal });
    if (!res.ok) {
        let errorDetail = "Fehler beim Exportieren";
        try {
            const data = await res.json();
            if (data && data.detail) errorDetail = data.detail;
        } catch (_) {}
        throw new Error(errorDetail);
    }
    let filename = `chat_${sessionId}.zip`;
    const disposition = res.headers.get("content-disposition");
    if (disposition) {
        const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";\r\n]+)"?/i);
        if (match && match[1]) {
            filename = match[1].replace(/["']/g, "").trim();
        }
    }
    const blob = await res.blob();
    return { blob, filename };
};

