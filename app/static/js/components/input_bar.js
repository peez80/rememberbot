/**
 * Input bar component for textarea auto-resize, preview cards, file drag-and-drop, and paste.
 */

import { isImageFile, getFileIconClass, formatFileSize } from '../utils/dom.js';
import { compressImage } from '../utils/image.js';
import { state } from '../state.js';

export const getImagePreviewContainer = () => document.getElementById("image-preview-container");
export const getMessageInput = () => document.getElementById("message-input");

export const updatePreviewUI = () => {
    const container = getImagePreviewContainer();
    if (!container) return;

    container.innerHTML = '';
    if (state.selectedFiles.length > 0) {
        container.style.display = "flex";
        state.selectedFiles.forEach((file, index) => {
            const isImg = isImageFile(file);
            if (isImg) {
                const itemDiv = document.createElement("div");
                itemDiv.className = "preview-item";

                const img = document.createElement("img");
                const blobUrl = URL.createObjectURL(file);
                img.src = blobUrl;
                img.alt = "Vorschau";

                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "remove-image-btn";
                btn.innerHTML = '<i class="ph-bold ph-x"></i>';
                btn.title = "Entfernen";
                btn.onclick = () => {
                    URL.revokeObjectURL(blobUrl);
                    state.selectedFiles.splice(index, 1);
                    updatePreviewUI();
                };

                itemDiv.appendChild(img);
                itemDiv.appendChild(btn);
                container.appendChild(itemDiv);
            } else {
                const cardDiv = document.createElement("div");
                cardDiv.className = "preview-file-card";

                const icon = document.createElement("i");
                icon.className = `ph-bold ${getFileIconClass(file.name)} preview-file-icon`;

                const details = document.createElement("div");
                details.className = "preview-file-details";

                const nameSpan = document.createElement("span");
                nameSpan.className = "preview-file-name";
                nameSpan.textContent = file.name || "Datei";
                nameSpan.title = file.name || "Datei";

                const sizeSpan = document.createElement("span");
                sizeSpan.className = "preview-file-size";
                sizeSpan.textContent = formatFileSize(file.size);

                details.appendChild(nameSpan);
                details.appendChild(sizeSpan);

                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "remove-image-btn";
                btn.innerHTML = '<i class="ph-bold ph-x"></i>';
                btn.title = "Entfernen";
                btn.onclick = () => {
                    state.selectedFiles.splice(index, 1);
                    updatePreviewUI();
                };

                cardDiv.appendChild(icon);
                cardDiv.appendChild(details);
                cardDiv.appendChild(btn);
                container.appendChild(cardDiv);
            }
        });
    } else {
        container.style.display = "none";
    }
};

export const addFilesToList = async (rawFiles) => {
    if (state.selectedFiles.length + rawFiles.length > 10) {
        alert("Du kannst maximal 10 Dateien auf einmal senden.");
        return;
    }

    const startIndex = state.selectedFiles.length;
    state.selectedFiles = [...state.selectedFiles, ...rawFiles];
    updatePreviewUI();
    const msgInput = getMessageInput();
    if (msgInput) msgInput.focus();

    try {
        const processedFiles = await Promise.all(rawFiles.map(f => isImageFile(f) ? compressImage(f) : f));
        for (let i = 0; i < processedFiles.length; i++) {
            if (state.selectedFiles[startIndex + i] === rawFiles[i]) {
                state.selectedFiles[startIndex + i] = processedFiles[i];
            }
        }
    } catch (err) {
        console.warn("Async compression error, keeping raw files", err);
    }
};

export const handleFileSelection = async (e, ...inputsToClear) => {
    if (e.target && e.target.files && e.target.files.length > 0) {
        await addFilesToList(Array.from(e.target.files));
        inputsToClear.forEach(input => { if (input) input.value = ""; });
        if (e.target) e.target.value = "";
    }
};

export const setupInputAutoResize = () => {
    const msgInput = getMessageInput();
    if (!msgInput) return;

    msgInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.scrollHeight > 150) {
            this.style.overflowY = 'auto';
        } else {
            this.style.overflowY = 'hidden';
        }
    });

    msgInput.addEventListener('keydown', function(e) {
        const isMobile = window.innerWidth <= 768 || /Mobi|Android/i.test(navigator.userAgent);
        if (e.key === 'Enter') {
            if (!isMobile && !e.shiftKey) {
                e.preventDefault();
                const sendBtn = document.getElementById('send-btn');
                if (sendBtn) sendBtn.click();
            }
        }
    });
};

export const setupDragAndDrop = (targets) => {
    targets.forEach(target => {
        if (!target) return;
        ['dragenter', 'dragover'].forEach(eventName => {
            target.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                target.classList.add('drag-over');
            });
        });
        ['dragleave', 'drop'].forEach(eventName => {
            target.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                target.classList.remove('drag-over');
            });
        });
        target.addEventListener('drop', (e) => {
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                addFilesToList(Array.from(e.dataTransfer.files));
            }
        });
    });
};

export const setupPaste = () => {
    document.addEventListener('paste', (e) => {
        if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length > 0) {
            addFilesToList(Array.from(e.clipboardData.files));
        }
    });
};
