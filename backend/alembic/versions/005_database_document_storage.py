"""Persist uploaded document bytes in the database when configured.

Revision ID: 005_database_document_storage
Revises: 004_voice_clone
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_database_document_storage"
down_revision: Union[str, None] = "004_voice_clone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return

    columns = {column["name"]: column for column in inspector.get_columns("documents")}
    with op.batch_alter_table("documents") as batch:
        if not columns.get("file_path", {}).get("nullable", True):
            batch.alter_column(
                "file_path",
                existing_type=sa.String(length=1000),
                nullable=True,
            )
        if "file_data" not in columns:
            batch.add_column(sa.Column("file_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "documents" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "file_data" in columns:
        has_database_files = bind.execute(
            sa.text("SELECT 1 FROM documents WHERE file_data IS NOT NULL LIMIT 1")
        ).first()
        if has_database_files:
            raise RuntimeError(
                "Cannot downgrade while documents are stored in the database; "
                "export them to local files first."
            )

    with op.batch_alter_table("documents") as batch:
        if "file_data" in columns:
            batch.drop_column("file_data")
        batch.alter_column(
            "file_path",
            existing_type=sa.String(length=1000),
            nullable=False,
        )
