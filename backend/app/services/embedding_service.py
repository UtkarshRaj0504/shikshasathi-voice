"""
Embedding service backed by the Google Gemini embeddings REST API.

Vectors come from ``gemini-embedding-001`` truncated to
``EMBEDDING_DIMENSION`` (384) so they stay compatible with the pgvector columns
created by migration 001. Gemini returns unit-length vectors at its native size
but *not* when ``outputDimensionality`` truncates them, so every vector is
L2-normalized here — retrieval relies on cosine similarity.

Nothing is loaded locally: the sentence-transformers model (and torch) was
removed so the API fits in a small container. Importing this module, reading
``active_model_name`` / ``is_real_model`` and starting the app perform no
network call; the only traffic is the embedding requests themselves.

When ``GEMINI_API_KEY`` is empty, or the app runs in test mode, the service
falls back to the deterministic in-process mock vectors.

Chunks stored with a different dimension (for example the legacy 1536-dim
placeholder model) cannot be compared against a query vector and must be
re-embedded with the re-embed script (``backend/scripts/reembed_chunks.py``).
"""

import abc
import hashlib
import math
import os
import sys
import time

import httpx

from app.core.config import settings

EMBEDDING_DIMENSION = 384

#: Gemini embedding model that produces every vector.
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

_MOCK_MODEL_NAME = "mock-384"
_REAL_MODEL_NAME = f"{GEMINI_EMBEDDING_MODEL}-{EMBEDDING_DIMENSION}"

#: ``batchEmbedContents`` accepts at most 100 requests per call.
_MAX_BATCH_SIZE = 100
#: Retries after the first attempt, only for 429 / 5xx responses.
_MAX_RETRIES = 3
#: Backoff before retry *n* is this value doubled *n* times (0.5 s, 1 s, 2 s).
_RETRY_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_REQUEST_TIMEOUT_SECONDS = 30.0


class EmbeddingError(RuntimeError):
    """Raised when the Gemini embeddings API cannot produce vectors."""


def _in_test_mode() -> bool:
    """Tests always use the mock vectors: no API key is read, no network used."""
    return "pytest" in sys.modules or os.getenv("APP_ENV") == "test"


def _safe_message(text: str, api_key: str = "") -> str:
    """One-line, length-capped error text that never leaks the API key."""
    cleaned = " ".join((text or "").split())[:240]
    if api_key:
        cleaned = cleaned.replace(api_key, "[redacted]")
    return cleaned


def _batched(texts: list[str], size: int) -> list[list[str]]:
    return [texts[i : i + size] for i in range(0, len(texts), size)]


def _error_message(response: httpx.Response) -> str:
    """The API's own error message, when the error body carries one."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return ""
    return str(error.get("message") or "") if isinstance(error, dict) else ""


def _normalized(values) -> list[float]:
    """Validate the dimension and L2-normalize the returned vector."""
    vector = [float(value) for value in (values or [])]
    if len(vector) != EMBEDDING_DIMENSION:
        raise EmbeddingError(
            f"Gemini returned a {len(vector)}-dimension embedding; "
            f"{EMBEDDING_DIMENSION} are required by the stored chunk vectors."
        )
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return vector
    return [value / norm for value in vector]


class BaseEmbeddingService(abc.ABC):

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a search query."""
        pass

    @abc.abstractmethod
    def embed_passage(self, text: str) -> list[float]:
        """Generate embedding for a document passage."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """Generate embeddings for a list of text strings."""
        pass


class SentenceTransformerEmbeddingService(BaseEmbeddingService):
    """Embedding service calling the Gemini embeddings REST API.

    The class name is kept from the previous sentence-transformers
    implementation so existing imports and call sites stay unchanged.
    """

    #: Dimension of every vector produced by this service.
    dimension = EMBEDDING_DIMENSION

    def __init__(self, model_name: str = GEMINI_EMBEDDING_MODEL):
        # A leftover EMBEDDING_MODEL value from the sentence-transformers era
        # (for example "intfloat/multilingual-e5-small") is not a Gemini model.
        configured = model_name if isinstance(model_name, str) else ""
        self.model_name = (
            configured if configured.startswith("gemini-embedding") else GEMINI_EMBEDDING_MODEL
        )

    @property
    def _api_key(self) -> str:
        """Read the key lazily so configuration changes are always honoured."""
        return (getattr(settings, "GEMINI_API_KEY", "") or "").strip()

    @property
    def _uses_api(self) -> bool:
        """True only when a key is configured and the app is not under test."""
        return bool(self._api_key) and not _in_test_mode()

    @property
    def active_model_name(self) -> str:
        """Identifier stored alongside chunks so stale embeddings can be detected.

        Purely configuration-based: it never loads a model or calls the API.
        """
        return _REAL_MODEL_NAME if self._uses_api else _MOCK_MODEL_NAME

    @property
    def is_real_model(self) -> bool:
        """True when the Gemini API is used instead of the mock fallback."""
        return self._uses_api

    def _mock_vector(self, text: str) -> list[float]:
        """Generate stable deterministic mock embedding for testing.
        Uses content hash (not just first word) so similar content gets similar embeddings.
        """
        # For mock: use all meaningful words to generate vector
        # This ensures "photosynthesis question" and "photosynthesis answer" get similar embeddings
        words = text.strip().lower().split()
        # Take up to 5 meaningful words (skip common stop words)
        stop_words = {"what", "is", "the", "a", "an", "how", "why", "does", "do", "can", "explain"}
        meaningful_words = [w for w in words if w not in stop_words][:5]
        key_text = " ".join(meaningful_words) if meaningful_words else text[:20]

        hash_bytes = hashlib.sha256(key_text.encode("utf-8")).digest()
        vector = []
        for i in range(384):
            byte_val = hash_bytes[i % len(hash_bytes)]
            val = ((byte_val + i) % 256) / 128.0 - 1.0
            vector.append(float(val))
        return vector

    def _request_body(self, text: str, task_type: str) -> dict:
        return {
            "model": f"models/{self.model_name}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": EMBEDDING_DIMENSION,
        }

    def _post_json(self, url: str, payload: dict) -> dict:
        """POST the payload, retrying 429/5xx with exponential backoff.

        The key travels in the ``x-goog-api-key`` header only and is never logged;
        error messages are sanitized and never contain it.
        """
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        failure = "no response"

        for attempt in range(_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                    response = client.post(url, headers=headers, json=payload)
            except httpx.RequestError as exc:
                raise EmbeddingError(
                    f"Could not reach the Gemini embeddings API ({type(exc).__name__}). "
                    "Check the backend's network access and try again."
                ) from None

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise EmbeddingError(
                        "The Gemini embeddings API returned a non-JSON response."
                    ) from None

            failure = (
                f"HTTP {response.status_code} "
                f"{_safe_message(_error_message(response), self._api_key)}"
            ).strip()
            if response.status_code not in _RETRYABLE_STATUS_CODES or attempt == _MAX_RETRIES:
                break
            time.sleep(_RETRY_BACKOFF_SECONDS * (2**attempt))

        raise EmbeddingError(f"Gemini embeddings request failed after retries: {failure}")

    def _embed_single(self, text: str, task_type: str) -> list[float]:
        data = self._post_json(
            f"{GEMINI_API_BASE}/models/{self.model_name}:embedContent",
            self._request_body(text, task_type),
        )
        return _normalized((data.get("embedding") or {}).get("values"))

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        data = self._post_json(
            f"{GEMINI_API_BASE}/models/{self.model_name}:batchEmbedContents",
            {"requests": [self._request_body(text, task_type) for text in texts]},
        )
        embeddings = data.get("embeddings") or []
        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"The Gemini embeddings API returned {len(embeddings)} vectors "
                f"for {len(texts)} texts."
            )
        return [_normalized((embedding or {}).get("values")) for embedding in embeddings]

    def embed_query(self, text: str) -> list[float]:
        if not self._uses_api:
            return self._mock_vector(text)
        return self._embed_single(text, "RETRIEVAL_QUERY")

    def embed_passage(self, text: str) -> list[float]:
        if not self._uses_api:
            return self._mock_vector(text)
        return self._embed_single(text, "RETRIEVAL_DOCUMENT")

    def embed_texts(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        if not self._uses_api:
            return [self._mock_vector(text) for text in texts]

        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        vectors: list[list[float]] = []
        for batch in _batched(texts, _MAX_BATCH_SIZE):
            vectors.extend(self._embed_batch(batch, task_type))
        return vectors


# Default embedding service instance
embedding_service = SentenceTransformerEmbeddingService(settings.EMBEDDING_MODEL)
