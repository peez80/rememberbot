/**
 * DOM utility functions for escaping, file typing, and size formatting.
 */

export const escapeHtml = (str) => {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
};

export const getFileIconClass = (fileName) => {
    if (!fileName) return 'ph-file';
    const ext = fileName.split('.').pop().toLowerCase();
    if (['pdf'].includes(ext)) return 'ph-file-pdf';
    if (['txt', 'md', 'rtf', 'log'].includes(ext)) return 'ph-file-text';
    if (['py', 'js', 'html', 'css', 'json', 'ts', 'java', 'c', 'cpp', 'sh', 'sql', 'yaml', 'yml'].includes(ext)) return 'ph-file-code';
    if (['csv', 'xlsx', 'xls'].includes(ext)) return 'ph-file-csv';
    if (['zip', 'tar', 'gz', '7z', 'rar'].includes(ext)) return 'ph-file-archive';
    if (['mp3', 'wav', 'ogg', 'm4a'].includes(ext)) return 'ph-file-audio';
    if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) return 'ph-file-video';
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) return 'ph-file-image';
    return 'ph-file';
};

export const formatFileSize = (bytes) => {
    if (!bytes && bytes !== 0) return '';
    if (bytes >= 1024 * 1024) {
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }
    if (bytes >= 1024) {
        return (bytes / 1024).toFixed(1) + ' KB';
    }
    return bytes + ' B';
};

export const isImageFile = (fileOrName) => {
    if (!fileOrName) return false;
    if (typeof fileOrName === 'object' && fileOrName.type && fileOrName.type.startsWith('image/')) return true;
    const name = typeof fileOrName === 'object' ? fileOrName.name : fileOrName;
    return /\.(jpe?g|png|webp|gif|bmp|svg)$/i.test(name || '') || name === 'blob';
};
