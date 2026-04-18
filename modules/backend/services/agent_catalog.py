"""
Agent Catalog Service.

Business logic for the global agent registry. Handles CRUD operations,
system prompt updates with version tracking, and catalog queries.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.exceptions import ConflictError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.models.agent_catalog import AgentCatalog
from modules.backend.repositories.agent_catalog import AgentCatalogRepository
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class AgentCatalogService(BaseService):
    """Service for agent catalog management."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._repo = AgentCatalogRepository(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["AgentCatalogService", None]:
        """Create an AgentCatalogService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield AgentCatalogService(db)
            await db.commit()

    async def get_by_name(self, agent_name: str) -> AgentCatalog:
        """Get a catalog entry by agent name. Raises NotFoundError."""
        entry = await self._repo.get_by_name(agent_name)
        if not entry:
            raise NotFoundError(f"Agent '{agent_name}' not found in catalog")
        return entry

    async def get_by_name_or_none(self, agent_name: str) -> AgentCatalog | None:
        """Get a catalog entry by agent name, or None."""
        return await self._repo.get_by_name(agent_name)

    async def list_catalog(
        self,
        enabled_only: bool = True,
        visibility: str | None = None,
        agent_type: str | None = None,
    ) -> list[AgentCatalog]:
        """List catalog entries with optional filters."""
        if agent_type:
            return await self._repo.list_by_type(agent_type, enabled_only=enabled_only)
        if enabled_only:
            return await self._repo.list_enabled(visibility=visibility)
        return await self._repo.get_all(limit=500)

    async def list_by_type(
        self,
        agent_type: str,
        enabled_only: bool = True,
    ) -> list[AgentCatalog]:
        """List catalog entries filtered by agent type."""
        return await self._repo.list_by_type(agent_type, enabled_only=enabled_only)

    async def create_entry(
        self,
        *,
        agent_name: str,
        agent_type: str,
        description: str,
        system_prompt: str = "",
        model_config_json: dict[str, Any] | None = None,
        version: str = "1.0.0",
        tools: list[str] | None = None,
        scope: dict[str, Any] | None = None,
        interface: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
        enabled: bool = True,
        chat_enabled: bool = False,
        visibility: str = "public",
        engine: str = "pydantic_ai",
        effort: str | None = None,
    ) -> AgentCatalog:
        """Create a new agent catalog entry."""
        existing = await self._repo.get_by_name(agent_name)
        if existing:
            raise ConflictError(f"Agent '{agent_name}' already exists in catalog")

        entry = await self._repo.create(
            agent_name=agent_name,
            agent_type=agent_type,
            version=version,
            description=description,
            system_prompt=system_prompt,
            model_config_json=model_config_json or {"name": "anthropic:claude-haiku-4-5-20251001", "temperature": 0.0, "max_tokens": 4096},
            tools=tools or [],
            scope=scope or {"read": [], "write": []},
            interface=interface,
            constraints=constraints or {"timeout_seconds": 120, "cost_ceiling_usd": 1.0, "retry_budget": 2},
            keywords=keywords or [],
            enabled=enabled,
            chat_enabled=chat_enabled,
            visibility=visibility,
            engine=engine,
            effort=effort,
        )

        self._log_operation(
            "Agent catalog entry created",
            agent_name=agent_name,
            agent_type=agent_type,
        )
        return entry

    async def update_system_prompt(
        self,
        agent_name: str,
        content: str,
        changed_by: str,
        change_reason: str | None = None,
    ) -> AgentCatalog:
        """Update an agent's system prompt and create a version record."""
        entry = await self.get_by_name(agent_name)

        old_prompt = entry.system_prompt
        entry.system_prompt = content
        await self._session.flush()
        await self._session.refresh(entry)

        from modules.backend.repositories.prompt_version import PromptVersionRepository
        pv_repo = PromptVersionRepository(self._session)
        await pv_repo.create_version(
            entity_type="agent_catalog",
            entity_id=entry.id,
            prompt_type="system",
            content=content,
            changed_by=changed_by,
            change_reason=change_reason,
        )

        self._log_operation(
            "System prompt updated",
            agent_name=agent_name,
            changed_by=changed_by,
            old_length=len(old_prompt),
            new_length=len(content),
        )
        return entry

    async def update_entry(
        self,
        agent_name: str,
        **updates: Any,
    ) -> AgentCatalog:
        """Update arbitrary fields on a catalog entry.

        Raises:
            ValidationError: If no fields are provided.
        """
        if not updates:
            from modules.backend.core.exceptions import ValidationError
            raise ValidationError("No fields to update")
        entry = await self.get_by_name(agent_name)
        return await self._repo.update(entry.id, **updates)

    async def is_catalog_empty(self) -> bool:
        """Check if the catalog needs seeding."""
        return await self._repo.is_empty()

    async def delete_entry(self, agent_name: str) -> None:
        """Delete an agent catalog entry by name."""
        entry = await self.get_by_name(agent_name)
        await self._repo.delete(entry.id)
        self._log_operation("Agent catalog entry deleted", agent_name=agent_name)

    async def get_prompt_history(
        self,
        agent_name: str,
        limit: int = 50,
    ) -> list:
        """Get prompt version history for an agent."""
        from modules.backend.repositories.prompt_version import PromptVersionRepository

        entry = await self.get_by_name(agent_name)
        pv_repo = PromptVersionRepository(self._session)
        return await pv_repo.list_versions(
            entity_type="agent_catalog",
            entity_id=entry.id,
            limit=limit,
        )

    async def search_by_keyword(self, text: str) -> list[AgentCatalog]:
        """Search catalog by keyword match."""
        return await self._repo.search_by_keyword(text)
