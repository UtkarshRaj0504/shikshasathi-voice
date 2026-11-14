"""add embedding_model to document_chunks for stale-embedding detection

Revision ID: 003_embed_model
Revises: 002_chunks
Create Date: 2026-11-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_embed_model'
down_revision: Union[str, None] = '002_chunks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_chunks',
        sa.Column('embedding_model', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_chunks', 'embedding_model')
