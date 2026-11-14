"""
SQLAlchemy 2.0 database engine, session factory, and dependency.
Supports lazy engine initialization for seamless test (SQLite in-memory) and production/dev switching.
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
            url = settings.SQLALCHEMY_DATABASE_URL
            is_sqlite = url.startswith("sqlite")
            connect_args = {"check_same_thread": False} if is_sqlite else {}
            # Neon closes idle Postgres connections, so pre-ping replaces a dead
            # pooled connection instead of raising OperationalError, and recycle
            # retires connections before the server-side idle timeout.
            pool_args = {} if is_sqlite else {"pool_pre_ping": True, "pool_recycle": 300}
            _engine = create_engine(
                url, echo=settings.APP_DEBUG, connect_args=connect_args, **pool_args
            )

            if str(_engine.url).startswith("sqlite"):
                @event.listens_for(_engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
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
