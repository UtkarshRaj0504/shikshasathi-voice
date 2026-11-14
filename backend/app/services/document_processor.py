"""
Background document processing pipeline: extraction, chunking, embedding, and storage.
"""

import logging
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_parser import extract_text
from app.services.chunker import chunk_text
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


def process_document(document_id: int):
    """Background task to parse, chunk, embed, and store document chunks."""
    db: Session = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            logger.error(f"Document {document_id} not found for processing.")
            return

        doc.status = "processing"
        db.commit()

        # 1. Extract text
        raw_text = extract_text(doc.file_path, doc.filename)
        if not raw_text.strip():
            raise ValueError("Extracted text is empty.")

        # 2. Chunk text
        chunks = chunk_text(raw_text)

        # 3. Generate embeddings
        embeddings = embedding_service.embed_texts(chunks)

        # 4. Save chunks to database
        for index, (content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=index,
                content=content,
                embedding=embedding,
            )
            db.add(chunk)

        doc.status = "ready"
        doc.error_message = None
        db.commit()
        logger.info(f"Successfully processed document {document_id} ({len(chunks)} chunks).")

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
