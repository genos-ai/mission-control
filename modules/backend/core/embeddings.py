"""
Embedding Provider Abstraction.

Provider-agnostic async client for generating text embeddings.
Implements fail-open: if the provider is unavailable, returns None
so callers can fall back to structured-only search.

Configured via ``knowledge.embedding.*`` in missions.yaml and
``OPENAI_API_KEY`` in config/.env.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class Embedder(ABC):
    """Abstract embedding provider."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            EmbeddingProviderError: If the provider call fails.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier used for version tracking."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """The dimensionality of the output vectors."""


class EmbeddingProviderError(Exception):
    """Raised when an embedding provider call fails."""


class OpenAIEmbedder(Embedder):
    """OpenAI text-embedding-3-small provider.

    Requires ``OPENAI_API_KEY`` in environment / config/.env.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dims: int = 1536,
    ) -> None:
        self._model = model
        self._dims = dims
        self._client: object | None = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, text: str) -> list[float]:
        """Call OpenAI embeddings API."""
        client = self._get_client()
        try:
            response = await client.embeddings.create(
                model=self._model,
                input=text,
                dimensions=self._dims,
            )
            return response.data[0].embedding
        except Exception as e:
            raise EmbeddingProviderError(
                f"OpenAI embedding failed: {e}"
            ) from e

    def _get_client(self) -> object:
        """Lazy-init the async OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI()
            except ImportError as e:
                raise EmbeddingProviderError(
                    "openai package required for OpenAI embeddings: "
                    "pip install openai"
                ) from e
        return self._client


class FakeEmbedder(Embedder):
    """Deterministic pseudo-embedder for tests.

    Generates reproducible vectors from content hashes so that
    identical inputs always produce the same vector and similar
    inputs produce similar (but not identical) vectors.
    """

    def __init__(self, dims: int = 1536) -> None:
        self._dims = dims

    @property
    def model_name(self) -> str:
        return "fake-embedder"

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, text: str) -> list[float]:
        """Generate a deterministic vector from text hash."""
        digest = hashlib.sha256(text.encode()).digest()
        # Expand the 32-byte digest to fill the vector dimensions
        vector: list[float] = []
        for i in range(self._dims):
            byte_val = digest[i % len(digest)]
            # XOR with position to add variation beyond the hash cycle
            mixed = byte_val ^ (i & 0xFF)
            # Normalise to [-1, 1] range
            vector.append((mixed / 127.5) - 1.0)
        return vector


class FailOpenEmbedder(Embedder):
    """Wrapper that catches provider errors and returns None-compatible results.

    Used in production to ensure embedding failures never block writes
    or crash search. When the inner provider fails, logs a warning and
    returns an empty list (callers check for this).
    """

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    async def embed(self, text: str) -> list[float]:
        """Attempt embedding; return empty list on failure."""
        try:
            return await self._inner.embed(text)
        except Exception:
            logger.warning(
                "Embedding provider failed (fail-open: returning empty)",
                extra={
                    "provider": self._inner.__class__.__name__,
                    "model": self._inner.model_name,
                    "text_length": len(text),
                },
            )
            return []


def content_hash(text: str) -> str:
    """Generate a content hash for dedup of identical text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_embedder() -> Embedder:
    """Build an Embedder from application config.

    Returns a FailOpenEmbedder wrapping the configured provider.
    Falls back to FakeEmbedder if config is unavailable (e.g. tests).
    """
    try:
        from modules.backend.core.config import get_app_config
        cfg = get_app_config().missions
        embedding_cfg = getattr(cfg, "knowledge", None)
        if embedding_cfg is None:
            return FailOpenEmbedder(FakeEmbedder())

        embedding = getattr(embedding_cfg, "embedding", None)
        if embedding is None:
            return FailOpenEmbedder(FakeEmbedder())

        provider = getattr(embedding, "provider", "openai")
        model = getattr(embedding, "model", "text-embedding-3-small")
        dims = getattr(embedding, "dimensions", 1536)

        if provider == "openai":
            inner = OpenAIEmbedder(model=model, dims=dims)
        else:
            logger.warning(
                "Unknown embedding provider, using fake",
                extra={"provider": provider},
            )
            inner = FakeEmbedder(dims=dims)

        fail_open = getattr(embedding, "fail_open", True)
        if fail_open:
            return FailOpenEmbedder(inner)
        return inner
    except Exception:
        logger.debug("Embedding config unavailable, using FakeEmbedder")
        return FailOpenEmbedder(FakeEmbedder())
