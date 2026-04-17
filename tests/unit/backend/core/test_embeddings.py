"""
Unit tests for the embedding provider abstraction.

No external API calls — tests FakeEmbedder, FailOpenEmbedder, and content_hash.
"""

import pytest

from modules.backend.core.embeddings import (
    EmbeddingProviderError,
    Embedder,
    FailOpenEmbedder,
    FakeEmbedder,
    content_hash,
)


# ── FakeEmbedder ─────────────────────────────────────────────


class TestFakeEmbedder:
    @pytest.fixture
    def embedder(self) -> FakeEmbedder:
        return FakeEmbedder(dims=1536)

    @pytest.mark.asyncio
    async def test_returns_correct_dimensions(self, embedder):
        vec = await embedder.embed("hello")
        assert len(vec) == 1536

    @pytest.mark.asyncio
    async def test_deterministic(self, embedder):
        vec1 = await embedder.embed("test input")
        vec2 = await embedder.embed("test input")
        assert vec1 == vec2

    @pytest.mark.asyncio
    async def test_different_inputs_different_vectors(self, embedder):
        vec1 = await embedder.embed("hello")
        vec2 = await embedder.embed("world")
        assert vec1 != vec2

    @pytest.mark.asyncio
    async def test_values_in_range(self, embedder):
        vec = await embedder.embed("test")
        assert all(-1.0 <= v <= 1.0 for v in vec)

    def test_model_name(self, embedder):
        assert embedder.model_name == "fake-embedder"

    def test_dimensions_property(self, embedder):
        assert embedder.dimensions == 1536

    @pytest.mark.asyncio
    async def test_custom_dimensions(self):
        embedder = FakeEmbedder(dims=768)
        vec = await embedder.embed("test")
        assert len(vec) == 768
        assert embedder.dimensions == 768

    @pytest.mark.asyncio
    async def test_empty_string(self, embedder):
        vec = await embedder.embed("")
        assert len(vec) == 1536


# ── FailOpenEmbedder ─────────────────────────────────────────


class TestFailOpenEmbedder:
    @pytest.mark.asyncio
    async def test_delegates_to_inner(self):
        inner = FakeEmbedder()
        wrapper = FailOpenEmbedder(inner)
        vec = await wrapper.embed("test")
        assert len(vec) == 1536

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        class BrokenEmbedder(Embedder):
            @property
            def model_name(self) -> str:
                return "broken"

            @property
            def dimensions(self) -> int:
                return 1536

            async def embed(self, text: str) -> list[float]:
                raise EmbeddingProviderError("API down")

        wrapper = FailOpenEmbedder(BrokenEmbedder())
        result = await wrapper.embed("test")
        assert result == []

    def test_model_name_delegates(self):
        inner = FakeEmbedder()
        wrapper = FailOpenEmbedder(inner)
        assert wrapper.model_name == "fake-embedder"

    def test_dimensions_delegates(self):
        inner = FakeEmbedder()
        wrapper = FailOpenEmbedder(inner)
        assert wrapper.dimensions == 1536


# ── content_hash ─────────────────────────────────────────────


class TestContentHash:
    def test_deterministic(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello world")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = content_hash("hello")
        h2 = content_hash("world")
        assert h1 != h2

    def test_returns_string(self):
        h = content_hash("test")
        assert isinstance(h, str)

    def test_length(self):
        h = content_hash("test")
        assert len(h) == 16  # truncated sha256
