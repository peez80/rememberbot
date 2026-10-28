/**
 * SSE streaming response consumer using the Fetch ReadableStream API.
 */

export const readSSEStream = async (response, { onDelta, onDone, onError, onDisconnect, onQueued, onProcessing }) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = "";
    let receivedTerminalEvent = false;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split("\n");
            sseBuffer = lines.pop(); // keep partial trailing line

            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith("data: ")) {
                    try {
                        const event = JSON.parse(trimmed.slice(6));
                        if (event.type === "delta") {
                            if (onDelta) onDelta(event);
                        } else if (event.type === "queued") {
                            if (onQueued) onQueued(event);
                        } else if (event.type === "processing") {
                            if (onProcessing) onProcessing(event);
                        } else if (event.type === "done") {
                            receivedTerminalEvent = true;
                            if (onDone) onDone(event);
                        } else if (event.type === "error") {
                            receivedTerminalEvent = true;
                            if (onError) onError(event);
                        }
                    } catch (e) {
                        console.warn("Error parsing SSE event:", e, trimmed);
                    }
                }
            }
        }
        if (!receivedTerminalEvent && onDisconnect) {
            onDisconnect(new Error("SSE stream closed before completion"));
        }
    } catch (err) {
        if (onDisconnect) {
            onDisconnect(err);
        } else if (onError) {
            onError({ error: err.message });
        }
    }
};

