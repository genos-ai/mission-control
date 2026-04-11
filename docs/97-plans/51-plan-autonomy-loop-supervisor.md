# Plan 51 — Autonomy Loop + Mission Supervisor Agent

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-11 |
| **Part of** | [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) Phase 3 (reframed from Signaling → Autonomy Loop) |
| **Depends on** | Plan 22 (Step-Through Gate — done), Plan 42 (Mission Backlog Model — done), Plan 43 (Persistent Artifacts — done), Plan 48 (Convergence Loop + Branch Automation — to be graduated for Phase B below) |
| **Supersedes** | The deferred "Director proactive follow-up" TODO entry (folded in as §5 Phase A), and the "Supervisor Agent" proposal reviewed in conversation on 2026-04-11 |
| **Target** | `modules/backend/agents/mission/supervisor/` (new), `modules/backend/agents/mission_control/gate*` (extension), `modules/backend/services/session_followup*` (new), `modules/backend/services/mission_plan.py` (emit `MissionPlanRunCompletedEvent` + in-process followup fire), `config/agents/mission/supervisor/` (new), `docs/97-plans/` |

---

## §1 The autonomy iteration gap

Mission Control today dispatches runs. It does not iterate missions.

A wave of approved tasks dispatches (Plan 42 §10.5), runs (Plan 47 isolation), writes back outcomes (Plan 42 §10.5), and then **the mission is inert** until a human reviews results, approves the next wave, and manually re-dispatches. The [`MissionPlanDaemon`](../../modules/backend/services/mission_plan_daemon.py) loops on already-approved tasks but has no authority to approve new ones. The `Director.refine_plan` tool can evolve plans but only fires in response to a user chat message. `mission_plan.run.completed` events are published to the event bus and consumed only by the SSE frontend — nothing intelligent reads them.

This is the single missing load-bearing piece behind Plan 46's goal *"a human can describe an ambitious goal, walk away for days, and return to trustworthy, durable output"*. Without closing this gap, [Plan 46 Phase 6](46-plan-autonomous-mission-roadmap.md) (the endurance test — one real 7+ day unattended mission) is architecturally impossible.

The diagnosis came from a parallel session's design doc in conversation on 2026-04-11. This plan is the chosen architecture after that critique.

---

## §2 Architecture decision — the options we considered and rejected

Three architectures were on the table. Keeping notes on the ones we rejected so future sessions don't re-litigate.

### 2.1 Rejected: Dedicated heavyweight Supervisor Agent

A new reasoning agent (Sonnet or Opus class) runs on every `mission_plan.run.completed` event. Reads outcomes, reasons about progress, decides `advance | retry | stall | complete | escalate`, calls Planning Agent to generate new tasks, posts chat updates.

**Rejected because** it inserts an LLM invocation into the feedback path for *every* run completion, even when the answer is mechanically obvious (~90% of wakes). On a 50-wave mission that's 50 reasoning-class calls to return "yes, advance" 45 times. The supervisor is doing work a deterministic loop runner would do for free. Also adds a third reasoning agent (Director + Supervisor + Planning) where two would cover the space.

### 2.2 Rejected: Pure convergence loops, no meta-layer

Every task declares a measurable exit condition. Deterministic loops run until the condition is met or a hard limit fires. No agent reasons about what's next — the Planning Agent only runs at mission creation.

**Rejected because** it doesn't handle fuzzy objectives (research, writing), multi-dimensional success criteria, or unexpected outcomes. Works for "run this quality loop until PQI ≥ 70" but breaks for "research Cetero's Q4 results". The architecture needs *some* meta-decision layer for situations that aren't reducible to a scalar.

### 2.3 Chosen: Convergence loops + thin supervisor + specialist delegates

Three-layer architecture:

- **Intra-task iteration** lives in convergence loops ([Plan 48](48-plan-convergence-loop-and-branch-automation.md)) with declarative exit conditions. Deterministic, no LLM in the feedback path. This handles the Karpathy "single measurable number" and IndyDevDan "till done" patterns cleanly for the 90% case.
- **Plan-level routing** lives in a thin supervisor (§4 below). **Mostly deterministic rules** — 7 of 8 decision branches are pure Python with no LLM call. The supervisor is framed as a new gate checkpoint (`post_run`) that reuses Plan 22's `GateReviewer` protocol. When an LLM *is* needed (ambiguous classification, unknown situations), it uses **Haiku** — fast, cheap, structured output. Never reasoning-class.
- **Specialist delegation** for the real work. The supervisor *never* designs tasks itself and *never* writes chat messages itself. When plan evolution is needed, it wakes the existing **Planning Agent** via its `refine_plan` tool. When user-facing communication is needed, it wakes the existing **Mission Director** via the new session followup primitive (§5 Phase A).

Under this architecture: the supervisor is a ~300-line rules + routing component with an optional Haiku fallback. It has no overlapping responsibility with the Planning Agent or Director. Each agent does exactly one thing. Total LLM cost for the supervisor itself across a multi-day mission is under a penny.

### 2.4 Why the supervisor is *also* a chattable agent

An architectural option inside Design 2.3: the supervisor could be a pure Python component with no user-facing surface, OR it could be a mission-tier agent (`mission.supervisor.agent`) that the user can open a chat with.

**Chosen: the latter.** The supervisor is a mission-tier agent the user can talk to directly. Reasoning:

1. **Troubleshooting** — when a user returns to a mission and wants to understand "why did you escalate wave 3? why didn't you advance after the quality check failed?", they should be able to just ask. Without a chat surface, the answer has to be inferred from gate_decisions audit logs, which requires operator-level access to the database.
2. **Transparency** — the supervisor is making autonomous decisions on the user's behalf. Giving it a chat presence makes it accountable and auditable by the mission owner, not hidden inside backend plumbing.
3. **Consistency with existing pattern** — `mission.director` and `mission.workflow` (the Workflow Architect) are both mission-tier agents exposed in the Chat tab. Adding `mission.supervisor` as a third sibling maintains the pattern: if you can chat with the Director and Workflow Architect, you can chat with the Supervisor.
4. **Override path** — the chat surface eventually lets the user *override* a supervisor decision ("no, don't escalate — advance anyway") without needing an admin endpoint. Not in v1 scope, but the chat surface makes it addable later without re-architecting.

The supervisor agent has two invocation modes sharing the same prompt and model:

| Mode | Trigger | Input | Output |
|---|---|---|---|
| **Event-triggered** | Session followup on `mission_plan.run.completed` | Plan state summary + recent run outcomes + mission brief | Structured `GateDecision` (routes to delegate) |
| **Chat-triggered** | User message in `mission.supervisor` chat session | User question + past decision history (read from gate_decisions table) | Natural-language explanation |

Both modes use the same Haiku agent with different system prompts (or different output types via pydantic-ai's structured output). Both read from the same audit trail, so a chat-mode query about a past decision returns exactly what the event-mode invocation wrote at the time.

### 2.5 Why Haiku is sufficient

The supervisor's LLM work is **classification with structured output**, not creative writing or multi-step reasoning:

- Input: ~2000 tokens (mission brief + plan state + recent outcomes)
- Output: ~100 tokens (structured decision + reason + confidence)
- Latency target: sub-second
- Failure mode: when unsure, route to `ESCALATE` (delegate to Director) — safe default

Haiku 4.5 handles this effortlessly. Sonnet would be overkill. Opus would be bizarre. The reasoning-class work happens at the **delegates** (Planning Agent, Director) which are Sonnet/Opus already — the supervisor is just the router.

Cost estimate: ~$0.003 per supervisor invocation, fired ~10 times over a multi-day mission = ~$0.03 total supervisor cost. Negligible compared to task-execution costs.

---

## §3 Prerequisites

Two capabilities this plan depends on. Both are graduated as part of this plan (§5 Phases A and B below), not separately — a clean Plan 51 implementation produces working versions of both.

### 3.1 Session followup primitive (Phase A)

Folds in the existing TODO.md entry *"Director proactive follow-up: wake on completion events"*. Generic wake-on-event mechanism. Any agent can register a followup. Builds on the existing Redis event bus (Plan 10) and session model (Plan 11).

**Not** a separate plan doc. The primitive is small enough to ship as Phase A of this plan. The TODO.md entry gets a `[x] DONE` mark referencing `51-plan-autonomy-loop-supervisor.md §5 Phase A` when it lands.

### 3.2 Convergence loop runner (Phase B)

Graduates [Plan 48](48-plan-convergence-loop-and-branch-automation.md) from stub to implementation for the intra-task iteration layer. The `dispatch/convergence.py` scaffold (~441 lines) gets wired into `dispatch/loop.py`, a `convergence_loop` task type gets added to `schemas/task_plan.py`, and declarative exit conditions (`score >= threshold`, boolean predicate, max iterations) become expressible on task definitions.

**Not** a full Plan 48 implementation — only Phase 6 of Plan 48 (the convergence loop pattern itself). Plan 48's other phases (branch strategy + PR automation, final verification) remain out of scope and stay deferred on Plan 48.

---

## §4 Design

### 4.1 Component map

```
                         ┌──────────────────────────┐
                         │ MissionPlanDaemon        │
                         │ (existing, unchanged)    │
                         │                          │
                         │ polls → dispatch_approved│
                         │ (on MissionPlanService)  │
                         └────────────┬─────────────┘
                                      │
                                      │ after write-back + cost update,
                                      │ dispatch_approved emits
                                      │ mission_plan.run.completed
                                      │ (NEW event — added in Phase C)
                                      ▼
                         ┌──────────────────────────┐
                         │ SessionFollowupService   │  ◀── Phase A
                         │ .fire_matching(event)    │
                         │ (invoked in-process,      │
                         │ no pub/sub round-trip)   │
                         └────────────┬─────────────┘
                                      │
                                      │ (multiple subscribers possible)
                                      ▼
             ┌────────────────────────┴────────────────────────┐
             │                                                  │
             ▼                                                  ▼
  ┌──────────────────────┐                       ┌──────────────────────┐
  │ mission.supervisor   │  ◀── Phase D          │ mission.director     │  ◀── Phase E
  │ (new Haiku agent)    │                       │ (existing, extended) │
  │                      │                       │                      │
  │ post_run Gate        │                       │ posts chat update    │
  │ reviewer + chat mode │                       │ when woken            │
  └──────────┬───────────┘                       └──────────────────────┘
             │
             │ DECISION:
             │   WAIT / ADVANCE_APPROVED / ADVANCE_REFINE /
             │   PROPOSE_COMPLETE / ESCALATE
             │
             ▼
  ┌────────────────────────────┐
  │ Routing action             │
  │ (7 of 8 branches = rules)  │
  └──────────┬─────────────────┘
             │
             ├──► approve_proposed  → writes plan_task_states, daemon picks up
             │
             ├──► wake Planning Agent → refine_plan → new proposed → auto-approve
             │
             ├──► propose_complete → wakes Director → chat: "I think we're done?"
             │
             └──► escalate         → wakes Director → chat: "need your help on X"
```

### 4.2 Decision matrix — the core of the supervisor

Every `post_run` gate invocation evaluates this matrix in order. First match wins. Rule-based branches fire no LLM. Only the final "fall through" branch consults Haiku, and only for classification between the remaining options.

| # | Situation | Gate mode | Action | Delegates to | LLM? |
|---|---|---|---|---|---|
| 1 | `total_spent_usd ≥ budget_usd_ceiling` | any | `ESCALATE` | Director | No |
| 2 | `supervisor_iterations ≥ max_supervisor_iterations` (default 20) | any | `ESCALATE` | Director | No |
| 3 | Stall: N consecutive waves with 0 completed tasks (default N=3) | any | `ESCALATE` | Director | No |
| 4 | Approved tasks remaining in plan | any | `WAIT` | daemon picks up | No |
| 5 | Proposed tasks + `off`/`autonomous` | off / autonomous | `ADVANCE_APPROVED` | writes directly | No |
| 6 | Proposed tasks + `ai_assisted` (within veto window) | ai_assisted | `ADVANCE_APPROVED` with `veto_expires_at` | Director (chat: "auto-approved N tasks, veto in Ns") | No |
| 7 | Proposed tasks + `interactive` | interactive | `ESCALATE` | Director (chat: "ready to advance — approve?") | No |
| 8 | Plan exhausted (no approved, no proposed), outcomes present | any | **Haiku classification** → either `ADVANCE_REFINE` or `PROPOSE_COMPLETE` | Planning Agent (refine) or Director (confirm) | **Haiku** |

Branch #8 is the only LLM-invoking branch. The Haiku prompt receives the mission brief, the plan's outcome summary, and the remaining budget headroom, and returns a structured classification:

```json
{
  "decision": "ADVANCE_REFINE" | "PROPOSE_COMPLETE" | "ESCALATE",
  "reason": "short human-readable justification",
  "confidence": 0.0-1.0
}
```

Confidence threshold < 0.6 → treat as `ESCALATE` regardless of stated decision (safer default). The Haiku supervisor never unilaterally marks a mission complete; `PROPOSE_COMPLETE` always delegates to the Director, which asks the user to confirm in chat before the plan's status flips.

**If no branch matches**, fall through to `ESCALATE` as the safe default. Unknown situations route to the Director for human attention, never silently auto-advance.

### 4.3 mission.supervisor.agent

New agent config at `config/agents/mission/supervisor/agent.yaml`:

```yaml
agent_name: "mission.supervisor.agent"
agent_type: "supervisor"
version: "1.0.0"
description: |
  Mission-tier supervisor that routes post-run decisions. Called automatically
  after each run completion via the session followup primitive; also
  chattable by the mission owner for troubleshooting past decisions.
  Haiku-class, delegates to Planning Agent and Director for real work.

invocation:
  tier: "user"            # user-tier so mission owners can chat with it
  required_role: null     # any mission member can read its decisions

model: "claude-haiku-4-5-20251001"
max_tokens: 1000          # structured output is short
max_requests: 5           # hard cap per invocation — rules-first, no long loops

execution:
  mode: "local"           # supervisor runs in-process, no container isolation needed
  prefer: "local"

scope:
  read: ["docs/"]         # chat mode reads plan docs if the user asks
  write: []               # supervisor never writes files; delegates write via Planning/Director

tools:
  - get_plan_state        # existing mission_plan service read path
  - get_recent_run_outcomes  # new — reads last N runs from execution_records
  - get_past_decisions    # new — reads gate_decisions for this mission
  - evaluate_decision     # new — event-mode structured output
  - explain_past_decision # new — chat-mode natural language response
```

Python module at `modules/backend/agents/mission/supervisor/agent.py` follows the same pattern as `mission/director/agent.py` and `mission/workflow/agent.py`:

```python
def create_agent(model: str | Model) -> Agent[MissionSupervisorDeps, SupervisorDecision]:
    """Factory for the mission supervisor agent.

    Two invocation modes share the same Agent instance with different
    output types:
        event_mode: output_type=SupervisorDecision (structured routing)
        chat_mode:  output_type=str (natural language explanation)

    Mode is selected at call time by the dispatcher, not by the agent
    itself.
    """
```

Prompt template at `config/prompts/agents/mission/supervisor/system.md`:

```markdown
You are the Mission Supervisor for Mission Control.

Your job is routing, not reasoning. When a mission run completes, a
deterministic rule engine evaluates the situation first. You are only
invoked when the rules cannot decide — specifically when the plan is
exhausted but outcomes are present, and the system needs to know
whether to advance the plan, propose completion, or escalate to the user.

## Decision options

- ADVANCE_REFINE: the mission objective is not yet met, and the Planning
  Agent should be invoked to generate the next wave of tasks based on
  recent outcomes. Choose this when recent work produced meaningful
  signal but the goal is clearly incomplete.

- PROPOSE_COMPLETE: the mission objective appears to be met based on
  the outcomes. Choose this conservatively — the Director will ask the
  user to confirm before the plan is marked complete.

- ESCALATE: unclear situation, or the outcomes suggest something
  unexpected happened (agent drift, contradictory results, missing
  dependencies). Choose this when in doubt. The Director will ask the
  user for input.

## Rules

1. You are not the Planning Agent. You do not design new tasks.
2. You are not the Director. You do not talk to users outside chat
   mode.
3. When uncertain, choose ESCALATE with confidence < 0.6. The default
   is always safe.
4. Output JSON matching the SupervisorDecision schema.
```

**Chat mode** uses a different system prompt that frames the agent as an explainer:

```markdown
You are the Mission Supervisor. You are being asked questions by the
mission owner about past decisions you made on this mission.

Use the get_past_decisions tool to read your audit trail. For each
question, quote the relevant past decision and explain the reason in
plain language. Do not make new decisions in chat mode — refer the
user to the Director if they want to override or force action.
```

### 4.4 Post-run Gate checkpoint

Extends the existing gate system ([gate_models.py](../../modules/backend/agents/mission_control/gate_models.py)) with a new gate type and new action values. The existing `GateAction` enum has 5 values; `GateContext` already carries `mission_id`, `total_cost_usd`, `budget_usd`; `GateDecision.reviewer` already exists as a string field (values like `"human"`, `"ai:<model>"`, `"noop"`, `"config:disabled"`) and is reused verbatim here, no schema change needed.

**New `gate_type` value:** `post_run`

**New `GateAction` values** (additive to the existing 5):
- `WAIT` — no action, daemon has more approved tasks to dispatch
- `ADVANCE_APPROVED` — proposed tasks → approved, daemon picks them up next tick
- `ADVANCE_REFINE` — wake Planning Agent to generate new tasks based on outcomes
- `PROPOSE_COMPLETE` — wake Director to ask user if mission is done
- `ESCALATE` — wake Director for user attention (semantically distinct from `ABORT`: ABORT halts the mission, ESCALATE pauses pending human decision)

Existing actions (`CONTINUE`, `SKIP`, `RETRY`, `ABORT`, `MODIFY`) remain unchanged and still valid at other checkpoints (`pre_dispatch`, `pre_layer`, `post_task`, `verification_failed`, `post_layer`). The new actions are valid only at `post_run`; other checkpoints that receive them should reject as a misconfigured call.

**New `GateContext` fields** for post-run specifically (all additive, all defaulted, so existing callers are unaffected):
- `recent_run_outcomes: list[dict]` — last N run summaries (default `[]`)
- `plan_task_summary: dict` — counts by status (proposed / approved / running / completed / failed) (default `{}`)
- `mission_brief: str | None` — for the Haiku prompt (default `None`)
- `supervisor_iteration_count: int` — for circuit breaker #1 (default `0`)

Note: the existing `total_cost_usd` / `budget_usd` fields already cover the headroom check — `remaining = budget_usd - total_cost_usd` — so no separate `remaining_budget_usd` field is added.

**`GateDecision` extension** — one new optional field:
- `model_metadata: dict | None = None` — `{confidence, tokens_used, cost_usd}` when branch #8's Haiku call populates the decision. All rule-based branches leave it `None`.

**New reviewer class:** `AutonomousPostRunReviewer` at `modules/backend/agents/mission_control/gate_post_run.py`. Implements `GateReviewer.review(context) -> GateDecision` per §4.2 decision matrix. Most branches return without invoking the LLM. Branch #8 calls the supervisor agent via pydantic-ai with `output_type=SupervisorDecision`.

### 4.5 Audit trail

Supervisor decisions are first-class in the existing `execution_records.decisions` structure (Plan 22). The existing [`ExecutionDecision` model](../../modules/backend/models/execution_record.py) already has `execution_record_id`, `decision_type`, `task_id`, and `reasoning` — the full minimum shape we need. No new columns are added; supervisor metadata is embedded in the existing text/JSON fields.

**One new `DecisionType` enum value** — `POST_RUN_SUPERVISOR = "post_run_supervisor"`. Added to `modules/backend/models/execution_record.py::DecisionType` alongside the existing `RETRY`, `FAIL`, `PASS`, `RE_PLAN`, `SKIP`, `ESCALATE` values. No migration required since `DecisionType` is a string enum stored as varchar.

**Encoding:** the `reasoning` field holds a short human-readable prefix followed by a machine-parseable JSON line. Example:

```
Advanced approved wave (rule #5) — 3 proposed tasks, autonomous mode, budget headroom $12.40.
{"action": "advance_approved", "reviewer": "config:rule_engine", "iteration": 7, "model_metadata": null}
```

When branch #8 invokes Haiku, the JSON line carries the full model metadata:

```
{"action": "advance_refine", "reviewer": "ai:claude-haiku-4-5-20251001", "iteration": 12,
 "model_metadata": {"confidence": 0.82, "tokens_used": 340, "cost_usd": 0.00085}}
```

The `get_past_decisions` tool parses the JSON tail when it reads the audit trail; chat-mode answers quote the human-readable prefix for display. This keeps the schema change to a single enum value add — if we later discover we need queryable columns (for cost dashboards or agent-specific filters), we can promote the JSON fields in a follow-up migration without re-architecting the write path.

Chat mode reads this table via `get_past_decisions` to answer "why did you ..." questions. Chat answers are *never* written back to this table — they're session messages in `session_messages` like any other chat response.

### 4.6 Circuit breakers (independent of the supervisor)

Four hard limits enforced *outside* the supervisor's decision logic. The supervisor cannot override them.

1. **Max supervisor iterations per mission.** New column `mission_plans.max_supervisor_iterations` (default 20) + counter `mission_plans.supervisor_iteration_count`. Every supervisor wake increments. If the counter reaches max, the supervisor is bypassed entirely — the post-run handler routes directly to `ESCALATE`.

2. **Stall detection.** Read the last N run outcomes from execution_records. If N consecutive runs have `completed_task_count = 0` (default N=3), route directly to `ESCALATE`. Prevents runaway supervisor advancing into a no-op loop.

3. **Duplicate detection.** Before routing to `ADVANCE_REFINE`, check that the Planning Agent's proposed new tasks don't exactly match task_ids of tasks that failed in the most recent run. If they do, override to `ESCALATE`. Prevents the Planning Agent from retrying identical work with identical inputs — clearly not useful.

4. **Budget headroom.** Before routing to `ADVANCE_APPROVED` or `ADVANCE_REFINE`, compute `remaining = ceiling - spent`. If remaining is less than the estimated cost of the next wave (estimated from task_plan_json `estimated_cost_usd` or a default floor), override to `ESCALATE`. The existing Plan 42 §10.7 budget check is a fallback safety net but the supervisor should escalate proactively rather than wait for dispatch to fail.

All four breakers fire before the Haiku call. They never cost LLM tokens.

### 4.7 Gate mode interaction

The supervisor's decision respects `mission_plans.gate_mode` absolutely:

| gate_mode | Supervisor behavior when proposed tasks exist |
|---|---|
| `off` | Auto-advance, no veto window |
| `autonomous` | Auto-advance, no veto window |
| `ai_assisted` | Auto-advance, `veto_expires_at` set to `now + veto_window_sec`, Director notified |
| `interactive` | **Never auto-advance.** Always escalate to Director, who asks user in chat |

This is a hard rule, not a supervisor recommendation. The post-run handler reads `gate_mode` *before* invoking the reviewer and short-circuits to `ESCALATE` when the mode is `interactive`. The supervisor is never even asked to classify in that case.

This matches the existing Plan 42 §10.4 contract: the Director's `approve_plan_tasks` tool already refuses in interactive mode. The supervisor inherits the same rule.

### 4.8 Director integration (user-visible feedback loop)

The Director uses the same Phase A session followup primitive, registering for the new `mission_plan.supervisor_decision` event (class `SupervisorDecisionEmittedEvent`, added in Phase E). When `AutonomousPostRunReviewer` writes a decision row, it constructs the event and calls `SessionFollowupService.fire_matching(event)` in-process. The Director's followup row matches, which wakes the Director in the mission owner's session with a system message:

> "Mission supervisor just decided `<action>` for run `<id>`. Reason: `<reason>`. Compose a brief user-facing update and post it to this session's chat stream."

The Director formats a natural-language message ("Wave 3 finished — I've started wave 4 with tasks X, Y, Z. You can review them in the Plan tab") and sends it through the existing chat response path. The frontend's SSE consumer renders it like any other assistant message, *unprompted*, in the user's session. The user sees proactive updates without polling the UI.

Escalation paths use stronger wording: "Mission is stalled — I've stopped advancing because the last 3 waves produced no new work. Can you take a look and tell me what to do next?".

**This replaces Telegram for v1 conversational continuity.** The original Plan 46 §4 Phase 3 was "Signaling via Telegram" — in-app chat messages via Director followup cover the same user story (proactive notifications when something needs attention) without requiring a separate channel. Telegram becomes a future enhancement: when the user is *not* looking at the app, push the same message to Telegram. Not v1 scope.

---

## §5 Implementation phases

Six phases in strict dependency order. Each phase is an independently buildable commit (or short chain) with its own acceptance criterion. Total estimated scope: ~2 focused weeks, broken into phases small enough that most can land in single sessions.

### Phase A — Session followup primitive

**Goal:** Generic wake-an-agent-on-an-event-trigger mechanism. Any agent can register; any event type can be a trigger.

**Transport decision.** The followup service is invoked **in-process** by event emitters (e.g. `MissionPlanService.dispatch_approved` calls `SessionFollowupService.fire_matching(event)` after emitting). No Redis Pub/Sub subscription required — the existing [`EventBus.publish_to_mission`](../../modules/backend/events/bus.py) is session/SSE transport, but the autonomy feedback loop runs inside the same process that emitted the event, so a direct method call is simpler, deterministic, and fully testable without Pub/Sub timing. If a future consumer needs cross-process delivery, a `subscribe_to_all_missions()` method using Redis `PSUBSCRIBE mission_events:*` can be added then — out of scope for v1.

**Files:**
- `modules/backend/migrations/versions/<date>_phase3_session_followups.py` (new)
- `modules/backend/models/session_followup.py` (new)
- `modules/backend/repositories/session_followup.py` (new)
- `modules/backend/services/session_followup.py` (new — `SessionFollowupService` with `fire_matching(event)` entry point)
- `modules/backend/events/types.py` — new event `SessionFollowupFiredEvent` for audit trail
- `modules/backend/agents/tools/followup.py` (new — `schedule_followup` tool for agents)

No new background task or daemon is needed for Phase A — the service is invoked from existing emission points. `main.py` lifespan is unchanged.

**Schema sketch** (full design in the TODO.md entry, not duplicated here):

```sql
CREATE TABLE session_followups (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    mission_id VARCHAR(36),
    trigger_event_types TEXT NOT NULL,  -- JSON array
    trigger_filter JSON,                -- e.g. {"mission_id": "..."}
    prompt_template TEXT NOT NULL,
    created_by_agent VARCHAR(200) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP,
    cooldown_seconds INTEGER DEFAULT 0,
    max_fires INTEGER DEFAULT 1,
    fire_count INTEGER DEFAULT 0,
    failure_reason TEXT
);
```

**Acceptance:** An agent calls `schedule_followup(trigger_events=["mission_plan.run.completed"], prompt="handle run completion")`. A test constructs a synthetic `MissionPlanRunCompletedEvent` and invokes `SessionFollowupService.fire_matching(event)` directly. The service finds the matching row, spawns a fresh turn for the registered agent, the agent's response streams through the existing session SSE pipeline, and the followup row's `consumed_at` is stamped. Verified via a new `scripts/verify_followup_primitive.py`. (Note: Phase A ships the service and tool but has no production emission site — Phase C wires `MissionPlanService.dispatch_approved` to call `fire_matching` as the first real consumer.)

Also closes the TODO.md entry *"Director proactive follow-up: wake on completion events"* by marking it `[x] DONE` with a pointer here.

### Phase B — Convergence loop runner (Plan 48 graduation)

**Goal:** Wire the existing `dispatch/convergence.py` scaffold so that task type `convergence_loop` runs a deterministic iteration loop with a declarative exit condition.

**Files:**
- `modules/backend/agents/mission_control/dispatch/convergence.py` (existing — finish wiring)
- `modules/backend/agents/mission_control/dispatch/loop.py` (extend dispatch switch)
- `modules/backend/schemas/task_plan.py` (add `convergence_loop` task type + `convergence_condition` field)
- `modules/backend/events/types.py` (add `ConvergenceCycleStartedEvent`, `ConvergenceCycleCompletedEvent`, `ConvergenceLoopConvergedEvent`, `ConvergenceLoopAbortedEvent`)

**Exit condition language (v1):**
- `score_threshold`: `{type: "score_threshold", source_field: "pqi.composite_score", threshold: 70.0, comparator: ">="}`
- `boolean_predicate`: `{type: "boolean_predicate", source_field: "tests.passed", expected: true}`
- `max_iterations`: `{type: "max_iterations", limit: 10}` (always combined with one of the above as a safety net)

The exit condition is evaluated after each inner iteration using the existing PQI service, the task output dict, or a simple Python expression. No LLM is used to check the condition — it's a mechanical evaluation.

**Acceptance:** A synthetic convergence_loop task with `score_threshold: {source: "mock.score", threshold: 50}` runs an inner agent that returns increasing scores on each iteration. The loop terminates at the first iteration where the score meets the threshold. Verified by extending or adding to the existing Plan 47 verifier. Plan 48's close-out gets the convergence loop phase marked done; branch automation + final verification stay deferred on Plan 48 as originally scoped.

### Phase C — Post-run Gate checkpoint

**Goal:** Extend the gate system to add the `post_run` checkpoint and new `GateAction` values, with `AutonomousPostRunReviewer` implementing the rules-first decision matrix. Also adds the `mission_plan.run.completed` event that the whole loop hangs off.

**Files:**
- `modules/backend/events/types.py` — new `MissionPlanRunCompletedEvent` class (`event_type = "mission_plan.run.completed"`, fields: `mission_id`, `plan_id`, `execution_record_id`, `run_status`, `run_cost_usd`, `completed_task_count`, `failed_task_count`, `total_spent_usd`) + add to `EVENT_TYPE_REGISTRY` dict
- `modules/backend/services/mission_plan.py` — **actual emission point**. After the existing `MissionPlanDispatchedEvent` emit in `dispatch_approved`, after write-back + cost update, emit `MissionPlanRunCompletedEvent` AND call `SessionFollowupService.fire_matching(event)` in-process. (The `MissionPlanDaemon` itself needs no changes — it just calls the service.)
- `modules/backend/models/execution_record.py` — add `POST_RUN_SUPERVISOR = "post_run_supervisor"` to the existing `DecisionType` enum (varchar-backed, no migration required)
- `modules/backend/agents/mission_control/gate_models.py` — new `GateAction` values (`WAIT`, `ADVANCE_APPROVED`, `ADVANCE_REFINE`, `PROPOSE_COMPLETE`, `ESCALATE`); new defaulted `GateContext` fields (`recent_run_outcomes`, `plan_task_summary`, `mission_brief`, `supervisor_iteration_count`); new optional `GateDecision.model_metadata` field. The existing `GateContext.total_cost_usd`/`budget_usd` and `GateDecision.reviewer` are reused verbatim.
- `modules/backend/agents/mission_control/gate_post_run.py` (new — `AutonomousPostRunReviewer`)
- `modules/backend/agents/mission_control/gate.py` (extend `ConfigurableGate` routing for `post_run` gate type)
- `config/settings/gate.yaml` (add `post_run` gate point config)
- `modules/backend/models/mission_plan.py` (new columns: `supervisor_iteration_count: int` default 0, `max_supervisor_iterations: int` default 20) + migration

**Acceptance:** All 7 rule-based branches of the decision matrix return correct `GateDecision` values without any LLM invocation, verified by a unit test with synthetic GateContext inputs. `MissionPlanRunCompletedEvent` is emitted by `MissionPlanService.dispatch_approved` on every dispatch and routes through `AutonomousPostRunReviewer.review()`. Branch #8 (the LLM branch) is stubbed as `raise NotImplementedError` — that's implemented in Phase D.

### Phase D — mission.supervisor agent

**Goal:** Haiku-class mission-tier agent that fulfills branch #8 (LLM classification) AND provides the user-facing chat surface.

**Files:**
- `config/agents/mission/supervisor/agent.yaml` (new)
- `config/prompts/agents/mission/supervisor/system.md` (new — event-mode prompt)
- `config/prompts/agents/mission/supervisor/chat.md` (new — chat-mode prompt)
- `modules/backend/agents/mission/supervisor/__init__.py` (new)
- `modules/backend/agents/mission/supervisor/agent.py` (new — `create_agent` factory, two pydantic-ai Agent instances sharing deps)
- `modules/backend/agents/mission/supervisor/deps.py` (new — `MissionSupervisorDeps` dataclass)
- `modules/backend/agents/mission/supervisor/models.py` (new — `SupervisorDecision` pydantic model for structured output)
- `modules/backend/agents/tools/supervisor_introspection.py` (new — `get_past_decisions`, `get_recent_run_outcomes`, `get_plan_state` tools)
- `modules/backend/agents/mission_control/gate_post_run.py` — wire the Haiku agent call into branch #8

**Acceptance:**
1. Event-mode: a synthetic branch #8 situation (plan exhausted, outcomes present, ambiguous) invokes the Haiku agent and returns a valid `SupervisorDecision` JSON. Verified end-to-end against the real Haiku API.
2. Chat-mode: opening `/missions/:id/chat` with `mission.supervisor` as the pinned agent allows asking "why did you escalate run X?" — the agent reads `get_past_decisions`, finds the decision, quotes the reason, explains in natural language.
3. Audit trail: both event-mode and chat-mode invocations log cost to `plan.total_spent_usd` via the standard agent executor path.
4. Chat mode does NOT make new decisions — it only explains past ones. Tested by asking "force advance" and confirming the agent refers the user to the Director instead.

### Phase E — Director followup integration

**Goal:** Director posts proactive chat messages in response to supervisor decisions, closing the user-visible feedback loop.

**Files:**
- `modules/backend/events/types.py` — new `SupervisorDecisionEmittedEvent` class (`event_type = "mission_plan.supervisor_decision"`, fields: `mission_id`, `plan_id`, `execution_record_id`, `action`, `reason`, `reviewer`) + register in `EVENT_TYPE_REGISTRY`
- `modules/backend/agents/mission_control/gate_post_run.py` — after writing the audit row in the reviewer, construct `SupervisorDecisionEmittedEvent` and call `SessionFollowupService.fire_matching(event)` (same in-process pattern Phase C uses for `MissionPlanRunCompletedEvent`)
- `modules/backend/agents/mission/director/agent.py` — new tool `schedule_run_completion_followup` (wraps the Phase A primitive with a Director-specific prompt template that registers a one-shot followup on `mission_plan.supervisor_decision`)
- `modules/backend/agents/mission/director/system.md` — prompt update: "When you dispatch a run, always schedule a followup to check back after the supervisor decides"

**Acceptance:** A user starts a mission in autonomous mode, walks away. The daemon dispatches wave 1. Wave 1 completes. The supervisor advances. The Director's followup fires. A new assistant message appears in the user's session chat ("Wave 1 complete. Cost $X. Wave 2 started with tasks Y, Z.") without the user typing anything. Verified by running a synthetic mission through to completion.

### Phase F — End-to-end verification

**Goal:** A real synthetic multi-wave mission exercises the full loop end-to-end.

**Files:**
- `scripts/verify_autonomy_loop.py` (new) — the acceptance test for the whole plan

The script:
1. Creates a synthetic mission with a 2-wave plan and `gate_mode = "autonomous"`
2. Dispatches wave 1 via the existing `MissionPlanService.dispatch_approved`
3. Asserts the supervisor fires, advances, and wave 2 dispatches automatically
4. After wave 2 completes, asserts the supervisor proposes completion and the Director posts a chat message
5. Runs through each circuit breaker in isolation:
   - Budget exhaustion path
   - Stall detection path
   - Duplicate task detection path
   - Max supervisor iterations path
6. Verifies gate_mode interaction: running the same mission in `interactive` mode never auto-advances
7. Verifies chat mode: opening a chat with `mission.supervisor` and asking a question about a past decision returns a coherent answer referencing the gate_decisions audit trail
8. Cleans up all synthetic rows after the run

**Acceptance:** `conda run -n mission-control python scripts/verify_autonomy_loop.py` exits 0 against real Redis + Postgres + Haiku API. Plan 51 is marked Done in its own header. Plan 46 Phase 3 exit criteria are updated to reference this verification script and marked as met.

---

## §6 Exit criteria

Plan 51 is Done when *all* of the following are observably true:

1. **Autonomy loop works end-to-end** on a real synthetic multi-wave mission: daemon dispatches → run completes → supervisor evaluates → advances → next wave dispatches → eventually proposes completion → Director posts chat updates throughout. Verified by `scripts/verify_autonomy_loop.py`.
2. **Circuit breakers fire independently** and each is individually tested: budget exhaustion, stall detection, duplicate detection, max supervisor iterations. Each verified by a dedicated check in the verification script.
3. **Gate mode respect:** the same mission in `interactive` mode always escalates instead of auto-advancing. Verified.
4. **Supervisor decisions are audited** via `execution_decisions` table rows with `decision_type = "post_run_supervisor"`. Query confirms decisions from the verification run are readable.
5. **Chat mode works:** the mission owner can open a chat with `mission.supervisor.agent`, ask "explain your last decision", and receive a natural-language answer that cites the audit trail. No new decisions are made in chat mode.
6. **In-app Director updates:** after a supervisor-driven advance, a new assistant message appears in the mission's Chat tab without user action, visible via the SSE stream.
7. **Cost budget:** total LLM cost of the supervisor across the verification run (which includes 4+ supervisor wakes) is under $0.05. Haiku class confirmed by reading the model field in the logged decisions.
8. **Plan 48 Phase 6** (convergence loop runner) is wired and verified; Plan 48's other phases remain deferred as originally scoped.
9. **TODO.md "Director proactive follow-up"** entry is marked `[x] DONE` with a pointer to this plan's Phase A.
10. **Plan 46 Phase 3** is marked Complete, its work units updated to reference this plan's phases, and its exit criteria updated to the ones above (instead of the original Telegram-focused ones).
11. **Plan 51 is marked Done** in its own header with a close-out note listing the commit hashes.

---

## §7 What this plan does NOT do

Explicit scope cuts. None of these are future commitments — they're places we deliberately chose not to go.

- **No Telegram notification channel.** Deferred. In-app Director chat updates cover v1 conversational continuity. Telegram becomes a future enhancement for "ping me when I'm not in the app".
- **No workflow step supervisor.** Plans 44/45 territory. If a plan task is a workflow invocation (Plan 44), the supervisor treats the whole workflow as a single task black-box. It doesn't supervise inside workflows.
- **No cross-mission learning.** The supervisor has no memory beyond its own mission's audit trail. Lessons from one mission do not influence another.
- **No mission objective classification or templates.** The supervisor doesn't categorize missions as "code", "research", "writing" etc. It makes the same rule-based routing decisions for all mission types and delegates type-specific reasoning to the Planning Agent and Director.
- **No override via chat mode.** In v1, chatting with the supervisor is read-only: the user can ask questions about past decisions but cannot force new ones. Overriding a decision means opening a chat with the Director instead, who has the write tools. Add chat-mode overrides in v2 if needed.
- **No auto-mark-complete.** The supervisor never unilaterally flips `mission_plans.status` to `completed`. Completion always requires human confirmation via the Director.
- **No adaptive circuit breakers.** The four breakers use fixed defaults (20 iterations, 3-wave stall, etc). Tuning them based on mission type or history is a future enhancement.
- **No supervisor for missions in `off` mode that have zero approved tasks.** The supervisor only wakes on `mission_plan.run.completed`. If a mission has never dispatched a run, it has nothing to supervise. Initial plan creation is the user's responsibility via the Director.
- **No replacement for the Gate system's other checkpoints.** `pre_dispatch`, `pre_layer`, `post_task`, `verification_failed`, `post_layer` all remain unchanged. The supervisor only adds a new checkpoint, not a replacement for existing ones.

---

## §8 Open questions — decisions already made

Five questions from the other-chat design doc, resolved:

**Q1: Who defines "mission complete"?**
A: Humans only, for v1. The supervisor never unilaterally marks complete. Branch #8's `PROPOSE_COMPLETE` delegates to the Director, which asks the user to confirm. This is the non-negotiable runaway-mission safeguard.

**Q2: Where does convergence.py fit?**
A: They compose. Convergence is intra-task (edit → test → fix until a scalar threshold is met, within one task). Supervisor is inter-task (wave finished → decide what to run next, across the whole plan). Different layers. Plan 48 Phase 6 graduates the convergence loop runner; this plan's supervisor never supervises inside a convergence loop.

**Q3: Budget for supervisor invocations?**
A: No separate budget. Supervisor LLM cost is mission spend, attributed to `mission_plans.total_spent_usd` via the standard agent executor path. Circuit breaker #4 (budget headroom) catches runaway spend before dispatch is authorized. Haiku class makes supervisor costs negligible anyway.

**Q4: Gate mode interaction?**
A: Hard rule: supervisor respects `gate_mode`. In `off`/`autonomous`, advances freely. In `ai_assisted`, advances with a veto window. In `interactive`, always escalates. The rule is enforced *before* the supervisor's reviewer is even invoked — the post-run handler short-circuits to `ESCALATE` when `gate_mode == "interactive"`. See §4.7.

**Q5: Failure modes / runaway detection?**
A: Four independent circuit breakers in §4.6, all deterministic and evaluated before any LLM call. Any one breaker tripping forces `ESCALATE`, not advancement. The supervisor cannot disable or override any breaker — they're gate-level rules, not supervisor decisions.

---

## §9 References

### Plan docs

- [Plan 22 — Step-Through Gate (X — done)](22-plan-step-through-gate-[X].md) — the gate protocol this plan extends
- [Plan 42 — Mission Backlog Model](42-plan-mission-backlog-model.md) — §10.4 gate_mode, §10.5 write-back, §10.7 budget enforcement, all reused
- [Plan 43 — Persistent Mission Artifacts](43-plan-persistent-mission-artifacts.md) — artifacts the supervisor reads when reasoning about completion
- [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) — this plan is the new Phase 3
- [Plan 48 — Convergence Loop + Branch Automation](48-plan-convergence-loop-and-branch-automation.md) — Phase 6 graduates as part of Phase B here

### Files this plan creates

Backend:
- `modules/backend/migrations/versions/<date>_phase3_session_followups.py`
- `modules/backend/models/session_followup.py`
- `modules/backend/repositories/session_followup.py`
- `modules/backend/services/session_followup.py`
- `modules/backend/agents/mission/supervisor/__init__.py`
- `modules/backend/agents/mission/supervisor/agent.py`
- `modules/backend/agents/mission/supervisor/deps.py`
- `modules/backend/agents/mission/supervisor/models.py`
- `modules/backend/agents/mission_control/gate_post_run.py`
- `modules/backend/agents/tools/followup.py`
- `modules/backend/agents/tools/supervisor_introspection.py`

Config:
- `config/agents/mission/supervisor/agent.yaml`
- `config/prompts/agents/mission/supervisor/system.md`
- `config/prompts/agents/mission/supervisor/chat.md`

Scripts:
- `scripts/verify_followup_primitive.py` (Phase A acceptance)
- `scripts/verify_autonomy_loop.py` (Phase F acceptance)

### Files this plan modifies

- `modules/backend/agents/mission_control/gate_models.py` — new `GateAction` values + defaulted `GateContext` fields + optional `GateDecision.model_metadata`
- `modules/backend/agents/mission_control/gate.py` — route `post_run` gate type in `ConfigurableGate`
- `modules/backend/agents/mission_control/dispatch/convergence.py` — wire the existing scaffold
- `modules/backend/agents/mission_control/dispatch/loop.py` — dispatch switch for `convergence_loop` task type
- `modules/backend/agents/mission/director/agent.py` — new `schedule_run_completion_followup` tool
- `modules/backend/schemas/task_plan.py` — new `convergence_loop` task type + exit condition schema
- `modules/backend/services/mission_plan.py` — emit `MissionPlanRunCompletedEvent` at the end of `dispatch_approved` + in-process call to `SessionFollowupService.fire_matching(event)`
- `modules/backend/models/execution_record.py` — add `POST_RUN_SUPERVISOR` to `DecisionType` enum
- `modules/backend/models/mission_plan.py` — new `supervisor_iteration_count` + `max_supervisor_iterations` columns (with migration)
- `modules/backend/events/types.py` — new `MissionPlanRunCompletedEvent` (Phase C), `SessionFollowupFiredEvent` (Phase A), `SupervisorDecisionEmittedEvent` (Phase E) + `EVENT_TYPE_REGISTRY` entries
- `config/settings/gate.yaml` — `post_run` gate point config
- `docs/97-plans/46-plan-autonomous-mission-roadmap.md` — Phase 3 reframing
- `docs/97-plans/48-plan-convergence-loop-and-branch-automation.md` — mark Phase 6 graduated

Files the plan does **not** touch: `modules/backend/services/mission_plan_daemon.py` (it calls the service, which owns emission) and `modules/backend/events/bus.py` (in-process `fire_matching` avoids needing a `subscribe_to_all_missions` method for v1).

### TODO items closed

- `TODO.md` *"Director proactive follow-up: wake on completion events"* — folded into Phase A, mark done when Phase A lands
