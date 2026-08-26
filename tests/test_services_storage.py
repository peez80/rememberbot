import os
import pytest
from PIL import Image

from app.services.storage_service import StorageService

@pytest.fixture
def storage_service(tmp_path):
    return StorageService(data_dir=str(tmp_path / "data"))

def test_storage_service_init_directories(storage_service, tmp_path):
    storage_service.init_storage()
    assert os.path.exists(os.path.join(storage_service.data_dir, "config"))

    storage_service.init_user_storage("alice")
    assert os.path.exists(os.path.join(storage_service.data_dir, "alice", "sessions"))

    storage_service.init_session_storage("alice", "sess-123")
    assert os.path.exists(os.path.join(storage_service.data_dir, "alice", "sessions", "sess-123", "uploads"))
    assert os.path.exists(os.path.join(storage_service.data_dir, "alice", "sessions", "sess-123", "thumbnails"))
    assert os.path.exists(os.path.join(storage_service.data_dir, "alice", "sessions", "sess-123", "data"))

def test_storage_service_atomic_write_json(storage_service, tmp_path):
    target = os.path.join(str(tmp_path), "test.json")
    storage_service.atomic_write_json(target, {"hello": "world"})
    assert os.path.exists(target)
    
    # Read back
    with open(target, "r", encoding="utf-8") as f:
        import json
        data = json.load(f)
        assert data == {"hello": "world"}

def test_storage_service_generate_thumbnail(storage_service, tmp_path):
    src = os.path.join(str(tmp_path), "src.png")
    dst = os.path.join(str(tmp_path), "thumb.jpg")
    
    # Create test image with RGBA
    img = Image.new("RGBA", (800, 600), (255, 0, 0, 128))
    img.save(src, "PNG")
    
    success = storage_service.generate_thumbnail(src, dst, max_dimension=200)
    assert success is True
    assert os.path.exists(dst)
    
    with Image.open(dst) as thumb_img:
        assert max(thumb_img.size) <= 200
