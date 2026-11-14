"""
Tests for the Gemini-backed embedding service.

Every test replaces ``httpx.Client`` with a local stub, so no socket is ever
opened and no API key is needed.
"""

import httpx
import pytest

from app.core.config import settings
from app.services import embedding_service as embedding_module
from app.services.embedding_service import (
    EMBEDDING_DIMENSION,
    EmbeddingError,
    SentenceTransformerEmbeddingService,
)

API_KEY = "fake-gemini-key-for-tests"
UNIT_VECTOR = [1.0] * EMBEDDING_DIMENSION


def _install_client(monkeypatch, handler):
    """Replace httpx.Client with a stub; returns the recorded calls."""
    calls: list[dict] = []

    class _StubClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def post(self, url, headers=None, json=None):
            calls.append({"url": url, "headers": headers or {}, "json": json})
            return handler(url, json or {})

    monkeypatch.setattr(embedding_module.httpx, "Client", _StubClient)
    return calls


def _values_response(count: int = 1, values: list[float] | None = None):
    payload_values = [1.0] * EMBEDDING_DIMENSION if values is None else values
    if count == 1:
        body = {"embedding": {"values": payload_values}}
    else:
        body = {"embeddings": [{"values": payload_values} for _ in range(count)]}
    return httpx.Response(200, json=body)


@pytest.fixture
def gemini_service(monkeypatch):
    """A service configured with a key and *not* in test mode (stubbed network)."""
    monkeypatch.setattr(embedding_module, "_in_test_mode", lambda: False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", API_KEY)
    monkeypatch.setattr(embedding_module.time, "sleep", lambda seconds: None)
    return SentenceTransformerEmbeddingService("gemini-embedding-001")


def test_status_properties_do_not_touch_the_network(monkeypatch):
    """Reading the model flags must not load a model or call the API."""
    calls = _install_client(monkeypatch, lambda url, payload: _values_response())
    monkeypatch.setattr(embedding_module, "_in_test_mode", lambda: False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", API_KEY)

    service = SentenceTransformerEmbeddingService("gemini-embedding-001")

    assert service.active_model_name == "gemini-embedding-001-384"
    assert service.is_real_model is True
    assert calls == []


def test_missing_key_and_test_mode_fall_back_to_mock_vectors(monkeypatch):
    calls = _install_client(monkeypatch, lambda url, payload: _values_response())
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    without_key = SentenceTransformerEmbeddingService("gemini-embedding-001")
    assert without_key.active_model_name == "mock-384"
    assert without_key.is_real_model is False

    # Tests always run in mock mode: APP_ENV=test / pytest is imported.
    monkeypatch.setattr(settings, "GEMINI_API_KEY", API_KEY)
    under_test = SentenceTransformerEmbeddingService("gemini-embedding-001")
    assert under_test.active_model_name == "mock-384"
    assert under_test.is_real_model is False

    vector = under_test.embed_query("What is photosynthesis?")
    assert len(vector) == EMBEDDING_DIMENSION
    assert calls == []


def test_embed_query_calls_embed_content_without_e5_prefix(gemini_service, monkeypatch):
    calls = _install_client(monkeypatch, lambda url, payload: _values_response())

    vector = gemini_service.embed_query("What is photosynthesis?")

    assert len(vector) == EMBEDDING_DIMENSION
    assert calls[0]["url"].endswith("/models/gemini-embedding-001:embedContent")
    assert calls[0]["headers"]["x-goog-api-key"] == API_KEY
    assert calls[0]["json"] == {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": "What is photosynthesis?"}]},
        "taskType": "RETRIEVAL_QUERY",
        "outputDimensionality": EMBEDDING_DIMENSION,
    }


def test_embed_passage_uses_retrieval_document_task(gemini_service, monkeypatch):
    calls = _install_client(monkeypatch, lambda url, payload: _values_response())

    gemini_service.embed_passage("Photosynthesis converts light into energy.")

    assert calls[0]["url"].endswith(":embedContent")
    assert calls[0]["json"]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert calls[0]["json"]["content"]["parts"][0]["text"] == (
        "Photosynthesis converts light into energy."
    )


def test_returned_vectors_are_l2_normalized(gemini_service, monkeypatch):
    # A truncated Gemini embedding is not unit-length: all-ones has norm sqrt(384).
    _install_client(monkeypatch, lambda url, payload: _values_response(values=[1.0] * EMBEDDING_DIMENSION))

    vector = gemini_service.embed_query("normalize me")

    assert len(vector) == EMBEDDING_DIMENSION
    assert pytest.approx(sum(value * value for value in vector), rel=1e-9) == 1.0


def test_embed_texts_batches_at_most_one_hundred_requests(gemini_service, monkeypatch):
    calls = _install_client(
        monkeypatch,
        lambda url, payload: _values_response(count=len(payload["requests"])),
    )

    vectors = gemini_service.embed_texts([f"chunk {i}" for i in range(250)], is_query=False)

    assert len(vectors) == 250
    assert all(len(vector) == EMBEDDING_DIMENSION for vector in vectors)
    assert [len(call["json"]["requests"]) for call in calls] == [100, 100, 50]
    assert all(call["url"].endswith(":batchEmbedContents") for call in calls)
    assert all(
        request["taskType"] == "RETRIEVAL_DOCUMENT" for call in calls for request in call["json"]["requests"]
    )
    assert calls[0]["json"]["requests"][0]["outputDimensionality"] == EMBEDDING_DIMENSION


def test_retries_on_429_and_5xx_then_succeeds(gemini_service, monkeypatch):
    statuses = [429, 503, 200]
    calls = _install_client(
        monkeypatch,
        lambda url, payload: httpx.Response(
            statuses.pop(0),
            json={"error": {"code": 429, "message": "Rate limit exceeded"}}
            if statuses
            else {"embedding": {"values": [1.0] * EMBEDDING_DIMENSION}},
        ),
    )
    slept: list[float] = []
    monkeypatch.setattr(embedding_module.time, "sleep", lambda seconds: slept.append(seconds))

    vector = gemini_service.embed_query("retry me")

    assert len(vector) == EMBEDDING_DIMENSION
    assert len(calls) == 3
    assert slept == [0.5, 1.0]


def test_retry_exhaustion_raises_a_clear_error_without_the_key(gemini_service, monkeypatch):
    calls = _install_client(
        monkeypatch,
        lambda url, payload: httpx.Response(
            429, json={"error": {"code": 429, "message": f"Quota exceeded for key {API_KEY}"}}
        ),
    )

    with pytest.raises(EmbeddingError) as error:
        gemini_service.embed_query("never succeeds")

    assert len(calls) == 4  # the first attempt plus three retries
    assert "HTTP 429" in str(error.value)
    assert API_KEY not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_non_retryable_status_is_reported_immediately(gemini_service, monkeypatch):
    calls = _install_client(
        monkeypatch,
        lambda url, payload: httpx.Response(400, json={"error": {"message": "Invalid model"}}),
    )

    with pytest.raises(EmbeddingError, match="HTTP 400"):
        gemini_service.embed_query("bad request")

    assert len(calls) == 1


def test_unexpected_dimension_is_rejected(gemini_service, monkeypatch):
    _install_client(monkeypatch, lambda url, payload: _values_response(values=[0.5] * 768))

    with pytest.raises(EmbeddingError, match="768-dimension"):
        gemini_service.embed_query("wrong size")
