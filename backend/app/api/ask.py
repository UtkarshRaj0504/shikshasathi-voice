"""
RAG Question Answering API endpoint (/ask).
"""

import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_student
from app.models.user import User
from app.models.document_chunk import DocumentChunk
from app.models.document import Document
from app.models.chapter import Chapter
from app.services.embedding_service import embedding_service
from app.services.llm_service import (
    get_llm_service,
    GeminiRateLimitError,
    GeminiTimeoutError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ask"])

LANGUAGE_NAMES: dict[str, str] = {
    "indic-auto": "the language of the student's question (e.g. Hindi, Kannada, Tamil, Telugu, English)",
    "auto": "the language of the student's question",
    "en": "English",
    "en-IN": "Indian English",
    "hi": "Hindi (हिन्दी)",
    "hi-IN": "Hindi (हिन्दी)",
    "kn": "Kannada (ಕನ್ನಡ)",
    "kn-IN": "Kannada (ಕನ್ನಡ)",
    "ta": "Tamil (தமிழ்)",
    "ta-IN": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)",
    "te-IN": "Telugu (తెలుగు)",
    "mr": "Marathi (मराठी)",
    "mr-IN": "Marathi (मराठी)",
    "gu": "Gujarati (ગુજરાતી)",
    "gu-IN": "Gujarati (ગુજરાતી)",
    "bn": "Bengali (বাংলা)",
    "bn-IN": "Bengali (বাংলা)",
    "ml": "Malayalam (മലയാളം)",
    "ml-IN": "Malayalam (മലയാളം)",
    "pa": "Punjabi (ਪੰਜਾਬੀ)",
    "pa-IN": "Punjabi (ਪੰਜਾਬੀ)",
    "as": "Assamese (অসমীয়া)",
    "as-IN": "Assamese (অসমীয়া)",
    "or": "Odia (ଓଡ଼ିଆ)",
    "or-IN": "Odia (ଓଡ଼ିଆ)",
}

LEVEL_INSTRUCTIONS: dict[str, str] = {
    "beginner": "Use simple, accessible language with everyday real-world examples and analogies. Avoid dense jargon.",
    "intermediate": "Provide a clear, balanced educational explanation with relevant textbook concepts and examples.",
    "advanced": "Provide an in-depth, rigorous, comprehensive explanation detailing core principles, nuances, and technical depth.",
}


def compute_lexical_similarity(query: str, content: str) -> float:
    """Calculate token overlap similarity between question and chunk content."""
    stop_words = {
        "what", "is", "a", "an", "the", "in", "of", "to", "and", "or", "for", "on",
        "with", "at", "by", "from", "up", "about", "into", "over", "after", "can",
        "you", "explain", "tell", "me", "how", "why", "does", "do", "did", "are",
        "were", "was", "be", "been", "being", "have", "has", "had", "define", "describe",
    }
    q_tokens = set(re.findall(r"\w+", query.lower())) - stop_words
    if not q_tokens:
        q_tokens = set(re.findall(r"\w+", query.lower()))
    if not q_tokens:
        return 0.0
    c_tokens = set(re.findall(r"\w+", content.lower()))
    overlap = q_tokens.intersection(c_tokens)
    return float(len(overlap) / len(q_tokens))


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    chapter_id: int | None = None
    current_page: int | None = None
    answer_language: str = Field(
        default="en",
        pattern=r"^(auto|indic-auto|[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)?)$"
    )
    level: str = Field(default="intermediate", pattern="^(beginner|intermediate|advanced)$")
    history: list[dict] = Field(default_factory=list)


class SourceItem(BaseModel):
    document_name: str
    excerpt: str
    page_number: int | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    grounded: bool
    debug: dict | None = None  # Added for RAG_DEBUG mode


@router.post("/ask", response_model=AskResponse)
def ask_question(
    body: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    """
    Student-only RAG question answering endpoint.
    Searches document chunks by semantic and lexical relevance, checks threshold,
    and prompts the LLM to answer strictly from retrieved material.
    """
    # 1. Generate query embedding using query prefix
    query_emb = embedding_service.embed_query(body.question)

    # 2. Vector & keyword similarity search over DocumentChunk
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == "ready")
    )

    if body.chapter_id is not None:
        stmt = stmt.join(Chapter, Document.chapter_id == Chapter.id).where(Chapter.id == body.chapter_id)

    is_postgres = False
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    if is_postgres:
        try:
            from pgvector.sqlalchemy import Vector
            pg_stmt = stmt.order_by(DocumentChunk.embedding.cosine_distance(query_emb)).limit(6)
            rows = db.execute(pg_stmt).all()
        except Exception:
            rows = db.execute(stmt).all()
    else:
        rows = db.execute(stmt).all()

    import numpy as np

    def _as_vector(value):
        """Coerce a stored embedding (list, JSON string, or pgvector array) to a 1-D float array."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return None
        if value is None:
            return None
        try:
            return np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return None

    query_dim = len(query_emb)

    def cosine_sim(a, b):
        a_arr = _as_vector(a)
        b_arr = _as_vector(b)
        if a_arr is None or b_arr is None:
            return 0.0
        if a_arr.ndim != 1 or b_arr.ndim != 1 or a_arr.size == 0 or a_arr.size != b_arr.size:
            # Dimension mismatch: the chunk was embedded with a different model.
            return 0.0
        norm_a = float(np.linalg.norm(a_arr))
        norm_b = float(np.linalg.norm(b_arr))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

    scored = []
    dimension_mismatch = 0
    for chunk, doc in rows:
        content = chunk.content or ""
        if not content.strip():
            continue
        chunk_vec = _as_vector(chunk.embedding)
        if chunk_vec is None or chunk_vec.ndim != 1 or chunk_vec.size != query_dim:
            # Stale embedding (embedded with an older model / different dimension).
            # Cannot be compared with the query vector: re-embed before it can match.
            dimension_mismatch += 1
            continue
        v_sim = cosine_sim(chunk_vec, query_emb)
        l_sim = compute_lexical_similarity(body.question, content)
        # Hybrid relevance: best of semantic similarity and keyword overlap.
        relevance = max(v_sim, l_sim)
        # Boost chunks matching the student's active reader page
        if body.current_page is not None and getattr(chunk, "page_number", None) == body.current_page:
            relevance += 0.2
        scored.append({
            "relevance": relevance,
            "v_sim": v_sim,
            "l_sim": l_sim,
            "chunk": chunk,
            "doc": doc,
        })

    scored.sort(key=lambda item: item["relevance"], reverse=True)

    matched_rows = [
        (item["chunk"], item["doc"])
        for item in scored[:4]
        if item["relevance"] >= settings.SIMILARITY_THRESHOLD
    ]

    # Debug detail is only returned (and logged) when RAG_DEBUG is enabled.
    debug_info = None
    if settings.RAG_DEBUG:
        debug_info = {
            "query": body.question[:100],
            "answer_language": body.answer_language,
            "embedding_model": embedding_service.active_model_name,
            "query_dimension": query_dim,
            "threshold": settings.SIMILARITY_THRESHOLD,
            "candidate_count": len(scored),
            "dimension_mismatch_chunks": dimension_mismatch,
            "matched_chunk_ids": [item["chunk"].id for item in scored[:4] if item["relevance"] >= settings.SIMILARITY_THRESHOLD],
            "scored_chunks": [
                {
                    "chunk_id": item["chunk"].id,
                    "document_id": item["doc"].id,
                    "doc": item["doc"].filename,
                    "page": getattr(item["chunk"], "page_number", None),
                    "score": round(item["relevance"], 4),
                    "vector_score": round(item["v_sim"], 4),
                    "keyword_score": round(item["l_sim"], 4),
                    "content_preview": (item["chunk"].content or "")[:80],
                }
                for item in scored[:10]
            ],
        }
        logger.info("RAG debug retrieval: %s", debug_info)

    if not matched_rows:
        return AskResponse(
            answer="This isn't in the uploaded material.",
            sources=[],
            grounded=False,
            debug=debug_info
        )

    context_texts = []
    sources = []
    for chunk, doc in matched_rows:
        page_info = f" (Page {chunk.page_number})" if getattr(chunk, "page_number", None) else ""
        context_texts.append(f"[{doc.filename}{page_info}]: {chunk.content}")
        sources.append(
            SourceItem(
                document_name=doc.filename,
                excerpt=chunk.content[:200] + "...",
                page_number=getattr(chunk, "page_number", None)
            )
        )

    context_str = "\n\n".join(context_texts)

    target_lang = LANGUAGE_NAMES.get(body.answer_language, body.answer_language)
    level_instruction = LEVEL_INSTRUCTIONS.get(body.level, f"comprehension level '{body.level}'")

    system_prompt = (
        "You are ShikshaSaathi, an expert multilingual educational AI tutor for students. "
        "Your mission is to help students learn and understand study concepts clearly.\n\n"
        "Guidelines:\n"
        "1. Grounding: Answer the student's question using the provided Study Material Context. "
        "Explain the concepts accurately based on the material.\n"
        "2. If the context does not contain sufficient information to answer the question, clearly state that "
        "this isn't in the uploaded material.\n"
        f"3. Language: Answer in {target_lang}. If the source material is in English and the student requests or speaks another language, "
        f"translate and explain the concepts accurately in {target_lang}.\n"
        f"4. Pedagogical Level: {level_instruction}\n"
        "5. Tone: Encouraging, supportive, clear, and educational."
    )

    history_str = ""
    if body.history:
        turns = []
        for turn in body.history[-6:]:
            role_name = "Student" if turn.get("role") in ["user", "student"] else "Tutor"
            txt = (turn.get("content") or "").strip()
            if txt:
                turns.append(f"{role_name}: {txt}")
        if turns:
            history_str = "Prior Conversation History:\n" + "\n".join(turns) + "\n\n"

    user_prompt = (
        f"Study Material Context:\n{context_str}\n\n"
        f"{history_str}"
        f"Student Question: {body.question}\n\n"
        f"Please provide an educational explanation in {target_lang} suitable for a {body.level} learner based on the study material."
    )

    llm_service = get_llm_service()
    try:
        answer = llm_service.generate_answer(user_prompt, system_prompt=system_prompt)
    except GeminiRateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"LLM generation error: {str(e)}"
        )
    except GeminiTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM generation error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM generation error: {str(e)}"
        )

    return AskResponse(
        answer=answer,
        sources=sources,
        grounded=True,
        debug=debug_info
    )
