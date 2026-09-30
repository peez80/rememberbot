import os
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app, _active_chat_sessions
from app.storage import (
    DATA_DIR,
    init_user_storage,
    init_session_storage,
    get_session_filepath,
    create_session,
    export_session_archive,
    import_session_archive,
)

client = TestClient(app)

current_test_user = "testuser"

def mock_auth():
    from app.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: current_test_user

def clear_mock_auth():
    from app.main import get_current_user
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.fixture(autouse=True)
def run_around_tests():
    global current_test_user
    current_test_user = "testuser"
    mock_auth()
    yield
    clear_mock_auth()
    _active_chat_sessions.clear()


@pytest.mark.asyncio
async def test_export_session_archive_creates_valid_zip_without_thumbnails(tmp_path):
    username = "testuser"
    session_id = "sess_export_01"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, session_id)
        
        session_dir = tmp_path / username / "sessions" / session_id
        session_file = session_dir / "session.json"
        icon_file = session_dir / "icon.svg"
        upload_doc = session_dir / "uploads" / "doc.pdf"
        upload_img = session_dir / "uploads" / "photo.png"
        data_file = session_dir / "data" / "result.csv"
        thumb_file = session_dir / "thumbnails" / "photo.jpg"
        
        session_data = {
            "id": session_id,
            "title": "Mein Export Test",
            "created_at": "2026-08-22T20:00:00+00:00",
            "history": [{"text": "Hallo", "is_user": True}],
            "system_prompt": "Test Prompt",
            "include_gps": True
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
        icon_file.write_text("<svg>icon</svg>", encoding="utf-8")
        upload_doc.write_bytes(b"%PDF-1.4 test")
        upload_img.write_bytes(b"\x89PNG\r\n\x1a\n")
        data_file.write_bytes(b"a,b\n1,2")
        thumb_file.write_bytes(b"thumb_bytes")
        
        zip_bytes = await export_session_archive(username, session_id)
        
        assert isinstance(zip_bytes, bytes)
        assert len(zip_bytes) > 0
        
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            namelist = zf.namelist()
            assert "session.json" in namelist
            assert "icon.svg" in namelist
            assert "uploads/doc.pdf" in namelist
            assert "uploads/photo.png" in namelist
            assert "data/result.csv" in namelist
            
            # Explicitly check that thumbnails are NOT included
            assert not any("thumbnails" in name for name in namelist)
            
            # Verify contents
            extracted_session = json.loads(zf.read("session.json").decode("utf-8"))
            assert extracted_session["id"] == session_id
            assert extracted_session["title"] == "Mein Export Test"
            assert zf.read("uploads/doc.pdf") == b"%PDF-1.4 test"
            assert zf.read("data/result.csv") == b"a,b\n1,2"


@pytest.mark.asyncio
async def test_export_session_archive_raises_on_nonexistent_session(tmp_path):
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        with pytest.raises((FileNotFoundError, ValueError)):
            await export_session_archive("testuser", "non_existent_id")


@pytest.mark.asyncio
async def test_import_session_archive_zipslip_protection(tmp_path):
    username = "testuser"
    target_session_id = "sess_target_01"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        
        # Create a malicious zip with ZipSlip path
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            session_data = {"id": "old_id", "title": "Evil Chat", "history": []}
            zf.writestr("session.json", json.dumps(session_data))
            zf.writestr("../../evil.txt", "malicious payload")
        
        malicious_zip = buf.getvalue()
        
        with pytest.raises(ValueError) as excinfo:
            await import_session_archive(username, target_session_id, malicious_zip)
        assert "ungültig" in str(excinfo.value).lower() or "zipslip" in str(excinfo.value).lower() or "traversal" in str(excinfo.value).lower() or "path" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_import_session_archive_missing_session_json(tmp_path):
    username = "testuser"
    target_session_id = "sess_target_02"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("uploads/test.txt", "hello")
        
        invalid_zip = buf.getvalue()
        
        with pytest.raises(ValueError) as excinfo:
            await import_session_archive(username, target_session_id, invalid_zip)
        assert "session.json" in str(excinfo.value)


@pytest.mark.asyncio
async def test_import_session_archive_corrupted_zip(tmp_path):
    username = "testuser"
    target_session_id = "sess_target_03"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        
        with pytest.raises(ValueError):
            await import_session_archive(username, target_session_id, b"not_a_valid_zip_file_bytes")


def test_api_export_endpoint_success(tmp_path):
    username = "testuser"
    session_id = "sess_api_export_01"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, session_id)
        
        session_file = tmp_path / username / "sessions" / session_id / "session.json"
        session_data = {
            "id": session_id,
            "title": "API Export Chat",
            "created_at": "2026-08-22T20:00:00+00:00",
            "history": []
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
        
        response = client.get(f"/api/sessions/{session_id}/export")
        assert response.status_code == 200
        assert "application/zip" in response.headers.get("content-type", "")
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert ".zip" in disposition
        
        # Verify it's a valid zip
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        assert "session.json" in zf.namelist()


def test_api_export_endpoint_404_on_missing_session(tmp_path):
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        response = client.get("/api/sessions/nonexistent_session/export")
        assert response.status_code == 404


def test_api_import_endpoint_success(tmp_path):
    username = "testuser"
    target_session_id = "sess_api_import_01"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        
        target_file = tmp_path / username / "sessions" / target_session_id / "session.json"
        target_file.write_text(json.dumps({"id": target_session_id, "title": "Neuer Chat", "history": []}), encoding="utf-8")
        
        # Build valid export zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            session_data = {
                "id": "old_origin_id",
                "title": "Importierter Chat Titel",
                "created_at": "2026-08-20T10:00:00+00:00",
                "history": [{"text": "Alte Nachricht", "is_user": True}],
                "system_prompt": "System Prompt Import",
                "include_gps": False
            }
            zf.writestr("session.json", json.dumps(session_data))
            zf.writestr("uploads/test_file.txt", "file content")
            zf.writestr("icon.svg", "<svg>chat icon</svg>")
            
        zip_bytes = buf.getvalue()
        files = {"file": ("chat_export.zip", zip_bytes, "application/zip")}
        
        response = client.post(f"/api/sessions/{target_session_id}/import", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["id"] == target_session_id
        assert data["title"] == "Importierter Chat Titel"
        assert data["has_icon"] is True
        
        # Verify file is extracted
        extracted_txt = tmp_path / username / "sessions" / target_session_id / "uploads" / "test_file.txt"
        assert extracted_txt.exists()
        assert extracted_txt.read_text() == "file content"


def test_api_import_endpoint_400_on_corrupt_zip(tmp_path):
    username = "testuser"
    target_session_id = "sess_api_import_02"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        target_file = tmp_path / username / "sessions" / target_session_id / "session.json"
        target_file.write_text(json.dumps({"id": target_session_id, "title": "Neuer Chat", "history": []}), encoding="utf-8")
        
        files = {"file": ("corrupt.zip", b"not a zip", "application/zip")}
        response = client.post(f"/api/sessions/{target_session_id}/import", files=files)
        assert response.status_code == 400


def test_api_import_endpoint_400_when_active_processing(tmp_path):
    username = "testuser"
    target_session_id = "sess_api_import_active"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, target_session_id)
        target_file = tmp_path / username / "sessions" / target_session_id / "session.json"
        target_file.write_text(json.dumps({"id": target_session_id, "title": "Neuer Chat", "history": []}), encoding="utf-8")
        
        _active_chat_sessions.add((username, target_session_id))
        
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("session.json", json.dumps({"id": "old", "title": "Chat", "history": []}))
            
        files = {"file": ("chat.zip", buf.getvalue(), "application/zip")}
        response = client.post(f"/api/sessions/{target_session_id}/import", files=files)
        assert response.status_code == 400
        assert "wird gerade verarbeitet" in response.json().get("detail", "") or "processing" in response.json().get("detail", "").lower()


def test_session_export_import_full_roundtrip(tmp_path):
    """
    Complete end-to-end roundtrip test:
    1. Pre-fill session for user_alice with messages, documents (PDF, CSV), photos, AI generated data, icon, system prompt & GPS.
    2. Export via API GET /api/sessions/{alice_session_id}/export.
    3. Verify ZIP structure and thumbnail exclusion.
    4. Create new empty session for user_bob.
    5. Import via API POST /api/sessions/{bob_session_id}/import as user_bob.
    6. Verify all files, metadata, remapped paths, and download endpoints for user_bob.
    """
    global current_test_user
    
    alice_user = "alice"
    bob_user = "bob"
    alice_session_id = "alice_sess_orig_123"
    bob_session_id = "bob_sess_dest_456"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        # 1. Setup Alice's session
        init_user_storage(alice_user)
        init_session_storage(alice_user, alice_session_id)
        
        alice_session_dir = tmp_path / alice_user / "sessions" / alice_session_id
        alice_uploads = alice_session_dir / "uploads"
        alice_data = alice_session_dir / "data"
        alice_thumbs = alice_session_dir / "thumbnails"
        
        pdf_bytes = b"%PDF-1.4 Alice Financial Report Content"
        csv_bytes = b"kpi,value\nrevenue,1000000\nprofit,250000"
        png_bytes = b"\x89PNG\r\n\x1a\nAliceSamplePhotoData"
        xlsx_bytes = b"PK\x03\x04AliceGeneratedExcelData"
        svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='10'/></svg>"
        thumb_bytes = b"JPEG_THUMBNAIL_ALICE"
        
        (alice_uploads / "report.pdf").write_bytes(pdf_bytes)
        (alice_uploads / "data.csv").write_bytes(csv_bytes)
        (alice_uploads / "photo.png").write_bytes(png_bytes)
        (alice_data / "analysis.xlsx").write_bytes(xlsx_bytes)
        (alice_session_dir / "icon.svg").write_bytes(svg_bytes)
        (alice_thumbs / "photo.png").write_bytes(thumb_bytes)
        
        alice_history = [
            {
                "text": "Bitte analysiere diese Dateien [1 Bild(er), 2 Datei(en) angehängt]",
                "is_user": True,
                "image_urls": [f"/uploads/{alice_session_id}/photo.png"],
                "images": [{"url": f"/uploads/{alice_session_id}/photo.png", "width": 800, "height": 600}],
                "files": [
                    {
                        "name": "report.pdf",
                        "size": len(pdf_bytes),
                        "is_image": False,
                        "url": f"/uploads/{alice_session_id}/report.pdf",
                        "path": str(alice_uploads / "report.pdf")
                    },
                    {
                        "name": "data.csv",
                        "size": len(csv_bytes),
                        "is_image": False,
                        "url": f"/uploads/{alice_session_id}/data.csv",
                        "path": str(alice_uploads / "data.csv")
                    },
                    {
                        "name": "photo.png",
                        "size": len(png_bytes),
                        "is_image": True,
                        "url": f"/uploads/{alice_session_id}/photo.png",
                        "path": str(alice_uploads / "photo.png"),
                        "width": 800,
                        "height": 600
                    }
                ],
                "timestamp": "2026-08-22T20:00:00+00:00"
            },
            {
                "text": (
                    "<details class='ai-reasoning'>\n  <summary>Gedankengang der KI</summary>\n  <div class='reasoning-content'>\nBerechne Kennzahlen...\n  </div>\n</details>\n"
                    f"Hier ist die fertige Analyse: [Excel-Bericht](/app/data/{alice_user}/sessions/{alice_session_id}/data/analysis.xlsx) sowie das Bild [Foto](/uploads/{alice_session_id}/photo.png)."
                ),
                "is_user": False,
                "timestamp": "2026-08-22T20:00:05+00:00"
            }
        ]
        
        alice_session_data = {
            "id": alice_session_id,
            "title": "Finanzanalyse 2026",
            "created_at": "2026-08-22T20:00:00+00:00",
            "history": alice_history,
            "system_prompt": "Du bist ein erfahrener Finanzanalyst.",
            "include_gps": True
        }
        (alice_session_dir / "session.json").write_text(json.dumps(alice_session_data, indent=2), encoding="utf-8")
        
        # 2. Export as Alice
        current_test_user = alice_user
        export_resp = client.get(f"/api/sessions/{alice_session_id}/export")
        assert export_resp.status_code == 200
        zip_content = export_resp.content
        
        # 3. Verify ZIP contents
        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zf:
            names = zf.namelist()
            assert "session.json" in names
            assert "icon.svg" in names
            assert "uploads/report.pdf" in names
            assert "uploads/data.csv" in names
            assert "uploads/photo.png" in names
            assert "data/analysis.xlsx" in names
            # Exclude thumbnails
            assert not any("thumbnails" in n for n in names)
            
        # 4. Setup Bob's target session
        current_test_user = bob_user
        init_user_storage(bob_user)
        init_session_storage(bob_user, bob_session_id)
        (tmp_path / bob_user / "sessions" / bob_session_id / "session.json").write_text(
            json.dumps({"id": bob_session_id, "title": "Neuer Chat", "history": []}),
            encoding="utf-8"
        )
        
        # 5. Import into Bob's session
        files = {"file": ("exported_chat.zip", zip_content, "application/zip")}
        import_resp = client.post(f"/api/sessions/{bob_session_id}/import", files=files)
        assert import_resp.status_code == 200
        import_json = import_resp.json()
        assert import_json["success"] is True
        assert import_json["id"] == bob_session_id
        assert import_json["title"] == "Finanzanalyse 2026"
        assert import_json["has_icon"] is True
        
        # 6. Deep Verification on Bob's side
        bob_session_dir = tmp_path / bob_user / "sessions" / bob_session_id
        bob_session_file = bob_session_dir / "session.json"
        assert bob_session_file.exists()
        
        bob_data = json.loads(bob_session_file.read_text(encoding="utf-8"))
        assert bob_data["id"] == bob_session_id
        assert bob_data["title"] == "Finanzanalyse 2026"
        assert bob_data["system_prompt"] == "Du bist ein erfahrener Finanzanalyst."
        assert bob_data["include_gps"] is True
        
        # Files exist and are binary identical
        assert (bob_session_dir / "icon.svg").read_bytes() == svg_bytes
        assert (bob_session_dir / "uploads" / "report.pdf").read_bytes() == pdf_bytes
        assert (bob_session_dir / "uploads" / "data.csv").read_bytes() == csv_bytes
        assert (bob_session_dir / "uploads" / "photo.png").read_bytes() == png_bytes
        assert (bob_session_dir / "data" / "analysis.xlsx").read_bytes() == xlsx_bytes
        
        # Thumbnails folder in Bob's session should not contain old thumbnails
        bob_thumbs = bob_session_dir / "thumbnails"
        assert not bob_thumbs.exists() or len(list(bob_thumbs.iterdir())) == 0
        
        # History URL / path remapping verification
        bob_history = bob_data["history"]
        assert len(bob_history) == 2
        
        user_msg = bob_history[0]
        assert user_msg["image_urls"] == [f"/uploads/{bob_session_id}/photo.png"]
        assert user_msg["images"][0]["url"] == f"/uploads/{bob_session_id}/photo.png"
        
        files_meta = user_msg["files"]
        assert files_meta[0]["url"] == f"/uploads/{bob_session_id}/report.pdf"
        assert files_meta[0]["path"] == str(bob_session_dir / "uploads" / "report.pdf")
        assert files_meta[1]["url"] == f"/uploads/{bob_session_id}/data.csv"
        assert files_meta[1]["path"] == str(bob_session_dir / "uploads" / "data.csv")
        assert files_meta[2]["url"] == f"/uploads/{bob_session_id}/photo.png"
        assert files_meta[2]["path"] == str(bob_session_dir / "uploads" / "photo.png")
        
        ai_msg = bob_history[1]
        assert f"/app/data/{bob_user}/{bob_session_id}/data/analysis.xlsx" in ai_msg["text"]
        assert f"/uploads/{bob_session_id}/photo.png" in ai_msg["text"]
        assert alice_session_id not in ai_msg["text"]
        assert alice_user not in ai_msg["text"]
        
        # Verify file download endpoints for Bob
        dl_report = client.get(f"/uploads/{bob_session_id}/report.pdf")
        assert dl_report.status_code == 200
        assert dl_report.content == pdf_bytes
        
        dl_analysis = client.get(f"/app/data/{bob_user}/{bob_session_id}/data/analysis.xlsx")
        assert dl_analysis.status_code == 200
        assert dl_analysis.content == xlsx_bytes
        
        dl_icon = client.get(f"/api/sessions/{bob_session_id}/icon")
        assert dl_icon.status_code == 200
        assert dl_icon.content == svg_bytes


def test_session_export_import_logging(tmp_path, caplog):
    username = "testuser"
    session_id = "sess_log_01"
    
    with patch("app.storage.DATA_DIR", str(tmp_path)), patch("app.main.DATA_DIR", str(tmp_path)):
        init_user_storage(username)
        init_session_storage(username, session_id)
        session_file = tmp_path / username / "sessions" / session_id / "session.json"
        session_file.write_text(json.dumps({"id": session_id, "title": "Log Test", "history": []}), encoding="utf-8")
        
        import logging
        with caplog.at_level(logging.INFO):
            exp_resp = client.get(f"/api/sessions/{session_id}/export")
            assert exp_resp.status_code == 200
            
            imp_resp = client.post(f"/api/sessions/{session_id}/import", files={"file": ("log.zip", exp_resp.content, "application/zip")})
            assert imp_resp.status_code == 200
            
        logs = [rec.message for rec in caplog.records]
        assert any(f"exported session {session_id}" in msg or "export" in msg.lower() for msg in logs)
        assert any(f"imported session" in msg or "import" in msg.lower() for msg in logs)
