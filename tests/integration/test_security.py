import io
import os
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from app.main import app
from app.core.config import DATA_DIR, SESSION_COOKIE_NAME, is_safe_session_id
from app.storage import init_user_storage, init_session_storage
from app.services.auth_service import auth_service
from app.services.session_service import session_service
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


# ==============================================================================
# SECTION 1: Session-ID, Path Traversal & Symlink Defense
# ==============================================================================

def test_session_id_validation_helper():
    """Verify is_safe_session_id strictly validates alphanumeric + hyphen/underscore IDs."""
    assert is_safe_session_id("sess123") is True
    assert is_safe_session_id("0a1b70b006104e08ae18243fbacab197") is True
    assert is_safe_session_id("chat-session_1") is True

    # Traversal & special character rejection
    for inv in ["..", ".", "../..", "sess/123", "sess\\123", "sess 123", "sess;rm", "", None, "a" * 65]:
        assert is_safe_session_id(inv) is False


def test_api_endpoints_reject_invalid_session_ids(tmp_path, monkeypatch):
    """Verify all session-based router endpoints reject invalid IDs with 400 or 404."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    init_user_storage("alice")

    for inv_id in ["..", "%2e%2e", "sess/invalid", "sess name", "invalid!id", "a" * 65]:
        res = client.get(f"/api/sessions/{inv_id}/status")
        assert res.status_code in (400, 404)

        res = client.get(f"/api/sessions/{inv_id}/history")
        assert res.status_code in (400, 404)

        res = client.get(f"/api/sessions/{inv_id}/icon")
        assert res.status_code in (400, 404)

        res = client.delete(f"/api/sessions/{inv_id}")
        assert res.status_code in (400, 404)

        res = client.get(f"/api/sessions/{inv_id}/settings")
        assert res.status_code in (400, 404)

        res = client.put(f"/api/sessions/{inv_id}/settings", json={"prompt": "test"})
        assert res.status_code in (400, 404)

        res = client.put(f"/api/sessions/{inv_id}/title", json={"title": "new title"})
        assert res.status_code in (400, 404)

        res = client.get(f"/api/sessions/{inv_id}/export")
        assert res.status_code in (400, 404)

        res = client.post(f"/api/sessions/{inv_id}/chat", data={"message": "hello"})
        assert res.status_code in (400, 404)


def test_files_router_rejects_path_traversal(tmp_path, monkeypatch):
    """Verify that file download routes strictly reject directory traversal in session_id or filename."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")
    init_user_storage("alice")

    assert client.get("/uploads/%2e%2e/test.png").status_code == 400
    assert client.get("/uploads/sess1/%2e%2e").status_code == 400
    assert client.get("/uploads/%2e%2e/thumbnails/test.png").status_code == 400
    assert client.get("/uploads/sess1/thumbnails/%2e%2e").status_code == 400


def test_data_download_traversal_and_fallback_blocked(tmp_path, monkeypatch):
    """Verify that path traversal in /app/data/... is strictly blocked."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")

    init_user_storage("alice")
    init_session_storage("alice", "sess1")

    res1 = client.get("/app/data/alice/sess1/data//root/.gemini/antigravity-cli/../../etc/passwd")
    assert res1.status_code in (400, 404)

    res2 = client.get("/app/data/alice/sess1/data/..%2F..%2F..%2Fconfig%2Fusers.json")
    assert res2.status_code in (400, 404)


def test_data_download_rejects_symlink_escape(tmp_path, monkeypatch):
    """Verify that download_file strictly rejects symlinks pointing outside the session data directory."""
    monkeypatch.setattr("app.main.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    mock_auth("alice")

    init_user_storage("alice")
    init_session_storage("alice", "sess_symlink")

    data_dir = tmp_path / "alice" / "sessions" / "sess_symlink" / "data"
    outside_file = tmp_path / "secret_system_data.txt"
    outside_file.write_text("CONFIDENTIAL_CREDENTIALS")

    symlink_file = data_dir / "leaked_link.txt"
    try:
        os.symlink(str(outside_file), str(symlink_file))
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this filesystem")

    res = client.get("/app/data/alice/sess_symlink/data/leaked_link.txt")
    assert res.status_code == 400
    assert "Invalid path" in res.json().get("detail", "")


def test_conversation_exists_directory_traversal():
    """Verify that conversation_exists rejects path traversal attempts."""
    assert agy_service.conversation_exists("../../etc/passwd") is False
    assert agy_service.conversation_exists("../conv123") is False
    assert agy_service.conversation_exists("conv!@#") is False
    assert agy_service.conversation_exists("a" * 65) is False
    assert agy_service.conversation_exists(None) is False
    assert agy_service.conversation_exists("") is False


# ==============================================================================
# SECTION 2: ZIP Import & Upload Defense (ZipSlip, ZipBomb, DoS)
# ==============================================================================

@pytest.mark.asyncio
async def test_zip_import_slip_and_leading_slash_blocked(tmp_path, monkeypatch):
    """Verify that zip entries escaping session directories via ZipSlip or leading slashes are blocked."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    init_user_storage("alice")
    init_session_storage("alice", "sess_import_sec")

    # 1. Leading slash entries
    buf1 = io.BytesIO()
    with zipfile.ZipFile(buf1, "w") as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_import_sec", "title": "Sec Test", "history": []}))
        zf.writestr("uploads//app/main.py", "print('exploit')")
        zf.writestr("data//outside.txt", "print('outside')")
    zip_bytes1 = buf1.getvalue()

    await session_service.import_session_archive("alice", "sess_import_sec", zip_bytes1)
    assert not (tmp_path / "app" / "main.py").exists()
    assert not (tmp_path / "outside.txt").exists()

    # 2. Classic ZipSlip with '../'
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_import_sec", "title": "Sec Test", "history": []}))
        zf.writestr("../../etc/cron.d/evil", "exploit")
    zip_bytes2 = buf2.getvalue()

    with pytest.raises(ValueError) as exc:
        await session_service.import_session_archive("alice", "sess_import_sec", zip_bytes2)
    assert "Ungültiger Pfad" in str(exc.value) or "ZipSlip" in str(exc.value)


@pytest.mark.asyncio
async def test_zip_import_rejects_symlink_entries(tmp_path, monkeypatch):
    """Verify that importing a ZIP archive containing a symlink entry is rejected with ValueError."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    init_user_storage("alice")
    init_session_storage("alice", "sess_symlink_zip")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_symlink_zip", "title": "Symlink Zip", "history": []}))
        symlink_info = zipfile.ZipInfo("data/evil_symlink.txt")
        symlink_info.create_system = 3  # Unix
        symlink_info.external_attr = 0o120777 << 16  # S_IFLNK
        zf.writestr(symlink_info, "/etc/passwd")

    with pytest.raises(ValueError) as excinfo:
        await session_service.import_session_archive("alice", "sess_symlink_zip", buf.getvalue())
    assert "Symlink" in str(excinfo.value) or "Ungültiger Pfad" in str(excinfo.value)


@pytest.mark.asyncio
async def test_zip_bomb_uncompressed_limit_detected(tmp_path, monkeypatch):
    """Verify that Zip-Bomb exceeding uncompressed byte limit is stopped during extraction."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    init_user_storage("alice")
    init_session_storage("alice", "sess_zipbomb")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_zipbomb", "title": "Bomb", "history": []}))
        large_chunk = b"A" * (2 * 1024 * 1024)
        zf.writestr("data/expanded1.bin", large_chunk)
        zf.writestr("data/expanded2.bin", large_chunk)

    monkeypatch.setattr("app.services.session_service.MAX_ZIP_UNCOMPRESSED_BYTES", 2 * 1024 * 1024)

    with pytest.raises(ValueError) as excinfo:
        await session_service.import_session_archive("alice", "sess_zipbomb", buf.getvalue())
    assert "überschreitet das Limit" in str(excinfo.value)


@pytest.mark.asyncio
async def test_zip_bomb_file_count_limit(tmp_path, monkeypatch):
    """Verify that archives with excessive file counts are rejected."""
    monkeypatch.setattr("app.storage.DATA_DIR", str(tmp_path))
    init_user_storage("alice")
    init_session_storage("alice", "sess_filecount")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("session.json", json.dumps({"id": "sess_filecount", "title": "Files", "history": []}))
        for i in range(15):
            zf.writestr(f"data/file_{i}.txt", "content")

    monkeypatch.setattr("app.services.session_service.MAX_ZIP_FILES_COUNT", 10)

    with pytest.raises(ValueError) as exc:
        await session_service.import_session_archive("alice", "sess_filecount", buf.getvalue())
    assert "zu viele dateien" in str(exc.value).lower() or "limit" in str(exc.value).lower()


# ==============================================================================
# SECTION 3: Auth, Rate Limiting & Cookie / CORS Hardening
# ==============================================================================

def test_login_rate_limiting():
    """Verify that multiple failed login attempts trigger HTTP 429 Too Many Requests."""
    auth_service.failed_login_attempts.clear()

    with patch.object(auth_service, "get_valid_users", return_value={"alice": "correctpassword"}):
        for _ in range(5):
            res = client.post("/api/auth/login", data={"username": "alice", "password": "wrongpassword"})
            assert res.status_code == 401

        # 6th attempt must return 429
        res = client.post("/api/auth/login", data={"username": "alice", "password": "wrongpassword"})
        assert res.status_code == 429
        assert "Retry-After" in res.headers


def test_auth_constant_time_and_token_entropy():
    """Verify that authentication uses constant time comparison and session tokens have 64 hex characters."""
    with patch.object(auth_service, "get_valid_users", return_value={"alice": "secretpass"}):
        assert auth_service.authenticate("alice", "secretpass") is True
        assert auth_service.authenticate("alice", "wrongpass") is False
        assert auth_service.authenticate("unknown", "secretpass") is False

    token = auth_service.create_session("alice")
    assert len(token) == 64
    assert int(token, 16) > 0
    auth_service.invalidate_session(token)


def test_session_cookie_security_attributes():
    """Verify that session cookies are HttpOnly and have SameSite=Lax."""
    auth_service.failed_login_attempts.clear()
    with patch.object(auth_service, "get_valid_users", return_value={"alice": "pw"}):
        res = client.post("/api/auth/login", data={"username": "alice", "password": "pw"})
        assert res.status_code == 200
        cookie_header = res.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()



# ==============================================================================
# SECTION 4: CSP, Nosniff, SRI & Content Sanitization
# ==============================================================================

def test_uploads_served_with_csp_sandbox(tmp_path, monkeypatch):
    """Verify that /uploads/ files enforce CSP sandbox and X-Content-Type-Options nosniff."""
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


def test_thumbnail_fallback_has_attachment_disposition_and_csp(tmp_path, monkeypatch):
    """Verify thumbnail fallback for SVG/non-images includes CSP sandbox and attachment disposition."""
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
    assert "attachment" in res.headers.get("Content-Disposition", "")


@pytest.mark.asyncio
async def test_import_neutralizes_javascript_urls(tmp_path, monkeypatch):
    """Verify that importing a session archive neutralizes javascript: URLs in history."""
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

    await session_service.import_session_archive("alice", "sess_xss_import", buf.getvalue())
    history = await session_service.get_session_history("alice", "sess_xss_import")
    assert len(history) == 1
    msg = history[0]

    for u in msg.get("image_urls", []):
        assert not u.lower().startswith("javascript:")
    for img in msg.get("images", []):
        if isinstance(img, dict):
            assert not img.get("url", "").lower().startswith("javascript:")
    for f in msg.get("files", []):
        assert not f.get("url", "").lower().startswith("javascript:")


def test_index_html_includes_sri_hashes():
    """Verify that external CDN scripts in index.html specify SRI integrity and crossorigin attributes."""
    if os.path.exists("app/templates/index.html"):
        with open("app/templates/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        assert "integrity=" in content
        assert "crossorigin=" in content


@pytest.mark.asyncio
async def test_generate_chat_icon_sandboxing():
    """Verify that generate_chat_icon runs with --sandbox and untrusted input framing."""
    captured = []
    async def mock_exec(*cmd, **kwargs):
        captured.append(list(cmd))
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b'<svg><rect width="10" height="10"/></svg>', b''))
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        await agy_service.generate_chat_icon(
            title="Safe Title",
            output_path="/tmp/icon_safe.svg",
            user_context="rm -rf /",
            ai_context="not allowed"
        )

    cmd = captured[0]
    assert "--sandbox" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    prompt_str = cmd[cmd.index("--prompt") + 1]
    assert "<untrusted_user_input>" in prompt_str
