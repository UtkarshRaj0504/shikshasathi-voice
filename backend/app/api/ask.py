"""
RAG Question Answering API endpoint (/ask).

Retrieval strategy (see docs/DECISIONS.md):
  * hybrid relevance = max(vector similarity, lexical overlap);
  * the similarity threshold is only a *lenient floor* — it never decides on its
    own that material is missing (rank-based fallback keeps the best chunk);
  * a non-English question is rewritten into English by the LLM and retrieved
    with both phrasings, merging the best score per chunk;
  * the "not covered" decision comes from the LLM refusing with a clear marker.
"""

import json
import logging
import re

import numpy as np
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

#: The LLM must reply with exactly this marker when the retrieved context does
#: not actually contain the answer. ``grounded`` is derived from it (never from
#: a raw similarity score alone).
NOT_IN_MATERIAL_MARKER = "NOT_IN_STUDY_MATERIAL"

#: Student-facing message shown when the material genuinely lacks the answer.
REFUSAL_MESSAGE = "This isn't in the uploaded material."

#: Number of chunks handed to the LLM as context.
MAX_CONTEXT_CHUNKS = 6

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

_STOP_WORDS = {
    "what", "is", "a", "an", "the", "in", "of", "to", "and", "or", "for", "on",
    "with", "at", "by", "from", "up", "about", "into", "over", "after", "can",
    "you", "explain", "tell", "me", "how", "why", "does", "do", "did", "are",
    "were", "was", "be", "been", "being", "have", "has", "had", "define", "describe",
}


def compute_lexical_similarity(query: str, content: str) -> float:
    """Calculate token overlap similarity between question and chunk content."""
    q_tokens = set(re.findall(r"\w+", query.lower())) - _STOP_WORDS
    if not q_tokens:
        q_tokens = set(re.findall(r"\w+", query.lower()))
    if not q_tokens:
        return 0.0
    c_tokens = set(re.findall(r"\w+", content.lower()))
    overlap = q_tokens.intersection(c_tokens)
    return float(len(overlap) / len(q_tokens))


def looks_non_english(text: str) -> bool:
    """True when the text contains letters outside the Basic Latin block.

    Used to decide whether a question needs translating before retrieval. Only
    alphabetic characters count, so smart quotes / dashes do not trigger it.
    """
    return any(ch.isalpha() and ord(ch) > 127 for ch in text or "")


def describe_question_language(declared: str, question: str) -> str:
    """Human-readable description of the language the student asked in."""
    if declared and declared not in ("auto", "indic-auto"):
        return LANGUAGE_NAMES.get(declared, declared)
    return "the language the student used in their question"


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


def _cosine_sim(a, b) -> float:
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


def retrieve_scored(
    db: Session,
    questions: list[str],
    chapter_id: int | None = None,
    current_page: int | None = None,
) -> tuple[list[dict], dict]:
    """Score document chunks against one or more query phrasings.

    Every query in ``questions`` is embedded and scored; the result keeps the
    best score per chunk, so a translated/rewritten phrasing can surface a chunk
    the original wording missed. Returns the scored chunks sorted by relevance
    (descending) plus retrieval metadata for debugging.
    """
    if not questions:
        questions = [""]

    query_embs = [embedding_service.embed_query(q) for q in questions]
    query_dim = len(query_embs[0]) if query_embs else 0

    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.status == "ready")
    )
    if chapter_id is not None:
        stmt = stmt.join(Chapter, Document.chapter_id == Chapter.id).where(Chapter.id == chapter_id)

    is_postgres = False
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            is_postgres = True
    except Exception:
        pass

    if is_postgres:
        rows_by_id: dict[int, tuple] = {}
        for q_emb in query_embs:
            try:
                from pgvector.sqlalchemy import Vector  # noqa: F401
                pg_stmt = stmt.order_by(DocumentChunk.embedding.cosine_distance(q_emb)).limit(12)
                for row in db.execute(pg_stmt).all():
                    rows_by_id[row[0].id] = (row[0], row[1])
            except Exception:
                for row in db.execute(stmt).all():
                    rows_by_id[row[0].id] = (row[0], row[1])
        rows = list(rows_by_id.values())
    else:
        rows = db.execute(stmt).all()

    best: dict[int, dict] = {}
    mismatch_ids: set[int] = set()
    for question, q_emb in zip(questions, query_embs):
        for chunk, doc in rows:
            content = chunk.content or ""
            if not content.strip():
                continue
            chunk_vec = _as_vector(chunk.embedding)
            if chunk_vec is None or chunk_vec.ndim != 1 or chunk_vec.size != query_dim:
                # Stale embedding (embedded with an older model / different dimension):
                # re-embed before it can match.
                mismatch_ids.add(chunk.id)
                continue
            v_sim = _cosine_sim(chunk_vec, q_emb)
            l_sim = compute_lexical_similarity(question, content)
            # Hybrid relevance: best of semantic similarity and keyword overlap.
            relevance = max(v_sim, l_sim)
            # Boost chunks matching the student's active reader page.
            if current_page is not None and getattr(chunk, "page_number", None) == current_page:
                relevance += 0.2
            previous = best.get(chunk.id)
            if previous is None or relevance > previous["relevance"]:
                best[chunk.id] = {
                    "relevance": relevance,
                    "v_sim": v_sim,
                    "l_sim": l_sim,
                    "chunk": chunk,
                    "doc": doc,
                    "matched_query": question,
                }

    scored = sorted(best.values(), key=lambda item: item["relevance"], reverse=True)
    meta = {
        "query_dimension": query_dim,
        "candidate_count": len(rows),
        "dimension_mismatch_chunks": len(mismatch_ids),
    }
    return scored, meta


def select_context_chunks(scored: list[dict]) -> tuple[list[dict], bool]:
    """Choose the chunks to hand to the LLM.

    Chunks at/above the lenient threshold are preferred, but if the threshold
    drops everything we still keep the single best chunk and let the LLM decide
    whether the material answers the question (the threshold never decides alone).

    Returns ``(matched, below_threshold_fallback)``.
    """
    above = [item for item in scored if item["relevance"] >= settings.SIMILARITY_THRESHOLD]
    if above:
        return above[:MAX_CONTEXT_CHUNKS], False
    if scored:
        return scored[:1], True
    return [], False


def _build_debug_info(
    body: "AskRequest",
    questions: list[str],
    scored: list[dict],
    meta: dict,
    matched: list[dict],
    refusal_reason: str | None,
    llm_marker: bool,
) -> dict:
    return {
        "question": body.question,
        "queries_used": questions,
        "question_language": body.question_language,
        "answer_language": body.answer_language,
        "embedding_model": embedding_service.active_model_name,
        "query_dimension": meta["query_dimension"],
        "threshold": settings.SIMILARITY_THRESHOLD,
        "candidate_count": meta["candidate_count"],
        "dimension_mismatch_chunks": meta["dimension_mismatch_chunks"],
        "matched_chunk_ids": [item["chunk"].id for item in matched],
        "refusal_reason": refusal_reason,
        "llm_marker_triggered": llm_marker,
        "scored_chunks": [
            {
                "chunk_id": item["chunk"].id,
                "document_id": item["doc"].id,
                "doc": item["doc"].filename,
                "page": getattr(item["chunk"], "page_number", None),
                "score": round(item["relevance"], 4),
                "vector_score": round(item["v_sim"], 4),
                "keyword_score": round(item["l_sim"], 4),
                "matched_query": item["matched_query"],
                "content_preview": (item["chunk"].content or "")[:80],
            }
            for item in scored[:10]
        ],
    }


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    chapter_id: int | None = None
    current_page: int | None = None
    answer_language: str = Field(
        default="en",
        pattern=r"^(auto|indic-auto|[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)?)$"
    )
    question_language: str = Field(
        default="auto",
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
    debug: dict | None = None  # Populated only when RAG_DEBUG is enabled.


@router.post("/ask", response_model=AskResponse)
def ask_question(
    body: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_student),
):
    """
    Student-only RAG question answering endpoint.

    Retrieves the most relevant chunks (hybrid semantic + keyword search), asks
    the LLM to answer strictly from that context, and reports ``grounded=False``
    only when the LLM explicitly says the material lacks the answer.
    """
    llm_service = get_llm_service()

    # 1. Build the list of query phrasings. A non-English question is rewritten
    #    into English so it can be matched against English study material. The
    #    translation is also kept so it can anchor the answer prompt for
    #    non-English questions (see step 5).
    is_non_english = looks_non_english(body.question)
    translated_question = ""
    questions = [body.question]
    if is_non_english:
        try:
            rewritten = (llm_service.rewrite_query(body.question) or "").strip()
        except Exception as exc:  # translation is best-effort, never fatal
            logger.warning("Query rewrite failed, using original question only: %s", exc)
            rewritten = ""
        if rewritten and rewritten.lower() != body.question.strip().lower():
            translated_question = rewritten
            questions.append(rewritten)

    # 2. Vector & keyword similarity search over DocumentChunk (best score per chunk).
    scored, meta = retrieve_scored(db, questions, body.chapter_id, body.current_page)

    debug_info = None

    # 3. No candidate material at all -> nothing to ground an answer in.
    if not scored:
        if settings.RAG_DEBUG:
            debug_info = _build_debug_info(body, questions, scored, meta, [], "no_material", False)
            logger.info("RAG debug retrieval: %s", debug_info)
        return AskResponse(answer=REFUSAL_MESSAGE, sources=[], grounded=False, debug=debug_info)

    matched, below_threshold = select_context_chunks(scored)

    context_texts = []
    sources = []
    for item in matched:
        chunk, doc = item["chunk"], item["doc"]
        page_info = f" (Page {chunk.page_number})" if getattr(chunk, "page_number", None) else ""
        context_texts.append(f"[{doc.filename}{page_info}]: {chunk.content}")
        sources.append(
            SourceItem(
                document_name=doc.filename,
                excerpt=(chunk.content or "")[:200] + "...",
                page_number=getattr(chunk, "page_number", None),
            )
        )
    context_str = "\n\n".join(context_texts)

    target_lang = LANGUAGE_NAMES.get(body.answer_language, body.answer_language)
    question_lang = describe_question_language(body.question_language, body.question)
    level_instruction = LEVEL_INSTRUCTIONS.get(body.level, f"comprehension level '{body.level}'")

    system_prompt = (
        "You are ShikshaSaathi, an expert multilingual educational AI tutor for students. "
        "Your mission is to help students learn and understand study concepts clearly.\n\n"
        "Guidelines:\n"
        "1. Grounding: Answer the student's question using ONLY the Study Material Context provided. "
        "Explain the concepts accurately based on that material; do not use outside knowledge.\n"
        f"2. If the Study Material Context truly does not contain the information needed to answer the "
        f"question, reply with exactly {NOT_IN_MATERIAL_MARKER} and nothing else.\n"
        f"3. Language: The student's question is in {question_lang}. Answer in {target_lang}. "
        f"If the source material is in English and the student requests or speaks another language, "
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
        f"Answer using only the Study Material Context above. Explain in {target_lang} for a "
        f"{body.level} learner. If the context does not contain the answer, reply with exactly "
        f"{NOT_IN_MATERIAL_MARKER}."
    )

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

    # 4. Grounded is decided by the LLM's refusal marker, not by the threshold.
    llm_marker = NOT_IN_MATERIAL_MARKER in (answer or "")

    # 5. A non-English question asks the model to translate English context into
    #    the answer language, and it occasionally gives up and emits the refusal
    #    marker even though the retrieved context is relevant. When that happens
    #    for a non-English question, retry once with the English translation
    #    supplied and an explicit "translate the context" instruction. This only
    #    runs after a refusal, so the working English/Hindi answers are unaffected.
    if llm_marker and is_non_english:
        retry_system_prompt = (
            "You are ShikshaSaathi, an expert multilingual educational AI tutor for students. "
            "The Study Material Context is written in English. The student asked in "
            f"{target_lang}; translate and explain the relevant information from the context "
            f"into {target_lang}. A translated explanation is still grounded in the context - do "
            f"not refuse merely because the question and the context are in different languages. "
            f"Only reply with {NOT_IN_MATERIAL_MARKER} if the context is genuinely unrelated to "
            f"the question.\n"
            f"Pedagogical Level: {level_instruction}"
        )
        retry_prompt_parts = [
            f"Study Material Context:\n{context_str}\n\n",
            f"Student Question: {body.question}\n",
        ]
        if translated_question:
            retry_prompt_parts.append(f"English translation of the question: {translated_question}\n")
        retry_prompt_parts.append(
            f"\nAnswer the question in {target_lang} by translating and explaining the relevant "
            f"information from the Study Material Context above."
        )
        try:
            retry_answer = (
                llm_service.generate_answer("".join(retry_prompt_parts), system_prompt=retry_system_prompt) or ""
            ).strip()
        except Exception as exc:  # a failed retry must never break the response
            logger.warning("Language-preserving retry failed: %s", exc)
            retry_answer = ""
        if retry_answer and NOT_IN_MATERIAL_MARKER not in retry_answer:
            answer = retry_answer
            llm_marker = False

    refusal_reason = "llm_marker" if llm_marker else None

    if settings.RAG_DEBUG:
        debug_info = _build_debug_info(
            body, questions, scored, meta, matched, refusal_reason, llm_marker
        )
        debug_info["below_threshold_fallback"] = below_threshold
        logger.info("RAG debug retrieval: %s", debug_info)

    if llm_marker:
        return AskResponse(answer=REFUSAL_MESSAGE, sources=[], grounded=False, debug=debug_info)

    return AskResponse(answer=answer, sources=sources, grounded=True, debug=debug_info)
