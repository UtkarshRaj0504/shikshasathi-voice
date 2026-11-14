"""
Tests for RAG question answering (/ask) endpoint and LLM service integration.
"""

import pytest
from unittest.mock import patch
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.chapter import Chapter
from app.models.subject import Subject
from app.services.embedding_service import embedding_service


def register_and_login(client, email, name, role):
    client.post("/auth/register", json={
        "email": email,
        "name": name,
        "password": "password123",
        "role": role
    })
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def test_ask_unauthenticated(client):
    response = client.post(
        "/ask",
        json={"question": "What is photosynthesis?", "answer_language": "en", "level": "intermediate"}
    )
    assert response.status_code == 401


def test_ask_teacher_forbidden(client):
    teacher_token = register_and_login(client, "prof_ask@example.com", "Prof Ask", "teacher")
    response = client.post(
        "/ask",
        json={"question": "What is photosynthesis?", "answer_language": "en", "level": "intermediate"},
        headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert response.status_code == 403


def test_ask_no_chunks_grounded_false(client):
    student_token = register_and_login(client, "student_ask1@example.com", "Student Ask 1", "student")
    response = client.post(
        "/ask",
        json={"question": "What is quantum mechanics?", "answer_language": "en", "level": "beginner"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grounded"] is False
    assert "isn't in the uploaded material" in data["answer"]
    assert data["sources"] == []


def test_ask_success_grounded_true(client, db_session):
    teacher_token = register_and_login(client, "teacher_bio@example.com", "Teacher Bio", "teacher")
    student_token = register_and_login(client, "student_bio@example.com", "Student Bio", "student")

    # Create subject, chapter, document, and chunk in DB
    subject = Subject(name="Biology", teacher_id=1)
    db_session.add(subject)
    db_session.commit()

    chapter = Chapter(subject_id=subject.id, title="Cell Division", order=1)
    db_session.add(chapter)
    db_session.commit()

    document = Document(chapter_id=chapter.id, filename="biology_notes.txt", file_path="./uploads/bio.txt", status="ready")
    db_session.add(document)
    db_session.commit()

    chunk_content = "Photosynthesis is the process used by plants to convert light energy into chemical energy."
    chunk_emb = embedding_service.embed_passage(chunk_content)

    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=chunk_content,
        embedding=chunk_emb
    )
    db_session.add(chunk)
    db_session.commit()

    response = client.post(
        "/ask",
        json={
            "question": "Photosynthesis",
            "chapter_id": chapter.id,
            "answer_language": "en",
            "level": "intermediate"
        },
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grounded"] is True
    assert "Photosynthesis" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["document_name"] == "biology_notes.txt"


def test_ask_llm_error_handling(client, db_session):
    student_token = register_and_login(client, "student_err@example.com", "Student Err", "student")

    # Seed chunk
    subject = Subject(name="Physics", teacher_id=1)
    db_session.add(subject)
    db_session.commit()
    chapter = Chapter(subject_id=subject.id, title="Mechanics", order=1)
    db_session.add(chapter)
    db_session.commit()
    document = Document(chapter_id=chapter.id, filename="physics.txt", file_path="./uploads/phys.txt", status="ready")
    db_session.add(document)
    db_session.commit()

    chunk_content = "Newton's second law states F equals m times a."
    chunk_emb = embedding_service.embed_passage(chunk_content)

    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=chunk_content,
        embedding=chunk_emb
    )
    db_session.add(chunk)
    db_session.commit()

    with patch("app.api.ask.get_llm_service") as mock_get_llm:
        mock_llm = mock_get_llm.return_value
        mock_llm.generate_answer.side_effect = Exception("LLM API failure")

        response = client.post(
            "/ask",
            json={
                "question": "Newton's second law",
                "answer_language": "en",
                "level": "beginner"
            },
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 502
        assert "LLM generation error" in response.json()["detail"]


def test_ask_indic_auto_language(client, db_session):
    student_token = register_and_login(client, "student_indic@example.com", "Student Indic", "student")

    subject = Subject(name="Chemistry", teacher_id=1)
    db_session.add(subject)
    db_session.commit()
    chapter = Chapter(subject_id=subject.id, title="Acids and Bases", order=1)
    db_session.add(chapter)
    db_session.commit()
    document = Document(chapter_id=chapter.id, filename="chemistry.txt", file_path="./uploads/chem.txt", status="ready")
    db_session.add(document)
    db_session.commit()

    chunk_content = "Acids taste sour and change blue litmus paper to red."
    chunk_emb = embedding_service.embed_passage(chunk_content)
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=chunk_content,
        embedding=chunk_emb,
    )
    db_session.add(chunk)
    db_session.commit()

    with patch("app.api.ask.get_llm_service") as mock_get_llm:
        mock_llm = mock_get_llm.return_value
        mock_llm.generate_answer.return_value = "Acids taste sour and turn blue litmus red."

        response = client.post(
            "/ask",
            json={
                "question": "What are acids?",
                "chapter_id": chapter.id,
                "answer_language": "indic-auto",
                "level": "intermediate"
            },
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["grounded"] is True
        assert len(data["sources"]) == 1


def test_ask_rate_limit_error(client, db_session):
    from app.services.llm_service import GeminiRateLimitError

    student_token = register_and_login(client, "student_rl@example.com", "Student RL", "student")

    subject = Subject(name="History", teacher_id=1)
    db_session.add(subject)
    db_session.commit()
    chapter = Chapter(subject_id=subject.id, title="Ancient India", order=1)
    db_session.add(chapter)
    db_session.commit()
    document = Document(chapter_id=chapter.id, filename="history.txt", file_path="./uploads/hist.txt", status="ready")
    db_session.add(document)
    db_session.commit()

    chunk_content = "The Indus Valley Civilization flourished around 2500 BCE."
    chunk_emb = embedding_service.embed_passage(chunk_content)
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=chunk_content,
        embedding=chunk_emb,
    )
    db_session.add(chunk)
    db_session.commit()

    with patch("app.api.ask.get_llm_service") as mock_get_llm:
        mock_llm = mock_get_llm.return_value
        mock_llm.generate_answer.side_effect = GeminiRateLimitError("Gemini API rate limit exceeded (429). Please try again in a minute.")

        response = client.post(
            "/ask",
            json={
                "question": "Indus Valley Civilization",
                "answer_language": "en",
                "level": "intermediate"
            },
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 429
        assert "try again in a minute" in response.json()["detail"]
