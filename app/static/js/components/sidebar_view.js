/**
 * Sidebar component for rendering session list, handling selection and deletions.
 */

import { escapeHtml } from '../utils/dom.js';
import { state } from '../state.js';

export const updateActiveSessionHighlight = (activeId) => {
    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === activeId);
    });
};

export const toggleSidebar = () => {
    const sidebar = document.getElementById("sidebar");
    if (sidebar) {
        sidebar.classList.toggle("open");
    }
};

export const renderSessionList = (sessions, onSelectSession, onDeleteSession) => {
    state.lastSessions = sessions;
    window.lastSessions = sessions;
    const sessionList = document.getElementById("session-list");
    if (!sessionList) return;

    sessionList.innerHTML = '';
    sessions.forEach(session => {
        const div = document.createElement("div");
        div.className = `session-item ${session.id === state.currentSessionId ? "active" : ""}`;
        div.dataset.sessionId = session.id;

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
                <div class="session-date">${escapeHtml(dateStr || "Neu")}</div>
                <div class="session-title">${escapeHtml(session.title)}</div>
            </div>
            <button class="icon-button danger delete-btn" title="Chat löschen">
                <i class="ph-bold ph-trash"></i>
            </button>
        `;

        div.addEventListener("click", () => onSelectSession(session.id));

        const deleteBtn = div.querySelector('.delete-btn');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onDeleteSession(session);
        });

        sessionList.appendChild(div);
    });
};
