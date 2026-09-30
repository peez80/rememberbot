import pytest
from pydantic import ValidationError

from app.models.chat import ChatMessage, AttachmentMeta, ChatStreamEvent, ChatProcessResult
from app.models.session import SessionMetadata, SessionSettingsRequest, SessionTitleRequest, SessionCreateResponse
from app.models.auth import UserCredentials, AuthSessionData, AuthStatusResponse

def test_chat_message_model_defaults_and_validation():
    msg = ChatMessage(text="Hello world", is_user=True)
    assert msg.text == "Hello world"
    assert msg.is_user is True
    assert msg.image_urls == []
    assert msg.images is None
    assert msg.files is None
    assert msg.timestamp is None

    msg_with_data = ChatMessage(
        text="Photo",
        is_user=True,
        image_urls=["/uploads/123/pic.jpg"],
        images=[{"url": "/uploads/123/pic.jpg", "width": 800, "height": 600}],
        files=[{"name": "doc.pdf", "size": 1024, "is_image": False, "url": "/uploads/123/doc.pdf"}],
        timestamp="2026-08-26T12:00:00Z"
    )
    assert len(msg_with_data.images) == 1
    assert msg_with_data.files[0]["size"] == 1024

def test_attachment_meta():
    att = AttachmentMeta(name="data.csv", path="/app/data/data.csv", size=500, is_image=False)
    assert att.name == "data.csv"
    assert att.size == 500
    assert not att.is_image

def test_session_models():
    settings_req = SessionSettingsRequest(prompt="You are an assistant", include_gps=True)
    assert settings_req.prompt == "You are an assistant"
    assert settings_req.include_gps is True

    title_req = SessionTitleRequest(title="Updated title")
    assert title_req.title == "Updated title"

    meta = SessionMetadata(id="sess-123", title="My Chat", created_at="2026-08-26T12:00:00Z", has_icon=True)
    assert meta.id == "sess-123"
    assert meta.has_icon is True

def test_auth_models():
    auth_status = AuthStatusResponse(authenticated=True, username="alice")
    assert auth_status.authenticated is True
    assert auth_status.username == "alice"

    unauth = AuthStatusResponse(authenticated=False)
    assert unauth.authenticated is False
    assert unauth.username == ""
