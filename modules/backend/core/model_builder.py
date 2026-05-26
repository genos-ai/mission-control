"""Model construction helpers — build PydanticAI Models from config."""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel

from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def build_model_settings(
    agent_config: AgentConfigSchema,
) -> "ModelSettings | None":
    """Build provider-specific model settings from agent config.

    Returns AnthropicModelSettings for ALL Anthropic agents (cache + thinking).
    Returns None for non-Anthropic providers (cache control is Anthropic-specific).
    """
    from pydantic_ai.models.anthropic import AnthropicModelSettings

    raw_name = (
        agent_config.model.name
        if isinstance(agent_config.model, AgentModelSchema)
        else agent_config.model
    )
    model_name = _resolve_model_alias(raw_name)
    provider = model_name.split(":")[0] if ":" in model_name else ""

    if provider != "anthropic":
        return None

    # ── Cache control (Plan 60) ──────────────────────────────
    cache_ttl = agent_config.cache_ttl or _get_default_cache_ttl()
    cache_kwargs = {
        "anthropic_cache_instructions": cache_ttl,
        "anthropic_cache_tool_definitions": cache_ttl,
        "anthropic_cache": True,
    }

    # ── Output token cap ─────────────────────────────────────
    # Prefer the model schema's max_tokens, fall back to the top-level
    # agent config max_tokens (from YAML), then default 4096.
    if isinstance(agent_config.model, AgentModelSchema):
        max_tokens = agent_config.model.max_tokens
    elif getattr(agent_config, "max_tokens", None):
        max_tokens = agent_config.max_tokens
    else:
        max_tokens = 4096

    # ── Thinking configuration ───────────────────────────────
    thinking_config = None
    if agent_config.thinking_budget:
        budget = agent_config.thinking_budget.get("max_thinking_tokens", 10000)
        _adaptive_models = ("claude-opus-4", "claude-sonnet-4", "opus-4", "sonnet-4")
        _use_adaptive = any(m in model_name for m in _adaptive_models)

        if _use_adaptive:
            thinking_config = {"type": "adaptive"}
        else:
            if max_tokens <= budget:
                max_tokens = budget + 8192
            thinking_config = {"type": "enabled", "budget_tokens": budget}

    # ── Beta feature flags ───────────────────────────────────
    betas: list[str] = []
    if isinstance(agent_config.model, AgentModelSchema):
        betas = agent_config.model.betas or []

    settings_kwargs = {
        **cache_kwargs,
        "max_tokens": max_tokens,
    }
    if thinking_config:
        settings_kwargs["anthropic_thinking"] = thinking_config
    if betas:
        settings_kwargs["anthropic_betas"] = betas

    return AnthropicModelSettings(**settings_kwargs)


def _get_default_cache_ttl() -> str:
    """Read default_cache_ttl from cost.yaml config."""
    from modules.backend.core.config import get_app_config
    return get_app_config().cost.default_cache_ttl


def _resolve_model_alias(model_name: str) -> str:
    """Resolve a model alias to a fully-qualified provider:model string.

    If the name contains ':', treat it as a literal provider:model string.
    If the name is a known alias (quick/moderate/comprehensive), resolve it.
    Otherwise fail immediately — no fallbacks.
    """
    if ":" in model_name:
        return model_name

    from modules.backend.core.config import get_app_config
    aliases = get_app_config().models.aliases
    if model_name in aliases:
        return aliases[model_name]

    raise ValidationError(
        f"Unknown model alias '{model_name}'. "
        f"Known aliases: {sorted(aliases)}. "
        f"Use a fully-qualified 'provider:model' string or add the alias to models.yaml."
    )


def _build_model(config_model: str | AgentModelSchema) -> Model:
    """Construct a PydanticAI Model from config string, alias, or AgentModelSchema."""
    if isinstance(config_model, AgentModelSchema):
        model_name = config_model.name
    else:
        model_name = config_model

    model_name = _resolve_model_alias(model_name)

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

    if model_name.startswith("foundry:"):
        # Native JSON-schema output is not supported by the gpt-4.1 deployment
        # (Phase 0 smoke Test 5 failed), so no ModelProfile override is needed —
        # PydanticAI defaults to tool mode (P17), which works fine.
        bare_name = model_name.split(":", 1)[1]
        from pydantic_ai.models.openai import OpenAIModel
        from modules.backend.core.model_providers import get_foundry_provider
        provider = get_foundry_provider()
        return OpenAIModel(bare_name, provider=provider)

    raise ValidationError(
        f"Unsupported model provider in '{model_name}'. "
        "Expected 'anthropic:...', 'openai:...', 'copilot:...', or 'foundry:...'."
    )


def _get_model_name(config_model: str | AgentModelSchema) -> str:
    """Extract resolved model name string from config model, expanding aliases."""
    if isinstance(config_model, AgentModelSchema):
        name = config_model.name
    else:
        name = config_model
    return _resolve_model_alias(name)
