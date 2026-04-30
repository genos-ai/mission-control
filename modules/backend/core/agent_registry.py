"""
Agent Registry.

DB-first agent configuration registry. The database catalog is the
source of truth; YAML files are seed data only (loaded as fallback
when DB is unavailable, e.g. during bootstrap or tests).

Provides lookup by name, keyword matching, module path resolution,
and listing. Caches results after first load. Call reload() to
refresh from DB after admin changes.
"""

import asyncio
import importlib
from functools import lru_cache
from typing import Any

import yaml
from pydantic import ValidationError

from modules.backend.schemas.agent_config import (
    AgentConfigSchema,
    AgentModelSchema,
    ExecutionSchema,
    FileScopeConfigSchema,
    InvocationSchema,
)
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _db_row_to_config(row: Any) -> AgentConfigSchema:
    """Map an AgentCatalog DB row to an AgentConfigSchema.

    The DB stores some fields in different shapes (e.g. model_config_json
    as a dict vs AgentModelSchema). This function normalises them.
    """
    model_cfg = row.model_config_json or {}
    if not model_cfg.get("name"):
        raise ValueError(
            f"Agent '{row.agent_name}' has no model name in model_config_json. "
            f"Fix the agent_catalog row in the database."
        )
    model_name = model_cfg["name"]

    # Reconstruct the model field as AgentModelSchema if it has extra fields
    if model_cfg.get("temperature") is not None or model_cfg.get("max_tokens"):
        model: str | AgentModelSchema = AgentModelSchema(
            name=model_name,
            temperature=model_cfg.get("temperature", 0.0),
            max_tokens=model_cfg.get("max_tokens"),
        )
    else:
        model = model_name

    scope_data = row.scope or {}
    interface_data = row.interface
    constraints = row.constraints or {}

    return AgentConfigSchema(
        agent_name=row.agent_name,
        agent_type=row.agent_type,
        description=row.description,
        enabled=row.enabled,
        model=model,
        keywords=row.keywords or [],
        tools=row.tools or [],
        max_input_length=getattr(row, "max_input_length", 32000) or 32000,
        max_budget_usd=getattr(row, "max_budget_usd", 1.0) or constraints.get("cost_ceiling_usd", 1.0),
        execution=ExecutionSchema(
            mode=getattr(row, "execution_mode", "standard") or "standard",
        ),
        invocation=InvocationSchema(
            tier=getattr(row, "invocation_tier", "user") or "user",
            required_role=getattr(row, "invocation_required_role", None),
        ),
        scope=FileScopeConfigSchema(
            read=scope_data.get("read", []),
            write=scope_data.get("write", []),
        ),
        interface=interface_data,
        version=row.version or "1.0.0",
        chat_enabled=row.chat_enabled,
        thinking_budget=getattr(row, "thinking_budget_json", None),
        engine=getattr(row, "engine", "pydantic_ai") or "pydantic_ai",
        effort=getattr(row, "effort", None),
        produces_artifact=getattr(row, "produces_artifact", False),
        artifact_type=getattr(row, "artifact_type", None),
    )


class AgentRegistry:
    """DB-first agent configuration registry.

    Loads from DB catalog on first access. Falls back to YAML if DB
    is unavailable (bootstrap, tests). Call reload() to refresh after
    admin changes.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfigSchema] = {}
        self._instances: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            self._load_from_db()
        except Exception as e:
            logger.warning(
                "DB catalog unavailable, falling back to YAML",
                extra={"error": str(e)},
            )
            self._load_from_yaml()
        self._loaded = True

    def _load_from_db(self) -> None:
        """Load agent configs from the DB catalog (source of truth)."""
        from modules.backend.core.database import get_sync_session
        from modules.backend.models.agent_catalog import AgentCatalog
        from sqlalchemy import select

        with get_sync_session() as session:
            result = session.execute(select(AgentCatalog))
            rows = result.scalars().all()

        count = 0
        for row in rows:
            if not row.enabled:
                logger.debug("Agent disabled", extra={"agent_name": row.agent_name})
                continue
            try:
                config = _db_row_to_config(row)
                self._agents[config.agent_name] = config
                count += 1
            except (ValidationError, Exception) as e:
                logger.error(
                    "Failed to load agent from DB",
                    extra={"agent_name": row.agent_name, "error": str(e)},
                )

        logger.debug("Agent registry loaded from DB", extra={"agent_count": count})

    def _load_from_yaml(self) -> None:
        """Fallback: load from YAML files (bootstrap/tests)."""
        agents_dir = find_project_root() / "config" / "agents"
        if not agents_dir.exists():
            return

        for path in sorted(agents_dir.rglob("agent.yaml")):
            try:
                with open(path) as f:
                    raw = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logger.error("Failed to parse agent config", extra={"path": str(path), "error": str(e)})
                continue

            if raw is None or not raw.get("agent_name"):
                continue

            try:
                config = AgentConfigSchema(**raw)
            except ValidationError as e:
                logger.error("Invalid agent config", extra={"path": str(path), "error": str(e)})
                continue

            if not config.enabled:
                continue

            self._agents[config.agent_name] = config

        logger.debug("Agent registry loaded from YAML (fallback)", extra={"agent_count": len(self._agents)})

    def reload(self) -> None:
        """Reload the registry from DB. Call after admin config changes."""
        self._agents.clear()
        self._instances.clear()
        self._loaded = False
        self._ensure_loaded()
        logger.info("Agent registry reloaded", extra={"agent_count": len(self._agents)})

    def get(self, agent_name: str) -> AgentConfigSchema:
        """Get agent config by name. Raises KeyError if not found."""
        self._ensure_loaded()
        if agent_name not in self._agents:
            available = ", ".join(self._agents.keys()) or "none"
            raise KeyError(f"Agent '{agent_name}' not found. Available: {available}")
        return self._agents[agent_name]

    def has(self, agent_name: str) -> bool:
        """Check if an agent exists in the registry."""
        self._ensure_loaded()
        return agent_name in self._agents

    def list_all(self, tier: str | None = None) -> list[dict[str, Any]]:
        """List registered agents with their metadata, filtered by tier."""
        self._ensure_loaded()
        result = []
        for config in self._agents.values():
            agent_tier = config.invocation.tier
            if agent_tier == "system":
                continue
            if tier == "user" and agent_tier == "platform":
                continue
            result.append({
                "agent_name": config.agent_name,
                "agent_type": config.agent_type,
                "description": config.description,
                "keywords": config.keywords,
                "tools": config.tools,
                "invocation_tier": agent_tier,
                "scope": {
                    "read": config.scope.read,
                    "write": config.scope.write,
                },
            })
        return result

    def list_system(self) -> list[dict[str, Any]]:
        """List system (dispatch infrastructure) agents only."""
        self._ensure_loaded()
        return [
            {
                "agent_name": config.agent_name,
                "agent_type": config.agent_type,
                "description": config.description,
            }
            for config in self._agents.values()
            if config.invocation.tier == "system"
        ]

    def get_by_keyword(self, text: str) -> str | None:
        """Find an agent whose keywords match the given text."""
        self._ensure_loaded()
        text_lower = text.lower()
        for agent_name, config in self._agents.items():
            for keyword in config.keywords:
                if keyword in text_lower:
                    return agent_name
        return None

    def resolve_module_path(self, agent_name: str) -> str:
        """Derive the Python import path from agent name."""
        parts = agent_name.replace(".agent", "").split(".")
        category = parts[0]
        name = parts[1]
        return f"modules.backend.agents.{category}.{name}.agent"

    def get_instance(self, agent_name: str, model: Any) -> Any:
        """Get or create a cached PydanticAI Agent instance.

        For chat-enabled agents whose create_agent() accepts chat_mode,
        passes chat_mode=True so tools and chat prompts are registered.
        """
        if agent_name in self._instances:
            return self._instances[agent_name]

        module_path = self.resolve_module_path(agent_name)
        module = importlib.import_module(module_path)

        # Pass chat_mode for agents that support it (e.g. planning agent)
        config = self._agents.get(agent_name)
        chat_enabled = config and getattr(config, "chat_enabled", False)
        try:
            agent = module.create_agent(model, chat_mode=chat_enabled)
        except TypeError:
            agent = module.create_agent(model)

        self._instances[agent_name] = agent

        logger.info("Agent instance created", extra={"agent_name": agent_name, "chat_mode": chat_enabled})
        return agent

    def reset(self) -> None:
        """Clear cached agent instances (for tests)."""
        self._instances.clear()


@lru_cache(maxsize=1)
def get_registry() -> AgentRegistry:
    """Get the cached registry instance."""
    return AgentRegistry()
