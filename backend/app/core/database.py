"""
SQLAlchemy 2.0 database engine, session factory, and dependency.
Supports lazy engine initialization for seamless test (SQLite in-memory) and production (PostgreSQL) switching.
"""

import os
import sys
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        is_test = "pytest" in sys.modules or os.getenv("APP_ENV") == "test"
        if is_test:
            _engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )

            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        else:
            _engine = create_engine(settings.DATABASE_URL, echo=settings.APP_DEBUG)
    return _engine


def get_session_maker():
    global _SessionLocal
    if _SessionLocal is None:
        eng = get_engine()
        _SessionLocal = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    return _SessionLocal


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def SessionLocal():
    return get_session_maker()()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
