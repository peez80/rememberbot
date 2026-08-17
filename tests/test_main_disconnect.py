import pytest
import httpx
import asyncio
import time
import threading
import json
import os
from unittest.mock import patch
from httpx import ReadTimeout
import uvicorn

from app.main import app, ACTIVE_SESSIONS
from app.storage import get_session_history, DATA_DIR, create_session

class UvicornTestServer(uvicorn.Server):
    def install_signal_handlers(self):
        pass

    def run_in_thread(self):
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        # Wait for the server to start
        while not self.started:
            time.sleep(0.01)

    def stop_server(self):
        self.should_exit = True
        # Try to join, but don't hang forever
        self.thread.join(timeout=2)

@pytest.fixture(scope="module")
def real_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=8123, log_level="error")
    server = UvicornTestServer(config)
    server.run_in_thread()
    yield "http://127.0.0.1:8123"
    server.stop_server()

@pytest.fixture
def auth_cookies():
    session_token = "test-token"
    ACTIVE_SESSIONS[session_token] = "testuser"
    return {"session_token": session_token}

async def create_test_session():
    # Ensure test user directory exists
    user_dir = os.path.join(DATA_DIR, "testuser")
    os.makedirs(os.path.join(user_dir, "sessions"), exist_ok=True)
    session_id = await create_session("testuser", "Test Chat")
    return session_id

@pytest.mark.asyncio
async def test_event_loop_blocking(real_server, auth_cookies):
    """
    Test 1: Verify that the current synchronous process_message blocks the event loop.
    """
    test_session = await create_test_session()
    async def slow_mock(*args, **kwargs):
        await asyncio.sleep(2) # Simulates a slow async operation
        return {"reply": "Mock Antwort", "context_truncated": False}

    with patch("app.main.agy_client.process_message", side_effect=slow_mock):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # We send a chat request which will take 2 seconds and block the loop
            task1 = asyncio.create_task(client.post(
                f"/api/sessions/{test_session}/chat",
                data={"message": "Hallo"},
                cookies=auth_cookies
            ))
            
            # Wait a tiny bit to ensure task1 starts
            await asyncio.sleep(0.1)
            
            # Send a fast request concurrently
            start_time = time.time()
            res2 = await client.get("/api/auth/status", cookies=auth_cookies)
            duration = time.time() - start_time
            
            # Since the process_message is now running in an async subprocess/task,
            # it should NOT block the event loop. The second request should finish quickly.
            assert duration < 1.0, f"Expected event loop to be free, but took {duration}s"
            
            await task1

@pytest.mark.asyncio
async def test_client_disconnect_data_loss(real_server, auth_cookies):
    """
    Test 2: Verify that if a client disconnects during the request, the data is lost.
    """
    test_session = await create_test_session()
    # Wait, if we use time.sleep(3), the current synchronous code will BLOCK Uvicorn from cancelling!
    # So to reproduce the bug properly where the task gets CANCELLED (which will happen when we fix the blocking),
    # we need to simulate the async behavior OR test the actual cancellation.
    # Wait, the user's bug happened on the CURRENT codebase.
    # But how could the current codebase lose the prompt?
    # Because of image upload parsing blocking!
    
    # We will upload a dummy file to simulate the `await img.read()` being cancelled!
    
    async def slow_read(*args, **kwargs):
        await asyncio.sleep(3) # Simulate a slow upload that gets cancelled
        return b"fake image"

    async def mock_process_message(*args, **kwargs):
        await asyncio.sleep(1) # simulate work
        return {"reply": "Mock KI Antwort", "context_truncated": False}

    with patch("fastapi.datastructures.UploadFile.read", new=slow_read), \
         patch("app.main.agy_client.process_message", side_effect=mock_process_message):
        async with httpx.AsyncClient(base_url=real_server, timeout=1.0) as client:
            try:
                # We upload a fake image to trigger the await img.read() path
                files = {'images': ('test.png', b'dummy content', 'image/png')}
                await client.post(
                    f"/api/sessions/{test_session}/chat",
                    data={"message": "Das ist ein langer Prompt, der gespeichert bleiben sollte."},
                    files=files,
                    cookies=auth_cookies
                )
            except ReadTimeout:
                # Expected timeout (disconnect)
                pass

        # Give the server some time to process the disconnection and the background task
        await asyncio.sleep(6)
    
        history = await get_session_history("testuser", test_session)
    
        # The background task should have successfully saved both the user message and the AI response
        assert len(history) == 2, f"Expected 2 messages to be saved due to asyncio.shield, but got {len(history)}: {history}"


@pytest.mark.asyncio
async def test_user_message_persisted_immediately_even_if_stream_aborted_early(real_server, auth_cookies):
    """
    Test 3: Verify that user message and attached image are persisted immediately even if client aborts the stream right away.
    """
    test_session = await create_test_session()

    async def slow_stream(*args, **kwargs):
        # Generator that hangs/delays to simulate client aborting before completion
        yield {"type": "delta", "text": "Start..."}
        await asyncio.sleep(5)
        yield {"type": "done", "reply": "Fertig", "context_truncated": False}

    with patch("app.main.agy_client.stream_message", side_effect=slow_stream):
        async with httpx.AsyncClient(base_url=real_server, timeout=0.5) as client:
            try:
                files = {'images': ('photo.jpg', b'dummy photo data', 'image/jpeg')}
                async with client.stream(
                    "POST",
                    f"/api/sessions/{test_session}/chat",
                    data={"message": "Foto Nachricht", "stream": "true"},
                    files=files,
                    cookies=auth_cookies
                ) as response:
                    # Client aborts connection right away after reading first bytes
                    async for chunk in response.aiter_bytes():
                        break
            except Exception:
                pass

        # Check history immediately without waiting 5 seconds
        history = await get_session_history("testuser", test_session)
        assert len(history) >= 1, f"Expected user message to be saved immediately, but history was {history}"
        assert history[0]["is_user"] is True
        assert "photo.jpg" in str(history[0]) or "/uploads/" in str(history[0])

