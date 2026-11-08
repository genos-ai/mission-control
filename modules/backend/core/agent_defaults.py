"""Values an agent gets when nothing sets them.

Each one comes from config or from the schema that defines the field, so no default
is written in code. Used by the catalog service (agents created without them), the
roster (catalog rows that lack them) and the catalog YAML sync.
"""

from typing import Any

from modules.backend.core.config import get_app_config, get_mission_control_config
from modules.backend.schemas.agent_config import (
    AgentConfigSchema,
    AgentModelSchema,
    InvocationSchema,
)


def _field_default(schema: type, name: str) -> Any:
    return schema.model_fields[name].get_default(call_default_factory=True)


# From config ----------------------------------------------------------------


def task_timeout_seconds() -> int:
    """Wall-clock seconds for one agent task (application.yaml timeouts.agent_task)."""
    return get_app_config().application.timeouts.agent_task


def retry_budget() -> int:
    """Retries per task (mission_control.yaml dispatch.default_retry_budget)."""
    return get_mission_control_config().dispatch.default_retry_budget


def max_budget_usd() -> float:
    """Cost ceiling per invocation (mission_control.yaml dispatch.default_max_budget_usd)."""
    return get_mission_control_config().dispatch.default_max_budget_usd


def max_input_length() -> int:
    """Input size limit in characters (mission_control.yaml dispatch.default_max_input_length)."""
    return get_mission_control_config().dispatch.default_max_input_length


def execution_mode() -> str:
    """Execution mode (mission_control.yaml dispatch.default_execution_mode)."""
    return get_mission_control_config().dispatch.default_execution_mode


# From the schemas that define the field -------------------------------------


def version() -> str:
    return _field_default(AgentConfigSchema, "version")


def engine() -> str:
    return _field_default(AgentConfigSchema, "engine")


def visibility() -> str:
    return _field_default(AgentConfigSchema, "visibility")


def invocation_tier() -> str:
    return _field_default(InvocationSchema, "tier")


def temperature() -> float:
    return _field_default(AgentModelSchema, "temperature")


def max_tokens() -> int:
    return _field_default(AgentModelSchema, "max_tokens")
