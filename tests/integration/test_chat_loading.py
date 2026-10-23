import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_index_contains_chat_loading_overlay():
    """Verify that index.html contains the chat loading overlay with spinner and text."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="chat-loading-overlay"' in response.text
    assert 'chat-loading-spinner' in response.text
    assert 'Chat wird geladen...' in response.text


def test_styles_contains_chat_loading_css():
    """Verify that styles.css contains rules for .chat-loading-overlay and spinner."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert '.chat-loading-overlay' in response.text
    assert '.chat-loading-overlay.visible' in response.text
    assert '.chat-loading-spinner' in response.text


def test_chat_view_exports_loading_functions():
    """Verify that chat_view.js exports showChatLoading and hideChatLoading."""
    response = client.get("/static/js/components/chat_view.js")
    assert response.status_code == 200
    assert 'export const showChatLoading' in response.text or 'export function showChatLoading' in response.text
    assert 'export const hideChatLoading' in response.text or 'export function hideChatLoading' in response.text
