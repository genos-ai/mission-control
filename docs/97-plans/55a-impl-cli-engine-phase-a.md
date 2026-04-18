# Plan 55 Phase A — Implementation Guide (CLI Agent Engine MVP)

**Version:** 1.0.0
**Date:** 2026-04-18
**Parent plan:** 55-plan-cli-agent-engine-integration.md
**Scope:** Phase A only (sections 3.1–3.7b of parent plan)
**Status:** Ready to implement

---

## 0. What This Achieves

After this implementation, an agent YAML can declare `engine: claude_code` and the dispatch loop will route it to the Claude Agent SDK subprocess instead of PydanticAI in-process execution. Subscription-based CLI agents (Claude Code, Codex, Copilot) report `cost_usd: 0.0` — costs are covered by the user's subscription, not per-call API billing.

Auth for MVP: manual `CLAUDE_CODE_OAUTH_TOKEN` env var. No frontend changes. No OAuth flow. No DB changes.

---

## 1. Add `engine` and `effort` Fields to Agent Config Schema

**File:** `modules/backend/agents/config_schema.py`
**Action:** Edit

### Step 1.1 — Add fields after line 151

Insert after the `thinking_budget` field (line 151), before the first `@field_validator` (line 153):

```python
    # Execution engine — determines how the agent runs.
    # "pydantic_ai" (default): in-process PydanticAI agent.run_stream()
    # "claude_code": subprocess via claude-agent-sdk
    # "codex": subprocess via codex exec CLI
    # "copilot": subprocess via copilot -p CLI
    engine: str = "pydantic_ai"

    # Effort level for CLI engines that support it (claude_code).
    # Ignored for pydantic_ai engine.
    effort: str | None = None
```

### Step 1.2 — Add field validators

Insert after the existing `_normalize_model` field validator (after line 157), before `_validate_model_config`:

```python
    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, v: str) -> str:
        valid = {"pydantic_ai", "claude_code", "codex", "copilot"}
        if v not in valid:
            raise ValueError(f"engine must be one of {valid}, got '{v}'")
        return v

    @field_validator("effort")
    @classmethod
    def _validate_effort(cls, v: str | None) -> str | None:
        if v is not None and v not in {"low", "medium", "high"}:
            raise ValueError(f"effort must be low/medium/high, got '{v}'")
        return v
```

### Step 1.3 — Add model validator for CLI engine + interface constraint

Insert after the existing `_validate_invocation_tier` model validator (after line 220):

```python
    @model_validator(mode="after")
    def _validate_cli_engine_interface(self) -> "AgentConfigSchema":
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

### Verification

```bash
python -c "
from modules.backend.agents.config_schema import AgentConfigSchema
# Default engine works
cfg = AgentConfigSchema(agent_name='test', agent_type='test', description='test', enabled=True, model='anthropic:claude-sonnet-4-6', max_input_length=4000, max_budget_usd=1.0, execution={'mode': 'standard'})
assert cfg.engine == 'pydantic_ai'
assert cfg.effort is None
print('Schema OK')
"
```

---

## 2. Create CLI Agent Executor Module

**File:** `modules/backend/agents/mission_control/helpers/cli_executor.py`
**Action:** Create new file

Copy the `cli_executor.py` code **exactly** from the parent plan §3.3 (lines 119–389). The code has been through 2 quality reviews and an adversarial review — do not modify it.

The file contains:
- `_cli_result(output: str) -> dict` — normalizes CLI output to match PydanticAI `_meta` structure
- `_compose_user_message(instructions, inputs) -> str` — builds user message
- `_run_subprocess(cmd, cwd, env, timeout, agent_name, engine_label) -> str` — runs CLI with timeout
- `execute_claude_code(...)` — dispatches via `claude-agent-sdk` `query()` async generator
- `execute_codex(...)` — dispatches via `codex exec` subprocess
- `execute_copilot(...)` — dispatches via `copilot -p` subprocess with AGENTS.md injection

**Critical details already handled in the plan's reviewed code:**
- `_cli_result()` returns `{"output": ..., "_meta": {"cost_usd": 0.0, ...}}` matching PydanticAI structure
- `execute_claude_code` sets effort via `CLAUDE_CODE_EFFORT_LEVEL` env var (SDK lacks the parameter) and cleans up in `finally`
- `execute_codex` passes system prompt via `--config developer_instructions=...`
- `execute_copilot` writes system prompt to temporary `AGENTS.md`, backs up existing, restores in `finally`
- `_run_subprocess` has 600s timeout with process kill on timeout
- `allowed_tools` is scope-aware: read-only agents get `["Read", "Grep", "Glob"]`, write agents additionally get `["Write", "Edit", "Bash"]`

---

## 3. Add System Prompt Loader for CLI Engines

**File:** `modules/backend/agents/mission_control/helpers/prompt_builder.py`
**Action:** Edit — append function at end of file

```python
def load_agent_system_prompt(agent_name: str) -> str:
    """Load the system prompt markdown for a CLI agent.

    Reads config/prompts/agents/{domain}/{name}/system.md.
    Returns the raw markdown content (no template substitution).

    Path resolution: agent_name "mission.director.agent" →
    config/prompts/agents/mission/director/system.md
    """
    from modules.backend.core.config import find_project_root

    # "mission.director.agent" → ["mission", "director"]
    parts = agent_name.rsplit(".", 1)[0].split(".")
    prompt_path = find_project_root() / "config" / "prompts" / "agents"
    for part in parts:
        prompt_path = prompt_path / part
    prompt_path = prompt_path / "system.md"

    if not prompt_path.is_file():
        return ""

    return prompt_path.read_text(encoding="utf-8")
```

**Verification:** The path resolution matches the actual file structure:
- `mission.director.agent` → `config/prompts/agents/mission/director/system.md` (exists)
- `software.quality.agent` → `config/prompts/agents/software/quality/system.md` (exists)
- `system.planning.agent` → `config/prompts/agents/system/planning/system.md` (exists)

---

## 4. Update `__init__.py` Re-exports

**File:** `modules/backend/agents/mission_control/helpers/__init__.py`
**Action:** Edit

Add to the `prompt_builder` import block (currently at lines 17-22):

```python
from modules.backend.agents.mission_control.helpers.prompt_builder import (
    _append_validation_feedback,
    _build_planning_prompt,
    _build_roster_prompt,
    assemble_instructions,
    load_agent_system_prompt,  # ← ADD THIS
)
```

No re-export needed for `cli_executor` — it's imported directly inside `agent_executor.py` via deferred import (to avoid importing `claude_agent_sdk` at module load time).

---

## 5. Add Engine Routing to Agent Executor

**File:** `modules/backend/agents/mission_control/helpers/agent_executor.py`
**Action:** Edit

### Step 5.1 — Update `_make_agent_executor` signature (line 38)

Add `current_user_id` parameter:

```python
def _make_agent_executor(
    event_bus: EventBusProtocol,
    *,
    session_id: str,
    mission_id: str,
    environment_handle: object | None = None,
    current_user_id: str | None = None,       # Plan 55
) -> ExecuteAgentFn:
```

### Step 5.2 — Insert engine routing block

**Location:** After line 76 (where `effective_handle` is computed), BEFORE line 78 (where PydanticAI deps are injected with `if effective_handle is not None: deps.environment_handle = ...`).

Insert this block between the `effective_handle` computation and the existing PydanticAI code:

```python
        # ── Engine routing (Plan 55) ────────────────────────────────
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

            engine_kwargs: dict = {
                "agent_name": agent_name,
                "instructions": instructions,
                "inputs": inputs,
                "system_prompt": system_prompt,
                "working_dir": working_dir,
                "event_bus": event_bus,
                "session_id": session_id,
            }
            if engine == "claude_code":
                if getattr(agent_config, "effort", None):
                    engine_kwargs["effort"] = agent_config.effort
                engine_kwargs["scope_read"] = agent_config.scope.read
                engine_kwargs["scope_write"] = agent_config.scope.write

            result = await engine_fn(**engine_kwargs)

            nonlocal cumulative_cost_usd
            cumulative_cost_usd += result.get("_meta", {}).get("cost_usd", 0.0)
            return result

        # ── Existing PydanticAI path (unchanged) ──────────────────
```

**Important:** The `nonlocal cumulative_cost_usd` is needed because `cumulative_cost_usd` is defined in the enclosing `_make_agent_executor` scope. Check line ~46 for the existing `cumulative_cost_usd = 0.0` declaration — if it exists, `nonlocal` is correct. If `cumulative_cost_usd` is defined inside `execute_agent`, just use it directly without `nonlocal`.

### Step 5.3 — Verify indentation

The engine routing block goes inside the `execute_agent` inner function (which is inside `_make_agent_executor`). The indentation level is 8 spaces (two levels deep).

---

## 6. Update Call Site in Mission Dispatch

**File:** `modules/backend/agents/mission_control/mission_dispatch.py`
**Action:** Edit

Update lines 298-303 to pass `current_user_id`:

```python
        execute_agent_fn=_make_agent_executor(
            event_bus,
            session_id=session_id or mission_run_id,
            mission_id=mission_run_id,
            environment_handle=env_handle,
        ),
```

→

```python
        execute_agent_fn=_make_agent_executor(
            event_bus,
            session_id=session_id or mission_run_id,
            mission_id=mission_run_id,
            environment_handle=env_handle,
            current_user_id=None,  # Plan 55: resolved in Phase B
        ),
```

**Note:** `current_user_id=None` for Phase A MVP. Phase B will thread the user ID through from the session.

Also check if `_make_agent_executor` is called anywhere else (there may be a second call site in `mission_control.py`). Update all call sites.

---

## 7. Add Dependency

**File:** `pyproject.toml`
**Action:** Edit

Add to `[project.dependencies]` (after `pydantic-ai`, around line 41):

```toml
"claude-agent-sdk>=0.1.0",
```

Then run:
```bash
pip install -e .
```

If `claude-agent-sdk` is not yet published or installable, wrap the import in `cli_executor.py`'s `execute_claude_code` with a try/except that raises a clear error:

```python
try:
    from claude_agent_sdk import ClaudeAgentOptions, query, AssistantMessage, TextBlock
except ImportError:
    raise ImportError(
        "claude-agent-sdk is required for engine='claude_code'. "
        "Install with: pip install claude-agent-sdk"
    )
```

---

## 8. Verification Steps

Run these in order after implementation:

### 8.1 Schema validation
```bash
python -c "
from modules.backend.agents.config_schema import AgentConfigSchema
# Test default engine
cfg = AgentConfigSchema(agent_name='t', agent_type='t', description='t', enabled=True, model='anthropic:claude-sonnet-4-6', max_input_length=4000, max_budget_usd=1.0, execution={'mode': 'standard'})
assert cfg.engine == 'pydantic_ai'

# Test claude_code engine
cfg2 = AgentConfigSchema(agent_name='t', agent_type='t', description='t', enabled=True, model='anthropic:claude-sonnet-4-6', max_input_length=4000, max_budget_usd=1.0, execution={'mode': 'standard'}, engine='claude_code', effort='high')
assert cfg2.engine == 'claude_code'
assert cfg2.effort == 'high'
print('Schema OK')
"
```

### 8.2 Existing agents still load
```bash
python -c "
from modules.backend.agents.mission_control.registry import get_registry
r = get_registry()
agents = r.list_all()
print(f'{len(agents)} agents loaded')
for a in agents:
    print(f'  {a[\"agent_name\"]}: engine={getattr(r.get(a[\"agent_name\"]), \"engine\", \"pydantic_ai\")}')
"
```

### 8.3 Prompt loader works
```bash
python -c "
from modules.backend.agents.mission_control.helpers.prompt_builder import load_agent_system_prompt
prompt = load_agent_system_prompt('mission.director.agent')
print(f'Director prompt: {len(prompt)} chars')
assert len(prompt) > 100
prompt2 = load_agent_system_prompt('nonexistent.agent')
assert prompt2 == ''
print('Prompt loader OK')
"
```

### 8.4 CLI executor module imports
```bash
python -c "
from modules.backend.agents.mission_control.helpers.cli_executor import (
    execute_claude_code, execute_codex, execute_copilot, _cli_result
)
r = _cli_result('test output')
assert r['output'] == 'test output'
assert r['_meta']['cost_usd'] == 0.0
print('CLI executor OK')
"
```

### 8.5 Import chain
```bash
python -c "
from modules.backend.agents.mission_control.helpers.agent_executor import _make_agent_executor
print('Agent executor imports OK')
"
```

### 8.6 API server starts
```bash
python -c "from modules.backend.main import app; print('API server OK')"
```

### 8.7 Layer violations
```bash
python scripts/check_layer_violations.py
```

### 8.8 Existing tests pass
```bash
python -m pytest tests/unit/backend/mission_control/ -x -q --tb=short
```

---

## 9. Files Summary

| # | File | Action | Lines Changed |
|---|------|--------|---------------|
| 1 | `modules/backend/agents/config_schema.py` | Edit | +30 (fields + validators) |
| 2 | `modules/backend/agents/mission_control/helpers/cli_executor.py` | Create | ~270 (from plan §3.3) |
| 3 | `modules/backend/agents/mission_control/helpers/prompt_builder.py` | Edit | +20 (append function) |
| 4 | `modules/backend/agents/mission_control/helpers/__init__.py` | Edit | +1 (re-export) |
| 5 | `modules/backend/agents/mission_control/helpers/agent_executor.py` | Edit | +35 (engine routing) |
| 6 | `modules/backend/agents/mission_control/mission_dispatch.py` | Edit | +1 (current_user_id param) |
| 7 | `pyproject.toml` | Edit | +1 (dependency) |

---

## 10. What NOT to Do

- Do NOT modify any agent YAML files (no `engine:` field needed for MVP — default is `pydantic_ai`)
- Do NOT create any frontend files
- Do NOT create OAuth endpoints or credential storage
- Do NOT create database migrations
- Do NOT change the `ExecuteAgentFn` protocol signature — CLI engines return the same `dict` type
- Do NOT add live event emission during CLI execution (documented MVP limitation §3.7b)

---

## 11. Exit Criteria (Phase A)

1. `AgentConfigSchema` accepts `engine: claude_code | codex | copilot | pydantic_ai` with default `pydantic_ai`
2. `AgentConfigSchema` accepts `effort: low | medium | high | null` with default `null`
3. CLI agents with `engine != pydantic_ai` and non-empty `interface.output` are rejected at config load
4. Existing agents (no `engine` field) work exactly as before — all 12 load, all tests pass
5. `execute_claude_code`, `execute_codex`, `execute_copilot` exist and return `{"output": ..., "_meta": {...}}`
6. Engine routing in `agent_executor.py` dispatches to the correct executor function
7. API server starts without errors
