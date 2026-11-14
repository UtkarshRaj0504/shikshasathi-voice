"""
DocumentChunk model — stores text chunks and pgvector embeddings for RAG.
Compatible with both PostgreSQL (pgvector) and SQLite (tests).
"""

import json
from datetime import datetime
from pgvector.sqlalchemy import Vector as PGVector
from sqlalchemy import DateTime, ForeignKey, Integer, Text, TypeDecorator, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FlexibleVector(TypeDecorator):
    """Uses native PGVector on PostgreSQL, and JSON-encoded Text on SQLite."""
    impl = Text
    cache_ok = True
    comparator_factory = PGVector.comparator_factory

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(384))
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name != "postgresql":
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name != "postgresql" and isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(FlexibleVector, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")  # noqa: F821
