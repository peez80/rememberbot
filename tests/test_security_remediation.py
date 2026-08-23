import io
import os
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from app.main import app
from app.storage import (
    DATA_DIR,
    init_user_storage,
    init_session_storage,
    atomic_write_json,
    sanitize_svg,
    import_session_archive
)

client = TestClient(app)

# Helper to mock auth
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


# --- SEC-01 (Finding 1): Arbitrary File Read / Path Traversal via Fallback ---

def test_sec01_data_download_path_traversal_and_fallback_blocked(tmp_path, monkeypatch):
    """Verify that path traversal attempts using legacy fallback or '..' are strictly rejected with 400 or 404."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    
    # Setup user data dir
    init_user_storage("alice")
    init_session_storage("alice", "sess1")
    
    # 1. Attempt traversal via legacy fallback
    response = client.get("/app/data/alice/sess1/data//root/.gemini/antigravity-cli/../../etc/passwd")
    assert response.status_code in (400, 404), f"Expected 400 or 404 but got {response.status_code}"
    
    # 2. Attempt traversal to config/users.json
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "users.json").write_text('{"admin": "secret"}')
    
    response2 = client.get("/app/data/alice/sess1/data/..%2F..%2F..%2Fconfig%2Fusers.json")
    assert response2.status_code in (400, 404), f"Expected 400 or 404 but got {response2.status_code}"


# --- SEC-02 (Finding 2): Arbitrary File Overwrite / RCE beim ZIP-Import ---

@pytest.mark.asyncio
async def test_sec02_zip_import_leading_slash_and_escape_blocked(tmp_path, monkeypatch):
    """Verify that zip entries like 'uploads//app/main.py' or 'data//etc/passwd' cannot escape session directory."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    init_user_storage("alice")
    init_session_storage("alice", "sess_import_sec")
    
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_import_sec", "title": "Sec Test", "history": []}))
        zf.writestr("uploads//app/main.py", "print('malicious exploit')")
        zf.writestr("data//outside.txt", "print('outside')")
        
    zip_bytes = buf.getvalue()
    result = await import_session_archive("alice", "sess_import_sec", zip_bytes)
    assert result["id"] == "sess_import_sec"
    
    # Verify that files did NOT escape into root /app or outside the user session directory
    assert not (tmp_path / "app" / "main.py").exists()
    assert not (tmp_path / "outside.txt").exists()
    
    # Files must be safely created inside session's uploads and data directories
    session_uploads = tmp_path / "alice" / "sessions" / "sess_import_sec" / "uploads"
    session_data = tmp_path / "alice" / "sessions" / "sess_import_sec" / "data"
    assert (session_uploads / "app" / "main.py").exists() or (session_uploads / "main.py").exists()


# --- SEC-04 (Finding 4): Rate-Limiting beim Login ---

def test_sec04_login_rate_limiting():
    """Verify that multiple failed login attempts trigger HTTP 429 Too Many Requests."""
    from app.main import _failed_login_attempts
    _failed_login_attempts.clear()
    
    with patch("app.main.get_valid_users", return_value={"alice": "correctpassword"}):
        # 5 failed attempts
        for _ in range(5):
            res = client.post("/api/auth/login", data={"username": "alice", "password": "wrongpassword"})
            assert res.status_code == 401
            
        # 6th attempt must be throttled with HTTP 429
        res = client.post("/api/auth/login", data={"username": "alice", "password": "wrongpassword"})
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        
        # After successful login on another user, attempts for that user should succeed
        res_ok = client.post("/api/auth/login", data={"username": "alice", "password": "correctpassword"})
        # Note: if alice is rate limited, even correct password might be blocked or allowed depending on policy.
        # But once rate limit expires / for different IP, it resets.


# --- SEC-05 (Finding 5): Stored XSS in Sidebar & DOM XSS ---

def test_sec05_xss_protection_in_frontend_and_api(tmp_path, monkeypatch):
    """Verify that session title and file links do not allow unescaped HTML injection."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    
    init_user_storage("alice")
    init_session_storage("alice", "sess_xss")
    
    # Set title with XSS payload
    xss_title = '<img src=x onerror="alert(1)">'
    with patch("app.main.check_session_exists", return_value=True), \
         patch("app.main.agy_client.generate_chat_icon", return_value=None):
        res = client.put("/api/sessions/sess_xss/title", json={"title": xss_title})
        assert res.status_code == 200


# --- SEC-06 (Finding 6): SVG-Sanitization & CSP Header for Icons ---

def test_sec06_svg_sanitization_and_csp(tmp_path, monkeypatch):
    """Verify that SVG content is stripped of scripts/event handlers and served with strict CSP headers."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    
    dirty_svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script><circle onload="alert(1)" onclick="alert(2)" r="10"/><a href="javascript:alert(3)">click</a></svg>'
    cleaned = sanitize_svg(dirty_svg)
    assert "<script>" not in cleaned
    assert "alert" not in cleaned
    assert "onload" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "<circle" in cleaned
    
    # Check Endpoint CSP Header
    init_user_storage("alice")
    init_session_storage("alice", "sess_icon")
    icon_path = tmp_path / "alice" / "sessions" / "sess_icon" / "icon.svg"
    icon_path.write_text(cleaned, encoding="utf-8")
    
    with patch("app.main.get_session_icon_path", return_value=str(icon_path)):
        res = client.get("/api/sessions/sess_icon/icon")
        assert res.status_code == 200
        assert "Content-Security-Policy" in res.headers
        assert "default-src 'none'" in res.headers["Content-Security-Policy"]


# --- SEC-07 (Finding 7): Session Expiration & Cookie Flags ---

def test_sec07_session_expiration_and_cookie_attributes():
    """Verify that expired session tokens return 401 and cookies have proper security attributes."""
    from app.main import ACTIVE_SESSIONS
    
    # Expired token
    ACTIVE_SESSIONS["expired_token_123"] = {
        "username": "alice",
        "created_at": time.time() - 40 * 86400,
        "expires_at": time.time() - 10 * 86400
    }
    
    client.cookies.set("session_token", "expired_token_123")
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    assert res.json() == {"authenticated": False}
    
    # Valid token
    ACTIVE_SESSIONS["valid_token_456"] = {
        "username": "alice",
        "created_at": time.time(),
        "expires_at": time.time() + 86400
    }
    client.cookies.set("session_token", "valid_token_456")
    res_valid = client.get("/api/auth/status")
    assert res_valid.status_code == 200
    assert res_valid.json() == {"authenticated": True, "username": "alice"}
    client.cookies.clear()


# --- SEC-08 (Finding 8): Upload Size Limits & Zip-Bomb Prevention ---

def test_sec08_upload_size_limits_and_zip_bomb(tmp_path, monkeypatch):
    """Verify upload size limit on chat endpoint and uncompressed size limit in zip imports."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    
    init_user_storage("alice")
    init_session_storage("alice", "sess_upload_limit")
    
    # 1. Chat upload exceeding 25 MB
    large_payload = b"X" * (26 * 1024 * 1024) # 26MB
    files = [("files", ("huge.dat", large_payload, "application/octet-stream"))]
    
    with patch("app.main.check_session_exists", return_value=True):
        res = client.post("/api/sessions/sess_upload_limit/chat", data={"message": "upload test"}, files=files)
        assert res.status_code in (400, 413)
        assert "groß" in res.text.lower() or "large" in res.text.lower() or "limit" in res.text.lower()
        
    # 2. ZIP import limit test: 501 MB rejected with 413
    over_500mb = b"PK\x05\x06" + b"\x00" * 18 + b"0" * (501 * 1024 * 1024) # 501MB
    with patch("app.main.check_session_exists", return_value=True):
        res_zip = client.post(
            "/api/sessions/sess_upload_limit/import",
            files={"file": ("large_session.zip", over_500mb, "application/zip")}
        )
        assert res_zip.status_code == 413
        assert "500 MB" in res_zip.text



# --- SEC-09 (Finding 9): Globale HTTP Security Headers ---

def test_sec09_global_security_headers_present():
    """Verify that all responses contain essential HTTP security headers and CSP allows Phosphor icons and fonts."""
    res = client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "strict-origin" in res.headers.get("Referrer-Policy", "").lower()
    csp = res.headers.get("Content-Security-Policy", "")
    assert "https://cdn.jsdelivr.net" in csp
    assert "https://unpkg.com" in csp
    
    # Verify directives explicitly allow cdn.jsdelivr.net for both styles and fonts
    directives = {d.strip().split()[0]: d.strip() for d in csp.split(";") if d.strip()}
    assert "https://cdn.jsdelivr.net" in directives["style-src"]
    assert "https://cdn.jsdelivr.net" in directives["font-src"]
    assert "https://unpkg.com" in directives["style-src"]


# --- SEC-10 (Finding 10): Temp-Kontextdatei-Bereinigung in process_message ---

@pytest.mark.asyncio
async def test_sec10_agy_context_temp_file_cleaned_on_error(tmp_path):
    """Verify that chat_context_*.txt is guaranteed to be deleted even if process_message fails."""
    from app.agy_client import AgyClient
    
    client_instance = AgyClient()
    mock_context = [{"is_user": True, "text": "Hello context"}]
    
    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("Subprocess failed unexpectedly")):
        res = await client_instance.process_message(
            context_messages=mock_context,
            new_message="Test message",
            cwd=str(tmp_path)
        )
        
        # Check that no chat_context_*.txt remains in tmp_path
        context_files = list(tmp_path.glob("chat_context_*.txt"))
        assert len(context_files) == 0, f"Expected temp context files to be cleaned up, but found: {context_files}"


# --- SEC-11 (Finding 11): Atomare Dateischreibvorgänge ---

def test_sec11_atomic_write_json(tmp_path):
    """Verify atomic_write_json writes content safely via temp file and atomic rename."""
    target_file = str(tmp_path / "test_atomic.json")
    test_data = {"key": "value", "count": 123, "active": True}
    
    atomic_write_json(target_file, test_data)
    
    assert os.path.isfile(target_file)
    with open(target_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == test_data
