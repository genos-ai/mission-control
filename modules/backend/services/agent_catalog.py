"""
Agent Catalog Service.

Business logic for the global agent registry. Handles CRUD operations,
system prompt updates with version tracking, and catalog queries.
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import agent_defaults
from modules.backend.core.exceptions import ConflictError, NotFoundError, ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.model_builder import (
    _resolve_model_alias,
    effective_output_mode,
    resolve_model,
)
from modules.backend.models.agent_catalog import AgentCatalog
from modules.backend.repositories.agent_catalog import AgentCatalogRepository
from modules.backend.schemas.agent_config import AgentModelSchema, Visibility
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _or(value: Any, default: Callable[[], Any]) -> Any:
    """``value`` unless it is None, else the default; 0 and empty values are kept."""
    return default() if value is None else value


def validated_model_config(raw: dict[str, Any]) -> dict[str, Any]:
    """``raw`` checked against AgentModelSchema: the keys given, coerced; a null drops its key.

    An output_mode is checked against the protocol the model registry files the
    model under, the same check the agent build makes, so a mode the model cannot
    honour is refused here rather than when the agent is next built.

    Raises:
        ValidationError: unknown key, bad value, or an output_mode the model's
            protocol cannot honour.
    """
    try:
        model = AgentModelSchema.from_catalog(raw)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "model_config_json"
        raise ValidationError(f"model_config_json.{location}: {first['msg']}") from exc
    if model.output_mode is not None:
        effective_output_mode(model, resolve_model(_resolve_model_alias(model.name)))
    return model.model_dump(mode="json", exclude_unset=True)


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

    @staticmethod
    def _default_model_config() -> dict[str, Any]:
        """Model block for an agent created without one: the ``quick`` alias, schema defaults."""
        return {
            "name": _resolve_model_alias("quick"),
            "temperature": agent_defaults.temperature(),
            "max_tokens": agent_defaults.max_tokens(),
        }

    @staticmethod
    def _default_constraints() -> dict[str, Any]:
        """Constraints for an agent created without any, all from config."""
        return {
            "timeout_seconds": agent_defaults.task_timeout_seconds(),
            "cost_ceiling_usd": agent_defaults.max_budget_usd(),
            "retry_budget": agent_defaults.retry_budget(),
        }

    async def create_entry(
        self,
        *,
        agent_name: str,
        agent_type: str,
        description: str,
        system_prompt: str = "",
        model_config_json: dict[str, Any] | None = None,
        version: str | None = None,
        tools: list[str] | None = None,
        scope: dict[str, Any] | None = None,
        interface: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
        enabled: bool = True,
        chat_enabled: bool = False,
        visibility: Visibility | None = None,
        engine: str | None = None,
        effort: str | None = None,
        invocation_tier: str | None = None,
        invocation_required_role: str | None = None,
        execution_mode: str | None = None,
        thinking_budget_json: dict | None = None,
        max_input_length: int | None = None,
        max_budget_usd: float | None = None,
        produces_artifact: bool = False,
        artifact_type: str | None = None,
    ) -> AgentCatalog:
        """Create a new agent catalog entry."""
        existing = await self._repo.get_by_name(agent_name)
        if existing:
            raise ConflictError(f"Agent '{agent_name}' already exists in catalog")

        entry = await self._repo.create(
            agent_name=agent_name,
            agent_type=agent_type,
            version=_or(version, agent_defaults.version),
            description=description,
            system_prompt=system_prompt,
            model_config_json=(
                validated_model_config(model_config_json)
                if model_config_json
                else self._default_model_config()
            ),
            tools=tools or [],
            scope=scope or {"read": [], "write": []},
            interface=interface,
            constraints=constraints or self._default_constraints(),
            keywords=keywords or [],
            enabled=enabled,
            chat_enabled=chat_enabled,
            visibility=_or(visibility, agent_defaults.visibility),
            engine=_or(engine, agent_defaults.engine),
            effort=effort,
            invocation_tier=_or(invocation_tier, agent_defaults.invocation_tier),
            invocation_required_role=invocation_required_role,
            execution_mode=_or(execution_mode, agent_defaults.execution_mode),
            thinking_budget_json=thinking_budget_json,
            max_input_length=_or(max_input_length, agent_defaults.max_input_length),
            max_budget_usd=_or(max_budget_usd, agent_defaults.max_budget_usd),
            produces_artifact=produces_artifact,
            artifact_type=artifact_type,
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
            raise ValidationError("No fields to update")
        if updates.get("model_config_json") is not None:
            updates["model_config_json"] = validated_model_config(updates["model_config_json"])
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
