import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_index_contains_header_chat_title_and_icon():
    """Verify that index.html contains the header title element and icon element."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="header-chat-title"' in response.text
    assert 'id="header-chat-icon"' in response.text


def test_styles_contains_header_title_and_icon_css():
    """Verify that styles.css contains rules for .chat-title-icon, .session-list-icon, and ellipsis in .header-title h1."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert '.chat-title-icon' in response.text
    assert '.session-list-icon' in response.text
    assert 'text-overflow: ellipsis' in response.text or 'ellipsis' in response.text


def test_app_js_contains_header_title_and_icon_logic():
    """Verify that app.js contains logic for updating header title and icon."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert 'header-chat-title' in response.text
    assert 'header-chat-icon' in response.text
