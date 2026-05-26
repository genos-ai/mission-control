# Plan 82 — Microsoft AI Foundry Provider

**Version:** 1.0.0
**Date:** 2026-05-26
**Author:** Herman + research synthesis
**Status:** Proposed
**Depends on:** existing `model_providers.py` factory pattern, `ProvidersSchema` config, PydanticAI `OpenAIChatModel`
**Unlocks:** Azure-billed agent execution, `gpt-4.1` / GPT-5 family / `o`-series reasoning models, prompt caching via Azure OpenAI v1 endpoint, Entra-ID-based auth for production deployment

---

## 0. Problem Statement

Mission Control currently runs every agent through one of three providers — `anthropic:`, `openai:`, or `copilot:`. The `copilot:` path is a 650-line `Model` subclass ([modules/backend/core/copilot_model.py](../../modules/backend/core/copilot_model.py)) that exists only because the GitHub Copilot SDK does not speak the OpenAI wire protocol.

We need to add **Microsoft Azure AI Foundry** as a fourth provider so that:

1. Agents can run against Azure-billed Azure OpenAI deployments (e.g. `gpt-4.1`, `gpt-5`, `o3`) using the org's existing Azure tenancy.
2. Auth can use Entra ID via `DefaultAzureCredential` — picking up `az login` locally and managed identity in production — instead of requiring per-developer API keys.
3. Structured output stays cheap to maintain: PydanticAI's tool-based final_result pattern (P17) just works without a new adapter.

**Critical empirical finding (from the reference bundle at [/Users/herman.young/development/foundry-structured-output-cli-bundle](file:///Users/herman.young/development/foundry-structured-output-cli-bundle)):** the Foundry deployment we have access to (`gis-mission-control-resource`) exposes Azure OpenAI's **new v1 GA endpoint** (`/openai/v1/chat/completions`), which is fully OpenAI-wire-compatible. No `api_version` query param, no `/deployments/<name>/` URL surgery, deployment name passed as the `model` field in the request body. This means **no `Model` subclass is needed** — plain `AsyncOpenAI` with `base_url` override does the job, and PydanticAI's existing `OpenAIChatModel` + `OpenAIProvider(openai_client=...)` consumes it directly.

---

## 1. Architecture After Implementation

```
┌────────────────────────────────────────────────────────┐
│  Agent YAML: model: foundry:gpt-4.1                    │
└─────────────────────┬──────────────────────────────────┘
                      ▼
┌────────────────────────────────────────────────────────┐
│  _build_model(model_name)                              │
│    if startswith("foundry:")                            │
│      → get_foundry_provider() (auth resolved here)     │
│      → OpenAIChatModel(deployment, provider=p)         │
└─────────────────────┬──────────────────────────────────┘
                      ▼
┌────────────────────────────────────────────────────────┐
│  OpenAIProvider(openai_client=AsyncOpenAI(             │
│    base_url=f"{endpoint}/openai/v1/",                  │
│    api_key=<bearer_token_provider | api_key_string>    │
│  ))                                                    │
└─────────────────────┬──────────────────────────────────┘
                      ▼
┌────────────────────────────────────────────────────────┐
│  POST {endpoint}/openai/v1/chat/completions            │
│    {"model": "gpt-4.1", "messages": [...], ...}        │
│  Authorization: Bearer <fresh token per request>       │
└────────────────────────────────────────────────────────┘
```

Auth modes (config-driven, no code branches in agents):
- `entra` — `DefaultAzureCredential` + `get_bearer_token_provider(cred, scope)` → callable passed as `api_key=`. Token auto-refreshes. **Default.**
- `api_key` — env var holding a static API key. Standard pattern; matches our existing providers.
- `bearer_token` — env var holding a pre-fetched bearer (manual override / break-glass).

---

## 2. Touchpoints (the entire change set)

| File | Change |
|---|---|
| [modules/backend/core/config_schema.py](../../modules/backend/core/config_schema.py) | Extend `ProviderAuthSchema` with optional `scope: str \| None = None` (commented as foundry-only). Extend `ProvidersSchema` with `foundry: ProviderAuthSchema` defaulting to `auth_mode="entra"`, `base_url=None`, `scope="https://ai.azure.com/.default"`. |
| [config/settings/providers.yaml](../../config/settings/providers.yaml) | Add `foundry:` block with the resource endpoint and the default Entra scope. |
| [modules/backend/core/model_providers.py](../../modules/backend/core/model_providers.py) | Add `get_foundry_provider()` — resolves auth mode → builds `AsyncOpenAI(base_url=f"{base_url}/openai/v1/", api_key=<resolved>)` → returns `OpenAIProvider(openai_client=client)`. Reuses existing `_read_credential()` and `_get_provider_config()` helpers. |
| [modules/backend/core/model_builder.py](../../modules/backend/core/model_builder.py) | `_build_model()` gains `foundry:` branch → `OpenAIModel(bare_name, provider=get_foundry_provider())`. Error message lists all four providers. **`build_model_settings()` requires no change** — its existing `if provider != "anthropic": return None` at line 33 already covers foundry. |
| [modules/backend/schemas/agent_config.py](../../modules/backend/schemas/agent_config.py) (line 91, 211, 230) | Add `output_mode: Literal["tool", "native"] = "tool"` to `AgentModelSchema`. Add validator that `output_mode="native"` requires provider in `{"openai", "foundry"}`. Add `"foundry"` to `known_providers`. |
| [admin.py](../../admin.py) (line 1022) | `catalog set-provider` Click choice gains `"foundry"`. Add `TO_FOUNDRY` mapping dict and reverse mapping. |
| [config/agents/mission_control.yaml](../../config/agents/mission_control.yaml) (line 46) | Add `foundry:gpt-4.1` pricing row. |
| [modules/clients/cli/credits.py](../../modules/clients/cli/credits.py) | Extend `check_credits` to force a token acquisition when any roster model starts with `foundry:` — surfaces `az login` expiry at preflight instead of mid-dispatch (see §4.8). |
| `scripts/foundry_smoke.py` | **New** — ~50-line smoke test that calls `get_foundry_provider()` and exercises structured output + tool calls + streaming + cached_tokens reporting against the live deployment. |
| [pyproject.toml](../../pyproject.toml) | Add `azure-identity>=1.17.1` to `[project] dependencies` (the canonical declaration). |
| [requirements.txt](../../requirements.txt) | Add the same `azure-identity>=1.17.1` pin. The file is hand-maintained for compatibility with tools that read it directly (header says so) — it does **not** auto-regenerate from `pyproject.toml`. Both files must be edited in the same commit. |

No new agent code. No new schemas in `agents/`. No `FoundryModel(Model)` subclass. No tool bridge. The diff lands at roughly **~250 lines of production code + ~80 lines of smoke test**.

---

## 3. Phase 0 — Factory + smoke test

Goal: implement the provider factory and prove it works end-to-end before exposing it via `_build_model()`.

**Why the factory lives in Phase 0, not Phase 1:** the smoke script must use `get_foundry_provider()` directly. Building parallel wiring in the smoke script (then re-implementing it in Phase 1 as a factory) would create exactly the duplication the project's principles forbid. So Phase 0 ships the factory + smoke; Phase 1 is reduced to wiring the factory into `_build_model()`.

### 3.1 Factory implementation (lands in Phase 0)

Implement these three changes — they are the minimum needed for the smoke script to import `get_foundry_provider()`:

- [modules/backend/core/config_schema.py](../../modules/backend/core/config_schema.py) — extend `ProviderAuthSchema` with `scope` field and add `foundry` to `ProvidersSchema` (see §4.1 for the exact code).
- [config/settings/providers.yaml](../../config/settings/providers.yaml) — add the `foundry:` block (see §4.2).
- [modules/backend/core/model_providers.py](../../modules/backend/core/model_providers.py) — add `get_foundry_provider()` (see §4.3).
- [pyproject.toml](../../pyproject.toml) — add `azure-identity>=1.17.1` to `[project] dependencies`.

These are the same changes documented under Phase 1 below — the split is purely a sequencing concern.

### 3.2 Smoke test

Deliverable: `scripts/foundry_smoke.py`.

```python
"""Foundry provider smoke test — run before flipping any agent.

Exercises the production factory get_foundry_provider() against the live deployment.
Tests: structured output (tool mode), tool calls, streaming, cost attribution,
native structured output (advisory). Reads endpoint + auth from providers.yaml.
"""

import asyncio
import logging
import os
import sys

import click
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.profiles import ModelProfile

from modules.backend.agents.mission_control.cost import compute_cost_usd
from modules.backend.core.logging import get_logger
from modules.backend.core.model_providers import get_foundry_provider

logger = get_logger(__name__)


class PersonInfo(BaseModel):
    name: str
    age: int
    occupation: str


async def _run(deployment: str) -> int:
    """Returns process exit code (0 on Tests 1–4 pass, 1 otherwise). Test 5 is advisory."""
    provider = get_foundry_provider()
    failures: list[str] = []

    # Test 1: structured output via PydanticAI's final_result tool path (default).
    tool_model = OpenAIModel(deployment, provider=provider)
    agent = Agent(tool_model, output_type=PersonInfo)
    result = await agent.run("Jane Doe is a 42-year-old risk analyst.")
    assert result.output.name == "Jane Doe"
    assert result.output.age == 42
    logger.info("PASS Test 1 structured output (tool mode): %s", result.output)

    # Test 2: tool call.
    tool_agent = Agent(tool_model)

    @tool_agent.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    r2 = await tool_agent.run("Use the tool to compute 17 + 25.")
    assert "42" in r2.output
    logger.info("PASS Test 2 tool call: %s", r2.output)

    # Test 3: streaming — must yield at least one non-empty chunk.
    chunks: list[str] = []
    async with tool_agent.run_stream("Say 'hello' once.") as stream:
        async for chunk in stream.stream_text():
            chunks.append(chunk)
    assert chunks, "stream yielded zero chunks"
    assert "".join(chunks).strip(), "stream produced only empty text"
    logger.info("PASS Test 3 streaming: %d chunks, %d chars", len(chunks), len("".join(chunks)))

    # Test 4: cost attribution — proves the pricing row is wired correctly.
    # If this matches the 'default' fallback rate, cost.py is silently misattributing.
    usage = result.usage()
    model_key = f"foundry:{deployment}"
    cost = compute_cost_usd(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model=model_key,
        cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or 0,
    )
    default_cost = compute_cost_usd(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model="__nonexistent__",  # forces the silent default-rate fallback
    )
    cached = getattr(usage, "cache_read_tokens", None)
    logger.info(
        "USAGE: input=%d output=%d cached=%s cost=$%.6f default_fallback=$%.6f",
        usage.input_tokens, usage.output_tokens, cached, cost, default_cost,
    )
    assert cost > 0, f"cost is zero — pricing row missing for {model_key!r}"
    assert cost != default_cost, (
        f"cost equals the default-rate fallback (${default_cost:.6f}); pricing row for "
        f"{model_key!r} is not being picked up by compute_cost_usd"
    )
    logger.info("PASS Test 4 cost attribution: $%.6f for %s", cost, model_key)

    # Test 5 (ADVISORY): native structured output mode via ModelProfile override.
    # This is the EXACT production path — _build_model() will construct the Model the
    # same way when an agent sets output_mode: native. Failure here does not fail the
    # smoke run; it just dictates that §4.4 _build_profile and §4.5 output_mode do not
    # ship. Tests 1–4 are the hard gate.
    try:
        native_model = OpenAIModel(
            deployment,
            provider=provider,
            profile=ModelProfile(default_structured_output_mode="native"),
        )
        native_agent = Agent(native_model, output_type=PersonInfo)
        r5 = await native_agent.run("Bob Lee is a 29-year-old chef.")
        assert r5.output.name == "Bob Lee"
        assert r5.output.age == 29
        logger.info("PASS Test 5 structured output (native mode): %s", r5.output)
    except Exception as exc:
        failures.append(f"Test 5 (native mode, ADVISORY): {exc}")
        logger.warning("ADVISORY FAIL Test 5 native mode: %s — drop §4.4/§4.5 native wiring", exc)

    if failures:
        logger.warning("Advisory failures: %s", failures)
    return 0


@click.command()
@click.option("--deployment", default=lambda: os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
              help="Foundry deployment name (defaults to $AZURE_OPENAI_DEPLOYMENT or 'gpt-4.1').")
@click.option("--verbose", is_flag=True, help="INFO-level logging.")
@click.option("--debug", is_flag=True, help="DEBUG-level logging.")
def main(deployment: str, verbose: bool, debug: bool) -> None:
    """Foundry provider smoke test. Exits 0 if Tests 1–4 pass; Test 5 is advisory."""
    level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s — %(message)s")
    sys.exit(asyncio.run(_run(deployment)))


if __name__ == "__main__":
    main()
```

Run via `python scripts/foundry_smoke.py --verbose` after `az login`. The smoke test is also the canonical empirical answer to the open question on `cached_tokens` reporting — if the USAGE line shows `cached=<int>` (not `None`), we get cache attribution for free in the cost tracker.

**Gate:** Tests 1–4 (tool-mode structured output, tool call, streaming, cost attribution) must pass. Test 5 (native mode) is **advisory**: its result decides whether §4.4's `_build_profile` helper and §4.5's `output_mode` field ship at all (see §4.4/§4.5 contingency notes).

- If Test 1 (tool mode) fails — deployment configuration issue, fix before Phase 1.
- If Tests 2 or 3 (tool call, streaming) fail — **stop and re-evaluate the plan**; we may need `OpenAIResponsesModel` instead of `OpenAIModel`.
- If Test 4 (cost attribution) fails — pricing row missing or misnamed; fix before Phase 2 (the silent fallback in `cost.py:28-31` makes this invisible at runtime).
- If Test 5 (native mode) fails — the native opt-in is not viable on this deployment. Ship the plan without §4.5's `output_mode` field and validator, and without the `_build_profile` helper in §4.4; agents can still use foundry via tool mode. Document the failure.

---

## 4. Phase 1 — Wire factory into `_build_model`

After Phase 0 ships, the factory exists but no agent can reference `foundry:` because `_build_model()` will reject it. Phase 1 is the small remaining glue.

**Phase 0 ships:** §4.1 (`ProviderAuthSchema` extension), §4.2 (`providers.yaml`), §4.3 (`get_foundry_provider()`), §4.7 (`pyproject.toml`), plus the smoke script.

**Phase 1 ships:** §4.4 (`_build_model()` branch — with or without the `profile=` argument depending on smoke Test 5), §4.5 (`output_mode` field + `known_providers`; ship only if Test 5 passed), §4.6 (pricing row), §4.8 (credits-command preflight).

The sub-sections below are the canonical reference for both phases — code blocks are not duplicated.

### 4.1 `ProviderAuthSchema` extension

[modules/backend/core/config_schema.py:522-527](../../modules/backend/core/config_schema.py#L522-L527):

```python
class ProviderAuthSchema(_StrictBase):
    """Authentication configuration for a model provider.

    Provider-specific fields (e.g. ``scope`` for Foundry Entra auth) live here
    rather than in a subclass. If a third provider needs its own quirk field,
    promote this to ``ProviderAuthBase`` + per-provider subclasses instead of
    growing the union — the pattern-of-three threshold for splitting is real.
    """

    auth_mode: str = "api_key"  # "api_key" | "auth_token" | "codex_oauth" | "entra" | "bearer_token"
    env_var: str | None = None
    base_url: str | None = None
    scope: str | None = None  # foundry-only: Entra ID token scope (e.g. "https://ai.azure.com/.default")
```

The `scope` field is unused by Anthropic and OpenAI configs — it follows the existing shape of `base_url` (also provider-specific). The pragmatic alternative (a `FoundryProviderAuthSchema` subclass) buys ~5 lines of type safety against a near-zero misconfiguration risk; not worth the split today. The class docstring records the trigger for revisiting that decision.

[modules/backend/core/config_schema.py:530-542](../../modules/backend/core/config_schema.py#L530-L542):

```python
class ProvidersSchema(_StrictBase):
    """Provider authentication configuration (providers.yaml)."""

    anthropic: ProviderAuthSchema = Field(...)
    openai: ProviderAuthSchema = Field(...)
    foundry: ProviderAuthSchema = Field(
        default_factory=lambda: ProviderAuthSchema(
            auth_mode="entra",
            env_var=None,
            base_url=None,
            scope="https://ai.azure.com/.default",
        ),
    )
```

### 4.2 `providers.yaml` entry

[config/settings/providers.yaml](../../config/settings/providers.yaml):

```yaml
# Foundry — Azure AI Foundry (Azure OpenAI on Foundry)
#
# Auth modes (in priority order):
#   entra         — DefaultAzureCredential + scope (recommended, picks up az login locally
#                   and managed identity in prod). No env_var required.
#   api_key       — static API key from env var (set env_var: AZURE_OPENAI_API_KEY)
#   bearer_token  — pre-fetched bearer from env var (set env_var: AZURE_OPENAI_AUTH_TOKEN)
#
# base_url is the Azure OpenAI resource endpoint (without /openai/v1/ suffix — code
# appends it). Example: https://gis-mission-control-resource.openai.azure.com
foundry:
  auth_mode: entra
  base_url: https://gis-mission-control-resource.openai.azure.com
  scope: https://ai.azure.com/.default
```

The base_url is a non-secret resource URL and lives in `providers.yaml` (not `.env`). API keys / bearer tokens, when used, live in `.env` per existing convention.

### 4.3 `get_foundry_provider()`

[modules/backend/core/model_providers.py](../../modules/backend/core/model_providers.py) — append after `get_openai_provider()`:

```python
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
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
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
```

### 4.4 `_build_model()` branch

**Contingency:** the `profile=` argument and `_build_profile` helper below ship **only if Test 5 of the Phase 0 smoke passes**. If Test 5 fails, the branch reduces to `return OpenAIModel(bare_name, provider=provider)` — drop the `profile` argument and skip §4.5 entirely.

[modules/backend/core/model_builder.py:113-140](../../modules/backend/core/model_builder.py#L113-L140) — add before the final `raise`:

```python
    if model_name.startswith("foundry:"):
        bare_name = model_name.split(":", 1)[1]
        from pydantic_ai.models.openai import OpenAIModel
        from modules.backend.core.model_providers import get_foundry_provider
        provider = get_foundry_provider()
        profile = _build_profile(config_model)  # omit if Test 5 failed
        return OpenAIModel(bare_name, provider=provider, profile=profile)
```

Add a tiny helper at module scope (omit if Test 5 failed):

```python
def _build_profile(config_model: str | AgentModelSchema):
    """Return a ModelProfile that pins structured-output mode, or None for defaults.

    Mirrors the pattern used by CopilotModel ([copilot_model.py:321-326]), which
    constructs its own ModelProfile to force tool mode. Here we use the same
    extension point to opt in to native mode per-agent without touching agent code.
    """
    if not isinstance(config_model, AgentModelSchema):
        return None
    if config_model.output_mode == "tool":
        return None  # let PydanticAI's per-model defaults apply
    from pydantic_ai.profiles import ModelProfile
    return ModelProfile(default_structured_output_mode=config_model.output_mode)
```

Update the final error message to list all four providers. Note: use `OpenAIModel` (not `OpenAIChatModel`) for consistency with the existing `openai:` branch at line 130.

**Why this design over a helper:** [agent_executor.py:67](../../modules/backend/agents/mission_control/helpers/agent_executor.py#L67) shows the contract is `module.create_agent(model, tool_names=...)` — uniform across all ~15 agent factories. A `resolve_output_type` helper would require widening every factory's signature to also accept agent config. Setting the mode on the `Model`'s `ModelProfile` at construction time is the existing PydanticAI extension point (CopilotModel uses it), needs zero agent file changes, and keeps all the routing logic in one place (`_build_model`).

### 4.5 `AgentModelSchema` extension + provider validation

**Contingent on Test 5 passing** (see §4.4). If Test 5 fails, do not ship this subsection — agents stay on the implicit tool-mode default for all providers.

[modules/backend/schemas/agent_config.py](../../modules/backend/schemas/agent_config.py).

Line 91 — extend `AgentModelSchema` with the opt-in field:

```python
class AgentModelSchema(_StrictBase):
    """Pinned model configuration. Immutable at runtime."""

    name: str = Field(...)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    betas: list[str] = Field(default_factory=list)
    output_mode: Literal["tool", "native"] = Field(
        default="tool",
        description=(
            "How PydanticAI enforces structured output. 'tool' uses the hidden "
            "final_result tool call (portable across all providers). 'native' uses "
            "response_format with json_schema strict mode (lower latency, model-level "
            "schema enforcement at decode time, but requires openai or foundry provider). "
            "Only effective when the agent's model is given in dict form "
            "(model: { name: ..., output_mode: native }); bare-string models cannot set "
            "this field and silently default to 'tool'."
        ),
    )
```

Line 230 — extend `known_providers`:

```python
known_providers = {"anthropic", "openai", "google", "bedrock", "copilot", "foundry"}
```

Line 211 `_validate_model_config` — add native-mode provider check:

```python
# After the existing provider validation
if isinstance(self.model, AgentModelSchema) and self.model.output_mode == "native":
    if provider not in {"openai", "foundry"}:
        raise ValueError(
            f"Agent '{self.agent_name}': output_mode='native' requires an openai or "
            f"foundry provider (got '{provider}'). Native JSON-schema strict mode is "
            f"only supported by providers that pass response_format through to the model."
        )
```

This validator fires at YAML load time — there's no path where a misconfigured agent reaches dispatch.

**Discoverability note:** `output_mode` is a field on `AgentModelSchema`, so it is only available when an agent's YAML uses the dict form (`model: { name: foundry:gpt-4.1, output_mode: native, ... }`). Agents that use the bare-string form (`model: foundry:gpt-4.1`) silently get tool mode — there is no place to set `output_mode` on a string. `_StrictBase` will reject `output_mode:` written as a sibling key of `model:`, so the failure mode is "user notices the field has no effect" rather than "user silently misconfigures." Acceptable; document in the field description that opt-in requires the dict form.

### 4.6 Pricing row

[config/agents/mission_control.yaml](../../config/agents/mission_control.yaml) line 46 (`model_pricing` block):

```yaml
  "foundry:gpt-4.1":
    input: 2.50
    output: 10.00
    cache_read: 0.625    # omit this field if Phase 0 smoke does not report cached_tokens
```

**This row MUST land in the same commit as the canary flip in Phase 2.** [cost.py:28-34](../../modules/backend/agents/mission_control/cost.py#L28-L34) silently falls back to the `default` pricing row (3.00 input / 15.00 output — Sonnet-grade) for unknown models, logging only a warning. If the pricing row is missed, every Foundry cost row will be misattributed at default rates until a follow-up commit fixes it. This is a pre-existing project violation of "no silent fallbacks", not something this plan introduces — but it makes the sequencing constraint hard.

**Cache fields are optional in the schema.** [agent_config.py:283-290](../../modules/backend/schemas/agent_config.py#L283-L290) defines `ModelPricingRateSchema` with `cache_read=0.0`, `cache_write_5m=0.0`, `cache_write_1h=0.0` as defaults. So if Phase 0's smoke does not surface `cached_tokens`, omit those fields entirely — they compute to zero rather than crash. Confirm `input` and `output` rates against the Foundry pricing page for the deployment region before merging; the values above are illustrative.

### 4.7 Dependency

Add `azure-identity>=1.17.1` to both files in the same commit:

- [pyproject.toml](../../pyproject.toml) `[project] dependencies` — the canonical declaration.
- [requirements.txt](../../requirements.txt) — hand-maintained per its file header (does not auto-regenerate from `pyproject.toml`). Add the same pin so consumers reading `requirements.txt` directly stay in sync.

`openai` is already pinned in both files; `pydantic_ai.providers.openai.OpenAIProvider` is already imported elsewhere. `pydantic_ai.profiles.ModelProfile` is part of PydanticAI's existing public API (used today by [copilot_model.py:321-326](../../modules/backend/core/copilot_model.py#L321-L326)).

---

### 4.8 Entra-token preflight

`DefaultAzureCredential()` is constructed eagerly inside `get_foundry_provider()` but does **not** acquire a token until the `get_bearer_token_provider`-returned callable is first invoked by `AsyncOpenAI`. That happens at the first agent dispatch. So an expired `az login` (or a misconfigured managed identity in prod) does not surface until a real mission run — at which point the error is a 401 mid-dispatch, hard to attribute.

Add a liveness check to the existing `python admin.py credits` command ([modules/clients/cli/credits.py](../../modules/clients/cli/credits.py)):

- If any roster agent's model starts with `foundry:`, call `get_foundry_provider()` and then *force* a token acquisition by invoking the bearer-token callable once. Report the token's expiry (`AccessToken.expires_on`) and the resolved credential class (e.g. `AzureCliCredential` vs `ManagedIdentityCredential`).
- On failure, surface the underlying `azure.identity` exception with the standard `az login` remediation hint.

This keeps Foundry on the same preflight surface as the existing Anthropic/Copilot/OpenAI credential checks. No new admin command — extend the one that already exists.

---

## 5. Phase 2 — Canary agent

Flip exactly one agent to `foundry:gpt-4.1` and monitor for a day.

**Target:** [config/agents/system/summarization/agent.yaml](../../config/agents/system/summarization/agent.yaml).

Why summarization:
- Low blast radius — failures don't break dispatch, only knowledge extraction.
- Runs frequently enough (daily KnowledgeExtractionWorkflow at 03:30 UTC) that we'll see real traffic within 24h.
- Doesn't use streaming-heavy patterns, so we exercise the request/response path before stressing streaming.
- Doesn't use structured output extensively, so any prompted-output regression won't masquerade as a foundry issue.

Procedure:
1. Update YAML: `model: foundry:gpt-4.1`.
2. Re-seed: `python admin.py admin seed-catalog`.
3. Run the smoke test once more to confirm the agent loads.
4. Trigger a summarization manually via `mc.py` or wait for the scheduled workflow.
5. Inspect [llm_calls] for the new rows: confirm `provider=foundry`, `cost_usd > 0`, `model=foundry:gpt-4.1`.
6. Monitor for 24h. Roll back to `copilot:claude-haiku-4.5` on any error spike.

**Gate to Phase 3:** 24h clean run with no error rate increase. If errors appear, do not proceed to admin tooling — fix the root cause first.

---

## 6. Phase 3 — Admin `catalog set-provider` support

**Gate:** Phase 2 must have completed its 24h clean canary run. Do not implement this phase until then — shipping a `--to foundry` fleet-migration command before the canary proves the provider works gives operators a footgun.


[admin.py:1022-1057](../../admin.py#L1022-L1057):

```python
@catalog.command("set-provider")
@click.argument("provider", type=click.Choice(["copilot", "anthropic", "foundry"]))
```

Add a `TO_FOUNDRY` mapping for the model families we expect to migrate. Since Foundry deployment names are operator-chosen (not standardised), this mapping reflects **our** deployment naming, not Azure's:

```python
    TO_FOUNDRY = {
        # Anthropic / Copilot model name → our Foundry deployment name
        "claude-haiku-4.5":        "gpt-4.1-mini",      # or whatever deployment we stand up
        "claude-sonnet-4.6":       "gpt-4.1",
        "claude-opus-4.6":         "gpt-5",
        "claude-haiku-4-5":        "gpt-4.1-mini",
        "claude-sonnet-4-6":       "gpt-4.1",
        "claude-opus-4-6":         "gpt-5",
        "claude-opus-4-7":         "gpt-5",
    }

    mapping = {
        "copilot": TO_COPILOT,
        "anthropic": TO_ANTHROPIC,
        "foundry": TO_FOUNDRY,
    }[provider]
```

The reverse mapping (`TO_FOUNDRY → original`) is **not** auto-generated because Foundry deployments may not have a 1:1 correspondence with the Claude / Copilot model graph. Document this in the docstring: fleet migrations *from* Foundry back to Anthropic/Copilot still require `--model-map` overrides on the CLI.

**Deployment-existence gate:** before the command writes (or before `--dry-run` reports "ready"), it must call `AsyncOpenAI(...).models.list()` against the Foundry endpoint and verify that every distinct target deployment name in the post-mapping plan is in the returned list. Unmapped or non-existent deployments must abort the run with the full list of missing names. Otherwise `TO_FOUNDRY` will happily map `claude-sonnet-4.6 → gpt-4.1` even when no `gpt-4.1` deployment exists, and the first agent flipped will 404 at dispatch. This is the same liveness principle as §4.8 applied to the fleet-flip path.

**Definition of success for the admin command:** `python admin.py catalog set-provider foundry --dry-run` lists every agent with a sensible target deployment name, no unmapped entries fall through to the default identity mapping, and every target deployment is verified to exist on the Foundry resource.

---

## 7. Open empirical questions (closed by Phase 0 smoke test)

The smoke test exists to close these before the canary flip. If any answer is "no", the relevant phase pauses until resolved:

1. **Does Azure OpenAI v1 GA report `usage.prompt_tokens_details.cached_tokens`?** Determines whether we get cache attribution. If no, we accept no cache visibility on `foundry:` and document it.
2. **Does the v1 endpoint accept PydanticAI's `final_result` tool-based structured output?** Confirmed by the smoke test's `PersonInfo` extraction. If no, P17 is broken on this provider and we need to investigate.
3. **Does streaming work alongside tool calls?** Smoke test exercises streaming separately. If parallel streaming + tool calls is broken, document the limitation and avoid running deliberation agents on Foundry until fixed.
4. **Does `DefaultAzureCredential` pick up `az login` cleanly with no extra config?** If no, document the required environment variables (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`) for the service-principal fallback.

---

## 8. What NOT to do

- **Do not write a `FoundryModel(Model)` subclass.** The Copilot adapter exists because Copilot's SDK isn't OpenAI-wire. Azure OpenAI v1 *is* OpenAI-wire. Wrapping `AsyncOpenAI` with a base_url override is the correct adapter.
- **Do not use `AsyncAzureOpenAI` from `openai[azure]`.** The reference bundle proved `AsyncOpenAI` + `base_url=f"{endpoint}/openai/v1/"` works directly. The Azure-specific client is for the older `/openai/deployments/<name>/...?api-version=...` URL shape, which we're not using.
- **Do not introduce `azure-ai-projects` or `azure-ai-inference`.** Neither is needed for our v1 endpoint. They become relevant only if we later add the **unified Foundry Models endpoint** (`/services.ai.azure.com/models`) to talk to non-OpenAI models on Foundry.
- **Do not assume Claude on Foundry works through `foundry:`** This plan covers Azure OpenAI on Foundry only. Claude on Foundry lives on the unified Foundry Models endpoint and is a future plan if/when we get access.
- **Do not seed cache pricing for `foundry:` until the smoke test confirms `cached_tokens` reporting.** Speculative cache rows will mislead the cost dashboard.
- **Do not migrate all agents in one go.** Canary on summarization first. The 24h monitoring window is non-negotiable.
- **Do not commit `AZURE_OPENAI_API_KEY` to git.** The `entra` default mode requires no static credential. If api_key mode is used for testing, it goes in `config/.env`, never in `providers.yaml`.

---

## 9. Definition of Done

1. Smoke test `scripts/foundry_smoke.py` exists. Tests 1–4 pass against the live Foundry deployment. Test 5's result is recorded and dictates whether §4.4 `_build_profile` + §4.5 `output_mode` ship (pass) or are dropped (fail) — see §3.2 gate.
2. Provider plumbing committed: schema, providers.yaml, `get_foundry_provider`, `_build_model` branch, `known_providers`, pricing row, requirements.
3. `system.summarization.agent` runs on `foundry:gpt-4.1` for 24h with no error rate increase. `llm_calls` rows confirm cost attribution.
4. `admin.py catalog set-provider foundry --dry-run` produces a clean mapping list (every agent has a target deployment, no unmapped entries).
5. The open empirical questions in §7 are answered in the smoke test output and documented in the plan or a follow-up note.
6. `MEMORY.md` updated with a project memory `project_foundry_provider.md` recording: (a) the deployment endpoint and resource name, (b) the default auth mode (`entra` with scope `https://ai.azure.com/.default`), (c) the smoke-script location `scripts/foundry_smoke.py`, (d) the empirical result for Test 5 (native mode supported / not supported on this deployment) — so future plans don't re-test it.

---

## 9.1. Inherited concern (not fixed by this plan)

`get_foundry_provider()` creates a fresh `AsyncOpenAI` (with its own connection pool) on every `_build_model()` call. This mirrors the existing behaviour of `get_openai_provider()` ([model_providers.py:117-120](../../modules/backend/core/model_providers.py#L117-L120)) and `get_anthropic_provider()` ([model_providers.py:71-74](../../modules/backend/core/model_providers.py#L71-L74)). Fixing it (memoize providers per process, share connection pools) is a separate refactor across all three providers — out of scope here.

---

## 10. Out of Scope (explicitly deferred)

- **Unified Foundry Models endpoint** (`/services.ai.azure.com/models`) for Claude / Llama / Mistral / DeepSeek / Phi on Foundry. Adds a second client type (`azure-ai-inference`) or a different base_url pattern. Separate plan when we have access.
- **`foundry-aoai:` vs `foundry:` split**. Only needed if we adopt the unified endpoint *and* keep the Azure-OpenAI-specific deployments separately for provisioned-throughput SLAs.
- **Responses API** (`OpenAIResponsesModel`). The current bundle and smoke test use chat completions. If we later need o-series reasoning summaries on Foundry, that's a separate switch in `_build_model`.
- **Per-deployment routing** (e.g. different deployments for different agents within the same provider). Possible via the model alias system if needed; not required for this plan.
