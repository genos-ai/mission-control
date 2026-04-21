# Platform Flow: End-to-End Execution Model

*How work flows through the Mission Control agentic platform — from mission creation to task execution and back.*

*Updated: 2026-04-21 — Reflects current architecture including autonomy loop (Plan 51). Projects and playbooks removed (see ADR-005).*

---

## Overview

The platform executes work through a three-layer chain:

```
Mission → Mission Control → Agents
```

Each layer has a clear responsibility, a distinct identity, and well-defined boundaries. Work flows **down** through planning and dispatch. Results flow **back up** through persistence, context updates, and knowledge extraction.

**What changed from the original BFA design:** The original 5-layer chain (`Project → Playbook → Mission → Mission Control → Agents`) was simplified. Projects and playbooks were removed — missions are the domain primitive, workflows replaced playbooks, and cross-mission knowledge uses platform-scoped promotion instead of project grouping. See [ADR-005](../02-architecture/005-adr-mission-primitive-no-projects-playbooks.md) for the rationale.

---

## The Full Flow

```
Mission (id: UUID)                            ← The domain primitive
│
├── Session (id: UUID, mission_id)            ← Tracks cost, conversation history
│
├── MCD (mission_id, 1:1)                     ← Living knowledge brief (Mission Context Document)
│   ├── Updated after each task via context_updates
│   └── Loaded into every agent's context window
│
├── Intent (mission_id, append-only)          ← Evolving goal tracked as revisions
│   └── Current intent injected into Director every turn
│
├── Workflow (mission_id, optional)           ← Multi-step orchestration recipe
│   ├── Cloned from system template or designed by Workflow Architect
│   └── Steps executed sequentially via WorkflowRunService
│       └── Each step creates a Mission execution
│
├── handle() — Chat path (user-initiated)     ← In-process, low latency
│   └── Director agent responds in chat
│       ├── Can call tools: refine_plan, approve_plan_tasks, run_workflow, capture_mission_intent
│       └── Knowledge query tool for "has anyone seen this before?"
│
├── handle_mission() — Execution path         ← Temporal-backed, durable
│   │
│   ├── Planning Agent → TaskPlan
│   │   ├── mission_id: "mission-{UUID}"
│   │   └── tasks: [{task_id, agent, agent_version, description, instructions, inputs, dependencies, verification}]
│   │
│   ├── Context Assembly (per task)
│   │   ├── Layer 0: MCD (always, never trimmed)
│   │   ├── Layer 1: Task definition + resolved upstream inputs
│   │   ├── Layer 2.5: Learnings (mission + platform-promoted)
│   │   ├── Layer 3: Code Map (for coding tasks)
│   │   └── Layer 2: History (recent failures, past executions)
│   │
│   └── dispatch()
│       └── For each task (topological order, parallel within layer):
│           │
│           │  execution_id = uuid4()
│           │
│           ├── _execute_with_retry()
│           │   ├── attempt 0 → agent.run()
│           │   ├── verify_task() (3-tier verification)
│           │   ├── attempt 1 (if needed) → agent.run() with feedback
│           │   └── ...up to retry_budget
│           │
│           └── TaskResult
│               ├── task_id, execution_id, agent_name
│               ├── status: SUCCESS | FAILED
│               ├── output_reference: {...}
│               └── context_updates: [...]        ← MCD patches
│
│       ← persist_mission_results()
│           ├── ExecutionRecord (mission_id, session_id)
│           ├── TaskExecution (execution_id, task_id, agent_name)
│           │   └── TaskAttempt (attempt_number, failure_reason, feedback)
│           └── MissionArtifact (summary/finding/code from outputs)
│
│       ← MissionLearningExtractor (deterministic, daily + post-mission)
│           └── Extracts failure_pattern / retry_strategy from TaskAttempt history
│
│       ← ContextCurator.apply_task_updates()
│           └── Patches MCD with agent context_updates
│
└── Knowledge Platform (Plan 57)
    ├── MCD — living knowledge brief per mission
    ├── Intent — event-sourced goal revisions
    ├── Learnings — extracted failure/success patterns
    ├── Decisions — archived from MCD pruning
    ├── Milestones — compressed execution history
    ├── Embeddings — pgvector for hybrid search
    └── KnowledgeService — unified query facade
```

---

## Layer-by-Layer Breakdown

### Layer 1: Mission

The **domain primitive**. Everything belongs to a mission — sessions, executions, context, history, learnings, intent. Missions are created by users (via CLI, web, or Director) and carry the brief, team, workflows, and accumulated context.

```
Mission
├── id: UUID
├── name: "auth-refactor"           ← Human-readable, unique
├── description: "..."
├── brief: "..."                    ← Detailed objective (seeds initial intent)
├── owner_id: "user:alice"
├── status: ACTIVE | PAUSED | ARCHIVED
├── gate_mode: off | interactive | ai_assisted | autonomous
├── tier: user | system
├── budget_ceiling_usd: 10.0
└── default_roster: "default"       ← Which agents to use
```

**Key files:** `modules/backend/models/mission.py`, `modules/backend/services/mission.py`

### Layer 2: Mission Control

The **orchestration brain**. Routes messages to agents, enforces budgets, streams events. Infrastructure, not intelligence (P6).

Two paths:
- **Chat path** (`handle()`) — user-initiated, in-process, low latency. Director agent responds in conversation.
- **Execution path** (`handle_mission()`) — Temporal-backed. Planning Agent decomposes into TaskPlan, dispatch loop executes tasks in topological order.

```
handle_mission(mission)
│
├── 1. Load Roster
├── 2. Planning Agent → TaskPlan (DAG of tasks)
├── 3. Context Assembly (MCD + learnings + code map + history per task)
├── 4. Topological Sort → parallel layers
├── 5. Dispatch Loop → execute + verify + retry
├── 6. Persist results + extract learnings + update MCD
└── 7. Build ExecutionOutcome
```

**Key files:** `modules/backend/agents/mission_control/mission_control.py`, `modules/backend/agents/mission_control/dispatch/`

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

**Key files:** `modules/backend/agents/mission_control/helpers/`, agent configs in `config/agents/`

---

## Autonomy Loop (Plan 51)

When the plan's gate mode is `autonomous` or `off`, the platform iterates through
waves without human intervention. The loop is driven by Temporal:

```
ScheduledMissionCheckWorkflow (every 5s)
│
├── find_ready_plans() — plans with status=active, gate_mode in {autonomous, off},
│                        at least one approved task
│
└── For each ready plan → start MissionRunWorkflow
    │
    └── Loop (up to 25 iterations):
        │
        ├── 1. execute_mission → dispatch_approved(skip_post_run_supervisor=True)
        │      → handle_mission(precomputed_plan, prior_outputs)
        │      → dispatch() → execute tasks in parallel waves
        │
        ├── 2. persist_mission_outcome → ExecutionRecord
        │
        ├── 3. evaluate_post_run → AutonomousPostRunReviewer (rules-first, Haiku fallback)
        │      → 7 deterministic branches + 1 Haiku branch
        │      → 4 circuit breakers: budget, max iterations, stall, budget headroom
        │
        ├── 4. fire_supervisor_followups → emit events + wake Director
        │
        ├── 5. check_plan_active → stop if plan was paused externally
        │
        └── 6. Route decision:
            ├── WAIT              → sleep, loop (approved tasks pending)
            ├── ADVANCE_APPROVED  → approve proposed tasks, loop
            ├── ADVANCE_REFINE    → Director refines plan, approve new tasks, loop
            ├── PROPOSE_COMPLETE  → Director notifies user, break (plan stays active)
            └── ESCALATE          → Director notifies user, pause plan, break
```

**Single execution path.** The daemon dispatch loop was removed. Temporal
`MissionRunWorkflow` is the sole autonomous dispatch mechanism. A manual Run
button exists for single-wave dispatch without looping (interactive/ai_assisted
modes) — it calls `dispatch_approved()` directly with the inline supervisor.

**Cross-wave result flow.** Task outputs are persisted as JSON in
`plan_task_states.result_summary`. When a new wave dispatches, `_load_prior_outputs()`
reads completed task results and passes them to `dispatch()` via the `prior_outputs`
parameter, so `from_upstream` references resolve across separate dispatch calls.

**Key files:**
- `modules/backend/temporal/mission_run_workflow.py` — autonomy loop workflow
- `modules/backend/temporal/supervisor_activities.py` — evaluate, approve, followup activities
- `modules/backend/temporal/scheduled_workflow.py` — 5-second poll scheduler
- `modules/backend/agents/mission_control/gate_post_run.py` — 8-branch decision matrix
- `modules/backend/services/mission_plan_dispatch.py` — dispatch_approved + inline supervisor

---

## Multi-Step Orchestration: Workflows

Workflows replaced the original BFA playbook concept. They serve the same purpose — multi-step recipes with data flow between steps — but are:

- **Mission-scoped** (stored in DB per mission, not filesystem YAML)
- **Agent-designable** (Workflow Architect creates them in conversation)
- **Template-seeded** (system templates in `config/workflow_templates/` seed on boot)
- **Clone-to-use** (templates are cloned into a mission before execution)

```yaml
# config/workflow_templates/system.platform-audit.workflow.yaml
workflow_name: system.platform-audit.workflow
steps:
  - id: quality-scan
    brief: "Run PQI code quality scan"
    agent: software.quality.agent
  - id: health-check
    brief: "Check platform health"
    agent: platform.health.agent
    depends_on: []  # parallel with quality-scan
```

**Key files:** `modules/backend/services/workflow_run.py`, `modules/backend/services/workflow_definition.py`, `config/workflow_templates/`

---

## Identity Model

Three layers of identity:

```
┌──────────────────────────────────────────────────────────────┐
│ Layer   ID              Assigned By          Scope            │
├──────────────────────────────────────────────────────────────┤
│ 1       mission.id      Database (UUID)      Per mission      │
│ 2       task_id         Planning Agent (LLM) Within TaskPlan  │
│ 3       execution_id    Dispatch loop (code) Global           │
└──────────────────────────────────────────────────────────────┘
```

**Why two task-level IDs?**
- `task_id` (layer 2) — LLM-assigned label like `"scrape-arxiv"`. Used for DAG dependencies within a TaskPlan. Not stable across runs.
- `execution_id` (layer 3) — code-assigned UUID. Globally unique. Use for monitoring, log correlation, tracing.

---

## Data Flow: Down and Back Up

### Downward: Planning & Dispatch

```
User creates mission (CLI / web / Director)
  → MissionService.create_mission() + seed MCD + seed Intent
    → mc run "objective" OR workflow step
      → MissionControl.handle_mission()
        → PlanningAgent.run() → TaskPlan
          → dispatch() → execute tasks in topological order
```

### Upward: Results & Knowledge

```
Agent returns output
  → verify_task() (3-tier)
    → TaskResult (with execution_id + context_updates)
      → persist_mission_results() → ExecutionRecord + TaskExecution + TaskAttempt
      → ContextCurator.apply_task_updates() → MCD updated
      → MissionLearningExtractor → learnings extracted from failures
      → embed_source → vector embedding for hybrid search
```

---

## Persistence Model

```
ExecutionRecord                        ← One per mission execution
├── id: UUID
├── mission_id: UUID
├── session_id: UUID
├── objective_statement: "..."
├── status: pending → running → completed | failed
│
├── TaskExecution                      ← One per task
│   ├── execution_id: UUID             ← Global correlation ID
│   ├── task_id: "scan-auth"           ← LLM-assigned label
│   ├── agent_name: "software.quality.agent"
│   ├── domain_tags: ["auth", "quality"]
│   ├── cost_usd: 0.03
│   │
│   └── TaskAttempt                    ← One per retry attempt
│       ├── attempt_number: 0
│       ├── status: passed | failed
│       ├── failure_reason: "..."
│       └── feedback_provided: "..."
│
├── MissionArtifact                    ← Extracted deliverables
│   ├── artifact_type: report | finding | code
│   └── content: {...}
│
└── MissionLearning                    ← Extracted patterns (Plan 57)
    ├── kind: failure_pattern | retry_strategy
    ├── confidence: 0.85
    └── recommendation: "..."
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
Mission.budget_ceiling_usd            ← Per-mission budget (propagated to plan on creation)
  └── MissionPlan.budget_usd_ceiling  ← Per-plan budget (checked before each dispatch)
        └── Session.cost_budget_usd   ← Per-session budget
              └── dispatch() tracks cumulative cost
                    └── Supervisor circuit breaker: budget exhaustion + headroom check
```

Every LLM call recorded in `llm_calls` table with agent name, model, mission_id,
token counts, and cost. Cost dashboard provides per-agent breakdown.

---

## Key Files

| Concern | File |
|---------|------|
| Mission lifecycle | `modules/backend/services/mission.py` |
| Mission Control orchestration | `modules/backend/agents/mission_control/mission_control.py` |
| Dispatch loop | `modules/backend/agents/mission_control/dispatch/` |
| Planning Agent | `modules/backend/agents/system/planning/agent.py` |
| Agent executor | `modules/backend/agents/mission_control/helpers/` |
| TaskPlan schema | `modules/backend/schemas/task_plan.py` |
| ExecutionOutcome | `modules/backend/agents/mission_control/outcome.py` |
| Roster | `modules/backend/agents/mission_control/roster.py` |
| Persistence bridge | `modules/backend/agents/mission_control/persistence_bridge.py` |
| Context Assembler | `modules/backend/services/context_assembler.py` |
| Knowledge Service | `modules/backend/services/knowledge.py` |
| Workflow definitions | `modules/backend/services/workflow_definition.py` |
| Workflow execution | `modules/backend/services/workflow_run.py` |
| DB models | `modules/backend/models/` |
