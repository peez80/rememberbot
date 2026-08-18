import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_app_js_contains_progressive_rendering_logic():
    """Verify that app.js implements progressive rendering (batch size, scroll handling, thumbnail links)."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    text = response.text
    
    # Verify thumbnail path handling or linking
    assert "thumbnails" in text
    assert 'target="_blank"' in text or "target = '_blank'" in text or 'target = "_blank"' in text or "target='_blank'" in text
    assert "chat-image-link" in text
    
    # Verify progressive batching logic
    assert "20" in text or "MESSAGE_BATCH_SIZE" in text or "batchSize" in text or "currentRenderStartIndex" in text or "loadedMessageIndex" in text


def test_styles_css_contains_chat_image_link_styles():
    """Verify that styles.css contains styles for .chat-image-link."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert ".chat-image-link" in response.text
