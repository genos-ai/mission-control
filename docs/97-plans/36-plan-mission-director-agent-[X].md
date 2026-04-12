# Plan 36 — Mission Director Agent

| Field | Value |
|-------|-------|
| **Status** | ✅ Done (2026-04-12) — agent at `mission.director.agent` with 9 tools, config, prompts, and mc chat integration |
| **Created** | 2026-03-27 |
| **Depends on** | Plan 28 (platform), Plan 35 (mc.py CLI) |
| **Target** | New agent: `horizontal.mission_director.agent` |
| **Model** | Opus 4.6 (conversational, tool-using) |
| **Default for** | `mc chat` |

---

## 1. Context

The `mc chat` command currently defaults to `horizontal.planning.agent`, which only creates TaskPlans and cannot execute, answer questions, or interact conversationally. Users need a smart conversational agent that:

- Knows the mission (brief, team, history, capabilities)
- Can trigger runs via the code dispatch infrastructure
- Can resolve approval gates on behalf of the user
- Can answer questions about mission state and history

**Core principle preserved:** The code dispatch loop (`handle_mission` / `dispatch`) remains the coordinator. The Mission Director is a **tool-using interface** that delegates to existing code infrastructure — it does not orchestrate agents itself.

### 1.1 Architecture Position

```
Human (authority)
  └── Mission Director (conversational delegate, Opus 4.6)
        ├── Tools → MissionService (query state)
        ├── Tools → ExecutionService (trigger runs)
        ├── Tools → MissionTeamService (query team)
        ├── Tools → HistoryQueryService (query history)
        ├── Tools → GateReviewer (resolve gates)
        └── Conversational (multi-turn, session-aware)

Code dispatch loop (handle_mission → dispatch)
  ├── Planning agent (creates TaskPlans)
  ├── Dispatch (executes plan layers)
  │     └── Specialist agents (do the work)
  ├── Verification agent (evaluates quality)
  └── Gate system (approval checkpoints)
```

### 1.2 References

- `modules/backend/agents/horizontal/workflow_architect/agent.py` — conversational agent with tools (pattern to follow)
- `modules/backend/agents/mission_control/gate.py` — GateReviewer protocol
- `modules/backend/services/mission.py` — MissionService
- `modules/backend/services/execution.py` — ExecutionService
- `modules/backend/services/mission_team.py` — MissionTeamService
- `modules/backend/services/history_query.py` — HistoryQueryService
- `config/agents/mission_control.yaml` — `chat_agent` config field

---

## 2. Agent Design

### 2.1 Identity

```yaml
agent_name: horizontal.mission_director.agent
agent_type: horizontal
version: "1.0.0"
description: >-
  Conversational mission delegate. Answers questions about the mission,
  triggers runs, queries history, and resolves approval gates on behalf
  of the user.
model:
  name: "anthropic:claude-opus-4-20250514"
  temperature: 0.0
  max_tokens: 16384
enabled: true
max_input_length: 64000
max_budget_usd: 5.00
```

### 2.2 Tools

The Mission Director has **read tools** (query state) and **action tools** (trigger changes). All tools delegate to existing backend services — no business logic in the agent.

#### Read Tools

| Tool | Service | Purpose |
|------|---------|---------|
| `get_mission_info` | `MissionService.get_mission()` | Current mission name, description, brief, gate mode, budget |
| `list_team` | `MissionTeamService.list_team()` + `AgentCatalogRepository` | Team members with capabilities, tools, scope |
| `get_execution_history` | `ExecutionService.list_executions()` | Recent runs with status, cost, objective |
| `get_execution_detail` | `ExecutionService.get_execution()` | Full detail of a specific execution |
| `get_mission_context` | `MissionContextManager.get_context()` | The Mission Context Document (MCD) |
| `list_workflows` | `WorkflowService.list_workflows()` | Available workflows for this mission |
| `get_pending_gates` | Query pending gate decisions | Gates waiting for approval |

#### Action Tools

| Tool | Service | Purpose |
|------|---------|---------|
| `run_objective` | `ExecutionService.create_adhoc_execution()` + `run_execution()` | Trigger an ad-hoc run (blocks until dispatch completes) |
| `run_workflow` | `MissionService.get_mission()` → `WorkflowRunService.run_workflow(mission_name=...)` | Trigger a named workflow (resolves mission_id → name first) |

#### Phase 2 Tools (deferred — requires async gate queue)

Gates currently resolve **inline during dispatch** via `GateReviewer.review()`. There is no pending gate queue or async resolution mechanism. These tools require a new gate storage layer before they can be implemented.

| Tool | Blocker | Purpose |
|------|---------|---------|
| `get_pending_gates` | No gate queue exists | List gates waiting for a decision |
| `approve_gate` | No async gate resolution | Approve a pending gate |
| `reject_gate` | No async gate resolution | Reject a pending gate |

### 2.3 Dependencies Dataclass

```python
@dataclass
class MissionDirectorDeps(BaseAgentDeps):
    """Dependencies injected into the Mission Director at runtime."""
    mission_id: str = ""
    db_session: Any = None  # AsyncSession for service access
```

### 2.4 System Prompt (Summary)

The system prompt should establish:

1. **Role:** You are the Mission Director for Mission Control. You are the user's delegate — you manage the mission on their behalf.
2. **Capabilities:** You have tools to query mission state (team, history, context, workflows) and trigger actions (run objectives, run workflows, approve/reject gates).
3. **Constraints:** You delegate execution to the dispatch infrastructure. You do NOT orchestrate agents directly. You do NOT create TaskPlans — that is the planning agent's job, invoked automatically when you trigger a run.
4. **Behavior:** Be concise and action-oriented. When the user asks you to do something, use tools. When they ask questions, query state and answer from data. Always confirm before triggering costly actions (runs).
5. **Context awareness:** You receive mission context (name, brief, team, capabilities) in your first message. Use this to ground your responses.

---

## 3. Implementation Phases

### Phase 1: Agent Configuration

**Files to create:**

#### 3.1.1 Agent YAML Config

**File:** `config/agents/horizontal/mission_director/agent.yaml`

```yaml
agent_name: horizontal.mission_director.agent
agent_type: horizontal
version: "1.0.0"
description: >-
  Conversational mission delegate. Answers questions about the mission,
  triggers runs, queries history, and resolves approval gates on behalf
  of the user.

model:
  name: "anthropic:claude-opus-4-20250514"
  temperature: 0.0
  max_tokens: 16384

enabled: true
max_input_length: 64000
max_budget_usd: 5.00

execution:
  mode: local

keywords:
  - mission
  - status
  - run
  - execute
  - approve
  - gate
  - team
  - history

tools:
  - get_mission_info
  - list_team
  - get_execution_history
  - get_execution_detail
  - get_mission_context
  - list_workflows
  - get_pending_gates
  - run_objective
  - run_workflow
  - approve_gate
  - reject_gate

scope:
  read:
    - "config/"
    - "modules/"
    - "var/logs/"
  write: []

interface:
  input:
    message: "string"
  output:
    response: "string"
```

#### 3.1.2 System Prompt

**File:** `config/prompts/agents/horizontal/mission_director/system.md`

Write a system prompt that covers:

- Role definition: "You are the Mission Director..."
- Available tools and when to use each
- Behavioral guidelines: concise, action-oriented, confirm before costly actions
- What you do NOT do: orchestrate directly, create plans, bypass the dispatch loop
- How to handle common requests:
  - "run X" → use `run_objective` or `run_workflow`
  - "what's our status?" → use `get_mission_info` + `get_execution_history`
  - "who's on the team?" → use `list_team`
  - "approve that" → use `approve_gate`
  - "what happened?" → use `get_execution_history` or `get_execution_detail`

**Prompt layering:** The system prompt is assembled via `assemble_instructions("horizontal", "mission_director")` which layers:
1. Organization prompts (`config/prompts/organization/*.md`)
2. Category prompt (`config/prompts/categories/horizontal.md`)
3. Agent prompt (`config/prompts/agents/horizontal/mission_director/system.md`)
4. Mission brief (injected at runtime)
5. User prompt (per-mission customization, if set on team member)

---

### Phase 2: Agent Implementation

**File:** `modules/backend/agents/horizontal/mission_director/agent.py`

#### 3.2.1 Module Structure

```
modules/backend/agents/horizontal/mission_director/
├── __init__.py          # Empty or minimal
├── agent.py             # create_agent(), tool definitions
└── deps.py              # MissionDirectorDeps dataclass
```

#### 3.2.2 Deps Dataclass

**File:** `modules/backend/agents/horizontal/mission_director/deps.py`

```python
from dataclasses import dataclass
from typing import Any

from modules.backend.agents.deps.base import BaseAgentDeps


@dataclass
class MissionDirectorDeps(BaseAgentDeps):
    """Dependencies for the Mission Director agent."""
    mission_id: str = ""
    db_session: Any = None  # AsyncSession — required for service access
```

#### 3.2.3 Agent Factory and Tools

**File:** `modules/backend/agents/horizontal/mission_director/agent.py`

Follow the workflow architect pattern:

```python
from pydantic_ai import Agent
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from .deps import MissionDirectorDeps


def create_agent(model: str | Model) -> Agent:
    """Create the Mission Director agent with all tools registered."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("horizontal", "mission_director")

    agent = Agent(
        model,
        system_prompt=system_prompt,
        deps_type=MissionDirectorDeps,
    )

    # ── Read Tools ────────────────────────────────────────

    @agent.tool
    async def get_mission_info(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get current mission details: name, description, brief, gate mode, budget."""
        # Use MissionService to load mission
        # Return JSON string with mission fields
        ...

    @agent.tool
    async def list_team(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List all agents on the mission team with their capabilities, tools, and access scope."""
        # Use MissionTeamService + AgentCatalogRepository
        # Return JSON array of team members
        ...

    @agent.tool
    async def get_execution_history(
        ctx: RunContext[MissionDirectorDeps],
        limit: int = 10,
    ) -> str:
        """Get recent execution history: status, cost, objective, timestamps."""
        # Use ExecutionService.list_executions(mission_id=...)
        # Return JSON array
        ...

    @agent.tool
    async def get_execution_detail(
        ctx: RunContext[MissionDirectorDeps],
        execution_id: str,
    ) -> str:
        """Get full detail for a specific execution including task results."""
        # Use ExecutionService.get_execution()
        # Return JSON
        ...

    @agent.tool
    async def get_mission_context(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get the Mission Context Document (MCD) — strategic context for the mission."""
        # Use MissionContextManager.get_context()
        # Return formatted text or JSON
        ...

    @agent.tool
    async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List available workflows that can be run against this mission."""
        # Use WorkflowService.list_workflows()
        # Return JSON array
        ...

    @agent.tool
    async def get_pending_gates(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List approval gates waiting for a decision."""
        # Query pending gate decisions for this mission
        # Return JSON array or "No pending gates"
        ...

    # ── Action Tools ──────────────────────────────────────

    @agent.tool
    async def run_objective(
        ctx: RunContext[MissionDirectorDeps],
        objective: str,
        budget_usd: float = 5.0,
    ) -> str:
        """Trigger an ad-hoc execution with the given objective.

        This creates an execution and runs it through the dispatch loop
        (planning → task assignment → agent execution → verification).

        Args:
            objective: What to accomplish (e.g., "run a health check")
            budget_usd: Maximum cost ceiling for this run
        """
        # Use ExecutionService.create_adhoc_execution() + run_execution()
        # Return outcome summary as JSON
        ...

    @agent.tool
    async def run_workflow(
        ctx: RunContext[MissionDirectorDeps],
        workflow_name: str,
    ) -> str:
        """Trigger a named workflow against the current mission.

        Args:
            workflow_name: The workflow identifier (e.g., "system.platform-audit.workflow")
        """
        # IMPORTANT: WorkflowRunService.run_workflow takes mission_name, not mission_id.
        # Resolve mission_id → mission.name via MissionService.get_mission() first.
        # Then call WorkflowRunService.run_workflow(mission_name=mission.name, ...)
        # Return run summary as JSON
        ...

    # NOTE: Gate tools (approve_gate, reject_gate, get_pending_gates) are
    # deferred to Phase 2. Gates currently resolve inline during dispatch —
    # no async queue exists for out-of-band resolution.
        ...

    return agent
```

**Implementation notes for tools:**

- All tools must create their own service instances using the `factory()` pattern or use `ctx.deps.db_session`
- Tools return `str` (JSON serialized) — same pattern as workflow architect
- Error handling: catch exceptions, return error JSON `{"error": "message"}` rather than raising
- `run_objective` and `run_workflow` are long-running — they should return the outcome, not stream events (the agent receives the result after dispatch completes)

---

### Phase 3: Wire into Registry and Chat

#### 3.3.1 Update `_build_agent_deps` in helpers.py

**File:** `modules/backend/agents/mission_control/helpers.py`

Add a case for the mission director in `_build_agent_deps()`:

```python
def _build_agent_deps(agent_name, agent_config, session_id=None):
    common = build_deps_from_config(agent_config)
    common["session_id"] = session_id

    # ... existing cases ...

    if "mission_director" in agent_name:
        from modules.backend.agents.horizontal.mission_director.deps import MissionDirectorDeps
        return MissionDirectorDeps(**common)

    return BaseAgentDeps(**common)
```

**Problem:** `_build_agent_deps` currently doesn't receive `mission_id` or `db_session`. The Mission Director needs both for its tools.

**Fix:** Add `mission_id` and `db_session` parameters to `_build_agent_deps`:

```python
def _build_agent_deps(
    agent_name, agent_config, session_id=None,
    mission_id=None, db_session=None,
):
    common = build_deps_from_config(agent_config)
    common["session_id"] = session_id

    if "mission_director" in agent_name:
        from modules.backend.agents.horizontal.mission_director.deps import MissionDirectorDeps
        return MissionDirectorDeps(**common, mission_id=mission_id or "", db_session=db_session)

    # ... rest unchanged ...
```

Update the call site in `handle()` (mission_control.py) to pass `mission_id`:

```python
deps = _build_agent_deps(agent_name, agent_config, session_id, mission_id=mission_id)
```

#### 3.3.2 Update `chat_agent` Config

**File:** `config/agents/mission_control.yaml`

Change the default chat agent:

```yaml
routing:
  chat_agent: horizontal.mission_director.agent  # was: horizontal.planning.agent
```

#### 3.3.3 Update `mc_chat.py` Display

**File:** `modules/clients/cli/mc_chat.py`

The agent label in the chat header will automatically show "mission_director" via the existing `agent_label` logic:

```python
agent_label = target_agent.split(".")[-2] if "." in target_agent else target_agent
# "horizontal.mission_director.agent" → "mission_director"
```

#### 3.3.4 Pass `db_session` to `handle()` for tool access

**File:** `modules/backend/agents/mission_control/mission_control.py`

The Mission Director's tools need a DB session. Currently `handle()` uses `session_service` which has a session, but the deps builder needs a raw `AsyncSession`.

**Option A (preferred):** Pass `db_session` from the caller. `mc_chat.py` already has `get_async_session()`:

```python
# In mc_chat.py, inside the event loop:
async with get_async_session() as db:
    session_svc = SessionService(db)
    async for event in handle(
        session_id=session_id,
        message=user_input,
        mission_id=mission_id,
        session_service=session_svc,
        channel="mc",
        db_session=db,  # NEW: pass through for tool deps
    ):
```

Add `db_session` parameter to `handle()`:

```python
async def handle(
    session_id: str,
    message: str,
    *,
    mission_id: str,
    session_service: SessionServiceProtocol,
    db_session: Any = None,  # NEW
    ...
):
```

Pass it to `_build_agent_deps`:

```python
deps = _build_agent_deps(
    agent_name, agent_config, session_id,
    mission_id=mission_id, db_session=db_session,
)
```

---

### Phase 4: Seed Catalog Entry

The catalog seeder (`catalog_seeder.py`) auto-discovers agents from `config/agents/**/agent.yaml`. No code changes needed — just run:

```bash
python admin.py admin seed-catalog --force
```

This will upsert the new agent entry (preserving existing team members).

After seeding, add the Mission Director to the active mission's team:

```bash
python mc.py team add horizontal.mission_director.agent
```

---

### Phase 5: Tests

#### 3.5.1 Unit Tests

**File:** `tests/unit/backend/agents/test_mission_director.py`

Test the agent factory and tool registration:

```python
class TestMissionDirectorAgent:
    def test_create_agent_returns_agent(self):
        """create_agent should return a PydanticAI Agent."""
        agent = create_agent(TestModel())
        assert isinstance(agent, Agent)

    def test_agent_has_expected_tools(self):
        """Agent should have all read and action tools registered."""
        agent = create_agent(TestModel())
        tool_names = {t.name for t in agent._tools}
        assert "get_mission_info" in tool_names
        assert "list_team" in tool_names
        assert "run_objective" in tool_names
        # Gate tools deferred to Phase 2
```

#### 3.5.2 Integration Consideration

The `run_objective` tool triggers `handle_mission()` which is a full dispatch cycle. Integration tests should mock the dispatch adapter rather than running real agent calls.

#### 3.5.3 Blocking Behavior Note

`run_objective` and `run_workflow` block until dispatch completes (can be 2-5 minutes). This matches `mc run` CLI behavior. Phase 2 enhancement: fire-and-forget with `get_execution_detail` for polling.

---

## 4. Files Summary

| Category | File | Action | Est. Lines |
|----------|------|--------|-----------|
| Config | `config/agents/horizontal/mission_director/agent.yaml` | New | ~40 |
| Prompt | `config/prompts/agents/horizontal/mission_director/system.md` | New | ~80 |
| Agent | `modules/backend/agents/horizontal/mission_director/__init__.py` | New | ~3 |
| Agent | `modules/backend/agents/horizontal/mission_director/deps.py` | New | ~15 |
| Agent | `modules/backend/agents/horizontal/mission_director/agent.py` | New | ~250 |
| Backend | `modules/backend/agents/mission_control/helpers.py` | Modify | ~10 |
| Backend | `modules/backend/agents/mission_control/mission_control.py` | Modify | ~5 |
| CLI | `modules/clients/cli/mc_chat.py` | Modify | ~3 |
| Config | `config/agents/mission_control.yaml` | Modify | ~1 |
| Tests | `tests/unit/backend/agents/test_mission_director.py` | New | ~60 |

**Total estimated new code:** ~470 lines

---

## 5. Success Criteria

- [ ] `mc chat` defaults to Mission Director (not planning agent)
- [ ] User can ask "what's our mission?" and get an answer from mission data
- [ ] User can ask "who's on the team?" and see agent capabilities
- [ ] User can say "run a health check" and the director triggers dispatch
- [ ] User can ask "what happened in the last run?" and get execution history
- [ ] User can ask "list workflows" and see available workflows
- [ ] User can say "run the platform audit workflow" and it executes
- [ ] Director confirms before triggering costly actions
- [ ] All tools return structured JSON, errors return `{"error": "message"}`
- [ ] Agent is auto-discovered by catalog seeder
- [ ] `mc chat -a system.health.agent` still works (direct agent override)
- [ ] Unit tests pass for agent factory and tool registration

---

## 6. Anti-Patterns

- **DO NOT** put orchestration logic in the agent — it delegates to `ExecutionService` and `handle_mission()`
- **DO NOT** make tools that call other agents directly — use the dispatch infrastructure
- **DO NOT** hardcode mission IDs or session IDs — always use `ctx.deps`
- **DO NOT** create new services — use existing `MissionService`, `ExecutionService`, `MissionTeamService`, etc.
- **DO NOT** make `run_objective` stream events — it returns the outcome after dispatch completes
- **DO NOT** add the Mission Director to the planning roster — it is a user-facing agent, not a dispatch-time agent

---

## 7. Implementation Order

1. Create deps dataclass (`deps.py`)
2. Create agent YAML config (`agent.yaml`)
3. Write system prompt (`system.md`)
4. Implement agent factory + read tools (`agent.py`)
5. Implement action tools (`run_objective`, `run_workflow`) — gate tools deferred to Phase 2
6. Wire into `_build_agent_deps` (`helpers.py`)
7. Add `db_session` passthrough to `handle()` and `mc_chat.py`
8. Update `chat_agent` config (`mission_control.yaml`)
9. Seed catalog and add to team
10. Write tests
11. End-to-end verification: `mc chat` → ask questions → trigger runs
