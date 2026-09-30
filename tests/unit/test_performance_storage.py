import os
import io
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock

from app.storage import session_exists, check_session_exists, generate_thumbnail, DATA_DIR


@pytest.mark.asyncio
async def test_session_exists():
    with patch("app.storage.os.path.isfile") as mock_isfile:
        mock_isfile.return_value = True
        exists = await check_session_exists("testuser", "sess-123")
        assert exists is True
        mock_isfile.assert_called_once()
        assert "testuser" in mock_isfile.call_args[0][0]
        assert "sess-123" in mock_isfile.call_args[0][0]
        assert mock_isfile.call_args[0][0].endswith("session.json")

    with patch("app.storage.os.path.isfile") as mock_isfile:
        mock_isfile.return_value = False
        exists = await check_session_exists("testuser", "non-existent")
        assert exists is False


def test_generate_thumbnail_resizes_image(tmp_path):
    # Create a test high-res image (1200x800)
    source_img_path = str(tmp_path / "test_orig.jpg")
    target_thumb_path = str(tmp_path / "thumb_test.jpg")
    
    img = Image.new("RGB", (1200, 800), color=(100, 150, 200))
    img.save(source_img_path, "JPEG")
    
    success = generate_thumbnail(source_img_path, target_thumb_path, max_dimension=400)
    assert success is True
    assert os.path.exists(target_thumb_path)
    
    with Image.open(target_thumb_path) as thumb:
        w, h = thumb.size
        assert max(w, h) == 400
        assert w == 400
        assert h == 266 or h == 267  # 800 * (400/1200) = 266.67


def test_generate_thumbnail_handles_rgba_transparency(tmp_path):
    source_img_path = str(tmp_path / "test_transparent.png")
    target_thumb_path = str(tmp_path / "thumb_transparent.jpg")
    
    img = Image.new("RGBA", (800, 600), color=(255, 0, 0, 128))
    img.save(source_img_path, "PNG")
    
    success = generate_thumbnail(source_img_path, target_thumb_path, max_dimension=400)
    assert success is True
    assert os.path.exists(target_thumb_path)
    
    with Image.open(target_thumb_path) as thumb:
        assert thumb.mode == "RGB"
        assert max(thumb.size) == 400


def test_generate_thumbnail_handles_invalid_file(tmp_path):
    invalid_file = str(tmp_path / "corrupt.jpg")
    with open(invalid_file, "w") as f:
        f.write("not an image")
        
    target_thumb = str(tmp_path / "thumb_corrupt.jpg")
    success = generate_thumbnail(invalid_file, target_thumb, max_dimension=400)
    assert success is False
    assert not os.path.exists(target_thumb)
