import os
import re
import pytest
from fastapi.testclient import TestClient

from app.main import app, static_dir
from app.services.auth_service import get_current_user
from app.services.storage_service import storage_service

client = TestClient(app)


def mock_auth():
    app.dependency_overrides[get_current_user] = lambda: "testuser"


def clear_mock_auth():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture(autouse=True)
def run_around_tests():
    mock_auth()
    yield
    clear_mock_auth()


def test_index_html_has_no_cache_headers_and_dynamic_cache_busters():
    """Verify that GET / returns no-cache headers and dynamically injected mtime cache-busters."""
    response = client.get("/")
    assert response.status_code == 200

    cache_control = response.headers.get("cache-control", "")
    assert "no-cache" in cache_control
    assert "no-store" in cache_control

    content = response.text

    # Verify styles.css has dynamic ?v=<mtime>
    styles_path = os.path.join(static_dir, "styles.css")
    assert os.path.exists(styles_path)
    expected_styles_mtime = str(int(os.path.getmtime(styles_path)))
    assert f"/static/styles.css?v={expected_styles_mtime}" in content

    # Verify main.js has dynamic ?v=<mtime>
    main_js_path = os.path.join(static_dir, "js", "main.js")
    assert os.path.exists(main_js_path)
    expected_main_mtime = str(int(os.path.getmtime(main_js_path)))
    assert f"/static/js/main.js?v={expected_main_mtime}" in content

    # Verify favicon has dynamic ?v=<mtime>
    favicon_path = os.path.join(static_dir, "favicon.png")
    assert os.path.exists(favicon_path)
    expected_favicon_mtime = str(int(os.path.getmtime(favicon_path)))
    assert f"/static/favicon.png?v={expected_favicon_mtime}" in content


def test_static_files_have_no_cache_headers():
    """Verify that all static files (CSS, JS, submodules) return Cache-Control: no-cache."""
    for path in ["/static/styles.css", "/static/js/main.js", "/static/js/state.js", "/static/js/components/chat_view.js"]:
        response = client.get(path)
        assert response.status_code == 200, f"Failed for {path}"
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control, f"Expected no-cache for {path}, got: {cache_control}"


def test_static_files_etag_revalidation():
    """Verify that static files return 304 Not Modified when ETag matches."""
    res1 = client.get("/static/js/state.js")
    assert res1.status_code == 200
    etag = res1.headers.get("etag")
    assert etag is not None

    res2 = client.get("/static/js/state.js", headers={"If-None-Match": etag})
    assert res2.status_code == 304


def test_favicon_ico_has_no_cache_header():
    """Verify that /favicon.ico has Cache-Control: no-cache."""
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    cache_control = response.headers.get("cache-control", "")
    assert "no-cache" in cache_control


def test_session_icon_has_no_cache_header(tmp_path):
    """Verify that /api/sessions/{session_id}/icon has Cache-Control: no-cache."""
    session_id = "test-icon-caching-sess"
    session_dir = tmp_path / "testuser" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    icon_file = session_dir / "icon.svg"
    icon_file.write_text("<svg></svg>", encoding="utf-8")

    from unittest.mock import patch
    with patch.object(storage_service, "_custom_data_dir", str(tmp_path)):
        response = client.get(f"/api/sessions/{session_id}/icon")
        assert response.status_code == 200
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control


def test_download_data_file_has_no_cache_header(tmp_path):
    """Verify that /app/data/... has Cache-Control: no-cache."""
    session_id = "test-data-caching-sess"
    data_dir = tmp_path / "testuser" / "sessions" / session_id / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    test_file = data_dir / "result.txt"
    test_file.write_text("agent result", encoding="utf-8")

    from unittest.mock import patch
    with patch.object(storage_service, "_custom_data_dir", str(tmp_path)):
        response = client.get(f"/app/data/testuser/{session_id}/data/result.txt")
        assert response.status_code == 200
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control
