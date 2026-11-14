"""
Re-embed all stored document chunks with the currently active embedding model.

Run this after the embedding model (or its dimension) changes so previously
indexed chunks become retrievable again:

    python backend/scripts/reembed_chunks.py

It reuses the same embedding service as the ingestion pipeline, so chunks are
re-embedded with the exact model/dimension used at query time.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal  # noqa: E402
from app.services.document_processor import find_stale_documents, reembed_all_chunks  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        before = find_stale_documents(db)
        print(
            f"Active embedding model: {before['active_model']} "
            f"(dimension {384})"
        )
        print(f"Total chunks: {before['chunk_count']}")
        print(f"Documents with stale embeddings: {before['stale_chunk_documents']}")

        updated = reembed_all_chunks(db)
        after = find_stale_documents(db)
        print(f"Re-embedded {updated} chunks.")
        print(f"Remaining documents with stale embeddings: {after['stale_chunk_documents']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
