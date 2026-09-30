import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_app_js_contains_lazy_loading_attributes():
    """Verify that frontend modules set loading='lazy' and decoding='async' on chat images."""
    response = client.get("/static/js/components/chat_view.js")
    if response.status_code == 404:
        response = client.get("/static/app.js")
    assert response.status_code == 200
    assert 'loading = "lazy"' in response.text or "loading = 'lazy'" in response.text or 'loading = "lazy"' in response.text
    assert 'decoding = "async"' in response.text or "decoding = 'async'" in response.text or 'decoding = "async"' in response.text


def test_styles_css_contains_image_loading_placeholder():
    """Verify that styles.css contains rules for chat image lazy loading background/dimensions."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert ".chat-image" in response.text
    # Verify presence of loading background style or min-height/aspect ratio
    assert "background-color:" in response.text or "background:" in response.text
