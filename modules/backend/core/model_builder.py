"""Model construction helpers — build PydanticAI Models from config."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.models import Model, ModelSettings

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.core.model_backends import (
    ANTHROPIC_SETTINGS_PROTOCOLS,
    BACKENDS,
    output_mode_error,
)
from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema

logger = get_logger(__name__)


def build_model_settings(
    agent_config: AgentConfigSchema,
) -> "ModelSettings | None":
    """Build provider-specific model settings from agent config.

    Returns AnthropicModelSettings for every model called over the Anthropic
    Messages protocol, whichever provider hosts it (cache, thinking, effort).
    Returns None for other protocols (cache control is Anthropic-specific).
    """
    from pydantic_ai.models.anthropic import AnthropicModelSettings

    raw_name = (
        agent_config.model.name
        if isinstance(agent_config.model, AgentModelSchema)
        else agent_config.model
    )
    resolved = resolve_model(_resolve_model_alias(raw_name))

    if resolved.protocol not in ANTHROPIC_SETTINGS_PROTOCOLS:
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
        if resolved.thinking == "adaptive":
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
    if agent_config.effort:
        settings_kwargs["anthropic_effort"] = agent_config.effort

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


@dataclass(frozen=True)
class ResolvedModel:
    """A qualified model name split into provider, bare name and its registry spec."""

    provider: str
    name: str
    protocol: str
    thinking: str
    output_mode: str


def resolve_model(qualified_name: str) -> ResolvedModel:
    """Split ``provider:model`` and look the model up in the registry.

    The registry decides how a model is called, so an unregistered model fails
    here rather than being guessed at.
    """
    from modules.backend.core.config import get_app_config

    provider, sep, name = qualified_name.partition(":")
    if not (sep and provider and name):
        raise ValidationError(f"'{qualified_name}' is not a 'provider:model' string.")
    if provider not in BACKENDS:
        raise ValidationError(
            f"Unsupported model provider in '{qualified_name}'. Known: {sorted(BACKENDS)}."
        )

    models = get_app_config().models
    spec = models.spec_of(provider, name)
    if spec is None:
        raise ValidationError(
            f"Model '{qualified_name}' is not in the model registry "
            f"(config/settings/models.yaml). Registered {provider} models: "
            f"{models.models_of(provider)}."
        )
    return ResolvedModel(
        provider=provider,
        name=name,
        protocol=spec.protocol,
        thinking=spec.thinking,
        output_mode=spec.output_mode,
    )


def effective_output_mode(config_model: str | AgentModelSchema, resolved: ResolvedModel) -> str:
    """The structured-output mode an agent's model is built with.

    The agent's own ``output_mode`` wins when set; otherwise the registry's, whose
    schema default is 'tool'. Raises when the model's protocol cannot honour it.
    """
    agent_mode = config_model.output_mode if isinstance(config_model, AgentModelSchema) else None
    mode = agent_mode if agent_mode is not None else resolved.output_mode

    error = output_mode_error(mode, {resolved.protocol})
    if error:
        raise ValidationError(
            f"'{resolved.provider}:{resolved.name}' is called over {resolved.protocol}; {error}."
        )
    return mode


def _build_model(config_model: str | AgentModelSchema) -> Model:
    """Construct a PydanticAI Model from config string, alias, or AgentModelSchema."""
    if isinstance(config_model, AgentModelSchema):
        model_name = config_model.name
    else:
        model_name = config_model

    resolved = resolve_model(_resolve_model_alias(model_name))
    output_mode = effective_output_mode(config_model, resolved)
    return BACKENDS[resolved.provider][resolved.protocol](resolved.name, output_mode)


def _get_model_name(config_model: str | AgentModelSchema) -> str:
    """Extract resolved model name string from config model, expanding aliases."""
    if isinstance(config_model, AgentModelSchema):
        name = config_model.name
    else:
        name = config_model
    return _resolve_model_alias(name)
