# Plan 58 — Subscription-Based Model Providers

**Version:** 1.0.0
**Date:** 2026-04-18
**Author:** Herman + Architecture Review
**Status:** Ready — research complete, implementation designed
**Depends on:** Plan 55 (CLI engine — done)

---

## 0. Problem

All PydanticAI agents authenticate via `ANTHROPIC_API_KEY`, billing per-token to API credits. The platform operator has enterprise subscriptions (Claude Max, ChatGPT Enterprise, GitHub Copilot Enterprise) that include API access. There is no way to route PydanticAI through these subscriptions.

### What we want

Switch authentication from API keys to subscription tokens **without changing any agent code, tools, streaming, or structured output**. The change is at the SDK client layer — everything above it (PydanticAI, tools, events) stays identical.

```
Before:  AgentConfig → model_builder → AnthropicProvider(api_key="sk-...") → API billing
After:   AgentConfig → model_builder → AnthropicProvider(client=AsyncAnthropic(auth_token="...")) → subscription billing
```

---

## 1. Research Findings

### 1.1 Anthropic SDK — `auth_token` parameter (CONFIRMED)

```python
anthropic.AsyncAnthropic(
    auth_token="bearer-token-here",  # sends Authorization: Bearer header
    api_key=None,                     # skip X-Api-Key header
)
```

The `auth_token` parameter exists and sends `Authorization: Bearer` instead of `X-Api-Key`. Falls back to `ANTHROPIC_AUTH_TOKEN` env var. **This is the injection point for Claude Max subscription tokens.**

### 1.2 PydanticAI Provider — pre-configured client injection (CONFIRMED)

```python
# PydanticAI already supports this:
custom_client = anthropic.AsyncAnthropic(auth_token="...")
provider = AnthropicProvider(anthropic_client=custom_client)
model = AnthropicModel("claude-sonnet-4-6", provider=provider)
```

When `anthropic_client=` is provided, the provider uses it directly — `api_key` is ignored. **No PydanticAI patches needed.**

### 1.3 OpenAI SDK — async key callable (CONFIRMED)

```python
openai.AsyncOpenAI(
    api_key=async_refresh_function,  # called for each request — perfect for token rotation
)
# OR for enterprise:
openai.AsyncOpenAI(
    api_key="enterprise-api-key",
)
```

Enterprise API keys work directly. The `api_key` parameter also accepts an async callable for dynamic token refresh.

### 1.4 GitHub Copilot SDK — high-level proxy (NOT directly usable)

The `github-copilot-sdk` is a JSON-RPC client that proxies through the Copilot CLI binary. It does NOT expose raw tokens for direct API calls. Copilot Enterprise integration would require either:
- Extracting the internal auth token from the CLI (fragile)
- Using the SDK's session-based API directly (different interface from PydanticAI)
- Waiting for GitHub to expose a programmatic token endpoint

**Recommendation:** Defer Copilot Enterprise integration. Focus on Anthropic and OpenAI first — they cover the primary use cases.

---

## 2. Architecture — Provider Factory

### Design principle

**Auth is configuration, not code.** Switching from API key to subscription token is a config change in `config/settings/providers.yaml`. No agent code, no model_builder logic, no PydanticAI patches.

### 2.1 Config schema

**New file:** `config/settings/providers.yaml`

```yaml
providers:
  anthropic:
    # Auth mode: "api_key" (default) or "auth_token" (subscription/OAuth)
    auth_mode: auth_token
    # Where to read the credential
    # "env" reads from an environment variable
    # "file" reads from a file path
    env_var: ANTHROPIC_AUTH_TOKEN
    # Optional: override base_url for proxied setups
    # base_url: https://custom-proxy.example.com

  openai:
    auth_mode: api_key
    env_var: OPENAI_API_KEY
    # For enterprise: just set the enterprise key in the env var
    # No code change needed — the SDK uses it as a Bearer token
```

### 2.2 Provider config schema

**New in:** `modules/backend/core/config_schema.py`

```python
class ProviderAuthSchema(_StrictBase):
    """Authentication configuration for a model provider."""
    auth_mode: str = "api_key"  # "api_key" | "auth_token"
    env_var: str | None = None
    file_path: str | None = None
    base_url: str | None = None

class ProvidersSchema(_StrictBase):
    """Provider authentication configuration."""
    anthropic: ProviderAuthSchema = ProviderAuthSchema(
        auth_mode="api_key",
        env_var="ANTHROPIC_API_KEY",
    )
    openai: ProviderAuthSchema = ProviderAuthSchema(
        auth_mode="api_key",
        env_var="OPENAI_API_KEY",
    )
```

### 2.3 Provider factory

**New file:** `modules/backend/core/model_providers.py`

```python
"""Model provider factory — creates SDK clients with the configured auth.

This is the single point where auth mode (api_key vs auth_token vs enterprise)
is resolved. Everything above this layer (PydanticAI, agents, tools) is
auth-agnostic.

Usage:
    from modules.backend.core.model_providers import get_anthropic_provider, get_openai_provider

    provider = get_anthropic_provider()  # reads config, returns PydanticAI Provider
    model = AnthropicModel("claude-sonnet-4-6", provider=provider)
"""

import os
from functools import lru_cache

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _read_credential(config) -> str | None:
    """Read a credential from the configured source."""
    if config.env_var:
        value = os.environ.get(config.env_var)
        if value:
            return value
    if config.file_path:
        from pathlib import Path
        path = Path(config.file_path).expanduser()
        if path.is_file():
            return path.read_text().strip()
    return None


def get_anthropic_provider():
    """Create a PydanticAI AnthropicProvider with configured auth."""
    from anthropic import AsyncAnthropic
    from pydantic_ai.providers.anthropic import AnthropicProvider

    config = _get_provider_config().anthropic
    credential = _read_credential(config)

    if not credential:
        raise ValueError(
            f"No credential found for Anthropic provider. "
            f"Set {config.env_var} environment variable."
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
    """Create a PydanticAI OpenAIProvider with configured auth."""
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openai import OpenAIProvider

    config = _get_provider_config().openai
    credential = _read_credential(config)

    if not credential:
        raise ValueError(
            f"No credential found for OpenAI provider. "
            f"Set {config.env_var} environment variable."
        )

    client = AsyncOpenAI(
        api_key=credential,
        base_url=config.base_url,
    )
    logger.info("OpenAI provider: %s mode", config.auth_mode)

    return OpenAIProvider(openai_client=client)


def _get_provider_config():
    """Load provider config from app config."""
    from modules.backend.core.config import get_app_config
    return get_app_config().providers
```

### 2.4 Update model_builder.py

**File:** `modules/backend/agents/mission_control/helpers/model_builder.py`

Change from:
```python
if model_name.startswith("anthropic:"):
    bare_name = model_name.split(":", 1)[1]
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    return AnthropicModel(bare_name, provider=provider)
```

To:
```python
if model_name.startswith("anthropic:"):
    bare_name = model_name.split(":", 1)[1]
    from modules.backend.core.model_providers import get_anthropic_provider
    provider = get_anthropic_provider()
    return AnthropicModel(bare_name, provider=provider)
```

Same pattern for OpenAI models. **This is the only file that changes.** Everything above it (agents, tools, streaming) is untouched.

---

## 3. What This Achieves

### Before
```
Agent YAML → model_builder → AnthropicProvider(api_key="sk-...") → API billing ($$$)
```

### After
```
Agent YAML → model_builder → get_anthropic_provider() → AnthropicProvider(client) → subscription ($0)
                                    ↑
                              reads providers.yaml
                              auth_mode: auth_token
                              env_var: ANTHROPIC_AUTH_TOKEN
```

### What stays identical
- All PydanticAI custom tools (create_plan, approve_tasks, etc.)
- Streaming events (chunks, tool calls, thinking)
- Conversation history
- Structured output / interface validation
- Cost tracking (tokens still counted, cost_usd may show $0 or actual)
- Every agent config, every agent module, every endpoint

### What changes
- One factory function reads config and builds the SDK client with the right auth
- One line in model_builder.py calls the factory instead of hardcoding api_key
- One YAML file controls auth mode per provider

---

## 4. Implementation Steps

### Phase 1: Anthropic auth_token (primary — solves the immediate cost problem)

| # | File | Action | Effort |
|---|------|--------|--------|
| 1 | `config/settings/providers.yaml` | Create — provider auth config | 5 min |
| 2 | `modules/backend/core/config_schema.py` | Add `ProviderAuthSchema` + `ProvidersSchema` | 10 min |
| 3 | `modules/backend/core/model_providers.py` | Create — provider factory | 20 min |
| 4 | `modules/backend/agents/mission_control/helpers/model_builder.py` | Replace `api_key=` with `get_anthropic_provider()` | 5 min |
| 5 | Set `ANTHROPIC_AUTH_TOKEN` env var | Operator task — get token from Claude Max account | 5 min |

**Total: ~45 minutes.**

### Phase 2: OpenAI Enterprise (if needed)

Same pattern — add `get_openai_provider()` call in model_builder for `openai:` prefixed models.

### Phase 3: Copilot Enterprise (deferred)

Blocked on GitHub exposing a programmatic token endpoint. The `github-copilot-sdk` proxies through the CLI binary — no raw tokens available.

---

## 5. Verification

### 5.1 Auth token mode works
```bash
export ANTHROPIC_AUTH_TOKEN="your-claude-max-oauth-token"
python -c "
from modules.backend.core.model_providers import get_anthropic_provider
from pydantic_ai.models.anthropic import AnthropicModel

provider = get_anthropic_provider()
model = AnthropicModel('claude-sonnet-4-6', provider=provider)
print(f'Provider: {provider.name}')
print(f'Client auth: auth_token mode')
print('OK')
"
```

### 5.2 Agent still works with tools
```bash
# Chat with the director — should use subscription auth, all tools working
mc chat "What missions are active?"
```

### 5.3 Fallback to api_key mode
```yaml
# config/settings/providers.yaml
providers:
  anthropic:
    auth_mode: api_key
    env_var: ANTHROPIC_API_KEY
```
All agents should work as before with API key billing.

### 5.4 Regression — existing tests pass
```bash
python -m pytest tests/unit/backend/mission_control/ -x -q --tb=short
```

---

## 6. Relationship to Plan 55 (CLI Engines)

Plan 55 and Plan 58 solve **different problems**:

| Plan | Problem | Solution |
|------|---------|----------|
| **Plan 55** (CLI engines) | Coding agents need filesystem tools (Read, Write, Bash) | Subprocess execution via Claude Code / Codex / Copilot CLI |
| **Plan 58** (this plan) | All PydanticAI agents should bill to subscription, not API keys | Swap SDK client auth from api_key to auth_token |

They are **complementary, not competing**:
- `engine: pydantic_ai` agents use Plan 58's provider factory for auth
- `engine: claude_code` agents use Plan 55's CLI executor subprocess
- Both bill to the subscription ($0)

After both plans ship, **every agent runs on subscription** — orchestration agents via auth_token, coding agents via Claude Code CLI.

---

## 7. Files Summary

| # | File | Action | Lines |
|---|------|--------|-------|
| 1 | `config/settings/providers.yaml` | Create | ~15 |
| 2 | `modules/backend/core/config_schema.py` | Edit — add schemas | ~15 |
| 3 | `modules/backend/core/model_providers.py` | Create — factory | ~80 |
| 4 | `modules/backend/agents/mission_control/helpers/model_builder.py` | Edit — use factory | ~5 |

**Total: ~115 lines of new code.** No agent changes. No frontend changes. No migration.

---

## 8. Getting the Auth Token

### Claude Max (Anthropic)

Option A — Claude Code CLI token:
```bash
# If you have Claude Code CLI installed and logged in:
claude setup-token
# This generates a long-lived OAuth token (valid 1 year)
# Set it as: export ANTHROPIC_AUTH_TOKEN="token-here"
```

Option B — Environment variable:
```bash
# The Claude Code CLI reads ANTHROPIC_AUTH_TOKEN if set
# Same token works for the anthropic SDK's auth_token parameter
```

### ChatGPT Enterprise (OpenAI)

Enterprise accounts have API keys that bill to the enterprise agreement:
```bash
export OPENAI_API_KEY="your-enterprise-api-key"
```
No special auth_mode needed — enterprise keys work with the standard `api_key` parameter.

---

## 9. Exit Criteria

1. `providers.yaml` config controls auth mode (api_key vs auth_token) per provider
2. `ANTHROPIC_AUTH_TOKEN` env var routes all Anthropic agents through subscription
3. All PydanticAI features work identically: tools, streaming, structured output, history
4. Switching back to `api_key` mode is a one-line config change
5. Existing tests pass without modification
6. No agent YAML changes, no frontend changes, no migration
