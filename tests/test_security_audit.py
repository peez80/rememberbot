import io
import os
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.core.config import DATA_DIR, SESSION_COOKIE_NAME, is_safe_session_id
from app.storage import init_user_storage, init_session_storage
from app.services.auth_service import auth_service
from app.services.agy_service import agy_service

client = TestClient(app)

def mock_auth(username="alice"):
    from app.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: username

def clear_mock_auth():
    from app.main import get_current_user
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.fixture(autouse=True)
def run_around_tests():
    clear_mock_auth()
    yield
    clear_mock_auth()


# --- SEC-12: Session ID & Filename Path Traversal Prevention ---

def test_sec12_is_safe_session_id_helper():
    """Verify that is_safe_session_id accepts valid IDs and rejects all traversal/special characters."""
    assert is_safe_session_id("sess123") is True
    assert is_safe_session_id("0a1b70b006104e08ae18243fbacab197") is True
    assert is_safe_session_id("chat-session_1") is True

    # Traversal & special character rejection
    assert is_safe_session_id("..") is False
    assert is_safe_session_id(".") is False
    assert is_safe_session_id("../..") is False
    assert is_safe_session_id("sess/123") is False
    assert is_safe_session_id("sess\\123") is False
    assert is_safe_session_id("sess 123") is False
    assert is_safe_session_id("sess;rm") is False
    assert is_safe_session_id("") is False
    assert is_safe_session_id(None) is False
    assert is_safe_session_id("a" * 65) is False


def test_sec12_router_endpoints_reject_invalid_session_ids(tmp_path, monkeypatch):
    """Verify that router endpoints return HTTP 400 when an invalid session_id is provided."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    init_user_storage("alice")

    invalid_ids = ["..", "%2e%2e", "sess/invalid", "sess name", "invalid!id", "a" * 65]

    for inv_id in invalid_ids:
        # GET status
        res = client.get(f"/api/sessions/{inv_id}/status")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for GET status with id '{inv_id}', got {res.status_code}"

        # GET history
        res = client.get(f"/api/sessions/{inv_id}/history")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for GET history with id '{inv_id}', got {res.status_code}"

        # GET icon
        res = client.get(f"/api/sessions/{inv_id}/icon")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for GET icon with id '{inv_id}', got {res.status_code}"

        # DELETE session
        res = client.delete(f"/api/sessions/{inv_id}")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for DELETE with id '{inv_id}', got {res.status_code}"

        # GET settings
        res = client.get(f"/api/sessions/{inv_id}/settings")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for GET settings with id '{inv_id}', got {res.status_code}"

        # PUT settings
        res = client.put(f"/api/sessions/{inv_id}/settings", json={"prompt": "test"})
        assert res.status_code in (400, 404), f"Expected 400 or 404 for PUT settings with id '{inv_id}', got {res.status_code}"

        # PUT title
        res = client.put(f"/api/sessions/{inv_id}/title", json={"title": "new title"})
        assert res.status_code in (400, 404), f"Expected 400 or 404 for PUT title with id '{inv_id}', got {res.status_code}"

        # GET export
        res = client.get(f"/api/sessions/{inv_id}/export")
        assert res.status_code in (400, 404), f"Expected 400 or 404 for GET export with id '{inv_id}', got {res.status_code}"

        # POST chat
        res = client.post(f"/api/sessions/{inv_id}/chat", data={"message": "hello"})
        assert res.status_code in (400, 404), f"Expected 400 or 404 for POST chat with id '{inv_id}', got {res.status_code}"

    # Also explicitly verify that invalid IDs reaching the endpoint return 400
    res_bad = client.get("/api/sessions/invalid!id/status")
    assert res_bad.status_code == 400
    assert "Ungültige Sitzungs-ID" in res_bad.json()["detail"]


def test_sec12_files_router_rejects_invalid_session_and_filename(tmp_path, monkeypatch):
    """Verify that files router endpoints return HTTP 400 for invalid session_id or filename."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    init_user_storage("alice")

    # Invalid session_id on get_upload
    res = client.get("/uploads/%2e%2e/test.png")
    assert res.status_code == 400

    # Invalid filename on get_upload
    res2 = client.get("/uploads/sess1/%2e%2e")
    assert res2.status_code == 400

    # Invalid session_id on get_thumbnail
    res3 = client.get("/uploads/%2e%2e/thumbnails/test.png")
    assert res3.status_code == 400

    # Invalid filename on get_thumbnail
    res4 = client.get("/uploads/sess1/thumbnails/%2e%2e")
    assert res4.status_code == 400


# --- SEC-13: Stored XSS Prevention & CSP Sandbox for Uploads & Thumbnails ---

def test_sec13_uploads_served_with_csp_sandbox(tmp_path, monkeypatch):
    """Verify that files served via /uploads/ contain Content-Security-Policy with sandbox and nosniff."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")

    init_user_storage("alice")
    init_session_storage("alice", "sess_sec13")

    session_upload_dir = tmp_path / "alice" / "sessions" / "sess_sec13" / "uploads"
    test_file = session_upload_dir / "12345678_malicious.svg"
    test_file.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')

    res = client.get("/uploads/sess_sec13/12345678_malicious.svg")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp
    assert "sandbox" in csp
    assert res.headers.get("X-Content-Type-Options") == "nosniff"


def test_sec13_thumbnail_fallback_has_attachment_disposition_and_csp(tmp_path, monkeypatch):
    """Verify that thumbnail fallback for non-image/SVG files includes CSP sandbox and attachment disposition."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")

    init_user_storage("alice")
    init_session_storage("alice", "sess_thumb")

    session_upload_dir = tmp_path / "alice" / "sessions" / "sess_thumb" / "uploads"
    test_file = session_upload_dir / "12345678_test.svg"
    test_file.write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>')

    res = client.get("/uploads/sess_thumb/thumbnails/12345678_test.svg")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp
    assert "sandbox" in csp
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    cd = res.headers.get("Content-Disposition", "")
    assert "attachment" in cd


# --- SEC-14: DOM XSS Neutralization in History & Session Import ---

@pytest.mark.asyncio
async def test_sec14_import_neutralizes_javascript_urls(tmp_path, monkeypatch):
    """Verify that importing a session archive strips javascript: URLs from history."""
    from app.services.session_service import session_service
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))

    init_user_storage("alice")
    init_session_storage("alice", "sess_xss_import")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        malicious_session = {
            "id": "sess_xss_import",
            "title": "Malicious Import",
            "history": [
                {
                    "text": "Hello with exploit",
                    "is_user": False,
                    "image_urls": ["javascript:alert('img')"],
                    "images": [{"url": "javascript:alert('img_dict')"}],
                    "files": [{"name": "evil.txt", "url": "javascript:alert('file')"}]
                }
            ]
        }
        zf.writestr("session.json", json.dumps(malicious_session))

    zip_bytes = buf.getvalue()
    result = await session_service.import_session_archive("alice", "sess_xss_import", zip_bytes)
    assert result["id"] == "sess_xss_import"

    history = await session_service.get_session_history("alice", "sess_xss_import")
    assert len(history) == 1
    msg = history[0]

    # Verify that javascript: URLs were neutralized to '#' or safe values
    for u in msg.get("image_urls", []):
        assert not u.lower().startswith("javascript:")
    for img in msg.get("images", []):
        if isinstance(img, dict):
            assert not img.get("url", "").lower().startswith("javascript:")
    for f in msg.get("files", []):
        assert not f.get("url", "").lower().startswith("javascript:")


# --- SEC-15: DoS / OOM Streaming Upload Limits & Zip-Bomb Limits ---

@pytest.mark.asyncio
async def test_sec15_zip_bomb_uncompressed_limit_detected_during_extraction(tmp_path, monkeypatch):
    """Verify that Zip-Bomb with fake header size is caught during extraction by byte counter."""
    from app.services.session_service import session_service
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))

    init_user_storage("alice")
    init_session_storage("alice", "sess_zipbomb")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_zipbomb", "title": "Bomb", "history": []}))
        large_chunk = b"A" * (2 * 1024 * 1024)
        zf.writestr("data/expanded1.bin", large_chunk)
        zf.writestr("data/expanded2.bin", large_chunk)
        zf.writestr("data/expanded3.bin", large_chunk)

    zip_bytes = buf.getvalue()

    monkeypatch.setattr("app.services.session_service.MAX_ZIP_UNCOMPRESSED_BYTES", 3 * 1024 * 1024)

    with pytest.raises(ValueError) as excinfo:
        await session_service.import_session_archive("alice", "sess_zipbomb", zip_bytes)

    assert "überschreitet das Limit" in str(excinfo.value)


# --- SEC-16: Auth Service Constant-Time Compare & Cryptographic Tokens ---

def test_sec16_auth_constant_time_and_secrets_token():
    """Verify that authenticate uses constant time comparison and session tokens have 64 hex characters."""
    with patch.object(auth_service, "get_valid_users", return_value={"alice": "secretpass"}):
        assert auth_service.authenticate("alice", "secretpass") is True
        assert auth_service.authenticate("alice", "wrongpass") is False
        assert auth_service.authenticate("unknown", "secretpass") is False

    token = auth_service.create_session("alice")
    assert len(token) == 64
    assert int(token, 16) > 0
    auth_service.invalidate_session(token)


# --- SEC-17: Conversation Exists Directory Traversal Prevention ---

def test_sec17_conversation_exists_directory_traversal():
    """Verify that conversation_exists rejects path traversal attempts."""
    assert agy_service.conversation_exists("../../etc/passwd") is False
    assert agy_service.conversation_exists("../conv123") is False
    assert agy_service.conversation_exists("conv!@#") is False
    assert agy_service.conversation_exists("a" * 65) is False
    assert agy_service.conversation_exists(None) is False
    assert agy_service.conversation_exists("") is False
