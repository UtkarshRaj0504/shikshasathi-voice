"""add document status and document_chunks with pgvector

Revision ID: 002_chunks
Revises: 001_initial
Create Date: 2026-11-12 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '002_chunks'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add status and error_message columns to documents
    op.add_column('documents', sa.Column('status', sa.String(length=50), server_default='pending', nullable=False))
    op.add_column('documents', sa.Column('error_message', sa.Text(), nullable=True))

    # Add cascade delete constraints if not already cascaded
    # Create document_chunks table with pgvector embedding (1536 dims)
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('document_chunks')
    op.drop_column('documents', 'error_message')
    op.drop_column('documents', 'status')
