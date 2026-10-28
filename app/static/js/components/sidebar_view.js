/**
 * Sidebar component for rendering session list, handling selection, deletions, and swipe gestures.
 */

import { escapeHtml } from '../utils/dom.js';
import { state } from '../state.js';
import { initSwipeListener } from '../utils/gestures.js';

export const updateActiveSessionHighlight = (activeId) => {
    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === activeId);
    });
};

export const isSidebarOpen = () => {
    const sidebar = document.getElementById("sidebar");
    return !!(sidebar && sidebar.classList.contains("open"));
};

export const openSidebar = () => {
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (sidebar) {
        sidebar.classList.add("open");
    }
    if (backdrop) {
        backdrop.classList.add("active");
    }
};

export const closeSidebar = () => {
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (sidebar) {
        sidebar.classList.remove("open");
    }
    if (backdrop) {
        backdrop.classList.remove("active");
    }
};

export const toggleSidebar = () => {
    if (isSidebarOpen()) {
        closeSidebar();
    } else {
        openSidebar();
    }
};

export const initSidebarSwipeGestures = () => {
    return initSwipeListener(document, {
        threshold: 50,
        maxVerticalRatio: 0.8,
        maxDurationMs: 800,
        shouldIgnoreTarget: (el) => {
            if (window.innerWidth > 768) return true;

            const activeModal = document.querySelector('.modal-overlay:not([style*="display: none"])');
            if (activeModal) return true;

            if (el.closest('input, textarea, select, button, label.icon-button')) {
                return true;
            }

            const pre = el.closest('pre');
            if (pre && pre.scrollWidth > pre.clientWidth) {
                return true;
            }

            return false;
        },
        onSwipeRight: () => {
            if (window.innerWidth <= 768 && !isSidebarOpen()) {
                openSidebar();
            }
        },
        onSwipeLeft: () => {
            if (window.innerWidth <= 768 && isSidebarOpen()) {
                closeSidebar();
            }
        }
    });
};

export const renderSessionList = (sessions, onSelectSession, onDeleteSession) => {
    state.lastSessions = sessions;
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

        const safeSessionId = encodeURIComponent(session.id || '');
        const iconHtml = session.has_icon 
            ? `<img class="session-list-icon" src="/api/sessions/${safeSessionId}/icon?t=${Date.now()}">`
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
