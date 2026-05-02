# Plan 69 — Incremental Plan Building via Tool Calls

**Status:** Ready for implementation
**Priority:** High — eliminates the single most fragile point in the pipeline
**Depends on:** Plan 42 (mission backlog model), Plan 62 (unified execution path)
**Branch:** `feature/incremental-plan-building`

---

## Problem

The Planning Agent produces a TaskPlan as a monolithic JSON blob (7.8 KB, 12 `$defs`). This forces three layers of compensating machinery:

1. **`extract_task_plan_json()`** — 4 extraction strategies (raw JSON, markdown fence, XML tags, first-brace-to-last-brace) because the LLM wraps its output unpredictably.
2. **8 normaliser layers** across `TaskPlan`, `TaskDefinition`, `TaskVerification`, `TaskInputs`, `TaskConstraints`, and `Tier3Verification` — each with `@model_validator(mode="before")` to fix field-name variations (`tier1`→`tier_1`, `agent_name`→`agent`, `id`→`task_id`, flat inputs→nested `static`, etc.).
3. **NativeOutput ban** — Anthropic's grammar compiler rejects the TaskPlan schema ("Schema is too complex", 12 `$defs`). The agent uses `output_type=str` and prompted JSON, which is inherently less reliable.
4. **Retry loop** — `MissionPlanOrchestrator.refine()` retries up to 3 times, feeding validation errors back as a correction prompt. Each retry burns a full LLM call.

The root cause: we ask the LLM to produce a complex data structure in one shot. LLMs are good at making sequential tool calls with simple schemas. They are bad at producing perfectly-structured multi-KB JSON blobs. We are fighting the model's natural behaviour.

---

## Solution

Replace the monolithic JSON output with **incremental plan construction via tool calls**. The Planning Agent calls tools that mutate an in-memory `PlanBuildingSession` — assembling the plan through small, validated mutations. On `finalise_plan`, the assembled plan is validated and persisted via the existing `MissionPlanOrchestrator._persist_plan()` path (reconciliation, version bump, SSE event). Each tool call has a trivially small schema. The TaskPlan Pydantic model remains the canonical internal representation; tools build it incrementally instead of parsing it from a blob.

**Key insight from pydantic-deep research (doc 028):** pydantic-deep's `write_todos`/`read_todos` pattern has the LLM build task graphs through simple tool calls (`add_todo`, `set_dependency`, `get_available_tasks`) instead of producing structured output. MC already has richer infrastructure than pydantic-deep's todo system — the shift is making the Planning Agent use it.

---

## Design

### Phase 1: Planning tools on the agent

Register 8 tools on the Planning Agent (dispatch mode). These replace the `output_type=str` + `extract_task_plan_json()` path.

#### Tool definitions

```
add_task(
    description: str,          # What the task does
    agent: str,                # Agent from roster (e.g. "security.webapp.scanner.agent")
    instructions: str,         # Detailed instructions for the agent
    dependencies: list[str],   # task_ids this depends on (default: [])
    domain_tags: list[str],    # Tags for filtering (default: [])
) -> { task_id: str, status: "proposed" }
```

```
update_task(
    task_id: str,              # Existing task to modify
    description: str | None,
    agent: str | None,
    instructions: str | None,
    dependencies: list[str] | None,
    domain_tags: list[str] | None,
) -> { task_id: str, updated_fields: list[str] }
```

```
remove_task(
    task_id: str,              # Task to remove
) -> { task_id: str, cancelled_dependents: list[str] }
```

```
set_upstream_input(
    task_id: str,              # Task receiving the input
    input_name: str,           # Name for this input binding
    source_task: str,          # task_id of the upstream provider
    source_field: str,         # Field name in upstream output
) -> { task_id: str, input_name: str }
```

```
set_static_input(
    task_id: str,
    key: str,
    value: str | int | float | bool | list | dict,
) -> { task_id: str, key: str }
```

```
set_file_manifest(
    task_id: str,
    read_for_pattern: list[dict],  # [{"path": "...", "reason": "..."}] (max 2)
    read_first: list[dict],        # [{"path": "...", "reason": "..."}] (max 5)
    modify: list[dict],            # [{"path": "...", "reason": "..."}] (max 5)
) -> { task_id: str }
```

```
set_verification(
    task_id: str,
    tier: int,                 # 1, 2, or 3
    config: dict,              # Tier-specific config (schema per tier)
) -> { task_id: str, tier: int }
```

```
finalise_plan(
    summary: str,              # Plan summary
    estimated_cost_usd: float, # Cost estimate
    estimated_duration_seconds: int,
) -> { plan_id: str, version: int, task_count: int, validation_errors: list[str] }
```

#### How they work

Each tool call goes through a **`PlanBuildingSession`** — a new helper class that holds an in-memory TaskPlan being assembled. It does NOT write to the database on every call (that would be expensive and emit premature SSE events). Instead:

1. **`add_task` / `update_task` / `remove_task`** — mutate the in-memory plan dict. `add_task` auto-generates `task_id` using the pattern `v{version}-task-{NNN}` (reuse the version-prefix logic from `MissionPlanService.add_task()` lines 464-473 — extract to a shared `generate_task_id()` utility, don't duplicate). `add_task` also validates the `agent` name against the roster eagerly and looks up `agent_version` from the registry (same pattern as `MissionPlanService.add_task()` lines 459-462) — returning an immediate error if the agent doesn't exist. Returns the assigned `task_id` so the LLM can reference it in subsequent calls.

2. **`set_upstream_input` / `set_static_input` / `set_file_manifest` / `set_verification`** — attach metadata to an existing task in the in-memory plan. `set_file_manifest` writes to `inputs.file_manifest` (a peer of `inputs.static`, not inside it) — this is how the Planning Agent tells coding agents which files to read and modify (doc 49).

3. **`finalise_plan`** — runs validation in two stages:
   - **Quick pre-check:** Pydantic `TaskPlan.model_validate()` (schema) + `_semantic_check()` (task_id format, dependency refs exist, cycle detection, tier 3 consistency). These are cheap, pure-Python checks that catch obvious structural errors before the heavier roster-based validation. Note: `_semantic_check` overlaps with rules 3, 4, 10 in `plan_validator.py` — this is intentional: the quick pre-check returns faster error messages for common LLM mistakes, while `validate_plan` does the full roster/budget-aware pass.
   - **Full validation:** `validate_plan()` from `plan_validator.py` (11 rules against roster + budget). Only runs if the pre-check passes.

   If validation passes: sets `build_session.finalised_plan` with the validated plan dict. The tool returns success. Persistence happens in the **caller** (`_call_planning_agent` reads `build_session.finalised_plan` and the orchestrator calls `_persist_plan()`) — not inside the tool. This keeps the tool pure (no DB dependency) and persistence transactional.

   If validation fails: returns `validation_errors` as a list of strings. The LLM reads the errors and makes corrective tool calls, then calls `finalise_plan` again. No full retry — just fix and re-validate.

#### Dynamic system prompt

An `@agent.instructions` function (matching the existing Director pattern in `mission/director/agent.py`) that runs before each model call:

```python
@agent.instructions
async def inject_plan_state(ctx: RunContext[PlanBuildingDeps]) -> str:
    session = ctx.deps.build_session
    if not session.tasks:
        return "Plan is empty. Start by adding tasks."
    return session.render_plan_summary()
```

`render_plan_summary()` produces a compact view:

```
## Current Plan (3 tasks)
v1-task-001: Scan codebase [security.webapp.scanner.agent] (no deps)
v1-task-002: Triage findings [security.webapp.triage.agent] (depends: v1-task-001)
v1-task-003: Generate report [security.webapp.reporter.agent] (depends: v1-task-002)
```

This gives the LLM clean context of what it's already built, without reconstructing it from tool-call history.

### Phase 2: Wire into dispatch and chat modes

#### Dispatch mode (`_call_planning_agent`)

**Current flow:**
```
_call_planning_agent()
  → agent.run_stream(planning_prompt)
  → extract_task_plan_json(full_content)  # 4 extraction strategies
  → _validate_plan_dict(plan_dict)        # normalisers + semantic checks
  → return plan_dict
```

**New flow:**
```
_call_planning_agent()
  → build_session = PlanBuildingSession(mission_id, version, roster)
  → deps = PlanBuildingDeps(build_session=build_session, ...)
  → agent.run(planning_prompt, deps=deps)  # LLM calls tools iteratively
  → return build_session.finalised_plan     # already validated by finalise_plan tool
```

Key changes:
- `agent.run()` instead of `agent.run_stream()` — tool-call mode doesn't benefit from text streaming (the plan builds via tool calls, not output text).
- No `extract_task_plan_json()` — tools produce structured data directly.
- No retry loop in `MissionPlanOrchestrator.refine()` — validation errors from `finalise_plan` are returned to the LLM inline, which self-corrects with tool calls. The 3-attempt retry loop can be reduced to a max-tool-calls safety limit.

#### Chat mode

The existing chat-mode tools (`get_current_plan`, `get_roster`, `get_mission_info`, `save_plan`) are replaced by the 8 planning tools plus the 3 read-only tools. `save_plan` (which takes a complete TaskPlan JSON blob) is replaced by `finalise_plan`.

**Tool split:** Dispatch mode registers only the 8 planning tools (the roster and mission info are already in the planning prompt). Chat mode registers the 8 planning tools + the 3 read-only introspection tools (the user may ask questions mid-planning). `register_planning_tools(agent)` is shared; `_register_read_tools(agent)` is chat-only.

**Chat-mode session lifecycle:** The chat handler creates a `PlanBuildingSession` seeded from the current DB plan (`plan.task_plan_json`), passes it in `PlanBuildingDeps`, and calls `MissionPlanOrchestrator._persist_plan()` after `finalise_plan` succeeds. This mirrors how `apply_plan()` works today — the session replaces the `json.loads(task_plan_json)` parse step.

#### SSE events: NOT per-tool-call

~~Per-tool-call SSE events for preview cards were considered and rejected.~~ The plan builds in-memory; preview tasks have no `PlanTaskState` rows, which would break the frontend's join logic (`statesById[body.task_id]`). The plan assembles in seconds — real-time preview adds UX confusion (tasks appearing then disappearing on `remove_task`) for negligible benefit.

Emit `MissionPlanRefinedEvent` once on `finalise_plan` via `_persist_plan()` — the existing pattern. The Kanban shimmer card (`showShimmer={def.id === 'proposed' && isRefining}`) already covers the "planning in progress" UX.

### Phase 3: Simplify normalisers

Once all plan creation flows through tools, the normaliser layers become dead code for the creation path. They should be kept temporarily for backward compatibility (existing plans in the database were created with the old normalisers), but new plans will never hit them.

**Deprecation schedule:**
1. After Phase 2 lands: add a `_LEGACY_NORMALISE = True` flag. Log a warning when any normaliser actually transforms data.
2. After 30 days with zero normaliser warnings in production logs: remove the normaliser code and set `_LEGACY_NORMALISE = False`.
3. `extract_task_plan_json()` is deleted immediately — it's only called by `_call_planning_agent()` which is being replaced.

---

## Files to create

| File | Purpose |
|---|---|
| `modules/backend/agents/mission/planning/build_session.py` | `PlanBuildingSession` class — in-memory plan assembly with validation |
| `modules/backend/agents/mission/planning/tools.py` | 8 tool definitions + `register_planning_tools(agent)` |
| `tests/unit/backend/agents/mission/planning/test_build_session.py` | Unit tests for PlanBuildingSession |
| `tests/unit/backend/agents/mission/planning/test_planning_tools.py` | Unit tests for each tool |

## Files to modify

| File | Change |
|---|---|
| `modules/backend/agents/mission/planning/agent.py` | `PlanBuildingDeps` extends `PlanningAgentDeps` (adds `build_session` field only — inherits `mission_brief`, `roster_description`, `upstream_context`, `event_bus`). Register tools in dispatch mode via `register_planning_tools()`. Add dynamic `@agent.instructions` prompt. `extract_task_plan_json()` and `_validate_plan_dict()` retained but no longer called from the main path. Chat-mode `_register_chat_tools()` replaced by shared `register_planning_tools()` + read-only tools. |
| `modules/backend/agents/mission_control/helpers/agent_executor.py` | `_call_planning_agent()` uses new tool-based flow. Remove `extract_task_plan_json` call and streaming text collection. |
| `modules/backend/services/mission_plan_orchestrator.py` | `refine()` simplified — no more 3-attempt retry loop. Validation is inline via `finalise_plan` tool. |
| `config/prompts/agents/mission/planning/system.md` | Update instructions: tell agent to use tools instead of producing raw JSON. Remove the "output a TaskPlan as raw JSON" directive. |
| `config/prompts/agents/mission/planning/chat.md` | Update chat variant to reference new tools. |
| `modules/backend/schemas/task_plan.py` | No structural changes. Normalisers stay for backward compat but are no longer the primary creation path. |
| `modules/backend/agents/mission_control/plan_validator.py` | No changes — `finalise_plan` calls `validate_plan()` exactly as before. |

## Files unchanged

| File | Why |
|---|---|
| `modules/backend/services/mission_plan.py` | `MissionPlanService` methods (approve, reject, retry, add_task, state transitions) are unchanged. `PlanBuildingSession` does not use them during assembly — it only calls `_persist_plan()` on finalise. |
| `modules/backend/models/mission_plan.py` | No schema changes. `MissionPlan.task_plan_json` still holds the serialized TaskPlan. |
| `modules/backend/api/v1/endpoints/missions_plan.py` | No endpoint changes. The API contract is unchanged. |
| `modules/frontend/src/**` | No frontend changes. The Kanban board, hooks, and SSE handlers are unchanged. `MissionPlanRefinedEvent` is emitted on `finalise_plan` exactly as before. |
| `modules/backend/repositories/mission_plan.py` | No changes. |
| `tests/unit/backend/agents/horizontal/planning/test_planning_agent.py` | Updated to test new tool registration, but the file itself is not restructured. |

---

## Implementation sequence

### Step 1: `PlanBuildingSession` (no agent dependency)

Create `build_session.py` with:

```python
class PlanBuildingSession:
    """In-memory TaskPlan assembly used by planning tools.

    Holds an evolving plan dict and provides mutation methods.
    Does NOT touch the database — that happens on finalise().
    """

    def __init__(
        self,
        mission_id: str,
        version: int,
        roster: Roster,
        budget_usd: float,
        *,
        current_plan: dict | None = None,
    ):
        self.mission_id = mission_id
        self.version = version
        self.roster = roster
        self.budget_usd = budget_usd
        self._task_counter = 0
        self.tasks: dict[str, dict] = {}  # task_id -> task body
        self.finalised_plan: dict | None = None

        # Seed from existing plan (refinement mode)
        if current_plan and "tasks" in current_plan:
            for task in current_plan["tasks"]:
                tid = task.get("task_id", "")
                self.tasks[tid] = dict(task)
                self._task_counter = max(
                    self._task_counter,
                    self._extract_seq(tid),
                )

    def add_task(self, ...) -> dict: ...
    def update_task(self, ...) -> dict: ...
    def remove_task(self, ...) -> dict: ...
    def set_upstream_input(self, ...) -> dict: ...
    def set_static_input(self, ...) -> dict: ...
    def set_file_manifest(self, ...) -> dict: ...
    def set_verification(self, ...) -> dict: ...

    def finalise(self, summary, cost, duration) -> dict:
        """Assemble TaskPlan dict, validate, return result or errors."""
        plan_dict = {
            "version": f"{self.version}.0.0",
            "mission_id": self.mission_id,
            "summary": summary,
            "estimated_cost_usd": cost,
            "estimated_duration_seconds": duration,
            "tasks": list(self.tasks.values()),
            "execution_hints": {"critical_path": []},
        }
        # Validate
        try:
            plan = TaskPlan.model_validate(plan_dict)
        except ValidationError as e:
            return {"valid": False, "errors": [str(e)]}

        errors = _semantic_check(plan)
        if errors:
            return {"valid": False, "errors": errors}

        validation = validate_plan(plan, self.roster, self.budget_usd)
        if not validation.is_valid:
            return {"valid": False, "errors": validation.errors}

        self.finalised_plan = plan.model_dump()
        return {"valid": True, "plan": self.finalised_plan}

    def render_plan_summary(self) -> str:
        """Compact text view for the dynamic system prompt."""
        ...
```

Write unit tests for all mutation methods + finalise validation.

### Step 2: Planning tools

Create `tools.py`:

```python
def register_planning_tools(agent: Agent) -> None:
    """Register the 8 incremental plan-building tools."""

    @agent.tool
    async def add_task(
        ctx: RunContext[PlanBuildingDeps],
        description: str,
        agent: str,
        instructions: str,
        dependencies: list[str] = [],
        domain_tags: list[str] = [],
    ) -> str:
        """Add a task to the plan. Returns the assigned task_id."""
        result = ctx.deps.build_session.add_task(
            description=description,
            agent=agent,
            instructions=instructions,
            dependencies=dependencies,
            domain_tags=domain_tags,
        )
        return json.dumps(result)

    # ... remaining tools follow the same pattern

    @agent.tool
    async def finalise_plan(
        ctx: RunContext[PlanBuildingDeps],
        summary: str,
        estimated_cost_usd: float,
        estimated_duration_seconds: int,
    ) -> str:
        """Validate and finalise the plan. Call this when all tasks are added.

        Returns validation_errors if the plan is invalid — fix the issues
        and call finalise_plan again.
        """
        result = ctx.deps.build_session.finalise(
            summary=summary,
            cost=estimated_cost_usd,
            duration=estimated_duration_seconds,
        )
        if not result["valid"]:
            return json.dumps({
                "status": "invalid",
                "validation_errors": result["errors"],
                "hint": "Fix the errors above with update_task/remove_task, then call finalise_plan again.",
            })
        return json.dumps({
            "status": "finalised",
            "task_count": len(ctx.deps.build_session.tasks),
        })
```

### Step 3: Wire `_call_planning_agent` to use tools

Modify `agent_executor.py`:

```python
async def _call_planning_agent(...) -> dict:
    # Build session with optional current plan seed
    build_session = PlanBuildingSession(
        mission_id=mission_id,
        version=plan_version,
        roster=roster,
        budget_usd=budget,
        current_plan=current_plan,
    )

    deps = PlanBuildingDeps(
        build_session=build_session,
        project_root=project_root,
        ...
    )

    agent = create_agent(model)  # now registers planning tools

    try:
        result = await agent.run(
            planning_prompt, deps=deps,
            usage_limits=UsageLimits(request_limit=50),
        )
    except UsageLimitExceeded:
        logger.warning(
            "Planning Agent exhausted tool-call budget",
            extra={"tasks": len(build_session.tasks), "mission_id": mission_id},
        )
        raise ValidationError(
            f"Planning Agent exhausted tool-call budget (50 calls). "
            f"{len(build_session.tasks)} tasks added but finalise_plan "
            f"did not succeed."
        )

    if build_session.finalised_plan is None:
        raise ValidationError(
            "Planning Agent did not call finalise_plan. "
            f"Plan has {len(build_session.tasks)} tasks but was not finalised."
        )

    return {"task_plan": build_session.finalised_plan}
```

### Step 4: Simplify `MissionPlanOrchestrator.refine()`

The 3-attempt retry loop with `_append_validation_feedback` is no longer needed — validation feedback is inline via the `finalise_plan` tool return value. Simplify to:

```python
async def refine(self, mission_plan_id, instructions, user_id, ...):
    # ... same setup (load mission, roster, brief) ...

    planning_result = await _call_planning_agent(
        prompt=brief,
        roster=roster,
        ...,
    )

    # planning_result["task_plan"] is already validated by finalise_plan.
    # Re-parse into TaskPlan for _persist_plan (which expects a TaskPlan model).
    candidate = TaskPlan(**planning_result["task_plan"])
    await self._persist_plan(plan, candidate, source="mission_plan_orchestrator")
    return await self._repo.get_by_mission_id_required(plan.mission_id)
```

No retry loop. No `_append_validation_feedback`. The agent self-corrected inline. Note: both `TaskPlan(**data)` and `TaskPlan.model_validate(data)` re-run normalisers in Pydantic v2 — there is no way to bypass `@model_validator(mode="before")`. Since the data is already normalised by `finalise()`, normalisers are idempotent no-ops. Use either form.

### Step 5: Update system prompts

`config/prompts/agents/mission/planning/system.md`:

```markdown
## Output

Build the plan incrementally using the provided tools:

1. Call `add_task` for each task in dependency order (root tasks first).
2. Use the returned `task_id` to set dependencies on downstream tasks.
3. Call `set_upstream_input` for each data flow between tasks.
4. Call `set_static_input` for fixed configuration values.
5. Call `set_file_manifest` for coding tasks that need specific files.
6. Call `set_verification` for tasks requiring quality checks.
7. Call `finalise_plan` when all tasks are added.

If `finalise_plan` returns validation errors, fix them with `update_task`
or `remove_task`, then call `finalise_plan` again.

Do NOT produce raw JSON output. Use the tools.
```

### Step 6: Update chat-mode tools

Replace the 4 existing chat tools (`get_current_plan`, `get_roster`, `get_mission_info`, `save_plan`) with the 8 planning tools + the 3 read-only tools (renamed but functionally identical). `save_plan` becomes `finalise_plan`.

---

## What this eliminates

| Component | Status after Plan 69 |
|---|---|
| `extract_task_plan_json()` | Deleted — no JSON extraction needed |
| `_try_parse_json()` | Deleted |
| `_validate_plan_dict()` | Deleted — validation moved to `finalise_plan` |
| `_semantic_check()` in `agent.py` | Extracted to `build_session.py` as a module-level function. `PlanBuildingSession.finalise()` calls it. The function is **moved, not duplicated** — `agent.py` imports it from `build_session.py` if any legacy path still needs it during the transition. |
| 3-attempt retry loop in `refine()` | Removed — inline correction via tool return values |
| `_append_validation_feedback()` | Deleted |
| NativeOutput ban | Irrelevant — tools use NativeOutput per-call (each schema is trivial) |
| Normalisers (8 layers) | Kept for backward compat but no longer on creation path; deprecation schedule above |

## What stays unchanged

| Component | Why |
|---|---|
| `TaskPlan` Pydantic model | Canonical internal representation — tools build it, `finalise_plan` validates it |
| `plan_validator.py` (11 rules) | Called by `PlanBuildingSession.finalise()` exactly as before |
| `MissionPlanService` (approve/reject/retry/add_task) | State machine unchanged — operates after plan is persisted |
| `MissionPlanOrchestrator._persist_plan()` | Called by `_call_planning_agent` after `finalise_plan` succeeds |
| `MissionPlanOrchestrator._reconcile_task_states()` | Called by `_persist_plan` — reconciliation logic unchanged |
| All frontend components | `MissionPlanRefinedEvent` emitted on persist — same SSE contract |
| All REST endpoints | API contract unchanged |
| All SSE events | Same events, same payloads |

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM forgets to call `finalise_plan` | Safety check in `_call_planning_agent`: if `build_session.finalised_plan is None` after `agent.run()` completes, raise `ValidationError`. The system prompt explicitly ends with "Call `finalise_plan` when all tasks are added." |
| LLM makes too many tool calls (runaway) | Set `usage_limits=UsageLimits(request_limit=50)` on `agent.run()`. A 20-task plan needs ~30-40 calls. 50 is generous. Catch `UsageLimitExceeded` in `_call_planning_agent`, log the partial plan state (`build_session.tasks`), and raise `ValidationError` with context: "Planning Agent exhausted tool-call budget (50 calls) without producing a valid plan. {N} tasks added but finalise_plan did not succeed." |
| LLM produces invalid agent names | `add_task` validates `agent` against the roster immediately and returns an error. The LLM corrects inline — no full retry needed. |
| Refinement mode: LLM ignores seeded tasks | `PlanBuildingSession.__init__` pre-populates `self.tasks` from `current_plan`. The dynamic system prompt shows the existing plan. The system prompt says "Preserve existing task_ids where possible." |
| Regression on plans created with old normalisers | Normalisers kept on `TaskPlan` schema. Any plan loaded from `task_plan_json` still goes through normalisation when deserialised. Only the creation path changes. |
| Chat-mode UX: too many tool calls visible to user | Tool calls are already suppressed in the chat UI (only agent text responses show). The LLM can interleave brief status messages: "Adding scan task... Adding triage task... Finalising plan." |

---

## Testing strategy

1. **Unit tests for `PlanBuildingSession`** — test each mutation method, validation on finalise, refinement seeding, error cases (duplicate task_id, invalid agent, cycle detection).
2. **Unit tests for planning tools** — mock `RunContext`, verify each tool returns correct shape, verify error propagation.
3. **Integration test** — use `scripts/test_planning_live.py` (existing harness) with the new tool-based agent. Compare plan quality and validation pass rate against the old blob-based approach.
4. **Existing `plan_validator.py` tests** — unchanged; the validator is called from a new location but the interface is the same.
5. **Frontend smoke test** — verify `MissionPlanRefinedEvent` fires correctly, Kanban board renders the plan as before.

---

## Cleanup checklist (after testing confirms parity)

Once the tool-based path is tested and validated (live test harness passes, plans are equivalent quality), remove all compensating machinery. This is not optional — dead workaround code is a maintenance trap.

### Delete entirely

| File / function | Why it's dead |
|---|---|
| `extract_task_plan_json()` in `agent.py` | No JSON extraction needed — tools produce structured data |
| `_try_parse_json()` in `agent.py` | Only called by `extract_task_plan_json` |
| `_validate_plan_dict()` in `agent.py` | Validation moved to `PlanBuildingSession.finalise()` |
| `_semantic_check()` in `agent.py` | Moved to `PlanBuildingSession.finalise()` (not duplicated — moved) |
| `_append_validation_feedback()` in `prompt_builder.py` | Retry loop removed — inline correction via tool return |
| The 3-attempt retry loop in `MissionPlanOrchestrator.refine()` | `finalise_plan` handles correction inline |
| `save_plan` tool in chat mode `_register_chat_tools()` | Replaced by `finalise_plan` |

### Remove from normalisers (after 30-day monitoring)

| Normaliser | Location | When to remove |
|---|---|---|
| `TaskPlan.normalise_plan_fields()` | `task_plan.py:396-435` | After 30 days with zero normaliser-transform log warnings |
| `TaskDefinition.normalise_task_fields()` | `task_plan.py:305-355` | Same |
| `TaskVerification.normalise_tier_keys()` | `task_plan.py:226-257` | Same |
| `TaskConstraints.normalise_constraint_fields()` | `task_plan.py:268-283` | Same |
| `TaskInputs.normalize_from_upstream()` | `task_plan.py:137-156` | Same |
| `TaskPlan.coerce_version()` | `task_plan.py:438-446` | Same |
| `Tier3Verification.coerce_criteria_to_list()` | `task_plan.py:201-207` | Same |
| `Tier3Verification.default_score_when_evaluation_enabled()` | `task_plan.py:209-214` | Same |

**How to monitor:** Add a structured log warning inside each normaliser that fires when it actually transforms data (i.e., the input differs from the output). After 30 days of zero warnings, the normaliser is confirmed dead and can be deleted.

### Update memory / docs

| Item | Action |
|---|---|
| `MEMORY.md` Patterns section: "Planning agent: NativeOutput rejected..." | Delete — no longer true |
| `MEMORY.md` Patterns section: "TaskPlan normalisers: tier1→tier_1..." | Update to note normalisers are legacy-only |
| `docs/98-research/028-Robust Schema-Compliant JSON Output...` | Archive — the problem it documents is solved |
| System prompt `system.md` "Output a TaskPlan as raw JSON" | Already replaced in Step 5 |

### Tests to delete / update

| Test | Action |
|---|---|
| `test_dispatch_mode_has_no_function_tools` | Update — dispatch mode now has 8+ tools |
| Any test exercising `extract_task_plan_json` | Delete — function no longer exists |
| Any test exercising normaliser edge cases | Keep until normalisers are removed (30-day window) |

---

## Success criteria

- Planning Agent produces valid plans on first `finalise_plan` call >90% of the time (vs. current ~70% first-attempt rate with blob output).
- `extract_task_plan_json()` is deleted.
- No normaliser warnings in production logs after 30 days.
- Plan quality (task count, dependency correctness, agent assignment accuracy) is equal or better than the blob approach — measured via the live test harness.
- Frontend renders plans identically — no visual changes.
- Chat-mode planning works with the same tools (no separate tool set).
