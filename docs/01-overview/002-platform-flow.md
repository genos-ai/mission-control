# Platform Flow: End-to-End Execution Model

*How work flows through the Mission Control agentic platform — from every entry point to task execution and back.*

*Updated: 2026-04-23 — Reflects current architecture including autonomy loop (Plan 51), Plan 62 unified execution, Temporal-backed dispatch, and SSE event streaming.*

---

## Overview

The platform executes work through a three-layer chain:

```
Mission → Mission Control → Agents
```

Each layer has a clear responsibility, a distinct identity, and well-defined boundaries. Work flows **down** through planning and dispatch. Results flow **back up** through persistence, context updates, and knowledge extraction.

Four entry points feed work into this chain:

| Entry Point | Path | Latency | Use Case |
|-------------|------|---------|----------|
| **CLI** (`mc.py`) | REST API calls | Blocking or polling | Developer workflow, scripting |
| **Web Frontend** | REST API + SSE streaming | Real-time | Interactive workspace |
| **Director Agent** (chat) | `handle()` → tools | In-process | Conversational orchestration |
| **Temporal Schedules** | Workflow activities | Background | Autonomous iteration, maintenance |

---

## Entry Points

### CLI (`mc.py`)

Thin client — all commands go through `CliApiClient` → REST API. No backend imports.

```
mc login                          → POST /auth/login
mc mission create                 → POST /missions
mc mission list                   → GET /missions
mc mission use <name>             → PUT /auth/me/current-mission
mc mission info                   → GET /missions/:id + GET /missions/:id/team
mc mission set-gate <mode>        → PATCH /missions/:id/plan  {gate_mode}
mc mission archive / unarchive    → PATCH /missions/:id  {status}
mc mission delete                 → DELETE /missions/:id

mc run "objective"                → POST /missions/:id/plan/run-objective  {async_dispatch: true}
                                    (polls GET /missions/:id/plan for progress)
mc retry --run N                  → POST /plan/tasks/:id/retry (per failed task)
                                    → POST /missions/:id/plan/dispatch

mc chat [-m "message"]            → POST /sessions (create)
                                    → POST /sessions/:id/messages (SSE streaming response)
mc design [-d "description"]      → POST /missions/:id/architect/chat

mc status                         → GET /missions/:id + GET /missions/:id/plan
                                    + GET /executions?mission_id=X&limit=1
mc history                        → GET /executions?mission_id=X&limit=20

mc team list / add / remove       → GET/POST/DELETE /missions/:id/team
mc team available                 → GET /catalog/agents

mc context show                   → GET /missions/:id/context
mc context history                → GET /missions/:id/context/history

mc intent show / set / history    → GET/POST /missions/:id/intent
mc learnings list / show          → GET /missions/:id/learnings
mc knowledge search               → GET /knowledge/search

mc console monitor                → GET /streams/runs/:sessionId (SSE)
```

### Web Frontend

All API calls go through `lib/api.ts` → `/api/v1/*`. Auth via Bearer token with automatic refresh on 401. SSE uses single-use token exchange (`POST /auth/sse-token`).

**Mission workspace actions:**

| UI Action | API Call | Real-Time Update |
|-----------|----------|-----------------|
| Send chat message | `POST /sessions/:id/messages` | SSE inline in response body |
| Click "Run" on plan board | `POST /missions/:id/plan/dispatch` | SSE `mission_plan.*` events |
| Click "Run" (autonomous) | `POST /missions/:id/plan/dispatch?autonomous=true` | Starts Temporal workflow |
| Refine plan | `POST /missions/:id/plan/refine` | Returns updated plan |
| Approve task | `POST /plan/tasks/:id/approve` | SSE `mission_plan.task_transitioned` |
| Reject task | `POST /plan/tasks/:id/reject` | SSE cascade cancellation |
| Retry failed task | `POST /plan/tasks/:id/retry` | Task → approved |
| Add task manually | `POST /missions/:id/plan/tasks` | Returns updated plan |
| Pause/resume plan | `PATCH /missions/:id/plan` `{status}` | SSE plan status change |
| Run objective (Plan 62) | `POST /missions/:id/plan/run-objective` | Refine + approve + dispatch in one call |
| Import workflow | `POST /missions/:id/workflows/import` | Clones template |
| Run workflow | `POST /missions/:id/workflows/:name/run` | Fire-and-forget |
| Design workflow | `POST /missions/:id/architect/chat` | Conversational iteration |

**SSE subscriptions (always-on per mission):**

```
GET /streams/missions/:id        → All mission events (plan, execution, agent, system)
GET /streams/runs/:sessionId     → Session-scoped events (run detail)
GET /streams/notifications       → User-level alerts (approvals, completions, budget warnings)
```

---

## Core Execution Flows

### Flow 1: Chat Path (`handle()`)

User-initiated, in-process, low latency. The Director agent responds in conversation and can invoke tools that trigger execution.

```
User sends message (CLI or web)
│
├── POST /sessions/:id/messages
│   ├── Persist user message to session
│   └── Spawn background task: _run_agent()
│
└── _run_agent()
    └── handle(session_id, message, agent_id="mission.director.agent")
        │
        ├── Director (Opus 4.6) responds in chat via SSE chunks
        │   Events: agent.thinking.started → agent.response.chunk (N) → agent.response.complete
        │
        └── Director tools (called mid-turn):
            ├── refine_plan         → MissionPlanService.refine() → Planning Agent
            ├── approve_plan_tasks  → MissionPlanService.approve_task() + schedule followup
            ├── run_objective       → MissionPlanService.run_objective(async_dispatch=True)
            │                         → starts MissionRunWorkflow (Temporal)
            ├── run_workflow         → WorkflowRunService.run_workflow()
            ├── capture_mission_intent → MissionIntentService.create()
            ├── get_plan            → MissionPlanService.get_or_create_plan()
            └── knowledge_query     → KnowledgeService.search()
```

### Flow 2: Execution Path (`handle_mission()`)

Temporal-backed, durable. Planning Agent decomposes objectives into a TaskPlan DAG, dispatch loop executes tasks in topological order.

```
Trigger: dispatch_approved() or run_objective()
│
└── handle_mission(precomputed_plan, prior_outputs)
    │
    ├── 1. Load Roster (which agents are on the team)
    │
    ├── 2. Planning Agent → TaskPlan (if no precomputed_plan)
    │      tasks: [{task_id, agent, description, instructions, inputs, dependencies}]
    │
    ├── 3. Context Assembly (per task)
    │      Layer 0: MCD (always, never trimmed)
    │      Layer 1: Task definition + resolved upstream inputs
    │      Layer 2.5: Learnings (mission + platform-promoted)
    │      Layer 3: Code Map (for coding tasks)
    │      Layer 2: History (recent failures, past executions)
    │
    ├── 4. dispatch() → topological sort → parallel within each layer
    │      For each task:
    │        execution_id = uuid4()
    │        _execute_with_retry()
    │          attempt 0 → agent.run() → verify_task() (3-tier)
    │          attempt 1 → agent.run(+feedback) → verify_task()
    │          ...up to retry_budget
    │        → TaskResult {task_id, status, output_reference, context_updates}
    │
    ├── 5. persist_mission_results()
    │      ExecutionRecord → TaskExecution → TaskAttempt
    │      MissionArtifact (summary/finding/code from outputs)
    │
    ├── 6. ContextCurator.apply_task_updates() → MCD patched
    │
    └── 7. Build ExecutionOutcome
```

### Flow 3: Unified Execution (`run_objective` — Plan 62)

Single entry point for all execution — CLI, chat, frontend. Refines a plan from an objective and dispatches it.

```
POST /missions/:id/plan/run-objective {objective, async_dispatch, gate_mode, budget}
│
└── MissionPlanService.run_objective()
    │
    ├── 1. get_or_create_plan()
    ├── 2. Apply overrides (gate_mode, budget)
    ├── 3. Concurrency guard (reject if tasks in-flight)
    ├── 4. refine() → Planning Agent decomposes objective → TaskPlan
    ├── 5. Auto-approve (unless gate_mode=interactive → return awaiting_approval)
    │
    └── 6. Dispatch:
        ├── async_dispatch=true (chat/frontend):
        │   ├── Temporal available:
        │   │   → _start_temporal_run_workflow() → MissionRunWorkflow
        │   │   → Returns immediately {outcome_status: "dispatching", workflow_id}
        │   └── Temporal unavailable:
        │       → Returns {outcome_status: "temporal_unavailable"} (never blocks)
        │
        └── async_dispatch=false (CLI sync mode):
            → dispatch_approved() inline → blocks until complete
            → Returns {outcome_status, total_cost_usd, dispatched_task_ids}
```

### Flow 4: Autonomy Loop (`MissionRunWorkflow`)

When `async_dispatch=true` or `dispatch?autonomous=true`, the Temporal `MissionRunWorkflow` handles multi-wave autonomous execution.

```
Entry points:
  1. run_objective(async_dispatch=True) → Director tool or CLI
  2. POST /plan/dispatch?autonomous=true → Frontend Run button
  3. ScheduledMissionCheckWorkflow (every 1s) → finds plans with approved tasks
│
└── MissionRunWorkflow (up to 25 iterations):
    │
    ├── 1. execute_mission activity
    │      → dispatch_approved(skip_post_run_supervisor=True)
    │      → handle_mission(precomputed_plan, prior_outputs)
    │      → Returns MissionExecutionResult
    │
    ├── 2. persist_mission_outcome activity → ExecutionRecord
    │
    ├── 3. evaluate_post_run activity → AutonomousPostRunReviewer
    │      7 deterministic branches + 1 Haiku fallback
    │      4 circuit breakers: budget, max iterations, stall, budget headroom
    │
    ├── 4. fire_supervisor_followups activity
    │      → Emits MissionPlanRunCompletedEvent + SupervisorDecisionEmittedEvent
    │      → Fires matching session followups → Director wakes, reports to user
    │
    ├── 5. check_plan_active → stop if plan was paused externally
    │
    └── 6. Route decision:
        ├── WAIT              → sleep 1s, loop (approved tasks still pending)
        ├── ADVANCE_APPROVED  → approve_proposed_tasks activity, loop
        ├── ADVANCE_REFINE    → start_director_turn activity (ChatTurnWorkflow)
        │                       → Director calls refine_plan + approve
        │                       → ChatTurnWorkflow signals refinement_complete
        │                       → Check for new tasks, loop
        ├── PROPOSE_COMPLETE  → start_director_turn (notify user), break
        │                       (plan stays active — idle plan costs nothing)
        └── ESCALATE          → start_director_turn + notification, pause plan, break
```

**Inline supervisor fallback.** When Temporal is unavailable, `dispatch_approved()` runs the supervisor inline (single evaluation, no looping). The inline path handles one wave + one decision then returns — the user must trigger the next wave manually.

**Cross-wave result flow.** Task outputs are persisted as JSON in `plan_task_states.result_summary`. When a new wave dispatches, `_load_prior_outputs()` reads completed task results and passes them to `dispatch()` via `prior_outputs`, so `from_upstream` references resolve across separate dispatch calls.

---

## SSE Event Flow

Events flow from agent execution through Redis Pub/Sub to frontend SSE streams.

```
Agent executes
│
├── SessionEventBus.publish(event)
│   └── Redis Pub/Sub: mission_events:{mission_id}
│
├── DB persistence (selective — blacklist excludes agent.response.chunk, session.cost.update)
│   └── mission_events table
│
└── SSE endpoints (subscribe to Redis channel):
    ├── /streams/missions/:id     → All events for mission (workspace tabs)
    ├── /streams/runs/:sessionId  → Session-filtered events (run detail)
    └── /streams/notifications    → User-scoped alerts (notify:{user_id} channel)
```

**Frontend event processing:**
1. `useMissionStream(missionId)` subscribes via `api.sse()` (token-exchanged)
2. Events decoded from `data: {...}` SSE lines
3. Fan into Zustand stores:
   - `useWorkspaceStore.onSseEvent()` → `agentStatuses`, `liveTaskOverlay`, `streamingArtifact`
   - `useConsoleStore.addEvent()` → console timeline
4. Query invalidation triggers:
   - `mission_plan.*` → refetch `GET /missions/:id/plan`
   - `mission.artifact.found` → refetch `GET /missions/:id/artifacts`

**Key event types:**

| Event | Source | Purpose |
|-------|--------|---------|
| `agent.thinking.started` | Agent executor | Show "thinking" spinner |
| `agent.tool.called` | Agent executor | Show current tool in UI |
| `agent.response.chunk` | Agent executor | Stream chat text (NOT persisted) |
| `agent.response.complete` | Agent executor | Final response (persisted) |
| `plan.step.started` | Dispatch loop | Task running indicator |
| `plan.step.completed` | Dispatch loop | Task done with cost |
| `mission_plan.task_transitioned` | MissionPlanService | Task state change (approve/reject/complete) |
| `mission_plan.dispatched` | MissionPlanService | Wave started |
| `mission_plan.run.completed` | Post-run supervisor | Wave finished |
| `mission_plan.supervisor_decision` | Post-run supervisor | Supervisor chose action |
| `mission.artifact.found` | persist_mission_results | New artifact |
| `system.execution.created` | Execution service | Run started |
| `system.execution.completed` | Execution service | Run finished |

---

## API Surface

### Router Structure

All endpoints mounted under `/api/v1`. Auth via Bearer token (JWT) or API key.

| Prefix | Module | Purpose |
|--------|--------|---------|
| `/auth` | auth.py | Login, token refresh, SSE token exchange, API keys |
| `/missions` | missions.py + sub-routers | Mission CRUD, plan, team, context, artifacts, costs, workflows |
| `/sessions` | sessions.py | Session CRUD, message sending (SSE streaming) |
| `/executions` | executions.py | Execution records, dispatch, approval signals |
| `/workflows` | workflows.py | Workflow templates, ad-hoc execution |
| `/catalog/agents` | catalog.py | Public agent catalog |
| `/streams` | streams.py | SSE event streams (3 endpoints) |
| `/knowledge` | knowledge.py | Platform knowledge search |
| `/admin` | admin.py + admin_users.py | Catalog management, metrics, user management, emergency stop |
| `/agents` | agents.py | Agent chat (streaming + non-streaming) |
| `/workshop` | workshop.py | Single-agent sandbox testing |
| `/notes` | notes.py | Note CRUD |
| `/client-errors` | client_errors.py | Frontend error reporting |

### Key Execution Endpoints

| Method | Path | Purpose | Blocking? |
|--------|------|---------|-----------|
| POST | `/missions/:id/plan/run-objective` | Plan 62: refine + approve + dispatch | Sync or async |
| POST | `/missions/:id/plan/dispatch` | Dispatch approved tasks | Sync (default) or Temporal (`?autonomous=true`) |
| POST | `/missions/:id/plan/refine` | Planning Agent generates tasks | Sync |
| POST | `/sessions/:id/messages` | Send chat message | SSE streaming response |
| POST | `/missions/:id/workflows/:name/run` | Run workflow | Fire-and-forget |
| POST | `/executions/:id/execute` | Start queued execution | Background task |
| POST | `/admin/dispatch/emergency-stop` | Pause all autonomous plans | Immediate |

### Response Envelope

Every endpoint returns `ApiResponse`:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "metadata": { "request_id": "..." }
}
```

Frontend unwraps via `json.data`. CLI unwraps identically.

---

## Multi-Step Orchestration: Workflows

Workflows are mission-scoped multi-step recipes with data flow between steps.

- **Template-seeded** — system templates in `config/workflow_templates/` seed on boot
- **Clone-to-use** — templates cloned into a mission before execution (`POST /missions/:id/workflows/import`)
- **Agent-designable** — Workflow Architect creates them in conversation (`POST /missions/:id/architect/chat`)
- **Schedulable** — cron schedules via `POST /missions/:id/schedules`

```
Template (YAML on disk)
  → Import to mission (DB row)
    → Run: WorkflowRunService.run_workflow()
      → For each step: handle_mission(step.brief)
        → Agent executes → TaskResult
```

Current executor (`workflow_run.py`) is agent-only — every step runs through `handle_mission()`. Phase 5 of the roadmap (Plans 44+45) will add a rich node schema (`AgentNode | ToolCallNode | ConditionNode | HumanInputNode`) and a React Flow visual editor.

---

## Temporal Workflow Catalog

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| **ScheduledMissionCheckWorkflow** | Every 1s | Find approved plans, start MissionRunWorkflow |
| **MissionRunWorkflow** | On-demand (child) | Autonomy loop: execute → supervisor → route → repeat |
| **AgentMissionWorkflow** | On-demand (child) | Legacy single-run with approval signals |
| **ChatTurnWorkflow** | On-demand (child) | Persist message + execute Director turn |
| **DesignWorkflowWorkflow** | On-demand (child) | Workflow design via Planning Agent |
| **RunWorkflowWorkflow** | On-demand (child) | Execute a designed workflow |
| **DailyCleanupWorkflow** | 02:00 UTC daily | DB cleanup |
| **HourlyHealthCheckWorkflow** | Hourly | Health checks |
| **WeeklyReportWorkflow** | Sunday 06:00 UTC | Weekly report |
| **MetricsAggregationWorkflow** | Every 15 min | Aggregate metrics |
| **CleanupEnvironmentsWorkflow** | Hourly | Stale container cleanup |
| **EvaluateWorkflowSchedulesWorkflow** | Every minute | Check workflow cron triggers |
| **KnowledgeExtractionWorkflow** | 03:30 UTC daily | Extract learnings from task history |
| **KnowledgeOfficerWorkflow** | 04:00 UTC daily | Curate knowledge base |
| **EmbeddingBackfillWorkflow** | 04:15 UTC daily | Backfill vector embeddings |

---

## Layer-by-Layer Breakdown

### Layer 1: Mission

The **domain primitive**. Everything belongs to a mission — sessions, executions, plans, context, history, learnings, intent.

```
Mission
├── id: UUID
├── name: "auth-refactor"
├── brief: "..."                    ← Detailed objective (seeds initial intent)
├── owner_id: "user:alice"
├── status: ACTIVE | PAUSED | ARCHIVED
├── gate_mode: off | interactive | ai_assisted | autonomous
├── tier: user | system
├── budget_ceiling_usd: 10.0
└── default_roster: "default"
```

### Layer 2: Mission Control

The **orchestration brain**. Routes messages to agents, enforces budgets, streams events.

Two paths:
- **Chat path** (`handle()`) — user-initiated, in-process, low latency. Director agent responds in conversation, can invoke tools.
- **Execution path** (`handle_mission()`) — Temporal-backed. Planning Agent decomposes into TaskPlan, dispatch loop executes tasks in topological order.

### Layer 3: Agent Execution

Individual **specialist agents** execute tasks. Each is a PydanticAI agent with YAML config, layered system prompt, and defined interface.

```
_execute_with_retry(task, agent)
│
├── execution_id = uuid4()
├── Attempt 0: agent.run() → verify_task() (3-tier)
├── Attempt 1: agent.run(+feedback) → verify_task()
└── Exhausted? → TaskResult(status=FAILED)
```

---

## Identity Model

```
┌──────────────────────────────────────────────────────────────┐
│ Layer   ID              Assigned By          Scope            │
├──────────────────────────────────────────────────────────────┤
│ 1       mission.id      Database (UUID)      Per mission      │
│ 2       task_id         Planning Agent (LLM) Within TaskPlan  │
│ 3       execution_id    Dispatch loop (code) Global           │
└──────────────────────────────────────────────────────────────┘
```

- `task_id` (layer 2) — LLM-assigned label like `"scrape-arxiv"`. Used for DAG dependencies within a TaskPlan. Not stable across runs.
- `execution_id` (layer 3) — code-assigned UUID. Globally unique. Use for monitoring, log correlation, tracing.

---

## Data Flow: Down and Back Up

### Downward: Planning & Dispatch

```
User creates mission (CLI / web / Director)
  → MissionService.create_mission() + seed MCD + seed Intent
    → mc run "objective" OR Director run_objective tool OR workflow step
      → MissionPlanService.run_objective()
        → PlanningAgent.run() → TaskPlan
          → dispatch_approved() → handle_mission(precomputed_plan)
            → dispatch() → execute tasks in topological order
```

### Upward: Results & Knowledge

```
Agent returns output
  → verify_task() (3-tier)
    → TaskResult (with execution_id + context_updates)
      → persist_mission_results() → ExecutionRecord + TaskExecution + TaskAttempt
      → ContextCurator.apply_task_updates() → MCD updated
      → MissionArtifact extracted (summary/finding/code)
      → MissionLearningExtractor → learnings from failures (daily batch)
      → embed_source → vector embedding for hybrid search
```

---

## Persistence Model

```
ExecutionRecord                        ← One per mission execution
├── id: UUID
├── mission_id: UUID
├── session_id: UUID
├── status: pending → running → completed | failed
│
├── TaskExecution                      ← One per task
│   ├── execution_id: UUID
│   ├── task_id: "scan-auth"
│   ├── agent_name: "software.quality.agent"
│   ├── cost_usd: 0.03
│   │
│   └── TaskAttempt                    ← One per retry attempt
│       ├── attempt_number: 0
│       ├── status: passed | failed
│       ├── failure_reason: "..."
│       └── feedback_provided: "..."
│
├── MissionArtifact                    ← Extracted deliverables
│   ├── artifact_type: report | finding | code | data | file
│   └── content: {...}
│
└── MissionLearning                    ← Extracted patterns (Plan 57)
    ├── kind: failure_pattern | retry_strategy
    ├── confidence: 0.85
    └── recommendation: "..."

MissionPlan                            ← Long-lived backlog (Plan 42)
├── task_plan_json: TaskPlan           ← DAG of tasks
├── task_states: [PlanTaskState]       ← Per-task status across runs
│   ├── status: proposed → approved → queued → running → completed | failed
│   ├── cost_usd, duration_seconds     ← Denormalized from TaskExecution
│   └── result_summary                 ← JSON output for cross-wave flow
├── gate_mode: off | interactive | ai_assisted | autonomous
├── budget_usd_ceiling / total_spent_usd
└── supervisor_iteration_count
```

---

## Knowledge Platform (Plan 57)

Five surfaces, one query service:

| Surface | Table | Scope | Purpose |
|---|---|---|---|
| MCD | `mission_contexts` | Mission | Living knowledge brief — always loaded |
| Intent | `mission_intents` | Mission | Event-sourced goal revisions |
| Learnings | `mission_learnings` | Mission → platform | Extracted failure/success patterns |
| Decisions | `mission_decisions` | Mission | Archived from MCD pruning |
| Milestones | `milestone_summaries` | Mission | Compressed execution history |

Cross-mission: learnings promoted via `platform_promoted=true` (sysadmin-gated).

---

## Cost Control

Budget enforcement at three levels:

```
Mission.budget_ceiling_usd            ← Per-mission budget (propagated to plan)
  └── MissionPlan.budget_usd_ceiling  ← Per-plan budget (checked before each dispatch)
        └── Session.cost_budget_usd   ← Per-session budget
              └── dispatch() tracks cumulative cost
                    └── Supervisor circuit breakers:
                        ├── Budget exhaustion (spent >= ceiling)
                        ├── Budget headroom (estimated next wave > remaining)
                        ├── Max iterations (25 hard cap)
                        └── Stall detection (consecutive zero-completion waves)
```

Every LLM call recorded in `llm_calls` table with agent name, model, mission_id, token counts, and cost. Admin metrics dashboard provides per-agent breakdown.

---

## Key Files

| Concern | File |
|---------|------|
| **Entry points** | |
| CLI entry point | `mc.py` |
| CLI handlers (thin) | `modules/clients/cli/mc_run.py`, `mc_chat.py`, `mc_mission.py`, etc. |
| Frontend API client | `modules/frontend/src/lib/api.ts` |
| API v1 router assembly | `modules/backend/api/v1/__init__.py` |
| App setup + lifespan | `modules/backend/main.py` |
| **Orchestration** | |
| Mission Control handle/handle_mission | `modules/backend/agents/mission_control/mission_control.py` |
| Dispatch loop | `modules/backend/agents/mission_control/dispatch/` |
| Planning Agent | `modules/backend/agents/system/planning/agent.py` |
| Director Agent | `modules/backend/agents/mission/director/agent.py` |
| Supervisor Agent | `modules/backend/agents/mission/supervisor/agent.py` |
| Post-run gate (8-branch) | `modules/backend/agents/mission_control/gate_post_run.py` |
| **Services** | |
| Mission lifecycle | `modules/backend/services/mission.py` |
| Plan service (CRUD + refine) | `modules/backend/services/mission_plan.py` |
| Plan dispatch mixin | `modules/backend/services/mission_plan_dispatch.py` |
| Workflow definitions | `modules/backend/services/workflow_definition.py` |
| Workflow execution | `modules/backend/services/workflow_run.py` |
| Session service | `modules/backend/services/session.py` |
| Knowledge service | `modules/backend/services/knowledge.py` |
| Context assembler | `modules/backend/services/context_assembler.py` |
| **Temporal** | |
| MissionRunWorkflow (autonomy loop) | `modules/backend/temporal/mission_run_workflow.py` |
| Supervisor activities | `modules/backend/temporal/supervisor_activities.py` |
| Mission execution activities | `modules/backend/temporal/activities.py` |
| Chat turn workflow | `modules/backend/temporal/chat_workflow.py` |
| Scheduled dispatch poll | `modules/backend/temporal/scheduled_workflow.py` |
| Temporal client factory | `modules/backend/temporal/client.py` |
| **Schemas** | |
| TaskPlan schema | `modules/backend/schemas/task_plan.py` |
| ExecutionOutcome | `modules/backend/agents/mission_control/outcome.py` |
| Plan API schemas | `modules/backend/schemas/mission_plan.py` |
| **Events** | |
| Event types | `modules/backend/events/types.py` |
| Event bus (Redis pub/sub) | `modules/backend/events/bus.py` |
| SSE streaming endpoints | `modules/backend/api/v1/endpoints/streams.py` |
| **Persistence** | |
| DB models | `modules/backend/models/` |
| Persistence bridge | `modules/backend/agents/mission_control/persistence_bridge.py` |
| Roster | `modules/backend/agents/mission_control/roster.py` |
| Agent configs | `config/agents/` |
| Workflow templates | `config/workflow_templates/` |
