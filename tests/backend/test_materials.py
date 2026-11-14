"""
Tests for subjects, chapters, document uploads, parsing, and teacher isolation.
"""

import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.models.chapter import Chapter
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.subject import Subject
from app.models.user import User, UserRole
from app.core.security import hash_password


def _create_teacher(db_session, email="teacher@example.com"):
    """Insert a teacher directly so FK-bound rows (subjects) can be created."""
    teacher = User(
        email=email,
        name="Teacher",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
    )
    db_session.add(teacher)
    db_session.commit()
    return teacher


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


def test_process_document_marks_failed_via_fresh_session(client, db_session, monkeypatch):
    """A commit failure during processing must still persist status="failed".

    The session that stores the chunks simulates a connection Neon closed
    mid-work: its ``commit`` raises. The failure must then be written through a
    brand-new session, not the dead one (which is the bug that left documents
    stuck on "processing" forever).
    """
    import app.services.document_processor as processor

    token = register_and_login(client, "failpath@example.com", "Fail Path", "teacher")
    subj_id = client.post(
        "/subjects", json={"name": "Failure"}, headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]
    chap_id = client.post(
        f"/subjects/{subj_id}/chapters",
        json={"title": "Boom", "order": 1},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]

    doc = Document(
        filename="boom.txt",
        file_data=b"Photosynthesis converts light energy into chemical energy.",
        status="pending",
        chapter_id=chap_id,
    )
    db_session.add(doc)
    db_session.commit()
    doc_id = doc.id

    real_session_local = processor.SessionLocal
    calls = {"n": 0}

    class _DeadCommitSession:
        """Real session whose commit fails, like a Neon-closed connection."""

        def __init__(self, inner):
            self._inner = inner

        def commit(self):
            raise OperationalError("connection is closed", None, None)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def flaky_session_local():
        calls["n"] += 1
        inner = real_session_local()
        # 1st: mark "processing"; 2nd: store chunks (commit fails); 3rd: fresh session for "failed".
        if calls["n"] == 2:
            return _DeadCommitSession(inner)
        return inner

    monkeypatch.setattr(processor, "SessionLocal", flaky_session_local)

    processor.process_document(doc_id)

    # A fresh (3rd) session recorded the failure; no chunk was persisted.
    assert calls["n"] == 3
    db_session.expire_all()
    refreshed = db_session.get(Document, doc_id)
    assert refreshed.status == "failed"
    assert refreshed.error_message
    assert "connection is closed" in refreshed.error_message
    assert db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() == 0

    # The API schema must expose the error message to the UI.
    api_doc = client.get(
        f"/documents/{doc_id}", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert api_doc["status"] == "failed"
    assert api_doc["error_message"]


def test_recover_stuck_documents_marks_old_one_failed(db_session):
    from app.services.document_processor import STUCK_DOCUMENT_MESSAGE, recover_stuck_documents

    teacher = _create_teacher(db_session, "recovery@example.com")
    subj = Subject(name="Recovery", teacher_id=teacher.id)
    db_session.add(subj)
    db_session.commit()
    chap = Chapter(subject_id=subj.id, title="Ch 1", order=1)
    db_session.add(chap)
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    fresh = datetime.now(timezone.utc)

    stuck_processing = Document(filename="a.pdf", status="processing", chapter_id=chap.id, uploaded_at=old)
    stuck_pending = Document(filename="b.pdf", status="pending", chapter_id=chap.id, uploaded_at=old)
    recent_pending = Document(filename="c.pdf", status="pending", chapter_id=chap.id, uploaded_at=fresh)
    already_done = Document(filename="d.pdf", status="ready", chapter_id=chap.id, uploaded_at=old)
    db_session.add_all([stuck_processing, stuck_pending, recent_pending, already_done])
    db_session.commit()

    recovered = recover_stuck_documents(db_session)
    assert recovered == 2

    db_session.expire_all()
    assert db_session.get(Document, stuck_processing.id).status == "failed"
    assert db_session.get(Document, stuck_processing.id).error_message == STUCK_DOCUMENT_MESSAGE
    assert db_session.get(Document, stuck_pending.id).status == "failed"
    # Recent and already-finished documents are left untouched.
    assert db_session.get(Document, recent_pending.id).status == "pending"
    assert db_session.get(Document, already_done.id).status == "ready"


def test_startup_recovers_stuck_documents(db_session):
    from app.main import on_startup
    from app.services.document_processor import STUCK_DOCUMENT_MESSAGE

    teacher = _create_teacher(db_session, "startup@example.com")
    subj = Subject(name="Startup", teacher_id=teacher.id)
    db_session.add(subj)
    db_session.commit()
    chap = Chapter(subject_id=subj.id, title="Ch", order=1)
    db_session.add(chap)
    db_session.commit()

    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    doc = Document(filename="stuck.pdf", status="processing", chapter_id=chap.id, uploaded_at=old)
    db_session.add(doc)
    db_session.commit()
    doc_id = doc.id

    # Startup performs the recovery with plain DB reads/writes (no network/model calls).
    on_startup()

    db_session.expire_all()
    refreshed = db_session.get(Document, doc_id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == STUCK_DOCUMENT_MESSAGE


def test_reprocess_endpoint_deletes_chunks_and_requeues(client, db_session, monkeypatch):
    token = register_and_login(client, "reprocess@example.com", "Reprocess Teacher", "teacher")
    other_token = register_and_login(client, "reprocess_other@example.com", "Other Teacher", "teacher")
    student_token = register_and_login(client, "reprocess_student@example.com", "Reprocess Student", "student")

    subj_id = client.post(
        "/subjects", json={"name": "Astronomy"}, headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]
    chap_id = client.post(
        f"/subjects/{subj_id}/chapters",
        json={"title": "Stars", "order": 1},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]

    upload = client.post(
        f"/chapters/{chap_id}/documents/upload",
        files={"file": ("stars.txt", io.BytesIO(b"Stars are massive luminous spheres of plasma."), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert upload.status_code == 202
    doc_id = upload.json()["id"]
    assert db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() > 0

    # Pretend the document previously failed.
    doc = db_session.get(Document, doc_id)
    doc.status = "failed"
    doc.error_message = "previous attempt exploded"
    db_session.commit()

    # Do not actually re-run the slow processing during this request.
    requeued = {}
    monkeypatch.setattr("app.api.documents.process_document", lambda did: requeued.setdefault("id", did))

    # A teacher who does not own the document is rejected.
    assert client.post(
        f"/documents/{doc_id}/reprocess", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 403
    # Students cannot reprocess (teacher-only).
    assert client.post(
        f"/documents/{doc_id}/reprocess", headers={"Authorization": f"Bearer {student_token}"}
    ).status_code == 403

    res = client.post(
        f"/documents/{doc_id}/reprocess", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "pending"
    assert body["error_message"] is None
    assert requeued.get("id") == doc_id

    db_session.expire_all()
    assert db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() == 0
