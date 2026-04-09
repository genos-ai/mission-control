"""Model construction helpers — build PydanticAI Models from config."""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from modules.backend.agents.config_schema import AgentConfigSchema, AgentModelSchema
from modules.backend.core.config import get_settings
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def build_model_settings(
    agent_config: AgentConfigSchema,
) -> "ModelSettings | None":
    """Build provider-specific model settings from agent config.

    Handles thinking configuration per provider:
    - Anthropic: uses anthropic_thinking with budget_tokens, ensures max_tokens > budget
    - Other providers: logs a warning and skips (thinking not supported)

    Returns None if the agent has no thinking_budget configured.
    """
    from pydantic_ai.settings import ModelSettings

    if not agent_config.thinking_budget:
        return None

    model_name = (
        agent_config.model.name
        if isinstance(agent_config.model, AgentModelSchema)
        else agent_config.model
    )
    provider = model_name.split(":")[0] if ":" in model_name else ""
    budget = agent_config.thinking_budget.get("max_thinking_tokens", 10000)

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModelSettings

        max_tokens = getattr(agent_config.model, "max_tokens", None) or 16384
        if max_tokens <= budget:
            max_tokens = budget + 8192

        return AnthropicModelSettings(
            anthropic_thinking={"type": "enabled", "budget_tokens": budget},
            max_tokens=max_tokens,
        )

    logger.info(
        "thinking_budget configured but provider '%s' does not support it, skipping",
        provider,
        extra={"agent": agent_config.agent_name},
    )
    return None


def _build_model(config_model: str | AgentModelSchema) -> Model:
    """Construct a PydanticAI Model from config string or AgentModelSchema."""
    if isinstance(config_model, AgentModelSchema):
        model_name = config_model.name
    else:
        model_name = config_model

    settings = get_settings()

    if model_name.startswith("anthropic:"):
        bare_name = model_name.split(":", 1)[1]
        provider = AnthropicProvider(api_key=settings.anthropic_api_key)
        return AnthropicModel(bare_name, provider=provider)

    raise ValidationError(f"Unsupported model provider in '{model_name}'. Expected 'anthropic:model_name'.")


def _get_model_name(config_model: str | AgentModelSchema) -> str:
    """Extract model name string from config model."""
    if isinstance(config_model, AgentModelSchema):
        return config_model.name
    return config_model
