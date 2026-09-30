import os
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.storage import DATA_DIR

client = TestClient(app)


def mock_auth():
    from app.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "testuser"


def clear_mock_auth():
    from app.main import get_current_user
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture(autouse=True)
def run_around_tests():
    mock_auth()
    yield
    clear_mock_auth()


def test_get_upload_returns_cache_control_headers(tmp_path):
    session_id = "test-caching-sess"
    filename = "test_image.jpg"
    uploads_dir = tmp_path / "testuser" / "sessions" / session_id / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    img_file = uploads_dir / filename
    
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(img_file), "JPEG")
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.get(f"/uploads/{session_id}/{filename}")
        assert response.status_code == 200
        assert "public" in response.headers.get("cache-control", "")
        assert "immutable" in response.headers.get("cache-control", "")
        assert "max-age=31536000" in response.headers.get("cache-control", "")


def test_get_thumbnail_generates_and_serves_thumbnail(tmp_path):
    session_id = "test-thumb-sess"
    filename = "large_image.jpg"
    uploads_dir = tmp_path / "testuser" / "sessions" / session_id / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    img_file = uploads_dir / filename
    
    # Create large image 1200x800
    img = Image.new("RGB", (1200, 800), color="green")
    img.save(str(img_file), "JPEG")
    
    thumb_dir = tmp_path / "testuser" / "sessions" / session_id / "thumbnails"
    assert not thumb_dir.exists()
    
    with patch("app.main.DATA_DIR", str(tmp_path)):
        # First request should dynamically generate thumbnail
        response = client.get(f"/uploads/{session_id}/thumbnails/{filename}")
        assert response.status_code == 200
        assert "public" in response.headers.get("cache-control", "")
        assert "immutable" in response.headers.get("cache-control", "")
        
        # Verify thumbnail was created on disk
        thumb_file = thumb_dir / filename
        assert thumb_file.exists()
        
        with Image.open(str(thumb_file)) as thumb:
            w, h = thumb.size
            assert max(w, h) == 400
            
        # Second request serves already existing thumbnail directly
        response2 = client.get(f"/uploads/{session_id}/thumbnails/{filename}")
        assert response2.status_code == 200
        assert "public" in response2.headers.get("cache-control", "")


def test_get_thumbnail_not_found_returns_404(tmp_path):
    session_id = "test-thumb-sess"
    with patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.get(f"/uploads/{session_id}/thumbnails/nonexistent.jpg")
        assert response.status_code == 404
