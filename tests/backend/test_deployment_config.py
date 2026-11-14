import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.config import Settings


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
