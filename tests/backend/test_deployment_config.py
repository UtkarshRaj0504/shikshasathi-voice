import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.models.document_chunk import FlexibleVector


REVISIONS_DIR = Path(__file__).resolve().parents[2] / "backend" / "alembic" / "versions"


def _load_migration(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, REVISIONS_DIR / filename)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_database_url_overrides_legacy_database_fields():
    config = Settings(
        _env_file=None,
        DATABASE_URL="postgres://neon.example.test/shiksha?sslmode=require",
        DATABASE_HOST="ignored.example.test",
        DATABASE_NAME="ignored",
        DATABASE_USER="ignored",
        DATABASE_PASSWORD="fake-only",
    )

    assert config.SQLALCHEMY_DATABASE_URL == (
        "postgresql://neon.example.test/shiksha?sslmode=require"
    )


def test_legacy_database_fields_are_used_when_url_is_empty():
    config = Settings(
        _env_file=None,
        DATABASE_URL="",
        DATABASE_HOST="db.example.test",
        DATABASE_PORT=6543,
        DATABASE_NAME="demo",
        DATABASE_USER="demo-user",
        DATABASE_PASSWORD="fake-only",
    )

    assert config.SQLALCHEMY_DATABASE_URL.startswith("postgresql+psycopg2://")
    assert "db.example.test:6543/demo" in config.SQLALCHEMY_DATABASE_URL


def test_allowed_origins_are_parsed_from_comma_separated_setting():
    config = Settings(
        _env_file=None,
        ALLOWED_ORIGINS=" https://school.example.test,https://preview.example.test ,,",
    )

    assert config.allowed_origins == [
        "https://school.example.test",
        "https://preview.example.test",
    ]
    assert Settings(_env_file=None).STORAGE_PROVIDER == "local"


def test_document_storage_migration_adds_blob_and_guards_downgrade():
    migration = _load_migration(
        "document_storage_migration", "005_database_document_storage.py"
    )

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE documents (id INTEGER PRIMARY KEY, file_path VARCHAR(1000) NOT NULL)")
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("documents")}
        assert columns["file_path"]["nullable"] is True
        assert isinstance(columns["file_data"]["type"], sa.LargeBinary)

        connection.execute(
            sa.text("INSERT INTO documents (id, file_path, file_data) VALUES (1, NULL, :data)"),
            {"data": b"fake demo bytes"},
        )
        with pytest.raises(RuntimeError, match="export them to local files"):
            migration.downgrade()

        connection.execute(sa.text("DELETE FROM documents"))
        migration.downgrade()
        downgraded_columns = {
            column["name"]: column for column in sa.inspect(connection).get_columns("documents")
        }
        assert "file_data" not in downgraded_columns
        assert downgraded_columns["file_path"]["nullable"] is False


def test_voice_profile_migration_widens_columns_and_downgrades():
    """006 turns the overflowing varchar columns into unbounded Text.

    ``gnani_voice_id`` stores a multi-thousand-character serialized embedding,
    which is what made POST /voice-profiles fail on Postgres with
    "value too long for type character varying(200)".
    """
    migration = _load_migration(
        "voice_profile_text_migration", "006_voice_profile_text_columns.py"
    )

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE voice_profiles ("
                "id INTEGER PRIMARY KEY, "
                "teacher_id INTEGER NOT NULL, "
                "voice_name VARCHAR(200) NOT NULL, "
                "gnani_voice_id VARCHAR(200), "
                "languages VARCHAR(200), "
                "status VARCHAR(50) NOT NULL, "
                "consent_text TEXT, "
                "sample_audio_path VARCHAR(1000))"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("voice_profiles")}
        for name in ("gnani_voice_id", "voice_name", "languages"):
            assert isinstance(columns[name]["type"], sa.Text), name
            assert columns[name]["type"].length is None, name

        # Columns that only ever hold short, application-controlled values keep
        # their lengths.
        assert columns["status"]["type"].length == 50
        assert columns["sample_audio_path"]["type"].length == 1000

        # The widened column now accepts a multi-thousand-character embedding.
        long_embedding = "[" + ",".join(["0.0"] * 3000) + "]"
        assert len(long_embedding) > 200
        connection.execute(
            sa.text(
                "INSERT INTO voice_profiles "
                "(id, teacher_id, voice_name, gnani_voice_id, status) "
                "VALUES (1, 1, 'Demo', :embedding, 'pending')"
            ),
            {"embedding": long_embedding},
        )
        stored = connection.execute(
            sa.text("SELECT gnani_voice_id FROM voice_profiles WHERE id = 1")
        ).scalar_one()
        assert stored == long_embedding

        migration.downgrade()
        downgraded = {
            column["name"]: column for column in sa.inspect(connection).get_columns("voice_profiles")
        }
        for name in ("gnani_voice_id", "voice_name", "languages"):
            assert isinstance(downgraded[name]["type"], sa.String), name
            assert downgraded[name]["type"].length == 200, name


def test_voice_profile_migration_is_a_noop_without_the_table():
    migration = _load_migration(
        "voice_profile_text_migration", "006_voice_profile_text_columns.py"
    )

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.downgrade()

        assert "voice_profiles" not in sa.inspect(connection).get_table_names()


#: The schema as produced by migration 006 (the previous head), minus the
#: embedding dimension which SQLite stores as text.
_PREVIOUS_HEAD_DDL = (
    "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(320) NOT NULL)",
    "CREATE TABLE subjects (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, teacher_id INTEGER NOT NULL)",
    "CREATE TABLE chapters (id INTEGER PRIMARY KEY, title VARCHAR(300) NOT NULL, subject_id INTEGER NOT NULL)",
    (
        "CREATE TABLE documents (id INTEGER PRIMARY KEY, filename VARCHAR(500) NOT NULL, "
        "file_path VARCHAR(1000), file_data BLOB, status VARCHAR(50) NOT NULL, "
        "error_message TEXT, chapter_id INTEGER NOT NULL)"
    ),
    (
        "CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, "
        "chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL, "
        "embedding_model VARCHAR(255), created_at TIMESTAMP)"
    ),
    "CREATE TABLE voice_profiles (id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL, gnani_voice_id TEXT)",
)


def _create_previous_head_schema(connection):
    for statement in _PREVIOUS_HEAD_DDL:
        connection.execute(sa.text(statement))


def test_align_migration_adds_missing_columns_and_tables():
    """007 adds page_number plus the three tables that had models but no migration."""
    migration = _load_migration("align_schema_migration", "007_align_schema_with_models.py")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_previous_head_schema(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert {"user_preferences", "conversations", "messages"} <= tables

        chunk_columns = {c["name"] for c in inspector.get_columns("document_chunks")}
        assert "page_number" in chunk_columns

        message_columns = {c["name"]: c for c in inspector.get_columns("messages")}
        assert {"conversation_id", "role", "content", "grounded", "language", "voice_used",
                "sources", "audio_base64", "page_number", "created_at"} <= set(message_columns)
        assert isinstance(message_columns["content"]["type"], sa.Text)

        conversation_columns = {c["name"] for c in inspector.get_columns("conversations")}
        assert {"student_id", "chapter_id", "title", "created_at", "updated_at"} <= conversation_columns

        preference_indexes = {i["name"] for i in inspector.get_indexes("user_preferences")}
        assert "ix_user_preferences_user_id" in preference_indexes

        # Every table is empty, so the data-mutating parts must be no-ops.
        assert connection.execute(sa.text("SELECT count(*) FROM document_chunks")).scalar() == 0

        # Re-running is safe (defensive checks), i.e. upgrade does not fail on the
        # schema it just produced.
        migration.upgrade()
        assert {c["name"] for c in sa.inspect(connection).get_columns("document_chunks")} >= {"page_number"}


def test_align_migration_is_a_noop_on_an_empty_database():
    """No tables at all: create what is missing and never raise."""
    migration = _load_migration("align_schema_migration", "007_align_schema_with_models.py")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        tables = set(sa.inspect(connection).get_table_names())
        assert {"user_preferences", "conversations", "messages"} <= tables
        # document_chunks does not exist, so page_number is simply skipped.
        assert "document_chunks" not in tables


def test_align_migration_downgrade_removes_what_it_added():
    migration = _load_migration("align_schema_migration", "007_align_schema_with_models.py")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_previous_head_schema(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.downgrade()

        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert not ({"user_preferences", "conversations", "messages"} & tables)
        assert "page_number" not in {c["name"] for c in inspector.get_columns("document_chunks")}


def test_align_migration_embedding_dimension_matches_the_model():
    """Guards issue (a): the migration, the model and the service must agree on 384."""
    migration = _load_migration("align_schema_migration", "007_align_schema_with_models.py")

    model_dim = FlexibleVector().load_dialect_impl(postgresql.dialect()).dim
    assert model_dim == 384
    assert migration.EMBEDDING_DIMENSION == model_dim
