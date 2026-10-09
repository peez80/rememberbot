import pytest
from playwright.async_api import async_playwright

@pytest.mark.asyncio
async def test_frontend_formatters_js_quoted_tags_in_browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        with open("app/static/js/utils/formatters.js", "r", encoding="utf-8") as f:
            js_code = f.read()
        res = await page.evaluate("""(code) => {
            // Transform export const into local variable
            const cleanCode = code.replace(/export const /g, 'const ');
            const run = new Function(cleanCode + '; return formatThoughtBlocks;');
            const formatThoughtBlocks = run();
            const raw = "<thinking>\\nRegeln beachten:\\n- Gedanken in `<thinking>` und `</thinking>` Tags am Anfang. - Kurz und prägnant antworten.\\nHier ist mein eigentlicher Plan.\\n</thinking>\\nHier ist die finale Antwort.";
            return formatThoughtBlocks(raw);
        }""", js_code)
        assert "<details class='ai-reasoning'>" in res
        parts = res.split("</details>")
        assert len(parts) == 2
        assert "Tags am Anfang" not in parts[1]
        assert parts[1].strip() == "Hier ist die finale Antwort."


@pytest.mark.asyncio
async def test_chat_view_streaming_preserves_user_opened_thinking_in_browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.add_script_tag(url='https://cdn.jsdelivr.net/npm/marked/marked.min.js')
        await page.add_script_tag(url='https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js')
        with open("app/static/js/utils/formatters.js", "r", encoding="utf-8") as f:
            fmt_code = f.read()
        with open("app/static/js/components/chat_view.js", "r", encoding="utf-8") as f:
            cv_code = f.read()

        res = await page.evaluate("""([fmtCode, cvCode]) => {
            // Setup DOM structure
            document.body.innerHTML = '<main class="chat-container" id="chat-container"></main>';
            
            // Clean module exports for browser eval
            const cleanFmt = fmtCode.replace(/export const /g, 'const ');
            const fmtRun = new Function(cleanFmt + '; return { formatThoughtBlocks, enhanceMarkdownLinksAndImages, attachDownloadButtons };');
            const { formatThoughtBlocks, enhanceMarkdownLinksAndImages, attachDownloadButtons } = fmtRun();
            
            let cleanCv = cvCode
                .replace(/import .*;\\n/g, '')
                .replace(/export const /g, 'const ');
            
            const cvRun = new Function(
                'formatThoughtBlocks', 'enhanceMarkdownLinksAndImages', 'attachDownloadButtons',
                cleanCv + '; return { initStreamingMessage, updateStreamingMessage, finalizeStreamingMessage };'
            );
            const { initStreamingMessage, updateStreamingMessage, finalizeStreamingMessage } = cvRun(
                formatThoughtBlocks, enhanceMarkdownLinksAndImages, attachDownloadButtons
            );

            const controller = initStreamingMessage();

            // 1. Thinking phase
            updateStreamingMessage(controller, "<thinking>Erster Schritt");
            const thinkingDetails = controller.textDiv.querySelector("details.ai-reasoning");
            const wasOpenDuringThinking = thinkingDetails ? thinkingDetails.open : false;

            // 2. Thought finishes, answer starts
            updateStreamingMessage(controller, "<thinking>Erster Schritt</thinking>Die Antwort lautet: ");
            const closedDetails = controller.textDiv.querySelector("details.ai-reasoning");
            const closedAfterThinking = closedDetails ? closedDetails.open : true;

            // 3. User clicks to open the thinking box
            const summary = closedDetails.querySelector("summary");
            summary.click();

            return new Promise(resolve => {
                setTimeout(() => {
                    const openedByUser = controller.textDiv.querySelector("details.ai-reasoning").open;

                    // 4. Stream 5 more tokens of the answer
                    for (let i = 0; i < 5; i++) {
                        updateStreamingMessage(controller, "<thinking>Erster Schritt</thinking>Die Antwort lautet: Teil " + i);
                    }
                    const stillOpenAfterStream = controller.textDiv.querySelector("details.ai-reasoning").open;

                    // 5. Finalize
                    finalizeStreamingMessage(controller, "<thinking>Erster Schritt</thinking>Die Antwort lautet: Fertig!");
                    const stillOpenAfterFinalize = controller.textDiv.querySelector("details.ai-reasoning").open;

                    resolve({
                        wasOpenDuringThinking,
                        closedAfterThinking,
                        openedByUser,
                        stillOpenAfterStream,
                        stillOpenAfterFinalize
                    });
                }, 10);
            });
        }""", [fmt_code, cv_code])

        assert res["wasOpenDuringThinking"] is True
        assert res["closedAfterThinking"] is False
        assert res["openedByUser"] is True
        assert res["stillOpenAfterStream"] is True
        assert res["stillOpenAfterFinalize"] is True
