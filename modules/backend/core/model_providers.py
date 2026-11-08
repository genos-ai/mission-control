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
from modules.backend.core.model_backends import ANTHROPIC_MESSAGES, OPENAI_CHAT

logger = get_logger(__name__)

# Key of the foundry_project endpoint_paths entry for the OpenAI Responses API. It is
# not a model-registry protocol: no model is called over it, only the search service.
OPENAI_RESPONSES = "openai_responses"


# Shared Azure Entra credential for the Foundry providers.
#
# Each `DefaultAzureCredential()` instance opens an internal aiohttp session
# for IMDS / token endpoints; if a new instance is created per factory call,
# those sessions leak and surface as "Unclosed client session" warnings at
# process exit (a real problem for CLI smoke tests, harmless for the API
# server which holds the credential for process lifetime).
#
# A single module-level instance is created on first use and reused by
# every Foundry provider (get_foundry_provider(), get_foundry_anthropic_provider()
# and get_foundry_project_provider()) — they all use the same auth chain and the
# credential is scope-agnostic (scope is passed per-call to
# get_bearer_token_provider()). Short-lived contexts call
# close_foundry_credentials() before exit to clean up the aiohttp session.
_foundry_credential = None


def get_foundry_credential():
    """Return the shared DefaultAzureCredential, creating it on first use."""
    global _foundry_credential
    if _foundry_credential is None:
        from azure.identity.aio import DefaultAzureCredential

        _foundry_credential = DefaultAzureCredential()
    return _foundry_credential


async def close_foundry_credentials() -> None:
    """Close the shared Foundry credential and its aiohttp transport.

    Idempotent. Safe to call when nothing was created. After this returns,
    the next factory call re-creates the credential.

    Only needed for short-lived contexts (CLI scripts, smoke tests). The
    API server doesn't need to call this — process exit handles cleanup
    and the credential is reused across the whole process lifetime.

    IMPORTANT: any AsyncOpenAI clients previously returned by the factory
    functions become unusable after this call, because the bearer-token
    provider they captured still references this (now-closed) credential.
    Only call this when no further LLM calls are expected.
    """
    global _foundry_credential
    if _foundry_credential is not None:
        await _foundry_credential.close()
        _foundry_credential = None


def _read_credential(config) -> str | None:
    """Read a credential from the configured source (env var)."""
    if config.env_var:
        value = os.environ.get(config.env_var)
        if value:
            return value
    return None


def _resolve_anthropic_credential(config) -> str | None:
    """Anthropic credential: the configured env var, else the Settings .env secret."""
    credential = _read_credential(config)

    if not credential:
        try:
            from modules.backend.core.config import get_settings

            credential = get_settings().anthropic_api_key
        except Exception:
            logger.debug(
                "settings API key lookup failed, continuing without credential", exc_info=True
            )

    return credential or None


# Auth modes whose credential is acquired at call time (a login or a token exchange),
# so its presence cannot be read without making a network call.
_LIVE_AUTH_MODES = frozenset({"entra", "codex_oauth"})


def credential_status(provider: str) -> str:
    """Whether the credential for ``provider`` is configured, without exposing it.

    Returns ``"present"`` or ``"missing"`` for static credentials (API key or
    bearer token). Returns ``"not_checked"`` when the provider has no entry in
    providers.yaml (Copilot signs in through its own SDK) or authenticates live
    (Entra, Codex OAuth): only a real call proves those, so use a ping.
    """
    config = getattr(_get_provider_config(), provider, None)
    if config is None or config.auth_mode in _LIVE_AUTH_MODES:
        return "not_checked"

    if provider == "anthropic":
        credential = _resolve_anthropic_credential(config)
    else:
        credential = _read_credential(config)
    return "present" if credential else "missing"


def get_anthropic_provider():
    """Create a PydanticAI AnthropicProvider with configured auth.

    Reads auth_mode from providers.yaml (or defaults).
    - api_key: standard API key from ANTHROPIC_API_KEY
    - auth_token: subscription bearer token from ANTHROPIC_AUTH_TOKEN
    """
    from anthropic import AsyncAnthropic
    from pydantic_ai.providers.anthropic import AnthropicProvider

    config = _get_provider_config().anthropic
    credential = _resolve_anthropic_credential(config)

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


def _endpoint_url(config, provider: str, protocol: str, base_url_hint: str) -> str:
    """``provider``'s URL for ``protocol``: base_url plus its path from providers.yaml.

    Both are required; there is no built-in path to fall back on.
    """
    if not config.base_url:
        raise ValueError(
            f"{provider} provider requires base_url in providers.yaml ({base_url_hint})."
        )
    path = config.endpoint_paths.get(protocol)
    if not path:
        raise ValueError(
            f"{provider} provider requires endpoint_paths.{protocol} in providers.yaml "
            "(the path appended to base_url for that protocol)."
        )
    return f"{config.base_url.rstrip('/')}/{path.strip('/')}/"


def _foundry_endpoint(config, protocol: str) -> str:
    """The Foundry resource URL for ``protocol``."""
    return _endpoint_url(config, "Foundry", protocol, "e.g. https://<resource>.openai.azure.com")


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
    sdk_base_url = _foundry_endpoint(config, OPENAI_CHAT)

    if config.auth_mode == "entra":
        # openai 2.x AsyncOpenAI expects api_key as Callable[[], Awaitable[str]] —
        # use azure.identity.aio (NOT the sync azure.identity) so the returned
        # bearer-token provider is awaitable. Token is fetched and cached on
        # each request; refresh is handled by the credential. The credential
        # itself is a module-level singleton (see get_foundry_credential)
        # to avoid leaking aiohttp sessions on repeated factory calls.
        from azure.identity.aio import get_bearer_token_provider

        if not config.scope:
            raise ValueError(
                "Foundry entra auth requires scope in providers.yaml "
                "(e.g. https://ai.azure.com/.default)."
            )
        token_provider = get_bearer_token_provider(get_foundry_credential(), config.scope)
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


def get_foundry_anthropic_provider():
    """Create a PydanticAI AnthropicProvider for Claude models deployed on Foundry.

    Same resource, credential and firewall rule as get_foundry_provider(); only
    the wire protocol differs. Claude on Foundry answers the Anthropic Messages
    API (its path is endpoint_paths.anthropic_messages in providers.yaml) and
    rejects OpenAI chat completions (``api_not_supported``).

    AsyncAnthropicFoundry takes a token *provider* rather than a token, so Entra
    tokens (about an hour) refresh per request; a static ``auth_token`` would
    expire mid-way through a long mission.

    Auth modes: entra, api_key, bearer_token, as for get_foundry_provider().
    """
    from anthropic import AsyncAnthropicFoundry
    from pydantic_ai.providers.anthropic import AnthropicProvider

    config = _get_provider_config().foundry
    sdk_base_url = _foundry_endpoint(config, ANTHROPIC_MESSAGES)

    if config.auth_mode == "entra":
        from azure.identity.aio import get_bearer_token_provider

        if not config.scope:
            raise ValueError(
                "Foundry entra auth requires scope in providers.yaml "
                "(e.g. https://ai.azure.com/.default)."
            )
        token_provider = get_bearer_token_provider(get_foundry_credential(), config.scope)
        client = AsyncAnthropicFoundry(
            base_url=sdk_base_url, azure_ad_token_provider=token_provider
        )
        logger.info("Foundry Anthropic provider: entra mode (scope=%s)", config.scope)
        return AnthropicProvider(anthropic_client=client)

    if config.auth_mode in ("api_key", "bearer_token"):
        credential = _read_credential(config)
        if not credential:
            raise ValueError(
                f"Foundry {config.auth_mode} mode requires {config.env_var} env var to be set."
            )
        if config.auth_mode == "api_key":
            client = AsyncAnthropicFoundry(base_url=sdk_base_url, api_key=credential)
        else:

            async def static_token() -> str:
                return credential

            client = AsyncAnthropicFoundry(
                base_url=sdk_base_url, azure_ad_token_provider=static_token
            )
        logger.info("Foundry Anthropic provider: %s mode", config.auth_mode)
        return AnthropicProvider(anthropic_client=client)

    raise ValueError(
        f"Foundry auth_mode '{config.auth_mode}' not supported. "
        "Expected one of: entra, api_key, bearer_token."
    )


def get_foundry_project_provider():
    """Create an AsyncOpenAI client pointed at a Foundry **project** endpoint.

    Unlike get_foundry_provider() (which targets the OpenAI-compatible
    `<resource>.openai.azure.com` host), this targets the project-scoped
    Foundry host `<account>.services.ai.azure.com/api/projects/<project>`.

    This endpoint is required for Foundry Agent Service features that rely
    on project-level connections — most notably the `web_search` tool
    (Grounding with Bing Search) on the Responses API. The Bing connection
    is attached at the project level, and only the project-scoped Responses
    endpoint can resolve it.

    Returns the bare AsyncOpenAI client (not a PydanticAI provider) because
    the only consumer right now is non-PydanticAI code that calls
    `client.responses.create(...)` directly. Wrap in OpenAIProvider at the
    callsite if a PydanticAI Model is needed later.
    """
    from openai import AsyncOpenAI

    config = _get_provider_config().foundry_project

    sdk_base_url = _endpoint_url(
        config,
        "foundry_project",
        OPENAI_RESPONSES,
        "format: https://<account>.services.ai.azure.com/api/projects/<project>",
    )

    if config.auth_mode == "entra":
        # Shares the module-level credential singleton with get_foundry_provider()
        # — see get_foundry_credential() for the lifecycle rationale.
        from azure.identity.aio import get_bearer_token_provider

        if not config.scope:
            raise ValueError(
                "foundry_project entra auth requires scope in providers.yaml "
                "(e.g. https://ai.azure.com/.default).",
            )
        token_provider = get_bearer_token_provider(get_foundry_credential(), config.scope)
        client = AsyncOpenAI(base_url=sdk_base_url, api_key=token_provider)
        logger.info("foundry_project provider: entra mode (scope=%s)", config.scope)
        return client

    if config.auth_mode in ("api_key", "bearer_token"):
        credential = _read_credential(config)
        if not credential:
            raise ValueError(
                f"foundry_project {config.auth_mode} mode requires "
                f"{config.env_var} env var to be set.",
            )
        client = AsyncOpenAI(base_url=sdk_base_url, api_key=credential)
        logger.info("foundry_project provider: %s mode", config.auth_mode)
        return client

    raise ValueError(
        f"foundry_project auth_mode '{config.auth_mode}' not supported. "
        "Expected one of: entra, api_key, bearer_token.",
    )


def _get_provider_config():
    """Load provider config from app config."""
    from modules.backend.core.config import get_app_config

    return get_app_config().providers
