/**
 * Client-side image compression & optimization to prevent mobile OOM.
 */

import { isImageFile } from './dom.js';

export const compressImage = async (file, maxDimension = 1920, quality = 0.85) => {
    if (!isImageFile(file)) return file;

    return new Promise((resolve) => {
        let settled = false;
        let url = "";

        const timeoutId = setTimeout(() => {
            if (!settled) {
                settled = true;
                try { if (url) URL.revokeObjectURL(url); } catch (_) {}
                resolve(file);
            }
        }, 3000);

        try {
            url = URL.createObjectURL(file);
        } catch (_) {
            clearTimeout(timeoutId);
            resolve(file);
            return;
        }

        const img = new Image();

        img.onload = () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeoutId);
            try { URL.revokeObjectURL(url); } catch (_) {}
            
            try {
                let { width, height } = img;
                if (width <= maxDimension && height <= maxDimension && file.size < 1024 * 1024) {
                    resolve(file);
                    return;
                }

                if (width > maxDimension || height > maxDimension) {
                    if (width > height) {
                        height = Math.round((height * maxDimension) / width);
                        width = maxDimension;
                    } else {
                        width = Math.round((width * maxDimension) / height);
                        height = maxDimension;
                    }
                }

                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext("2d");
                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob(
                    (blob) => {
                        if (blob) {
                            const originalName = file.name || "photo.jpg";
                            const newFileName = originalName.replace(/\.[^/.]+$/, "") + ".jpg";
                            const compressedFile = new File([blob], newFileName, {
                                type: "image/jpeg",
                                lastModified: Date.now()
                            });
                            resolve(compressedFile);
                        } else {
                            resolve(file);
                        }
                    },
                    "image/jpeg",
                    quality
                );
            } catch (e) {
                resolve(file);
            }
        };

        img.onerror = () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeoutId);
            try { URL.revokeObjectURL(url); } catch (_) {}
            resolve(file);
        };

        img.src = url;
    });
};
