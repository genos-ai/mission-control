"""Model provider factory — creates SDK clients with the configured auth.

This is the single point where auth mode is resolved. Everything above
this layer (PydanticAI, agents, tools) is auth-agnostic.

Auth modes:
  api_key       — standard API key (per-token billing)
  auth_token    — subscription/OAuth bearer token (Anthropic — blocked by API)
  codex_oauth   — ChatGPT Enterprise OAuth via codex-auth (OpenAI — $0)
  entra         — Azure Entra ID via DefaultAzureCredential (Foundry)
  bearer_token  — pre-fetched Azure bearer from env (Foundry)

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
            logger.debug("settings API key lookup failed, continuing without credential", exc_info=True)

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


def get_foundry_provider():
    """Create a PydanticAI OpenAIProvider pointed at Azure AI Foundry.

    Uses Azure OpenAI's v1 GA endpoint (/openai/v1/chat/completions) which is
    fully OpenAI-wire-compatible. The OpenAI Python SDK with base_url override
    is the entire adapter — no custom Model subclass needed.

    Auth modes:
      entra         — DefaultAzureCredential + scope, refreshed per request.
                      Default. No env var required.
      api_key       — static key from env_var.
      bearer_token  — pre-fetched bearer from env_var (manual override).
    """
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openai import OpenAIProvider

    config = _get_provider_config().foundry

    if not config.base_url:
        raise ValueError(
            "Foundry provider requires base_url in providers.yaml "
            "(e.g. https://<resource>.openai.azure.com)."
        )

    sdk_base_url = f"{config.base_url.rstrip('/')}/openai/v1/"

    if config.auth_mode == "entra":
        # openai 2.x AsyncOpenAI expects api_key as Callable[[], Awaitable[str]] —
        # use azure.identity.aio (NOT the sync azure.identity) so the returned
        # bearer-token provider is awaitable. Token is fetched and cached on
        # each request; refresh is handled by the credential.
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
        if not config.scope:
            raise ValueError(
                "Foundry entra auth requires scope in providers.yaml "
                "(e.g. https://ai.azure.com/.default)."
            )
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), config.scope)
        client = AsyncOpenAI(base_url=sdk_base_url, api_key=token_provider)
        logger.info("Foundry provider: entra mode (scope=%s)", config.scope)
        return OpenAIProvider(openai_client=client)

    if config.auth_mode in ("api_key", "bearer_token"):
        credential = _read_credential(config)
        if not credential:
            raise ValueError(
                f"Foundry {config.auth_mode} mode requires {config.env_var} env var to be set."
            )
        client = AsyncOpenAI(base_url=sdk_base_url, api_key=credential)
        logger.info("Foundry provider: %s mode", config.auth_mode)
        return OpenAIProvider(openai_client=client)

    raise ValueError(
        f"Foundry auth_mode '{config.auth_mode}' not supported. "
        "Expected one of: entra, api_key, bearer_token."
    )


def _get_provider_config():
    """Load provider config from app config."""
    from modules.backend.core.config import get_app_config
    return get_app_config().providers
