import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_index_contains_scroll_to_bottom_button():
    """Verify that index.html contains the scroll-to-bottom button with icon."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="scroll-to-bottom-btn"' in response.text
    assert 'ph-arrow-down' in response.text


def test_styles_contains_scroll_button_css():
    """Verify that styles.css contains rules for .scroll-to-bottom-btn."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert '.scroll-to-bottom-btn' in response.text
    assert 'position:' in response.text


def test_app_js_contains_scroll_button_logic():
    """Verify that frontend modules contain logic for scroll-to-bottom button."""
    response = client.get("/static/js/components/chat_view.js")
    if response.status_code == 404:
        response = client.get("/static/app.js")
    assert response.status_code == 200
    assert 'scroll-to-bottom-btn' in response.text or 'scrollToBottom' in response.text
    assert 'checkScrollPosition' in response.text or 'scrollTop' in response.text
