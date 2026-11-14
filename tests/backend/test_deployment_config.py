import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.config import Settings


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
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "005_database_document_storage.py"
    )
    spec = importlib.util.spec_from_file_location("document_storage_migration", revision_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

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
