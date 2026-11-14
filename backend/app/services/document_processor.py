"""
Background document processing pipeline: extraction, chunking, embedding, and storage.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_parser import extract_document_pages
from app.services.chunker import chunk_text
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


def process_document(document_id: int):
    """Background task to parse, chunk, embed, and store document chunks with page attribution."""
    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            logger.error(f"Document {document_id} not found for processing.")
            return

        doc.status = "processing"
        db.commit()

        # 1. Extract pages with page numbers
        pages = extract_document_pages(doc.file_path, doc.filename)
        if not pages:
            raise ValueError(
                "No extractable text found. The document may be a scanned image PDF "
                "without a text layer (OCR is not supported)."
            )

        # 2. Chunk text while tracking page numbers
        chunks: list[str] = []
        chunk_pages: list[int | None] = []

        for page_num, page_text in pages:
            page_chunks = chunk_text(page_text)
            for c in page_chunks:
                chunks.append(c)
                chunk_pages.append(page_num)

        if not chunks:
            raise ValueError("No text chunks generated.")

        # 3. Generate embeddings using the active model with the passage prefix
        embeddings = embedding_service.embed_texts(chunks, is_query=False)
        active_model = embedding_service.active_model_name

        # 4. Save chunks to database
        for index, (content, embedding, page_num) in enumerate(zip(chunks, embeddings, chunk_pages)):
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=index,
                page_number=page_num,
                content=content,
                embedding=embedding,
                embedding_model=active_model,
            )
            db.add(chunk)

        doc.status = "ready"
        doc.error_message = None
        db.commit()
        logger.info(
            f"Successfully processed document {document_id} "
            f"({len(chunks)} chunks, model: {active_model})."
        )

    except Exception as e:
        logger.exception(f"Error processing document {document_id}: {e}")
        try:
            doc = db.get(Document, document_id)
            if doc:
                doc.status = "failed"
                doc.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


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
