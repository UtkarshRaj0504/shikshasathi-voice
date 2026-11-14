"""
Background document processing pipeline: extraction, chunking, embedding, and storage.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_parser import extract_document_pages
from app.services.chunker import chunk_text
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

#: Parser tracebacks are truncated so they can never overflow the column.
ERROR_MESSAGE_MAX_LENGTH = 500
#: Chunks per embedding request; also the unit of the per-batch progress log.
EMBED_BATCH_SIZE = 100
#: A pending/processing document older than this was interrupted by a restart.
STUCK_DOCUMENT_AGE_SECONDS = 10 * 60
STUCK_DOCUMENT_MESSAGE = "Processing was interrupted; please re-upload or retry"
EMBEDDINGS_NOT_CONFIGURED_MESSAGE = (
    "Embeddings are not configured: GEMINI_API_KEY is missing, so this document "
    "cannot be indexed. Set GEMINI_API_KEY and retry."
)


def _in_test_mode() -> bool:
    """Tests index with the offline mock vectors, so this check is skipped there."""
    return "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or settings.APP_ENV == "test"


def _mark_document_failed(document_id: int, error: Exception) -> None:
    """Record a processing failure on a FRESH session.

    The session used for the failed work may already be dead (Neon closes idle
    connections), which is exactly why the old code lost the "failed" status. The
    failure is therefore always written through a brand-new connection, and a
    failure to record the failure is logged rather than swallowed.
    """
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.error("Document %s vanished before its failure could be recorded.", document_id)
            return
        doc.status = "failed"
        doc.error_message = str(error)[:ERROR_MESSAGE_MAX_LENGTH]
        db.commit()
    except Exception:
        logger.exception("Could not mark document %s as failed.", document_id)
        db.rollback()
    finally:
        db.close()


def _start_processing(document_id: int) -> tuple[str, str | None, bytes | None] | None:
    """Short session: mark the document "processing" and return the inputs it needs.

    Nothing slow happens while this session is open — holding one across PDF
    extraction and the Gemini embedding calls is what used to lose the final commit.
    """
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.error("Document %s not found for processing.", document_id)
            return None
        doc.status = "processing"
        doc.error_message = None
        db.commit()
        return doc.filename, doc.file_path, doc.file_data
    finally:
        db.close()


def _extract_chunks(filename: str, file_path: str | None, file_data: bytes | None):
    """Extract every page's text and split it into page-attributed chunks."""
    pages = extract_document_pages(file_path, filename, file_data=file_data)
    if not pages:
        raise ValueError(
            "No extractable text found. The document may be a scanned image PDF "
            "without a text layer (OCR is not supported)."
        )

    chunks: list[str] = []
    chunk_pages: list[int | None] = []
    for page_num, page_text in pages:
        for content in chunk_text(page_text):
            chunks.append(content)
            chunk_pages.append(page_num)

    if not chunks:
        raise ValueError("No text chunks generated.")
    return chunks, chunk_pages


def _embed_chunks(document_id: int, chunks: list[str]) -> list[list[float]]:
    """Embed the chunks in batches, logging progress so the deploy log shows where it is."""
    batches = [
        chunks[index : index + EMBED_BATCH_SIZE]
        for index in range(0, len(chunks), EMBED_BATCH_SIZE)
    ]
    embeddings: list[list[float]] = []
    for number, batch in enumerate(batches, start=1):
        logger.info(
            "Document %s: embedding batch %s/%s (%s chunks).",
            document_id,
            number,
            len(batches),
            len(batch),
        )
        embeddings.extend(embedding_service.embed_texts(batch, is_query=False))
    return embeddings


def _store_chunks(
    document_id: int,
    chunks: list[str],
    chunk_pages: list[int | None],
    embeddings: list[list[float]],
) -> None:
    """New session: insert the chunks and mark the document "ready" in one commit."""
    active_model = embedding_service.active_model_name
    db = SessionLocal()
    try:
        for index, (content, embedding, page_num) in enumerate(zip(chunks, embeddings, chunk_pages)):
            db.add(
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=index,
                    page_number=page_num,
                    content=content,
                    embedding=embedding,
                    embedding_model=active_model,
                )
            )
        doc = db.get(Document, document_id)
        if doc is None:
            raise RuntimeError(f"Document {document_id} disappeared while storing its chunks.")
        doc.status = "ready"
        doc.error_message = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def process_document(document_id: int):
    """Background task to parse, chunk, embed, and store document chunks with page attribution.

    Every database session is short-lived: no connection is held open across the
    slow PDF extraction or the Gemini embedding calls. Neon closes idle
    connections, so the single long-lived session used previously lost its final
    commit — and with it the "ready" (or "failed") status — leaving documents stuck
    on "processing" forever.
    """
    inputs = _start_processing(document_id)
    if inputs is None:
        return
    filename, file_path, file_data = inputs

    try:
        chunks, chunk_pages = _extract_chunks(filename, file_path, file_data)

        if not embedding_service.is_real_model and not _in_test_mode():
            # Otherwise mock vectors would be indexed silently and retrieval would
            # return unrelated material instead of the document failing loudly.
            raise RuntimeError(EMBEDDINGS_NOT_CONFIGURED_MESSAGE)

        embeddings = _embed_chunks(document_id, chunks)
        active_model = embedding_service.active_model_name
        _store_chunks(document_id, chunks, chunk_pages, embeddings)
        logger.info(
            "Successfully processed document %s (%s chunks, model: %s).",
            document_id,
            len(chunks),
            active_model,
        )
    except Exception as e:
        logger.exception("Error processing document %s: %s", document_id, e)
        _mark_document_failed(document_id, e)


def recover_stuck_documents(db: Session, now: datetime | None = None) -> int:
    """Mark documents abandoned mid-processing as failed; returns how many.

    Called on startup. A document still "pending"/"processing" long after it was
    uploaded cannot be progressing — Render's free tier spins the instance down
    mid-task and the in-flight background job dies with it — so it would otherwise
    stay in that state forever with no way for the teacher to retry. Database reads
    and one UPDATE only: no network and no model calls.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=STUCK_DOCUMENT_AGE_SECONDS)
    result = db.execute(
        update(Document)
        .where(Document.status.in_(("pending", "processing")))
        .where(Document.uploaded_at <= cutoff)
        .values(status="failed", error_message=STUCK_DOCUMENT_MESSAGE)
    )
    db.commit()
    return result.rowcount or 0


def reembed_document_chunks(document_id: int, db: Session) -> int:
    """Re-embed every chunk of a document with the currently active embedding model.

    Returns the number of chunks re-embedded. Chunks are re-embedded in place so
    the document stays retrievable; ``embedding_model`` is refreshed on each chunk.
    """
    chunks = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).scalars().all()
    if not chunks:
        return 0

    active_model = embedding_service.active_model_name
    embeddings = embedding_service.embed_texts([c.content for c in chunks], is_query=False)
    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding
        chunk.embedding_model = active_model
    db.commit()
    return len(chunks)


def reembed_all_chunks(db: Session) -> int:
    """Re-embed all document chunks with the currently active embedding model.

    Used when the embedding model or its dimension changes (for example after
    migrating away from the legacy 1536-dim placeholder model).
    """
    chunks = db.execute(select(DocumentChunk)).scalars().all()
    if not chunks:
        return 0

    active_model = embedding_service.active_model_name
    embeddings = embedding_service.embed_texts([c.content for c in chunks], is_query=False)
    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding
        chunk.embedding_model = active_model
    db.commit()
    return len(chunks)


def find_stale_documents(db: Session) -> dict:
    """Report documents whose chunks were indexed with a different model/dimension.

    Non-secret diagnostics used by the startup check and the re-embed script.
    """
    active_model = embedding_service.active_model_name
    stale_doc_ids: set[int] = set()
    chunk_count = 0

    for chunk in db.execute(select(DocumentChunk)).scalars().all():
        chunk_count += 1
        embedding = chunk.embedding
        dim = len(embedding) if isinstance(embedding, (list, tuple)) else 0
        if dim != embedding_service.dimension or (chunk.embedding_model or "") != active_model:
            stale_doc_ids.add(chunk.document_id)

    return {
        "active_model": active_model,
        "chunk_count": chunk_count,
        "stale_chunk_documents": sorted(stale_doc_ids),
    }
