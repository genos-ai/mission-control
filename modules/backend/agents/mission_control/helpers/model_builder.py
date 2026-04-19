"""Model construction helpers — build PydanticAI Models from config."""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel

from modules.backend.agents.config_schema import AgentConfigSchema, AgentModelSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def build_model_settings(
    agent_config: AgentConfigSchema,
) -> "ModelSettings | None":
    """Build provider-specific model settings from agent config.

    Handles thinking configuration per provider:
    - Anthropic (Opus/Sonnet 4.x): uses adaptive thinking (budget_tokens deprecated)
    - Anthropic (older models): uses enabled thinking with explicit budget_tokens
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

        # Opus 4.6 and Sonnet 4.6 use adaptive thinking (budget_tokens deprecated).
        # Older models (e.g. claude-3-7-sonnet) require budget_tokens.
        _adaptive_models = ("claude-opus-4", "claude-sonnet-4", "opus-4", "sonnet-4")
        _use_adaptive = any(m in model_name for m in _adaptive_models)

        if _use_adaptive:
            thinking_config: dict = {"type": "adaptive"}
        else:
            if max_tokens <= budget:
                max_tokens = budget + 8192
            thinking_config = {"type": "enabled", "budget_tokens": budget}

        return AnthropicModelSettings(
            anthropic_thinking=thinking_config,
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

    if model_name.startswith("anthropic:"):
        bare_name = model_name.split(":", 1)[1]
        from modules.backend.core.model_providers import get_anthropic_provider
        provider = get_anthropic_provider()
        return AnthropicModel(bare_name, provider=provider)

    if model_name.startswith("openai:"):
        bare_name = model_name.split(":", 1)[1]
        from pydantic_ai.models.openai import OpenAIModel
        from modules.backend.core.model_providers import get_openai_provider
        provider = get_openai_provider()
        return OpenAIModel(bare_name, provider=provider)

    if model_name.startswith("copilot:"):
        bare_name = model_name.split(":", 1)[1]
        from modules.backend.core.copilot_model import CopilotModel
        return CopilotModel(model_id=bare_name)

    raise ValidationError(f"Unsupported model provider in '{model_name}'. Expected 'anthropic:...', 'openai:...', or 'copilot:...'.")


def _get_model_name(config_model: str | AgentModelSchema) -> str:
    """Extract model name string from config model."""
    if isinstance(config_model, AgentModelSchema):
        return config_model.name
    return config_model
