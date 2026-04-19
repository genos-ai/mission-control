"""Model provider factory — creates SDK clients with the configured auth.

This is the single point where auth mode is resolved. Everything above
this layer (PydanticAI, agents, tools) is auth-agnostic.

Auth modes:
  api_key      — standard API key (per-token billing)
  auth_token   — subscription/OAuth bearer token (Anthropic — blocked by API)
  codex_oauth  — ChatGPT Enterprise OAuth via codex-auth (OpenAI — $0)

Usage:
    from modules.backend.core.model_providers import get_anthropic_provider

    provider = get_anthropic_provider()
    model = AnthropicModel("claude-sonnet-4-6", provider=provider)
"""

from __future__ import annotations

import os

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _read_credential(config) -> str | None:
    """Read a credential from the configured source (env var)."""
    if config.env_var:
        value = os.environ.get(config.env_var)
        if value:
            return value
    return None


def get_anthropic_provider():
    """Create a PydanticAI AnthropicProvider with configured auth.

    Reads auth_mode from providers.yaml (or defaults).
    - api_key: standard API key from ANTHROPIC_API_KEY
    - auth_token: subscription bearer token from ANTHROPIC_AUTH_TOKEN
    """
    from anthropic import AsyncAnthropic
    from pydantic_ai.providers.anthropic import AnthropicProvider

    config = _get_provider_config().anthropic
    credential = _read_credential(config)

    # Fallback: try the Settings .env secret if no env var found
    if not credential:
        try:
            from modules.backend.core.config import get_settings
            credential = get_settings().anthropic_api_key
        except Exception:
            pass

    if not credential:
        raise ValueError(
            f"No credential found for Anthropic provider. "
            f"Set {config.env_var or 'ANTHROPIC_API_KEY'} environment variable."
        )

    if config.auth_mode == "auth_token":
        client = AsyncAnthropic(
            auth_token=credential,
            api_key=None,
            base_url=config.base_url,
        )
        logger.info("Anthropic provider: auth_token mode (subscription)")
    else:
        client = AsyncAnthropic(
            api_key=credential,
            base_url=config.base_url,
        )
        logger.info("Anthropic provider: api_key mode")

    return AnthropicProvider(anthropic_client=client)


def get_openai_provider():
    """Create a PydanticAI OpenAIProvider with configured auth.

    Auth modes:
      api_key     — standard API key or Enterprise key
      codex_oauth — ChatGPT Enterprise OAuth via codex-auth package.
                    First run opens browser for OAuth login; token is
                    cached and auto-refreshed. The returned client IS
                    AsyncOpenAI — all PydanticAI features work.
    """
    from pydantic_ai.providers.openai import OpenAIProvider

    config = _get_provider_config().openai

    if config.auth_mode == "codex_oauth":
        try:
            from codex_auth import AsyncCodexClient
        except ImportError:
            raise ImportError(
                "codex-auth is required for auth_mode='codex_oauth'. "
                "Install with: pip install codex-auth"
            )
        # AsyncCodexClient IS AsyncOpenAI — handles OAuth + token refresh
        client = AsyncCodexClient()
        logger.info("OpenAI provider: codex_oauth mode (ChatGPT Enterprise subscription)")
        return OpenAIProvider(openai_client=client)

    # Standard api_key mode
    from openai import AsyncOpenAI

    credential = _read_credential(config)
    if not credential:
        raise ValueError(
            f"No credential found for OpenAI provider. "
            f"Set {config.env_var or 'OPENAI_API_KEY'} environment variable."
        )

    client = AsyncOpenAI(
        api_key=credential,
        base_url=config.base_url,
    )
    logger.info("OpenAI provider: api_key mode")

    return OpenAIProvider(openai_client=client)


def _get_provider_config():
    """Load provider config from app config."""
    from modules.backend.core.config import get_app_config
    return get_app_config().providers
