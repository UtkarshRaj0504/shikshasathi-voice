"""Align the migration-built schema with the SQLAlchemy models.

Revision ID: 007_align_schema_with_models
Revises: 006_voice_profile_text_columns

A database built from the migrations alone (production Postgres on Neon) had
drifted from ``Base.metadata``. Reading every migration and comparing it with the
models shows exactly three substantive differences:

1. ``document_chunks.embedding`` was ``vector(1536)`` (created by migration 002)
   while ``FlexibleVector`` in ``app/models/document_chunk.py`` and the Gemini
   embedding service both use 384 dimensions, so storing a chunk failed with
   "expected 1536 dimensions, not 384".
2. ``document_chunks.page_number`` was never created by any migration; it only
   existed because ``app.main.on_startup`` runs a bare ``ALTER TABLE ... ADD
   COLUMN``. A migration-only database therefore could not store page
   attribution.
3. ``user_preferences``, ``conversations`` and ``messages`` have models but no
   migration, so they were entirely absent from a migration-only database.

``voice_profiles.voice_name`` / ``gnani_voice_id`` / ``languages`` were widened to
``Text`` by the immediately preceding migration 006, so they are not touched
here (building on it rather than duplicating it).

The 1536-dimension vectors cannot be cast to 384, so the existing chunks are
deleted and every document that had chunks — or that is still marked
``processing`` / ``ready`` / ``failed`` — is put back to ``pending`` with an
explanation, ready to be reprocessed from the teacher view. That purge is
PostgreSQL-only; SQLite (tests) stores embeddings as JSON text.

Column-level server defaults are deliberately not normalised: ``autogenerate``
does not compare them, and the values the migrations already set are harmless
(``voice_profiles.status``/``consent_confirmed``, ``documents.status``).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007_align_schema_with_models"
down_revision: Union[str, None] = "006_voice_profile_text_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Must match ``FlexibleVector`` in app/models/document_chunk.py (and the Gemini
#: embedding service), which normalise every stored vector to 384 dimensions.
EMBEDDING_DIMENSION = 384
#: Explains to the teacher why a previously fine document must be reprocessed.
REPROCESS_MESSAGE = "Re-processing required after embedding model change"


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_columns(table: str) -> dict[str, dict]:
    if table not in _existing_tables():
        return {}
    return {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}


def _embedding_indexes() -> list[dict]:
    """Indexes covering ``document_chunks.embedding`` (none ship in this repo)."""
    if "document_chunks" not in _existing_tables():
        return []
    return [
        index
        for index in sa.inspect(op.get_bind()).get_indexes("document_chunks")
        if "embedding" in (index.get("column_names") or [])
    ]


def _embedding_typmod() -> int | None:
    """Current pgvector dimension of ``document_chunks.embedding`` (PostgreSQL only)."""
    return op.get_bind().execute(
        sa.text(
            "SELECT a.atttypmod FROM pg_attribute a "
            "WHERE a.attrelid = 'document_chunks'::regclass "
            "AND a.attname = 'embedding' AND NOT a.attisdropped"
        )
    ).scalar()


def _resize_embedding_to_384() -> None:
    """Purge un-castable 1536-dim chunks, re-queue their documents, then resize."""
    if "document_chunks" not in _existing_tables():
        return
    if _embedding_typmod() == EMBEDDING_DIMENSION:
        # Already 384 (e.g. a schema bootstrapped by Base.metadata.create_all):
        # nothing to convert and no reason to throw the existing chunks away.
        return

    bind = op.get_bind()
    indexes = _embedding_indexes()

    # 1. Re-queue documents before their chunks are dropped: those that still have
    #    chunks of the old dimension, plus any left mid/near processing.
    bind.execute(
        sa.text(
            "UPDATE documents SET status = 'pending', error_message = :message "
            "WHERE status IN ('processing', 'ready', 'failed') "
            "   OR id IN (SELECT DISTINCT document_id FROM document_chunks)"
        ),
        {"message": REPROCESS_MESSAGE},
    )

    # 2. The stored 1536-dimension vectors cannot be cast to 384.
    bind.execute(sa.text("DELETE FROM document_chunks"))

    # 3. A vector index would block the type change, so drop and re-add it.
    for index in indexes:
        op.drop_index(index["name"], table_name="document_chunks")

    bind.execute(
        sa.text(
            f"ALTER TABLE document_chunks "
            f"ALTER COLUMN embedding TYPE vector({EMBEDDING_DIMENSION})"
        )
    )

    # NOTE: an index recreated here keeps its name/columns/uniqueness but not a
    # custom access method or operator class; no such index exists in this repo.
    for index in indexes:
        op.create_index(
            index["name"],
            "document_chunks",
            list(index["column_names"]),
            unique=bool(index.get("unique")),
        )


def _add_page_number() -> None:
    if "document_chunks" not in _existing_tables():
        return
    if "page_number" in _existing_columns("document_chunks"):
        return
    op.add_column("document_chunks", sa.Column("page_number", sa.Integer(), nullable=True))


def _create_missing_tables() -> None:
    tables = _existing_tables()

    if "user_preferences" not in tables:
        op.create_table(
            "user_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "voice_profile_id",
                sa.Integer(),
                sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "question_language",
                sa.String(length=30),
                nullable=False,
                server_default="indic-auto",
            ),
            sa.Column(
                "answer_language", sa.String(length=30), nullable=False, server_default="en"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index(
            "ix_user_preferences_user_id",
            "user_preferences",
            ["user_id"],
            unique=True,
        )

    if "conversations" not in tables:
        op.create_table(
            "conversations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "student_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "title", sa.String(length=500), nullable=False, server_default="Study Session"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if "messages" not in tables:
        op.create_table(
            "messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "conversation_id",
                sa.Integer(),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("grounded", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("language", sa.String(length=20), nullable=False, server_default="en"),
            sa.Column(
                "voice_used", sa.String(length=50), nullable=False, server_default="default"
            ),
            sa.Column("sources", sa.Text(), nullable=True),
            sa.Column("audio_base64", sa.Text(), nullable=True),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        _resize_embedding_to_384()

    _add_page_number()
    _create_missing_tables()


def downgrade() -> None:
    bind = op.get_bind()
    tables = _existing_tables()

    # Drop the tables this revision added, children first.
    for table in ("messages", "conversations", "user_preferences"):
        if table in tables:
            op.drop_table(table)

    if "document_chunks" in tables and "page_number" in _existing_columns("document_chunks"):
        with op.batch_alter_table("document_chunks") as batch:
            batch.drop_column("page_number")

    if bind.dialect.name != "postgresql":
        return

    # Widen the embedding column back to the 1536 dimensions of migration 002.
    # 384-dimension vectors cannot be cast to 1536, and the original vectors were
    # already discarded by upgrade(), so this data is unrecoverable.
    if "document_chunks" not in _existing_tables():
        return

    rows = bind.execute(sa.text("SELECT count(*) FROM document_chunks")).scalar() or 0
    if rows:
        raise RuntimeError(
            "Cannot downgrade while document_chunks holds rows: 384-dimension vectors "
            "cannot be cast back to vector(1536). Reprocess the documents or "
            "TRUNCATE document_chunks, then retry."
        )

    indexes = _embedding_indexes()
    for index in indexes:
        op.drop_index(index["name"], table_name="document_chunks")

    bind.execute(
        sa.text("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536)")
    )

    for index in indexes:
        op.create_index(
            index["name"],
            "document_chunks",
            list(index["column_names"]),
            unique=bool(index.get("unique")),
        )
