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


def test_storage_service_generate_thumbnail_modes(storage_service, tmp_path):
    # Palette mode (P)
    src_p = str(tmp_path / "src_p.png")
    dst_p = str(tmp_path / "thumb_p.jpg")
    img_p = Image.new("P", (300, 300))
    img_p.save(src_p, "PNG")
    assert storage_service.generate_thumbnail(src_p, dst_p) is True

    # Grayscale with Alpha (LA)
    src_la = str(tmp_path / "src_la.png")
    dst_la = str(tmp_path / "thumb_la.jpg")
    img_la = Image.new("LA", (300, 300))
    img_la.save(src_la, "PNG")
    assert storage_service.generate_thumbnail(src_la, dst_la) is True

    # Grayscale (L)
    src_l = str(tmp_path / "src_l.png")
    dst_l = str(tmp_path / "thumb_l.jpg")
    img_l = Image.new("L", (300, 300))
    img_l.save(src_l, "PNG")
    assert storage_service.generate_thumbnail(src_l, dst_l) is True

    # Corrupt / invalid image file
    src_corrupt = str(tmp_path / "corrupt.jpg")
    dst_corrupt = str(tmp_path / "thumb_corrupt.jpg")
    with open(src_corrupt, "w") as f:
        f.write("not image data")
    assert storage_service.generate_thumbnail(src_corrupt, dst_corrupt) is False
    assert not os.path.exists(dst_corrupt)


def test_storage_service_atomic_write_json_cleanup_on_error(storage_service, tmp_path, monkeypatch, caplog):
    import logging
    from unittest.mock import patch
    target = os.path.join(str(tmp_path), "fail.json")

    with patch("json.dump", side_effect=OSError("Simulated atomic write failure")):
        with caplog.at_level(logging.ERROR, logger="app.services.storage_service"):
            with pytest.raises(OSError):
                storage_service.atomic_write_json(target, {"key": "val"})

    assert "Failed atomic write" in caplog.text
    # Ensure temporary files are cleaned up
    tmp_files = [f for f in os.listdir(str(tmp_path)) if f.startswith(".tmp.")]
    assert len(tmp_files) == 0


def test_storage_service_cleanup_deleted_sessions(storage_service, tmp_path):
    user_sessions_dir = tmp_path / "data" / "alice" / "sessions"
    user_sessions_dir.mkdir(parents=True, exist_ok=True)

    import time
    now = time.time()
    old_time = int(now - (35 * 86400))
    recent_time = int(now - (10 * 86400))

    old_dir = user_sessions_dir / f"DELETED_{old_time}_oldsess"
    recent_dir = user_sessions_dir / f"DELETED_{recent_time}_recentsess"
    active_dir = user_sessions_dir / "activesess"

    old_dir.mkdir()
    recent_dir.mkdir()
    active_dir.mkdir()

    storage_service.cleanup_deleted_sessions("alice")

    # Old directory should be pruned (> 30 days)
    assert not old_dir.exists()
    # Recent deleted and active directories should be kept
    assert recent_dir.exists()
    assert active_dir.exists()

    # Rate limiting: calling again immediately should not perform another cleanup
    another_old = user_sessions_dir / f"DELETED_{old_time}_another"
    another_old.mkdir()
    storage_service.cleanup_deleted_sessions("alice")
    # Rate limit prevents scanning again within 24h
    assert another_old.exists()


def test_storage_facade_delegates_to_service(storage_service):
    from app import storage
    assert storage.session_locks is storage.storage_service.session_locks
    assert callable(storage.atomic_write_json)
    assert callable(storage.create_session)

