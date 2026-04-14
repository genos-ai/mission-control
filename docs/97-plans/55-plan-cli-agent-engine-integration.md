# Plan 55 — CLI Agent Engine Integration (Claude Code, Codex, Copilot)

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-13 |
| **Depends on** | Plan 52 (Temporal Backbone — done), Plan 37 (Execution Environments — in progress) |
| **Target** | Agent config schema, dispatch loop, execution service, frontend agent settings |

---

## 1  Problem

All agents execute via PydanticAI in-process (`agent.run_stream()`), which requires Anthropic API keys. Three CLI coding agents — Claude Code, OpenAI Codex, and GitHub Copilot CLI — can authenticate via web browser OAuth (subscription-based, no API keys) and execute as subprocesses. The platform has no way to use them.

### What we want

A per-agent `engine` field that selects *how* an agent executes:

| Engine | Runtime | Auth | SDK/CLI |
|--------|---------|------|---------|
| `pydantic_ai` | In-process Python | API key | PydanticAI `agent.run_stream()` |
| `claude_code` | Subprocess | OAuth token (Pro/Max/Team/Enterprise) | `claude-agent-sdk` Python package |
| `codex` | Subprocess | OAuth token (ChatGPT Plus/Pro/Business) | `codex exec` CLI |
| `copilot` | Subprocess | OAuth token (Copilot Individual/Business/Enterprise) | `copilot -p` CLI |

The agent's system prompt, tools list, scope, and budget transfer to the CLI engine. The dispatch loop routes by engine. Existing PydanticAI agents are unchanged (engine defaults to `pydantic_ai`).

---

## 2  Design Decisions

### D1 — Engine is a property of the agent config, not the task or mission

The `engine` field lives in the agent YAML (`config/agents/**/agent.yaml`). The dispatch loop reads it from the agent config. The frontend exposes it as a dropdown on the agent settings page.

**Why not per-task:** The same agent shouldn't flip engines between tasks — its tools and capabilities differ by engine. A `software.quality.agent` with PydanticAI tools can't suddenly use Claude Code's built-in tools mid-plan.

**Why not per-mission:** Missions use multiple agents. Engine selection is per-agent, not per-mission.

### D2 — CLI agents get the system prompt, not custom PydanticAI tools

When `engine != pydantic_ai`, the agent's `system_prompt` from the prompt file (`config/prompts/agents/.../system.md`) is passed to the CLI. The agent's `tools` list from YAML is **not** passed — CLI engines have their own built-in tools. Custom tools are a Phase 2 feature (MCP server).

### D3 — OAuth tokens stored per-user per-provider

A new `provider_credentials` table stores encrypted OAuth tokens. The frontend has a "Connections" page where users authorize each provider via OAuth. The backend injects the token as an environment variable when spawning the CLI subprocess.

### D4 — Subprocess spawning reuses execution environment infrastructure

CLI agents spawn inside the same execution environment (local/worktree/container) as PydanticAI agents. `ContainerBackend` already handles subprocess spawning with env vars and working directories. The CLI engine is a new code path in the dispatch loop, not a new execution environment.

### D5 — MVP skips MCP tools and frontend OAuth page

Phase A proves the engine field works end-to-end with a manually-configured OAuth token (env var). Phase B adds the provider credential storage and frontend OAuth flow. Phase C adds MCP server integration for custom tools.

---

## 3  Phases

### Phase A — Engine Field + Claude Code Dispatch (MVP)

**Goal:** An agent with `engine: claude_code` dispatches via `claude-agent-sdk` subprocess. Token provided via `CLAUDE_CODE_OAUTH_TOKEN` env var. No frontend changes.

#### 3.1 Add `engine` Field to Agent Config Schema

**Modified file:** `modules/backend/agents/config_schema.py`

Add to `AgentConfigSchema` (after `execution` field, ~line 132):

```python
# Execution engine — determines how the agent runs.
# "pydantic_ai" (default): in-process PydanticAI agent.run_stream()
# "claude_code": subprocess via claude-agent-sdk
# "codex": subprocess via codex exec CLI
# "copilot": subprocess via copilot -p CLI
engine: str = "pydantic_ai"
```

Add a validator:

```python
@field_validator("engine")
@classmethod
def _validate_engine(cls, v: str) -> str:
    valid = {"pydantic_ai", "claude_code", "codex", "copilot"}
    if v not in valid:
        raise ValueError(f"engine must be one of {valid}, got '{v}'")
    return v
```

**Note:** `extra='forbid'` on `_StrictBase` means the field MUST be added to the schema — YAML files with `engine:` will fail validation otherwise. Since it has a default, existing YAMLs without `engine:` continue to work.

#### 3.2 Add `effort` Field to Agent Config Schema

**Modified file:** `modules/backend/agents/config_schema.py`

Add to `AgentConfigSchema` (after `engine`):

```python
# Effort level for CLI engines that support it (claude_code).
# Ignored for pydantic_ai engine.
effort: str | None = None

@field_validator("effort")
@classmethod
def _validate_effort(cls, v: str | None) -> str | None:
    if v is not None and v not in {"low", "medium", "high"}:
        raise ValueError(f"effort must be low/medium/high, got '{v}'")
    return v
```

#### 3.3 New Module: CLI Agent Executor

**New file:** `modules/backend/agents/mission_control/helpers/cli_executor.py`

This is the core of the plan — the equivalent of `execute_agent()` in `agent_executor.py` but for CLI engines.

```python
"""CLI agent executor — dispatches tasks to CLI coding agents (Claude Code, Codex, Copilot).

Counterpart to agent_executor.py which handles PydanticAI in-process agents.
Each engine function spawns a subprocess, passes the system prompt and task
instructions, and returns the agent's output as a dict matching the _meta
structure expected by retry_handler.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Subprocess timeout — prevents hung CLI processes from blocking dispatch.
# The outer step_executor.py timeout cancels the coroutine, but a hung
# subprocess child process survives. This timeout kills it directly.
CLI_SUBPROCESS_TIMEOUT_SECONDS = 600


def _cli_result(output: str) -> dict:
    """Normalize CLI executor output to match PydanticAI agent return structure.

    The dispatch loop (retry_handler.py:134-139) extracts costs from
    output["_meta"]["cost_usd"] and tokens from output["_meta"]["input_tokens"].
    Subscription-based CLI agents report 0 for all — costs are covered by
    the user's subscription, not per-call API billing.
    """
    return {
        "output": output,
        "_meta": {
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
        },
    }


def _compose_user_message(instructions: str, inputs: dict) -> str:
    """Build the user message from task instructions and inputs."""
    message = instructions
    if inputs:
        message += f"\n\nInputs:\n```json\n{json.dumps(inputs, indent=2)}\n```"
    return message


async def _run_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    timeout: float = CLI_SUBPROCESS_TIMEOUT_SECONDS,
    agent_name: str = "",
    engine_label: str = "",
) -> str:
    """Run a CLI subprocess with timeout and cleanup.

    Returns stdout on success. On failure or timeout, logs the error
    and returns an error message (does not raise — the dispatch loop
    handles failure via TaskResult status).
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.error(
            f"{engine_label} subprocess timed out",
            extra={"agent": agent_name, "timeout": timeout},
        )
        return f"ERROR: {engine_label} subprocess timed out after {timeout}s"

    if proc.returncode != 0:
        logger.error(
            f"{engine_label} subprocess failed",
            extra={
                "agent": agent_name,
                "returncode": proc.returncode,
                "stderr": stderr.decode("utf-8", errors="replace")[:500],
            },
        )

    return stdout.decode("utf-8", errors="replace").strip()


async def execute_claude_code(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    effort: str | None = None,
    max_turns: int = 50,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
    scope_read: list[str] | None = None,
    scope_write: list[str] | None = None,
) -> dict:
    """Execute a task via Claude Code Agent SDK.

    Spawns the Claude Code CLI as a subprocess, passes the system prompt
    and task instructions, and returns the final response.

    Auth: reads CLAUDE_CODE_OAUTH_TOKEN from environment (set by
    ProviderCredentialService in Phase B, or manually for MVP).

    Effort: The Python Agent SDK does not yet expose an `effort` parameter
    in ClaudeAgentOptions (see github.com/anthropics/claude-code/issues/19425).
    As a workaround, effort is set via the CLAUDE_CODE_EFFORT_LEVEL env var
    which the CLI binary reads.

    Returns dict matching PydanticAI agent output structure (see _cli_result).
    """
    from claude_agent_sdk import ClaudeAgentOptions, query, AssistantMessage, TextBlock

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=str(working_dir or find_project_root()),
        max_turns=max_turns,
    )

    # Build allowed_tools based on agent scope.
    # Agents with non-empty scope.write get write/edit/bash tools.
    # Read-only agents (scope.write empty or absent) get only read tools.
    allowed_tools = ["Read", "Grep", "Glob"]
    if scope_write:
        allowed_tools.extend(["Write", "Edit", "Bash"])
    options.allowed_tools = allowed_tools

    # Effort: set via env var since Python SDK lacks the parameter.
    # The Claude CLI binary reads CLAUDE_CODE_EFFORT_LEVEL.
    if effort:
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = effort

    user_message = _compose_user_message(instructions, inputs)

    # Collect response
    response_parts: list[str] = []

    try:
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
    finally:
        # Clean up env var to avoid leaking to other agents in same process
        os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)

    output = "\n".join(response_parts)

    return _cli_result(output)


async def execute_codex(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> dict:
    """Execute a task via OpenAI Codex CLI (codex exec).

    Spawns `codex exec` as a subprocess in non-interactive mode.
    Auth: reads from ~/.codex/auth.json (set by codex login or
    ProviderCredentialService in Phase B).

    System prompt: passed via --config developer_instructions="...".
    See: developers.openai.com/codex/config-reference

    Returns dict matching PydanticAI agent output structure (see _cli_result).
    """
    cwd = str(working_dir or find_project_root())
    user_message = _compose_user_message(instructions, inputs)

    cmd = [
        "codex", "exec", user_message,
        "--approval-mode", "never",
        "--full-auto",
    ]

    # Pass system prompt via developer_instructions config flag.
    # This is the Codex-supported mechanism for custom instructions.
    if system_prompt:
        cmd.extend(["--config", f"developer_instructions={system_prompt}"])

    output = await _run_subprocess(
        cmd, cwd=cwd, agent_name=agent_name, engine_label="Codex",
    )

    return _cli_result(output)


async def execute_copilot(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> dict:
    """Execute a task via GitHub Copilot CLI (copilot -p).

    Spawns `copilot -p` as a subprocess in non-interactive mode.
    Auth: reads GH_TOKEN or GITHUB_TOKEN from environment, or
    ~/.copilot/config.json (set by copilot /login or ProviderCredentialService).

    System prompt: Copilot CLI reads AGENTS.md from the working directory.
    We write the system prompt to a temporary AGENTS.md in the cwd before
    spawning, and clean it up after.

    Returns dict matching PydanticAI agent output structure (see _cli_result).
    """
    cwd = str(working_dir or find_project_root())
    agents_md = Path(cwd) / "AGENTS.md"
    agents_md_backup = None

    # Inject system prompt via AGENTS.md (Copilot's instruction mechanism).
    # Back up existing AGENTS.md if present, restore after execution.
    try:
        if system_prompt:
            if agents_md.exists():
                agents_md_backup = agents_md.read_text(encoding="utf-8")
            agents_md.write_text(system_prompt, encoding="utf-8")

        user_message = _compose_user_message(instructions, inputs)

        cmd = [
            "copilot",
            "-p", user_message,
            "-s",  # Stripped output (no formatting/stats)
        ]

        output = await _run_subprocess(
            cmd, cwd=cwd, agent_name=agent_name, engine_label="Copilot",
        )
    finally:
        # Restore original AGENTS.md or remove the temporary one
        if agents_md_backup is not None:
            agents_md.write_text(agents_md_backup, encoding="utf-8")
        elif system_prompt and agents_md.exists():
            agents_md.unlink()

    return _cli_result(output)
```

#### 3.4 Load System Prompt for CLI Engines

**New function in:** `modules/backend/agents/mission_control/helpers/prompt_builder.py`

Add a function to load the raw system prompt markdown for CLI engines:

```python
def load_agent_system_prompt(agent_name: str) -> str:
    """Load the system prompt markdown for a CLI agent.

    Reads config/prompts/agents/{domain}/{name}/system.md.
    Returns the raw markdown content (no template substitution).
    """
    # Convert agent_name (e.g. "mission.director.agent") to path
    parts = agent_name.rsplit(".", 1)[0].split(".")  # ["mission", "director"]
    prompt_path = find_project_root() / "config" / "prompts" / "agents"
    for part in parts:
        prompt_path = prompt_path / part
    prompt_path = prompt_path / "system.md"

    if not prompt_path.is_file():
        return ""

    return prompt_path.read_text(encoding="utf-8")
```

**Check:** Verify this path resolution matches existing prompt files. The existing `_build_planning_prompt` in prompt_builder.py may already have similar logic — reuse if possible.

#### 3.5 Route by Engine in Agent Executor

**Modified file:** `modules/backend/agents/mission_control/helpers/agent_executor.py`

**Step 1:** Add `current_user_id` to the closure factory signature (needed for Phase B token resolution, but add the parameter now to avoid breaking the signature later):

```python
def _make_agent_executor(
    event_bus: EventBusProtocol,
    *,
    session_id: str,
    mission_id: str,
    environment_handle: object | None = None,
    current_user_id: str | None = None,       # NEW (Plan 55)
) -> ExecuteAgentFn:
```

**Step 2:** In the inner `execute_agent()` function (line 48), add engine routing **after** the `effective_handle` computation (line 76 in current code). This is critical — `effective_handle` is computed at line 72-76 inside the existing PydanticAI block. The engine routing must come after it, not before, because CLI engines need `effective_handle.host_working_dir` for the working directory.

Insert the engine routing block between the `effective_handle` computation (line 76) and the existing `if effective_handle is not None: deps.environment_handle = ...` block (line 78):

```python
    # existing code: lines 71-76 compute effective_handle
    agent_tier = agent_config.invocation.tier
    effective_handle = (
        environment_handle
        if environment_handle is not None and agent_tier == "user"
        else None
    )

    # ── Engine routing (Plan 55) ────────────────────────────────
    # Placed AFTER effective_handle is computed (line 76) because CLI
    # engines need host_working_dir from the handle.
    engine = getattr(agent_config, "engine", "pydantic_ai")

    if engine != "pydantic_ai":
        from modules.backend.agents.mission_control.helpers.cli_executor import (
            execute_claude_code,
            execute_codex,
            execute_copilot,
        )
        from modules.backend.agents.mission_control.helpers.prompt_builder import (
            load_agent_system_prompt,
        )

        system_prompt = load_agent_system_prompt(agent_name)
        working_dir = None
        if effective_handle is not None:
            working_dir = getattr(effective_handle, "host_working_dir", None)

        engine_fn = {
            "claude_code": execute_claude_code,
            "codex": execute_codex,
            "copilot": execute_copilot,
        }[engine]

        result = await engine_fn(
            agent_name=agent_name,
            instructions=instructions,
            inputs=inputs,
            system_prompt=system_prompt,
            working_dir=working_dir,
            event_bus=event_bus,
            session_id=session_id,
            **({"effort": agent_config.effort} if engine == "claude_code" and agent_config.effort else {}),
            **({"scope_read": agent_config.scope.read} if engine == "claude_code" else {}),
            **({"scope_write": agent_config.scope.write} if engine == "claude_code" else {}),
        )

        # Cost extraction uses _meta structure (matching PydanticAI output)
        cumulative_cost_usd += result.get("_meta", {}).get("cost_usd", 0.0)
        return result

    # ── Existing PydanticAI path (unchanged, continues from line 78) ──
    if effective_handle is not None:
        deps.environment_handle = effective_handle
        # ... rest of existing code unchanged ...
```

**Step 3:** Update the call site in `mission_control.py` (line ~817 where `_make_agent_executor()` is called) to pass `current_user_id`. The session object is available at that point — extract `user_id` from it:

```python
executor = _make_agent_executor(
    event_bus,
    session_id=session_id,
    mission_id=mission_id,
    environment_handle=environment_handle,
    current_user_id=session.user_id if session else None,  # Plan 55
)
```

**Notes:**
- Engine routing is placed **after** line 76 (where `effective_handle` is computed) and **before** line 78 (where PydanticAI deps injection begins). This ensures `effective_handle` is in scope for CLI engines.
- `scope_write` is now passed to `execute_claude_code` so it can build the correct `allowed_tools` list (agents with write scope get Write/Edit/Bash tools)
- `current_user_id` is used in Phase B (§3.11) for token resolution — unused in Phase A MVP

#### 3.6 Install Dependencies

**Modified file:** `pyproject.toml`

Add to `[project.dependencies]`:

```toml
# CLI agent engines (Plan 55)
"claude-agent-sdk>=0.1.0",
# Token encryption for Phase B (not a transitive dependency — must be explicit)
"cryptography>=42.0.0",
```

Codex and Copilot are CLI-only — no Python packages needed. They must be installed on the system (`npm install -g @openai/codex`, `npm install -g @github/copilot-cli`).

**Note:** `claude-agent-sdk` requires the `claude` CLI binary to be installed on the system. `cryptography` is needed for Phase B AES-256-GCM token encryption (not currently in `pyproject.toml` — the plan previously claimed it was a transitive dependency, but it is not).

#### 3.7 Test Agent Config with Engine Field

Update an existing agent YAML to test:

```yaml
# config/agents/mission/director/agent.yaml (test only — revert after)
engine: claude_code
effort: high
```

**New file:** `tests/unit/backend/agents/test_cli_executor.py`

- Test `execute_claude_code` returns output dict with expected `_meta` keys
- Test `execute_codex` returns output dict with expected `_meta` keys
- Test `execute_copilot` returns output dict with expected `_meta` keys
- Test `_cli_result()` output passes through retry_handler cost extraction correctly
- Test engine routing in `execute_agent()` — mock the CLI executor, verify it's called when `engine: claude_code`
- Test that `engine: pydantic_ai` (default) still goes through PydanticAI path
- Test CLI agent with `interface: null` passes Tier 1 verification

**Acceptance:** Set `engine: claude_code` on an agent, run `mc run "describe the project structure"`, verify the response comes from Claude Code CLI (you'll see Claude Code's tool calls in the output, not PydanticAI's).

#### 3.7a Constraint: CLI Agents Must Not Have Strict Interface Output

Tier 1 verification (`verification_tiers.py:58-62`) checks that agent output contains all fields declared in `agent_config.interface.output`. CLI executors return `{"output": "...", "_meta": {...}}` — if an agent declares specific output fields (e.g., `interface.output.result: string`), verification will fail.

**Rule:** Any agent with `engine != pydantic_ai` must have `interface: null` or `interface.output: {}`. Add a validator to `AgentConfigSchema`:

```python
@model_validator(mode="after")
def _validate_cli_engine_interface(self) -> Self:
    """CLI engines cannot have strict interface.output requirements."""
    if self.engine != "pydantic_ai" and self.interface:
        output_fields = getattr(self.interface, "output", None)
        if output_fields:
            raise ValueError(
                f"Agent '{self.agent_name}' has engine='{self.engine}' but declares "
                f"interface.output fields. CLI engines return unstructured output — "
                f"remove interface.output or set engine to pydantic_ai."
            )
    return self
```

#### 3.7b Known Limitation: No Live Events During CLI Execution (MVP)

The PydanticAI path emits 7+ event types during execution (AgentThinkingEvent, AgentToolCallEvent, AgentResponseChunkEvent, CostUpdateEvent, etc.). CLI executors in this MVP emit **no events** — the TUI/SSE will show silence between PlanStepStartedEvent and PlanStepCompletedEvent.

The `event_bus` and `session_id` parameters are already threaded through for Phase 2 streaming. For Claude Code Agent SDK, the `query()` async generator yields messages that could be mapped to events. For Codex/Copilot CLI (subprocess stdout capture), events would require streaming output parsing.

**Not blocking for MVP.** Document in the agent YAML as a comment:

```yaml
# NOTE: CLI engines do not emit real-time events in MVP.
# TUI/SSE will show step start → silence → step complete.
engine: claude_code
```

---

### Phase B — Provider Credential Storage + Frontend OAuth

**Goal:** Users authorize CLI providers through the web frontend. Tokens stored encrypted in DB. Backend injects tokens when spawning CLI agents.

#### 3.8 Provider Credential Model

**New file:** `modules/backend/models/provider_credential.py`

```python
"""Provider credential storage for CLI agent engines.

Stores encrypted OAuth tokens per user per provider.
Tokens are refreshed automatically when possible.
"""

import enum

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ProviderName(str, enum.Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    COPILOT = "copilot"


class ProviderCredential(Base, UUIDMixin, TimestampMixin):
    """Encrypted OAuth token for a CLI agent provider."""

    __tablename__ = "provider_credentials"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        Enum(ProviderName), nullable=False,
    )
    # Encrypted token blob (access + refresh tokens as encrypted JSON)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    # Provider-specific metadata (e.g., scopes, expiry)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Status
    is_active: Mapped[bool] = mapped_column(default=True)

    # Unique constraint: one credential per user per provider
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider"),
    )
```

**Migration:** Add `provider_credentials` table with unique index on `(user_id, provider)`.

#### 3.9 Provider Credential Service

**New file:** `modules/backend/services/provider_credential.py`

```python
"""Service for managing provider OAuth credentials."""

class ProviderCredentialService(BaseService):
    """Encrypt, store, retrieve, and refresh provider OAuth tokens."""

    async def store_token(self, user_id: str, provider: str, token_data: dict) -> None:
        """Encrypt and store OAuth tokens for a provider."""
        ...

    async def get_token(self, user_id: str, provider: str) -> str | None:
        """Retrieve and decrypt the access token for a provider.
        Returns None if no credential exists or token is expired.
        """
        ...

    async def refresh_if_needed(self, user_id: str, provider: str) -> str | None:
        """Check expiry, refresh if needed, return valid token."""
        ...

    async def revoke(self, user_id: str, provider: str) -> None:
        """Delete stored credential."""
        ...

    async def list_connections(self, user_id: str) -> list[dict]:
        """List all provider connections with status (connected/expired/none)."""
        ...
```

Token encryption uses the existing `JWT_SECRET_KEY` from `.env` as the encryption key (AES-256-GCM via `cryptography` package, added explicitly in §3.6).

#### 3.10 OAuth Endpoints

**New file:** `modules/backend/api/v1/endpoints/provider_auth.py`

Three endpoints per provider pattern:

```python
# Initiate OAuth flow
@router.get("/auth/providers/{provider}/connect")
async def initiate_oauth(provider: str, user: CurrentUser):
    """Return the OAuth authorization URL (Claude Code, Codex) or
    device code + verification URI (Copilot).
    """
    ...

# Handle OAuth callback (Claude Code — authorization code flow)
@router.get("/auth/providers/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str):
    """Exchange authorization code for tokens, store encrypted."""
    ...

# List connections
@router.get("/auth/providers")
async def list_providers(user: CurrentUser):
    """Return connection status for all providers."""
    ...

# Disconnect
@router.delete("/auth/providers/{provider}")
async def disconnect_provider(provider: str, user: CurrentUser):
    """Revoke and delete stored credential."""
    ...
```

**Provider-specific OAuth flows:**

| Provider | Flow | Authorization Endpoint | Token Endpoint |
|----------|------|----------------------|----------------|
| `claude_code` | Authorization Code + PKCE | `console.anthropic.com/oauth/authorize` | `console.anthropic.com/v1/oauth/token` |
| `codex` | Device Code | `auth.openai.com/api/accounts/deviceauth/usercode` | `auth.openai.com/oauth/token` |
| `copilot` | Device Code | `github.com/login/device/code` | `github.com/login/oauth/access_token` |

#### 3.11 Inject Token in CLI Executor

**Modified file:** `modules/backend/agents/mission_control/helpers/cli_executor.py`

Update each `execute_*` function to accept and inject tokens:

```python
async def execute_claude_code(
    ...
    oauth_token: str | None = None,
) -> dict:
    import os
    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    # Pass env to ClaudeAgentOptions or subprocess
    ...
```

**Modified file:** `modules/backend/agents/mission_control/helpers/agent_executor.py`

In the engine routing block (§3.5), resolve the token before calling the executor:

```python
if engine != "pydantic_ai":
    # Resolve OAuth token for the current user
    oauth_token = None
    if current_user_id:
        from modules.backend.services.provider_credential import ProviderCredentialService
        async with ProviderCredentialService.factory() as cred_svc:
            oauth_token = await cred_svc.get_token(current_user_id, engine)

    result = await engine_fn(
        ...
        oauth_token=oauth_token,
    )
```

**Note:** `current_user_id` was already added to `_make_agent_executor()` in Phase A (§3.5). It's available in the executor closure for token resolution here.

#### 3.12 Frontend Connections Page

**New file:** `modules/frontend/src/pages/settings/connections.tsx`

A settings page with three provider cards:

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Claude Code     │  │  OpenAI Codex   │  │  GitHub Copilot │
│                  │  │                  │  │                  │
│  ● Connected     │  │  ○ Not connected │  │  ○ Not connected │
│                  │  │                  │  │                  │
│  [Disconnect]    │  │  [Connect]       │  │  [Connect]       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

- "Connect" for Claude Code → redirects to Anthropic OAuth page
- "Connect" for Codex/Copilot → shows device code + "Open verification page" link
- Status fetched from `GET /api/v1/auth/providers`

#### 3.13 Frontend Engine Dropdown on Agent Config

**Modified file:** Agent settings/detail component in frontend (wherever agent config is displayed).

Add a dropdown:

```typescript
<Select value={agent.engine} onChange={...}>
  <option value="pydantic_ai">PydanticAI (API Key)</option>
  <option value="claude_code">Claude Code (Subscription)</option>
  <option value="codex">OpenAI Codex (Subscription)</option>
  <option value="copilot">GitHub Copilot (Subscription)</option>
</Select>
```

The dropdown is disabled for providers that aren't connected (checked via `GET /api/v1/auth/providers`).

#### 3.14 Tests

- Test `ProviderCredentialService.store_token()` + `get_token()` roundtrip
- Test OAuth callback endpoint with mocked provider response
- Test token injection into CLI executor env
- Test frontend shows correct connection status

**Acceptance:** User clicks "Connect Claude Code" in the frontend, completes Anthropic OAuth, the token is stored. An agent with `engine: claude_code` executes using the stored token.

---

### Phase C — MCP Server for Custom Tools (Future)

**Goal:** CLI agents can call Mission Control's custom tools (get_mission_info, compliance scanner, etc.) via an MCP server.

#### 3.15 Mission Control MCP Server

**New file:** `modules/backend/mcp_server.py`

An MCP server that wraps existing service layer methods as tools:

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("get_mission_info", "Get mission details", {...})
async def get_mission_info(args: dict) -> dict:
    async with MissionService.factory() as svc:
        mission = await svc.get_mission(args["mission_id"])
        return {"content": [{"type": "text", "text": json.dumps(mission_to_dict(mission))}]}

@tool("scan_compliance", "Run compliance scan on a file", {...})
async def scan_compliance(args: dict) -> dict:
    # Wraps existing compliance.scan_* tools
    ...

server = create_sdk_mcp_server(
    name="mission-control",
    version="1.0",
    tools=[get_mission_info, scan_compliance, ...],
)
```

#### 3.16 Agent YAML MCP Config

Add an optional `mcp_tools` field to `AgentConfigSchema`:

```yaml
# config/agents/software/quality/agent.yaml
engine: claude_code
mcp_tools:
  - scan_compliance
  - get_mission_info
  - generate_code_map
```

The CLI executor passes the MCP server to `ClaudeAgentOptions.mcp_servers` with only the tools listed in `mcp_tools`.

#### 3.17 Tests

- Test MCP server tool invocation returns expected results
- Test agent with `mcp_tools` gets the MCP server attached
- Test agent without `mcp_tools` gets no MCP server

**Acceptance:** An agent with `engine: claude_code` and `mcp_tools: [scan_compliance]` can call the compliance scanner during execution.

---

## 4  Files Changed (Summary)

| Phase | File | Action |
|-------|------|--------|
| A | `modules/backend/agents/config_schema.py` | **Modify** — add `engine`, `effort` fields + validators |
| A | `modules/backend/agents/mission_control/helpers/cli_executor.py` | **New** — `execute_claude_code()`, `execute_codex()`, `execute_copilot()` |
| A | `modules/backend/agents/mission_control/helpers/prompt_builder.py` | **Modify** — add `load_agent_system_prompt()` |
| A | `modules/backend/agents/mission_control/helpers/agent_executor.py` | **Modify** — add engine routing before PydanticAI path |
| A | `pyproject.toml` | **Modify** — add `claude-agent-sdk` dependency |
| A | `tests/unit/backend/agents/test_cli_executor.py` | **New** — unit tests |
| B | `modules/backend/models/provider_credential.py` | **New** — `ProviderCredential` model |
| B | `modules/backend/services/provider_credential.py` | **New** — token CRUD + encryption |
| B | `modules/backend/api/v1/endpoints/provider_auth.py` | **New** — OAuth initiate/callback/list/disconnect |
| B | `modules/backend/migrations/versions/` | **New** — `provider_credentials` table |
| B | `modules/backend/agents/mission_control/helpers/cli_executor.py` | **Modify** — accept + inject `oauth_token` |
| B | `modules/backend/agents/mission_control/helpers/agent_executor.py` | **Modify** — resolve token from credential service |
| B | `modules/frontend/src/pages/settings/connections.tsx` | **New** — provider connection cards |
| B | `modules/frontend/src/components/` | **Modify** — engine dropdown on agent detail |
| C | `modules/backend/mcp_server.py` | **New** — MCP server wrapping service tools |
| C | `modules/backend/agents/config_schema.py` | **Modify** — add `mcp_tools` field |
| C | `modules/backend/agents/mission_control/helpers/cli_executor.py` | **Modify** — attach MCP server |

---

## 5  What Gets Deleted

Nothing. This is additive — existing PydanticAI agents are unchanged.

---

## 6  Provider-Specific Implementation Notes

### Claude Code

- **SDK:** `pip install claude-agent-sdk` — Python package, spawns CLI subprocess
- **API:** `query()` async generator for one-shot, `ClaudeSDKClient` for interactive
- **Auth env var:** `CLAUDE_CODE_OAUTH_TOKEN`
- **System prompt:** `ClaudeAgentOptions(system_prompt=...)`
- **Working dir:** `ClaudeAgentOptions(cwd=...)`
- **Tool control:** `ClaudeAgentOptions(allowed_tools=[...], disallowed_tools=[...])`
- **MCP tools:** `ClaudeAgentOptions(mcp_servers={...})`
- **Prerequisite:** `claude` CLI installed (`npm install -g @anthropic-ai/claude-code`)

### OpenAI Codex

- **CLI:** `codex exec "prompt"` — non-interactive mode, stdout capture
- **Auth:** `~/.codex/auth.json` (seeded from OAuth) or `OPENAI_API_KEY` env var
- **System prompt:** No direct flag — prepend to prompt or use `CODEX_INSTRUCTIONS` file
- **Working dir:** `--working-dir` flag or `cwd` on subprocess
- **Tool control:** `--approval-mode never` for fully autonomous
- **Prerequisite:** `codex` CLI installed (`npm install -g @openai/codex`)

### GitHub Copilot CLI

- **CLI:** `copilot -p "prompt" -s` — non-interactive, stripped output
- **Auth:** `GH_TOKEN` or `GITHUB_TOKEN` env var, or `~/.copilot/config.json`
- **Model:** `--model=MODEL` flag (e.g., `claude-sonnet-4.6`, `gpt-5.2`)
- **Working dir:** `--add-dir=DIR` flag or `cwd` on subprocess
- **Tool control:** `--allow-tool=TOOL` / `--deny-tool=TOOL`
- **Prerequisite:** `copilot` CLI installed (`npm install -g @github/copilot-cli`)

---

## 7  Exit Criteria

1. `AgentConfigSchema` accepts `engine: claude_code | codex | copilot | pydantic_ai` (default: `pydantic_ai`)
2. An agent with `engine: claude_code` dispatches via `claude-agent-sdk` and returns a result
3. An agent with `engine: codex` dispatches via `codex exec` and returns a result
4. An agent with `engine: copilot` dispatches via `copilot -p` and returns a result
5. Existing agents with no `engine` field (or `engine: pydantic_ai`) work exactly as before
6. (Phase B) Users can connect/disconnect providers via the web frontend
7. (Phase B) Stored OAuth tokens are encrypted at rest
8. (Phase B) Frontend shows engine dropdown on agent config, disabled for unconnected providers
9. (Phase C) CLI agents can invoke custom Mission Control tools via MCP server

---

## 8  Estimated Effort

| Phase | Scope | Effort |
|-------|-------|--------|
| A | Engine field + CLI executor + dispatch routing | ~4 hours |
| B | Provider credentials + OAuth endpoints + frontend | ~8 hours |
| C | MCP server for custom tools | ~4 hours |
| **Total** | | **~16 hours** |

---

## 9  Risks

| Risk | Mitigation |
|------|------------|
| Claude Agent SDK API changes (package is young) | Pin version in pyproject.toml. The `query()` async generator is the stable API — avoid internal APIs. |
| Codex/Copilot CLI not installed on server | Preflight check at startup: verify `which codex`, `which copilot`. Disable engine options if not found. |
| OAuth token expiry during long execution | `ProviderCredentialService.refresh_if_needed()` called before each dispatch. Claude Code and Codex auto-refresh internally. |
| Subscription rate limits | CLI tools enforce their own rate limits. No additional handling needed — errors surface as subprocess failures. |
| Cost tracking for subscription-based agents | Subscription agents return `cost_usd: 0.0` — they're included in the subscription. Document that plan cost tracking only covers API-key agents. |
| Security: OAuth tokens in memory during execution | Tokens are passed as env vars to subprocesses (same pattern as `ContainerBackend`). Not written to disk beyond encrypted DB storage. |

---

## 10  Quality Review Corrections (2026-04-13)

Three issues were found during code quality review and corrected in-place:

### 10.1 Return dict structure mismatch (fixed: §3.3)

**Problem:** The dispatch loop's `retry_handler.py` (lines 134-139) extracts costs from `output["_meta"]["cost_usd"]` and tokens from `output["_meta"]["input_tokens"]`. The original plan's CLI executors returned a flat dict `{"output": ..., "cost_usd": 0.0, "token_usage": {}}` — no `_meta` key. Cost aggregation in the dispatch loop would silently get zeros.

**Fix:** Added `_cli_result()` helper that normalizes all CLI executor output to match the PydanticAI agent return structure: `{"output": ..., "_meta": {"cost_usd": 0.0, "input_tokens": 0, ...}}`. All three executor functions (`execute_claude_code`, `execute_codex`, `execute_copilot`) call `_cli_result()` instead of building their own return dicts.

### 10.2 `current_user_id` not available in executor closure (fixed: §3.5)

**Problem:** The engine routing block needs `current_user_id` to resolve OAuth tokens from `ProviderCredentialService` (Phase B). But `_make_agent_executor()` (agent_executor.py:38) only takes `event_bus`, `session_id`, `mission_id`, `environment_handle` — no user ID.

**Fix:** Added `current_user_id: str | None = None` parameter to `_make_agent_executor()`. Updated the call site in `mission_control.py` to pass `session.user_id`. The parameter is unused in Phase A (MVP uses env var) but exists so Phase B doesn't require a signature change.

### 10.3 Missing `cryptography` dependency (fixed: §3.6)

**Problem:** The original plan stated "`cryptography` package, already a transitive dependency." It is not — `pyproject.toml` does not include it directly, and `python-jose[cryptography]` brings in a different subset.

**Fix:** Added `"cryptography>=42.0.0"` explicitly to `pyproject.toml` dependencies with a note that it's needed for Phase B token encryption.

---

## 11  Quality Review — Second Pass (2026-04-14)

Two additional findings from deeper audit. Both verified and addressed in-place.

### 11.1 Verification Tier 1 rejects CLI output with strict interface (fixed: §3.7a)

**Problem:** `verification_tiers.py:58-62` checks that agent output dict contains all fields declared in `agent_config.interface.output`. CLI executors return `{"output": "...", "_meta": {...}}`. An agent with `interface.output.result: string` would fail Tier 1 verification every time.

**Fix:** Added §3.7a — a Pydantic model validator on `AgentConfigSchema` that rejects `engine != pydantic_ai` combined with non-empty `interface.output`. Fail-fast at config load time, not at runtime.

### 11.2 No live events during CLI execution (documented: §3.7b)

**Problem:** PydanticAI path emits 7+ event types (AgentThinkingEvent, AgentToolCallEvent, AgentResponseChunkEvent, CostUpdateEvent, etc.). CLI executors emit nothing. TUI/SSE streams will show silence between step start and step complete.

**Status:** Documented as known MVP limitation in §3.7b. The `event_bus` and `session_id` params are already threaded through for Phase 2. Not blocking — Claude Code Agent SDK's `query()` async generator yields messages that can be mapped to events in a future phase.

### 11.3 Items verified clean (no action needed)

| Check | Result |
|-------|--------|
| Prompt path resolution matches actual files | All 12 agents verified ✓ |
| `registry.get()` returns `AgentConfigSchema` (supports `getattr`) | Verified ✓ |
| `_make_agent_executor` has exactly 1 call site | `mission_control.py:820` ✓ |
| `ExecuteAgentFn` protocol accepts plain `dict` return | Verified ✓ |
| Dispatch loop only reads `_meta` keys from agent output | Verified ✓ |
| `retry_handler` safely handles missing keys via `.get()` | Verified ✓ |
| Copilot CLI binary name is `copilot` | Verified ✓ |
| `extra="forbid"` on config schema allows new fields with defaults | Verified ✓ |

---

## 12  Adversarial Review Corrections (2026-04-14)

Eight findings from adversarial review. All fixed in-place.

### 12.1 `effort` parameter doesn't exist in Python Agent SDK (BLOCKING → fixed: §3.3)

**Problem:** `ClaudeAgentOptions` in the Python SDK [does not expose an `effort` parameter](https://github.com/anthropics/claude-code/issues/19425). The plan silently accepted the value and never applied it.

**Fix:** `effort` is now set via `CLAUDE_CODE_EFFORT_LEVEL` environment variable, which the CLI binary reads. The env var is set before calling `query()` and cleaned up in a `finally` block to prevent leaking to other agents.

### 12.2 Codex system_prompt silently dropped (SHOULD FIX → fixed: §3.3)

**Problem:** `execute_codex()` accepted `system_prompt` but never passed it to the `codex exec` command.

**Fix:** System prompt is now passed via `--config developer_instructions="..."`, which is the Codex-supported mechanism for custom instructions.

### 12.3 Copilot system_prompt silently dropped (SHOULD FIX → fixed: §3.3)

**Problem:** Same issue — `execute_copilot()` accepted `system_prompt` but Copilot CLI never received it.

**Fix:** Copilot CLI reads instructions from `AGENTS.md` in the working directory. The executor now writes the system prompt to a temporary `AGENTS.md` before spawning, backs up any existing file, and restores it in a `finally` block.

### 12.4 `scope_read` logic was a no-op (SHOULD FIX → fixed: §3.3)

**Problem:** `if scope_read: pass` — did nothing. Agents with write scope still got read-only tools.

**Fix:** Replaced with `scope_write` parameter. Agents with non-empty `scope.write` get `["Write", "Edit", "Bash"]` in addition to read tools. Updated §3.5 to pass `scope_write` from agent config.

### 12.5 No timeout on CLI subprocess execution (SHOULD FIX → fixed: §3.3)

**Problem:** `proc.communicate()` had no timeout. A hung CLI blocks the dispatch loop forever.

**Fix:** Extracted `_run_subprocess()` helper with `asyncio.wait_for(proc.communicate(), timeout=600)`. On timeout: kills the process, logs the error, returns an error message (doesn't raise — dispatch loop handles failure via TaskResult status).

### 12.6 `effective_handle` scoped inside PydanticAI block (SHOULD FIX → fixed: §3.5)

**Problem:** The plan inserted engine routing before `effective_handle` was computed (line 72-76 in current code). The variable was out of scope.

**Fix:** Engine routing block is now explicitly placed **after** line 76 (effective_handle computation) and **before** line 78 (PydanticAI deps injection). Code placement in §3.5 is annotated with exact line references.

### 12.7 `__table_args__` missing unique constraint (CONSIDER → fixed: §3.8)

**Problem:** `ProviderCredential` model had `__table_args__ = ({"schema": None},)` instead of the unique constraint the prose promised.

**Fix:** Replaced with `UniqueConstraint("user_id", "provider", name="uq_provider_credentials_user_provider")`.

### 12.8 Stale "transitive dependency" text (CONSIDER → fixed: §3.9)

**Problem:** §3.9 still said `cryptography` was "already a transitive dependency" despite §10.3 correcting this.

**Fix:** Updated to "added explicitly in §3.6".
