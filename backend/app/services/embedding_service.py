"""
Embedding service interface and placeholder implementation.
Produces 1536-dimensional vectors for pgvector compatibility.
"""

import abc
import hashlib


class BaseEmbeddingService(abc.ABC):

    @abc.abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of text strings."""
        pass

    @abc.abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""
        pass


class PlaceholderEmbeddingService(BaseEmbeddingService):
    """Placeholder embedding service generating deterministic 1536-dim vectors."""

    def embed_text(self, text: str) -> list[float]:
        # Generate a deterministic pseudo-random 1536-dim vector from text hash
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand 32 bytes into 1536 floats normalized between -1 and 1
        vector = []
        for i in range(1536):
            byte_val = hash_bytes[i % len(hash_bytes)]
            # Modify slightly by index
            val = ((byte_val + i) % 256) / 128.0 - 1.0
            vector.append(val)
        return vector

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


# Default embedding service instance
embedding_service = PlaceholderEmbeddingService()
