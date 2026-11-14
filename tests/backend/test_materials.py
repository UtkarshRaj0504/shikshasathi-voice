"""
Tests for subjects, chapters, document uploads, parsing, and teacher isolation.
"""

import io
import pytest
from app.models.document import Document


def register_and_login(client, email, name, role):
    client.post("/auth/register", json={
        "email": email,
        "name": name,
        "password": "password123",
        "role": role
    })
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def test_subject_crud_and_isolation(client):
    token_a = register_and_login(client, "teacherA@example.com", "Teacher A", "teacher")
    token_b = register_and_login(client, "teacherB@example.com", "Teacher B", "teacher")

    # Teacher A creates subject
    res = client.post(
        "/subjects",
        json={"name": "Physics", "description": "Mechanics & Optics"},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res.status_code == 201
    subj = res.json()
    assert subj["name"] == "Physics"
    subj_id = subj["id"]

    # Teacher A lists subjects -> sees Physics
    list_res = client.get("/subjects", headers={"Authorization": f"Bearer {token_a}"})
    assert len(list_res.json()) == 1

    # Teacher B lists subjects -> sees 0 subjects (isolation)
    list_res_b = client.get("/subjects", headers={"Authorization": f"Bearer {token_b}"})
    assert len(list_res_b.json()) == 0

    # Teacher B tries to get Teacher A's subject -> 404
    get_b = client.get(f"/subjects/{subj_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert get_b.status_code == 404


def test_chapter_crud(client):
    token = register_and_login(client, "prof@example.com", "Prof", "teacher")
    subj_id = client.post(
        "/subjects",
        json={"name": "Chemistry"},
        headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]

    # Create chapter
    chap_res = client.post(
        f"/subjects/{subj_id}/chapters",
        json={"title": "Atomic Structure", "order": 1},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert chap_res.status_code == 201
    chap = chap_res.json()
    assert chap["title"] == "Atomic Structure"
    chap_id = chap["id"]

    # List chapters
    chapters = client.get(f"/subjects/{subj_id}/chapters", headers={"Authorization": f"Bearer {token}"}).json()
    assert len(chapters) == 1

    # Delete chapter
    del_res = client.delete(f"/subjects/chapters/{chap_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 204


def test_document_upload_and_processing(client, db_session):
    token = register_and_login(client, "uploadprof@example.com", "Upload Prof", "teacher")
    subj_id = client.post(
        "/subjects",
        json={"name": "Biology"},
        headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]
    chap_id = client.post(
        f"/subjects/{subj_id}/chapters",
        json={"title": "Cell Biology"},
        headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]

    # Upload TXT file
    file_content = b"The cell is the basic structural and functional unit of all known living organisms."
    response = client.post(
        f"/chapters/{chap_id}/documents/upload",
        files={"file": ("cell_biology.txt", io.BytesIO(file_content), "text/plain")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202
    doc_data = response.json()
    assert doc_data["filename"] == "cell_biology.txt"
    doc_id = doc_data["id"]

    # Verify background processing ran (TestClient runs background tasks synchronously)
    doc_status = client.get(f"/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}).json()
    assert doc_status["status"] == "ready"


def test_database_storage_upload_stream_and_delete(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.documents.settings.STORAGE_PROVIDER", "database")
    token = register_and_login(client, "databaseprof@example.com", "Database Prof", "teacher")
    subj_id = client.post(
        "/subjects",
        json={"name": "Botany"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    chap_id = client.post(
        f"/subjects/{subj_id}/chapters",
        json={"title": "Plant Cells"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    content = b"Chloroplasts capture light energy for photosynthesis."

    response = client.post(
        f"/chapters/{chap_id}/documents/upload",
        files={"file": ("plant_cells.txt", io.BytesIO(content), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    document_id = response.json()["id"]
    document = db_session.get(Document, document_id)
    assert document is not None
    assert document.file_path is None
    assert document.file_data == content
    assert document.status == "ready"

    streamed = client.get(
        f"/documents/{document_id}/file",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert streamed.status_code == 200
    assert streamed.content == content
    assert "plant_cells.txt" in streamed.headers["content-disposition"]

    deleted = client.delete(
        f"/documents/{document_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 204
    assert db_session.get(Document, document_id) is None


def test_document_upload_invalid_type(client):
    token = register_and_login(client, "badprof@example.com", "Bad Prof", "teacher")
    subj_id = client.post("/subjects", json={"name": "Math"}, headers={"Authorization": f"Bearer {token}"}).json()["id"]
    chap_id = client.post(f"/subjects/{subj_id}/chapters", json={"title": "Algebra"}, headers={"Authorization": f"Bearer {token}"}).json()["id"]

    response = client.post(
        f"/chapters/{chap_id}/documents/upload",
        files={"file": ("malware.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_document_upload_oversized(client):
    token = register_and_login(client, "bigprof@example.com", "Big Prof", "teacher")
    subj_id = client.post("/subjects", json={"name": "History"}, headers={"Authorization": f"Bearer {token}"}).json()["id"]
    chap_id = client.post(f"/subjects/{subj_id}/chapters", json={"title": "Ancient History"}, headers={"Authorization": f"Bearer {token}"}).json()["id"]

    # 21MB dummy file (> 20MB limit)
    large_data = b"a" * (21 * 1024 * 1024)
    response = client.post(
        f"/chapters/{chap_id}/documents/upload",
        files={"file": ("huge.txt", io.BytesIO(large_data), "text/plain")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 413
    assert "exceeds maximum size" in response.json()["detail"]
