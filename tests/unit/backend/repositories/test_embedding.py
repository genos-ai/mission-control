"""
Unit tests for EmbeddingRepository's source_table allowlist.

semantic_search/hybrid_search bind source_table values as query params
(already injection-safe), but list_missing interpolates one directly as
a FROM-clause identifier, which SQL bind params can't cover. All three
validate against VALID_SOURCE_TABLES before touching the session so a
bad table name never reaches raw SQL.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.backend.core.exceptions import ValidationError
from modules.backend.repositories.embedding import EmbeddingRepository


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.fetchall = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture
def repo(mock_session: MagicMock) -> EmbeddingRepository:
    return EmbeddingRepository(mock_session)


class TestSemanticSearchAllowlist:
    @pytest.mark.asyncio
    async def test_rejects_unknown_source_table(self, repo, mock_session):
        with pytest.raises(ValidationError):
            await repo.semantic_search([0.1, 0.2], source_tables=["users"])
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_known_source_table(self, repo, mock_session):
        await repo.semantic_search([0.1, 0.2], source_tables=["mission_learnings"])
        mock_session.execute.assert_awaited_once()


class TestHybridSearchAllowlist:
    @pytest.mark.asyncio
    async def test_rejects_unknown_source_table(self, repo, mock_session):
        with pytest.raises(ValidationError):
            await repo.hybrid_search([0.1, 0.2], filter_ids={"users": ["1"]})
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_known_source_table(self, repo, mock_session):
        await repo.hybrid_search([0.1, 0.2], filter_ids={"mission_learnings": ["1"]})
        mock_session.execute.assert_awaited_once()


class TestListMissingAllowlist:
    @pytest.mark.asyncio
    async def test_rejects_unknown_source_table(self, repo, mock_session):
        with pytest.raises(ValidationError):
            await repo.list_missing("users", 1)
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_known_source_table(self, repo, mock_session):
        await repo.list_missing("mission_learnings", 1)
        mock_session.execute.assert_awaited_once()
