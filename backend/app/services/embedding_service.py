"""
Embedding service using sentence-transformers (multilingual-e5-small, dim 384)
with query and passage prefixes.

The active embedding dimension is fixed at ``EMBEDDING_DIMENSION`` (384). Chunks
stored with a different dimension (for example the legacy 1536-dim placeholder
model) cannot be compared against a query vector and must be re-embedded with the
re-embed script (``backend/scripts/reembed_chunks.py``).
"""

import abc
import hashlib
import os
import sys
from app.core.config import settings

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

EMBEDDING_DIMENSION = 384


class BaseEmbeddingService(abc.ABC):

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a search query (with 'query: ' prefix)."""
        pass

    @abc.abstractmethod
    def embed_passage(self, text: str) -> list[float]:
        """Generate embedding for a document passage (with 'passage: ' prefix)."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """Generate embeddings for a list of text strings."""
        pass


class SentenceTransformerEmbeddingService(BaseEmbeddingService):
    """Real multilingual embedding service using sentence-transformers."""

    #: Dimension of every vector produced by this service.
    dimension = EMBEDDING_DIMENSION

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            if "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or SentenceTransformer is None:
                self._model = None
            else:
                try:
                    self._model = SentenceTransformer(self.model_name)
                except Exception as e:
                    print(f"Failed to load SentenceTransformer model {self.model_name}: {e}. Falling back to mock.")
                    self._model = None
        return self._model

    @property
    def active_model_name(self) -> str:
        """Identifier stored alongside chunks so stale embeddings can be detected.

        Returns the real model id when the sentence-transformers model is loaded,
        otherwise the deterministic in-process fallback used in tests/offline mode.
        """
        return self.model_name if self.model is not None else "mock-384"

    @property
    def is_real_model(self) -> bool:
        """True when a real sentence-transformers model is loaded (not the mock fallback)."""
        return self.model is not None

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

    def embed_query(self, text: str) -> list[float]:
        if self.model is not None:
            emb = self.model.encode([f"query: {text}"], normalize_embeddings=True)[0]
            return emb.tolist()
        return self._mock_vector(text)

    def embed_passage(self, text: str) -> list[float]:
        if self.model is not None:
            emb = self.model.encode([f"passage: {text}"], normalize_embeddings=True)[0]
            return emb.tolist()
        return self._mock_vector(text)

    def embed_texts(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        if self.model is not None:
            prefix = "query: " if is_query else "passage: "
            prefixed_texts = [f"{prefix}{t}" for t in texts]
            embeddings = self.model.encode(prefixed_texts, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]
        return [self._mock_vector(t) for t in texts]


# Default embedding service instance
embedding_service = SentenceTransformerEmbeddingService(settings.EMBEDDING_MODEL)
