"""
Pytest configuration for backend tests.
Uses SQLite in-memory database for fast, isolated test execution.
"""

import os
os.environ["APP_ENV"] = "test"
os.environ["LLM_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient

# Import models FIRST so Base.metadata populates them before create_all
import app.models  # noqa: F401

from app.core.config import settings
from app.core.database import Base, SessionLocal, get_engine, get_db
from app.main import app as fastapi_app


@pytest.fixture(autouse=True)
def default_mock_llm(monkeypatch):
    """Ensure tests always default to mock LLM without live external API calls."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")


@pytest.fixture(autouse=True)
def setup_database():
    """Create all tables before each test and drop them after."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
