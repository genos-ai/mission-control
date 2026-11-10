"""
Agent Registry.

DB-first agent configuration registry. The database catalog is the
source of truth; YAML files are seed data only (loaded as fallback
when DB is unavailable, e.g. during bootstrap or tests).

Provides lookup by name, keyword matching, module path resolution,
and listing. Caches results after first load. Call reload() to
refresh from DB after admin changes.
"""

import importlib
import inspect
from functools import lru_cache
from typing import Any

import yaml
from pydantic import ValidationError

from modules.backend.core.agent_files import agents_dir, find_agent_files
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.schemas.agent_config import (
    AgentConfigSchema,
    AgentModelSchema,
    ExecutionSchema,
    FileScopeConfigSchema,
    InvocationSchema,
)

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
    # Every AgentModelSchema field round-trips; an absent key takes the schema
    # default (output_mode None means the model registry decides).
    model = AgentModelSchema.from_catalog(model_cfg)

    scope_data = row.scope or {}
    interface_data = row.interface

    return AgentConfigSchema(
        agent_name=row.agent_name,
        agent_type=row.agent_type,
        description=row.description,
        enabled=row.enabled,
        model=model,
        keywords=row.keywords or [],
        tools=row.tools or [],
        max_input_length=row.max_input_length,
        max_budget_usd=row.max_budget_usd,
        execution=ExecutionSchema(
            mode=row.execution_mode,
        ),
        invocation=InvocationSchema(
            tier=row.invocation_tier,
            required_role=getattr(row, "invocation_required_role", None),
        ),
        scope=FileScopeConfigSchema(
            read=scope_data.get("read", []),
            write=scope_data.get("write", []),
        ),
        interface=interface_data,
        version=row.version,
        chat_enabled=row.chat_enabled,
        thinking_budget=getattr(row, "thinking_budget_json", None),
        engine=row.engine,
        effort=getattr(row, "effort", None),
        produces_artifact=getattr(row, "produces_artifact", False),
        artifact_type=getattr(row, "artifact_type", None),
        system_prompt=row.system_prompt or None,
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
        from sqlalchemy import select

        from modules.backend.core.database import get_sync_session
        from modules.backend.models.agent_catalog import AgentCatalog

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
        root = find_project_root()
        if not agents_dir(root).exists():
            return

        for path in find_agent_files(root):
            try:
                with open(path) as f:
                    raw = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logger.error(
                    "Failed to parse agent config", extra={"path": str(path), "error": str(e)}
                )
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

        logger.debug(
            "Agent registry loaded from YAML (fallback)", extra={"agent_count": len(self._agents)}
        )

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
            result.append(
                {
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
                }
            )
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

    @staticmethod
    def resolve_module_path(agent_name: str) -> str:
        """Derive the Python import path from agent name.

        Supports any depth: security.webapp.scanner.agent resolves to
        modules.backend.agents.security.webapp.scanner.agent. Backward-
        compatible — 2-segment names (mission.director.agent) produce
        the same path as before.

        Static because the mapping uses no instance state — callable
        without spinning up the registry (which needs an async DB
        session). Used by workflow_validator's seed-time check before
        the registry is initialised.
        """
        parts = agent_name.replace(".agent", "").split(".")
        return f"modules.backend.agents.{'.'.join(parts)}.agent"

    def get_instance(self, agent_name: str, model: Any) -> Any:
        """Get or create a cached PydanticAI Agent instance.

        For chat-enabled agents whose create_agent() accepts chat_mode,
        passes chat_mode=True so tools and chat prompts are registered.
        """
        if agent_name in self._instances:
            return self._instances[agent_name]

        module_path = self.resolve_module_path(agent_name)
        module = importlib.import_module(module_path)

        # Pass chat_mode for agents whose create_agent() accepts it
        config = self._agents.get(agent_name)
        chat_enabled = config and getattr(config, "chat_enabled", False)
        sig = inspect.signature(module.create_agent)
        if chat_enabled and "chat_mode" in sig.parameters:
            agent = module.create_agent(model, chat_mode=True)
        else:
            agent = module.create_agent(model)

        self._instances[agent_name] = agent

        logger.info(
            "Agent instance created", extra={"agent_name": agent_name, "chat_mode": chat_enabled}
        )
        return agent

    def reset(self) -> None:
        """Clear cached agent instances (for tests)."""
        self._instances.clear()


@lru_cache(maxsize=1)
def get_registry() -> AgentRegistry:
    """Get the cached registry instance."""
    return AgentRegistry()
