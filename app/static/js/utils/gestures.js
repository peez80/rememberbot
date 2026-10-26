/**
 * Touch gesture utilities for mobile interactions.
 */

export const initSwipeListener = (target, {
    onSwipeLeft,
    onSwipeRight,
    threshold = 50,
    maxVerticalRatio = 0.8,
    maxDurationMs = 800,
    shouldIgnoreTarget = null,
} = {}) => {
    let startX = 0;
    let startY = 0;
    let startTime = 0;
    let isTracking = false;

    const onTouchStart = (e) => {
        if (!e.touches || e.touches.length !== 1) {
            isTracking = false;
            return;
        }

        const targetEl = e.target;
        if (typeof shouldIgnoreTarget === 'function' && shouldIgnoreTarget(targetEl)) {
            isTracking = false;
            return;
        }

        const touch = e.touches[0];
        startX = touch.clientX;
        startY = touch.clientY;
        startTime = Date.now();
        isTracking = true;
    };

    const onTouchEnd = (e) => {
        if (!isTracking) return;
        isTracking = false;

        if (!e.changedTouches || e.changedTouches.length === 0) return;
        const touch = e.changedTouches[0];
        const deltaX = touch.clientX - startX;
        const deltaY = touch.clientY - startY;
        const duration = Date.now() - startTime;

        if (duration > maxDurationMs) return;

        const absX = Math.abs(deltaX);
        const absY = Math.abs(deltaY);

        if (absX < threshold) return;
        if (absY / absX > maxVerticalRatio) return;

        if (deltaX > 0 && typeof onSwipeRight === 'function') {
            onSwipeRight(e);
        } else if (deltaX < 0 && typeof onSwipeLeft === 'function') {
            onSwipeLeft(e);
        }
    };

    const onTouchCancel = () => {
        isTracking = false;
    };

    target.addEventListener('touchstart', onTouchStart, { passive: true });
    target.addEventListener('touchend', onTouchEnd, { passive: true });
    target.addEventListener('touchcancel', onTouchCancel, { passive: true });

    return () => {
        target.removeEventListener('touchstart', onTouchStart);
        target.removeEventListener('touchend', onTouchEnd);
        target.removeEventListener('touchcancel', onTouchCancel);
    };
};
