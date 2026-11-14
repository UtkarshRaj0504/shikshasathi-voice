"""Widen the voice_profiles text columns that hold long values.

Revision ID: 006_voice_profile_text_columns
Revises: 005_database_document_storage

``gnani_voice_id`` stores the serialized cloned-voice speaker embedding, which is
several thousand characters, so ``varchar(200)`` made ``POST /voice-profiles`` fail
on Postgres with "value too long for type character varying(200)". ``voice_name``
and ``languages`` carry teacher-supplied form values that are not length-validated
either, so they are widened as well.

``status`` (an application-controlled enum) and ``sample_audio_path`` (never
written) keep their lengths, and ``consent_text`` is already ``Text``.

The application still bootstraps its schema with ``Base.metadata.create_all`` on
startup, so existing tables only change through this migration; it is written
defensively (column presence is checked, ``batch_alter_table`` keeps it working on
SQLite) so ``alembic upgrade head`` is safe on both a fresh and an existing schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "006_voice_profile_text_columns"
down_revision: Union[str, None] = "005_database_document_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: column name -> (previous type, new type, nullable)
TEXT_COLUMNS: dict[str, tuple[sa.types.TypeEngine, sa.types.TypeEngine, bool]] = {
    "gnani_voice_id": (sa.String(length=200), sa.Text(), True),
    "voice_name": (sa.String(length=200), sa.Text(), False),
    "languages": (sa.String(length=200), sa.Text(), True),
}


def _existing_voice_profile_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "voice_profiles" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("voice_profiles")}


def upgrade() -> None:
    columns = _existing_voice_profile_columns()
    if not columns:
        return

    with op.batch_alter_table("voice_profiles") as batch:
        for name, (previous_type, new_type, nullable) in TEXT_COLUMNS.items():
            if name not in columns:
                continue
            batch.alter_column(
                name,
                existing_type=previous_type,
                type_=new_type,
                nullable=nullable,
            )


def downgrade() -> None:
    columns = _existing_voice_profile_columns()
    if not columns:
        return

    with op.batch_alter_table("voice_profiles") as batch:
        for name, (previous_type, new_type, nullable) in TEXT_COLUMNS.items():
            if name not in columns:
                continue
            batch.alter_column(
                name,
                existing_type=new_type,
                type_=previous_type,
                nullable=nullable,
            )
