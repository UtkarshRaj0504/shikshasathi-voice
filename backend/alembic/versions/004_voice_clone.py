"""voice cloning: voice_profiles + voice_consents tables and languages column

Revision ID: 004_voice_clone
Revises: 003_embed_model
Create Date: 2026-11-15 12:00:00.000000

The application still bootstraps its schema with ``Base.metadata.create_all`` on
startup, so this migration is written defensively: it creates the two tables only
when they do not already exist and adds the ``languages`` column only when missing.
This keeps ``alembic upgrade head`` safe on an existing development database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "004_voice_clone"
down_revision: Union[str, None] = "003_embed_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "voice_profiles" not in tables:
        op.create_table(
            "voice_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("voice_name", sa.String(length=200), nullable=False),
            sa.Column("gnani_voice_id", sa.String(length=200), nullable=True),
            sa.Column("languages", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
            sa.Column("consent_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("consent_text", sa.Text(), nullable=True),
            sa.Column("sample_audio_path", sa.String(length=1000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        columns = {c["name"] for c in inspector.get_columns("voice_profiles")}
        if "languages" not in columns:
            op.add_column("voice_profiles", sa.Column("languages", sa.String(length=200), nullable=True))

    if "voice_consents" not in tables:
        op.create_table(
            "voice_consents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("voice_profile_id", sa.Integer(), sa.ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=True),
            sa.Column("consent_text_version", sa.String(length=50), nullable=False, server_default="1.0"),
            sa.Column("full_consent_text", sa.Text(), nullable=False),
            sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.String(length=500), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoke_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "voice_consents" in tables:
        op.drop_table("voice_consents")
    if "voice_profiles" in tables:
        columns = {c["name"] for c in inspector.get_columns("voice_profiles")}
        if "languages" in columns:
            op.drop_column("voice_profiles", "languages")
