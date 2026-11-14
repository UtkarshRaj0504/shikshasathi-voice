"""
Tests for RAG question answering (/ask) endpoint and LLM service integration.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.chapter import Chapter
from app.models.subject import Subject
from app.services.embedding_service import EMBEDDING_DIMENSION, embedding_service
from app.api.ask import NOT_IN_MATERIAL_MARKER


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


# ---------------------------------------------------------------------------
# BUG 1 regression tests: RAG grounding false negatives
# ---------------------------------------------------------------------------

class FakeEmbeddingService:
    """Deterministic embedding stand-in for tests (no model download, no network).

    Texts about the same topic map to an identical unit vector; unrelated topics
    map to orthogonal vectors, so semantic scores are fully predictable.
    """

    dimension = EMBEDDING_DIMENSION
    active_model_name = "fake-test-model"
    TOPICS = {"photosynthesis": 0, "cricket": 1, "grammar": 2}

    def _vec(self, text: str):
        vec = np.zeros(EMBEDDING_DIMENSION)
        lowered = (text or "").lower()
        for topic, idx in self.TOPICS.items():
            if topic in lowered:
                vec[idx] = 1.0
                return vec.tolist()
        vec[EMBEDDING_DIMENSION - 1] = 1.0
        return vec.tolist()

    def embed_query(self, text):
        return self._vec(text)

    def embed_passage(self, text):
        return self._vec(text)

    def embed_texts(self, texts, is_query=False):
        return [self._vec(t) for t in texts]


class FakeLLMService:
    """Deterministic LLM stand-in (no network).

    ``translation`` simulates translating a non-English question; ``answer`` is
    what the model returns for a grounded question. Returning the refusal marker
    simulates the model deciding the material does not contain the answer.
    """

    def __init__(self, answer: str = "Photosynthesis turns light energy into chemical energy.", translation: str | None = None):
        self._answer = answer
        self._translation = translation
        self.rewrite_calls: list[str] = []
        self.last_prompt: str | None = None
        self.last_system_prompt: str | None = None

    def rewrite_query(self, question: str, target_language: str = "English") -> str:
        self.rewrite_calls.append(question)
        return self._translation if self._translation is not None else question

    def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt
        return self._answer


def _create_materials(db_session, filename, content, embedding, embedding_model="fake-test-model"):
    subject = Subject(name="Science", teacher_id=1)
    db_session.add(subject)
    db_session.commit()
    chapter = Chapter(subject_id=subject.id, title="Chapter 1", order=1)
    db_session.add(chapter)
    db_session.commit()
    document = Document(chapter_id=chapter.id, filename=filename, file_path="./uploads/x.txt", status="ready")
    db_session.add(document)
    db_session.commit()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=content,
        embedding=embedding,
        embedding_model=embedding_model,
    )
    db_session.add(chunk)
    db_session.commit()
    return chapter, document, chunk


def _student_and_token(client, suffix):
    register_and_login(client, f"teacher_{suffix}@example.com", "Teacher", "teacher")
    return register_and_login(client, f"student_{suffix}@example.com", "Student", "student")


def test_embedding_dimension_is_384():
    """The active embedding service must produce 384-dim vectors (e5-small), not the legacy 1536."""
    assert EMBEDDING_DIMENSION == 384
    assert embedding_service.dimension == 384


def test_embedding_service_applies_e5_prefixes():
    """Both query and passage sides must apply the e5 'query: ' / 'passage: ' prefixes."""
    from app.services.embedding_service import SentenceTransformerEmbeddingService

    svc = SentenceTransformerEmbeddingService()

    class _Emb:
        def tolist(self):
            return [0.0] * EMBEDDING_DIMENSION

    fake_model = MagicMock()
    fake_model.encode.return_value = [_Emb()]
    svc._model = fake_model

    svc.embed_query("hello")
    assert fake_model.encode.call_args[0][0] == ["query: hello"]

    svc.embed_passage("hello")
    assert fake_model.encode.call_args[0][0] == ["passage: hello"]

    svc.embed_texts(["a", "b"], is_query=True)
    assert fake_model.encode.call_args[0][0] == ["query: a", "query: b"]


def test_ask_answered_from_notes(client, db_session):
    """A question clearly answered by the uploaded notes must be grounded (not refused)."""
    token = _student_and_token(client, "notes")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    with patch("app.api.ask.embedding_service", fake):
        res = client.post(
            "/ask",
            json={"question": "What is photosynthesis?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["grounded"] is True
    assert data["debug"] is None  # RAG_DEBUG is off by default
    assert any(s["document_name"] == "biology.txt" for s in data["sources"])


def test_ask_out_of_scope_question_refused(client, db_session):
    """A genuinely out-of-scope question must be refused.

    The refusal now comes from the LLM's marker (the similarity floor never
    decides on its own), so the fake LLM returns the marker for this material.
    """
    token = _student_and_token(client, "oop")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    llm = FakeLLMService(answer=NOT_IN_MATERIAL_MARKER)
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        res = client.post(
            "/ask",
            json={"question": "Who won the cricket world cup?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["grounded"] is False
    assert data["sources"] == []
    assert "isn't in the uploaded material" in data["answer"]


def test_ask_refusal_comes_from_llm_marker_not_the_threshold(client, db_session, monkeypatch):
    """Even when chunks score below the floor, the chunk is still passed to the LLM."""
    monkeypatch.setattr(settings, "RAG_DEBUG", True)
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", 1.5)  # nothing can clear this floor
    token = _student_and_token(client, "floor")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    # An in-scope question that the LLM *does* answer must stay grounded even though
    # its score is below the (deliberately impossible) floor.
    llm = FakeLLMService(answer="Photosynthesis turns light energy into chemical energy.")
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        res = client.post(
            "/ask",
            json={"question": "What is photosynthesis?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    data = res.json()
    assert data["grounded"] is True
    assert data["debug"]["below_threshold_fallback"] is True
    assert data["debug"]["matched_chunk_ids"] == [chunk.id]


def test_ask_hindi_question_retrieves_english_chunk(client, db_session, monkeypatch):
    """A Hindi question must retrieve the correct English chunk via query rewriting."""
    monkeypatch.setattr(settings, "RAG_DEBUG", True)
    token = _student_and_token(client, "hindi")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    hindi_question = "प्रकाश संश्लेषण क्या है?"
    llm = FakeLLMService(translation="What is photosynthesis?")
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        res = client.post(
            "/ask",
            json={"question": hindi_question, "chapter_id": chapter.id, "answer_language": "hi", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert llm.rewrite_calls == [hindi_question]
    assert data["grounded"] is True
    assert any(s["document_name"] == "biology.txt" for s in data["sources"])
    # Original + rewritten query were both used for retrieval.
    assert data["debug"]["queries_used"] == [hindi_question, "What is photosynthesis?"]


def test_ask_kannada_question_retrieves_english_chunk(client, db_session):
    """A Kannada question must retrieve the correct English chunk via query rewriting."""
    token = _student_and_token(client, "kannada")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    kannada_question = "ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ ಎಂದರೇನು?"
    llm = FakeLLMService(translation="What is photosynthesis?")
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        res = client.post(
            "/ask",
            json={"question": kannada_question, "chapter_id": chapter.id, "answer_language": "kn", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert llm.rewrite_calls == [kannada_question]
    assert data["grounded"] is True
    assert any(s["document_name"] == "biology.txt" for s in data["sources"])


def test_ask_english_question_is_not_rewritten(client, db_session):
    """An English question must not trigger a translation round-trip."""
    token = _student_and_token(client, "no_rewrite")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    llm = FakeLLMService(translation="SHOULD NOT BE USED")
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        res = client.post(
            "/ask",
            json={"question": "What is photosynthesis?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    assert llm.rewrite_calls == []
    assert res.json()["grounded"] is True


def test_ask_prompt_includes_question_and_answer_language(client, db_session):
    """The (English) prompt must mention both the question language and the answer language."""
    token = _student_and_token(client, "prompt")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    llm = FakeLLMService()
    with patch("app.api.ask.embedding_service", fake), patch("app.api.ask.get_llm_service", return_value=llm):
        client.post(
            "/ask",
            json={
                "question": "What is photosynthesis?",
                "chapter_id": chapter.id,
                "question_language": "hi",
                "answer_language": "kn",
                "level": "intermediate",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert "Hindi" in llm.last_system_prompt
    assert "Kannada" in llm.last_system_prompt
    # Instructions stay in English and ask for the refusal marker.
    assert NOT_IN_MATERIAL_MARKER in llm.last_system_prompt
    assert NOT_IN_MATERIAL_MARKER in llm.last_prompt



def test_ask_reembedded_document_becomes_retrievable(client, db_session):
    """Chunks embedded with a legacy model/dimension must be re-embeddable and retrievable again."""
    from app.services.document_processor import reembed_document_chunks

    token = _student_and_token(client, "reembed")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."

    # Simulate a chunk indexed by the old 1536-dim placeholder model.
    legacy_embedding = [0.01] * 1536
    chapter, document, chunk = _create_materials(
        db_session, "legacy.txt", content, legacy_embedding, embedding_model="legacy-placeholder-1536"
    )

    payload = {"question": "What is photosynthesis?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"}

    with patch("app.api.ask.embedding_service", fake):
        before = client.post("/ask", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert before.json()["grounded"] is False  # stale dimension -> not comparable

    with patch("app.services.document_processor.embedding_service", fake):
        count = reembed_document_chunks(document.id, db_session)
    assert count == 1

    db_session.expire_all()
    with patch("app.api.ask.embedding_service", fake):
        after = client.post("/ask", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert after.json()["grounded"] is True


def test_ask_returns_debug_when_rag_debug_enabled(client, db_session, monkeypatch):
    """When RAG_DEBUG is on, /ask returns chunk ids and scores for collapsible UI display."""
    monkeypatch.setattr(settings, "RAG_DEBUG", True)
    token = _student_and_token(client, "debug")
    fake = FakeEmbeddingService()
    content = "Photosynthesis is the process plants use to convert light energy into chemical energy."
    chapter, document, chunk = _create_materials(db_session, "biology.txt", content, fake.embed_passage(content))

    with patch("app.api.ask.embedding_service", fake):
        res = client.post(
            "/ask",
            json={"question": "What is photosynthesis?", "chapter_id": chapter.id, "answer_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {token}"},
        )

    data = res.json()
    assert data["debug"] is not None
    assert data["debug"]["embedding_model"] == "fake-test-model"
    assert data["debug"]["query_dimension"] == EMBEDDING_DIMENSION
    assert data["debug"]["scored_chunks"][0]["chunk_id"] == chunk.id
    assert data["debug"]["matched_chunk_ids"] == [chunk.id]

