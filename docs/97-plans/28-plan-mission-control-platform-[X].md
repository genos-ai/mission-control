# Plan 28 — Mission Control Platform Architecture

| Field | Value |
|-------|-------|
| **Status** | Backend Complete — frontend implementation tracked by Plan 29 |
| **Created** | 2026-03-20 |
| **Depends on** | All prior plans (1-27) as reference architecture foundation |
| **Blocked by** | Nothing — P3 (Breaking Changes Are Free) applies |
| **Target** | Full codebase: models, schemas, services, API, CLI, TUI, frontend, agents, config |

---

## 1  Objective

Fork the reference architecture into the **Mission Control** platform — an AI-first
autonomous agent orchestration platform where users create missions, assemble agent teams,
design workflows conversationally with an AI Workflow Architect, and run them on schedule
or on demand.

This plan covers three concerns:

1. **Entity rename** — Align code vocabulary with the user-facing "Mission Control" brand
2. **DB schema expansion** — Move agent configuration and prompts from YAML to database for editing, versioning, and per-mission customisation
3. **User journey definition** — Establish the canonical flow from login to production operation

**Dev mode: breaking changes allowed.** P3 applies. No shims, no backward compatibility.
All frontend files are untracked — rename before first commit at zero cost.

---

## 2  Platform Identity

| Attribute | Value |
|-----------|-------|
| Platform name | **Mission Control** |
| Tagline | AI agent orchestration for technical teams |
| Primary users | Technical operators (engineers, analysts, security teams) |
| Admin users | Sysadmins (manage agent catalog, system prompts, tools, permissions) |
| Design philosophy | AI-first (P1), mission as domain primitive, session as transport primitive, streaming-default (P5) |

---

## 3  Entity Rename Map

### 3.1  Core entities

| Current name | New name | What it is |
|---|---|---|
| `Project` | **`Mission`** | Top-level container — brief, team, workflows, history |
| `ProjectMember` | **`MissionMember`** | User membership with role (owner, maintainer, viewer) |
| `ProjectStatus` | **`MissionStatus`** | ACTIVE, PAUSED, ARCHIVED |
| `ProjectContext` | **`MissionContext`** | Living context document (was PCD) |
| `ContextChange` | **`ContextChange`** | Keep — generic enough |
| `ProjectDecision` | **`MissionDecision`** | Archived decisions from context pruning (in mission_history.py) |
| `MilestoneSummary` | **`MilestoneSummary`** | Keep — generic enough |
| `Playbook` / `PlaybookSchema` | **`Workflow`** / **`WorkflowSchema`** | Recipe — how agents collaborate |
| `PlaybookStepSchema` | **`WorkflowStepSchema`** | Single step in a workflow |
| `PlaybookTriggerSchema` | **`WorkflowTriggerSchema`** | When/how a workflow runs |
| `PlaybookBudgetSchema` | **`WorkflowBudgetSchema`** | Cost constraints |
| `PlaybookObjectiveSchema` | **`WorkflowObjectiveSchema`** | Strategic outcome |
| `PlaybookOutputFieldMapping` | **`WorkflowOutputFieldMapping`** | Inter-step data flow |
| `PlaybookStepOutputMapping` | **`WorkflowStepOutputMapping`** | Step output extraction |
| `PlaybookRun` | **`WorkflowRun`** | Single execution of an entire workflow |
| `PlaybookRunState` | **`WorkflowRunState`** | PENDING → RUNNING → COMPLETED/FAILED |
| `Mission` (current) | **`Execution`** | Single step-level execution within a workflow run |
| `MissionState` | **`ExecutionState`** | PENDING → RUNNING → COMPLETED/FAILED |
| `MissionOutcome` | **`ExecutionOutcome`** | Result of a Mission Control dispatch |
| `MissionStatus` (in outcome.py) | **`ExecutionStatus`** | SUCCESS, PARTIAL, FAILED (dispatch outcome) |
| `MissionRecord` | **`ExecutionRecord`** | Persisted audit record of a dispatch execution |
| `MissionRecordStatus` | **`ExecutionRecordStatus`** | COMPLETED, FAILED, CANCELLED, TIMED_OUT |
| `MissionDecision` (in mission_record.py) | **`ExecutionDecision`** | MC decision audit trail (retry, fail, pass, skip) |
| `TaskExecution` | **`TaskExecution`** | Keep — already correct (child of ExecutionRecord) |
| `TaskAttempt` | **`TaskAttempt`** | Keep — already correct (child of TaskExecution) |

**Name collision note:** Two different `MissionDecision` classes exist in the current codebase:
- `mission_record.py` → `MissionDecision` (MC execution audit trail) → renamed to **`ExecutionDecision`** (table: `execution_decisions`)
- `project_history.py` → `ProjectDecision` (PCD pruning decisions) → renamed to **`MissionDecision`** (table: `mission_decisions`)

These are distinct concepts that must not collide after rename.

### 3.2  Modules and services

| Current | New | Notes |
|---|---|---|
| `modules/backend/models/project.py` | `models/mission.py` | Rename file + classes |
| `modules/backend/models/project_context.py` | `models/mission_context.py` | Rename file + classes |
| `modules/backend/models/project_history.py` | `models/mission_history.py` | Rename file + classes |
| `modules/backend/models/mission.py` | `models/execution.py` | Current mission model → execution |
| `modules/backend/repositories/project.py` | `repositories/mission.py` | |
| `modules/backend/repositories/project_context.py` | `repositories/mission_context.py` | |
| `modules/backend/repositories/project_history.py` | `repositories/mission_history.py` | |
| `modules/backend/repositories/mission.py` | `repositories/execution.py` | |
| `modules/backend/repositories/playbook_run.py` | `repositories/workflow_run.py` | |
| `modules/backend/services/project.py` | `services/mission.py` | |
| `modules/backend/services/project_context.py` | `services/mission_context.py` | |
| `modules/backend/services/mission.py` | `services/execution.py` | |
| `modules/backend/services/playbook.py` | `services/workflow.py` | |
| `modules/backend/services/playbook_run.py` | `services/workflow_run.py` | |
| `modules/backend/schemas/playbook.py` | `schemas/workflow.py` | |
| `modules/backend/schemas/project_context.py` | `schemas/mission_context.py` | |
| `modules/backend/models/mission_record.py` | `models/execution_record.py` | Rename file + all classes (ExecutionRecord, ExecutionDecision, etc.) |
| `modules/backend/schemas/mission_record.py` | `schemas/execution_record.py` | |
| `modules/backend/repositories/mission_record.py` | `repositories/execution_record.py` | |
| `modules/backend/services/mission_persistence.py` | `services/execution_persistence.py` | |
| `modules/backend/agents/mission_control/outcome.py` | Keep file path | Rename classes: MissionOutcome→ExecutionOutcome, MissionStatus→ExecutionStatus |
| `modules/backend/agents/mission_control/models.py` | Keep file path | Update protocol param names: project_id→mission_id |
| `modules/backend/agents/mission_control/persistence_bridge.py` | Keep file path | Update references: MissionOutcome→ExecutionOutcome |
| `modules/backend/services/summarization.py` | Keep file path | Update references: ProjectHistory→MissionHistory |
| `modules/backend/services/context_assembler.py` | Keep file path | Update param names: project_id→mission_id |
| `modules/backend/services/context_curator.py` | Keep file path | Update param names: project_id→mission_id |
| `modules/backend/services/history_query.py` | Keep file path | Update references: MissionRecord→ExecutionRecord |
| `modules/backend/api/v1/endpoints/playbooks.py` | `endpoints/workflows.py` | |
| `modules/backend/api/v1/endpoints/missions.py` | `endpoints/executions.py` | Current missions endpoint → executions |
| `modules/clients/cli/project.py` | `cli/mission_cmds.py` | Avoid collision with model name |
| `modules/clients/cli/mission.py` | `cli/execution_cmds.py` | |
| `modules/clients/cli/playbook.py` | `cli/workflow_cmds.py` | |
| `config/playbooks/` | `config/workflow_templates/` | Rename directory + files from `.playbook.yaml` to `.workflow.yaml` |
| `config/settings/playbooks.yaml` | `config/settings/workflows.yaml` | Rename keys: `playbooks_dir` → `workflows_dir` etc. |
| `config/settings/missions.yaml` | `config/settings/executions.yaml` | Current mission execution settings → execution settings |
| `config/settings/projects.yaml` | `config/settings/missions.yaml` | Current project settings → mission settings |
| `modules/backend/core/config_schema.py` | Keep file path | Rename classes: `PlaybooksSchema`→`WorkflowsSchema`, `MissionsSchema`→`ExecutionsSchema`, `ProjectsSchema`→`MissionsSchema` (same collision pattern — rename `MissionsSchema` first) |
| `modules/backend/core/config.py` | Keep file path | Rename properties: `playbooks`→`workflows`, `missions`→`executions`, `projects`→`missions` (same collision pattern) |

### 3.3  API routes

| Current | New |
|---|---|
| `GET/POST /api/v1/projects` | `/api/v1/missions` |
| `GET /api/v1/projects/{id}` | `/api/v1/missions/{id}` |
| `GET /api/v1/projects/{id}/context` | `/api/v1/missions/{id}/context` |
| `GET/POST /api/v1/playbooks` | `/api/v1/workflows` |
| `POST /api/v1/playbooks/{name}/run` | `/api/v1/workflows/{name}/run` |
| `GET /api/v1/missions` (current — execution list) | `/api/v1/executions` |
| `GET /api/v1/missions/{id}` (current — execution detail) | `/api/v1/executions/{id}` |

New routes added later:

| Route | Purpose |
|---|---|
| `GET /api/v1/missions/{id}/team` | List mission team members |
| `POST /api/v1/missions/{id}/team` | Add agent to mission team |
| `GET /api/v1/missions/{id}/workflows` | List mission workflows |
| `GET /api/v1/missions/{id}/runs` | List workflow runs for a mission |
| `GET /api/v1/catalog/agents` | Browse agent catalog |
| `POST /api/v1/missions/{id}/workshop/{agent_id}/test` | Workshop: test agent with cached inputs |

### 3.4  CLI commands

| Current | New |
|---|---|
| `cli.py project create` | `cli.py mission create` |
| `cli.py project list` | `cli.py mission list` |
| `cli.py project detail` | `cli.py mission detail` |
| `cli.py project archive` | `cli.py mission archive` |
| `cli.py project context show` | `cli.py mission context show` |
| `cli.py mission run "objective"` | `cli.py execution run "objective"` |
| `cli.py mission list` (current) | `cli.py execution list` |
| `cli.py mission detail <id>` (current) | `cli.py execution detail <id>` |
| `cli.py playbook list` | `cli.py workflow list` |
| `cli.py playbook run <name>` | `cli.py workflow run <name>` |
| `cli.py playbook detail <name>` | `cli.py workflow detail <name>` |

### 3.5  Event types and event classes

Event type strings are part of the SSE protocol and the `EVENT_TYPE_MAP` registry. Both the class names and the string constants must rename.

| Current class | New class | Current event_type string | New event_type string |
|---|---|---|---|
| `PlaybookRunStartedEvent` | **`WorkflowRunStartedEvent`** | `playbook.run.started` | `workflow.run.started` |
| `PlaybookMissionStartedEvent` | **`WorkflowExecutionStartedEvent`** | `playbook.mission.started` | `workflow.execution.started` |
| `PlaybookMissionCompletedEvent` | **`WorkflowExecutionCompletedEvent`** | `playbook.mission.completed` | `workflow.execution.completed` |
| `PlaybookRunCompletedEvent` | **`WorkflowRunCompletedEvent`** | `playbook.run.completed` | `workflow.run.completed` |
| `PlaybookRunFailedEvent` | **`WorkflowRunFailedEvent`** | `playbook.run.failed` | `workflow.run.failed` |

The `EVENT_TYPE_MAP` dictionary in `events/types.py` must be updated with the new string keys. Any frontend or TUI code that matches on these strings must also be updated.

### 3.6  Protocol and parameter renames

Several internal protocols and function signatures use `project_id` as a parameter name. These must become `mission_id` for consistency, even though the module files themselves do not rename.

| Location | Change |
|---|---|
| `agents/mission_control/models.py` → `ContextCuratorProtocol` | `project_id` → `mission_id` in method signatures |
| `agents/mission_control/models.py` → `ContextAssemblerProtocol` | `project_id` → `mission_id` in method signatures |
| `core/protocols.py` | Audit all protocol methods for `project_id` params |
| `services/context_assembler.py` | `project_id` → `mission_id` in public methods |
| `services/context_curator.py` | `project_id` → `mission_id` in public methods |
| `services/history_query.py` | `project_id` → `mission_id` in public methods |
| `services/summarization.py` | `project_id` → `mission_id` in public methods |
| `agents/mission_control/helpers.py` | All `project_id` references in function args |
| `agents/mission_control/dispatch.py` | All `project_id` references in function args |

### 3.7  What does NOT rename

| Entity | Reason |
|---|---|
| `MissionControl` (module at `agents/mission_control/`) | Still correct — it controls executions within missions |
| `config/mission_control/` directory | Holds roster YAML files. Directory name matches the module, not the domain entity |
| `config/agents/` directory | Holds agent YAML configs used for DB seeding. Stays as-is |
| `TaskPlan` / `TaskDefinition` | Runtime execution plan, not user-facing |
| `SessionEvent` hierarchy (non-playbook events) | Transport layer, not domain entity |
| `GateReviewer` / `GateContext` | Review mechanism, not domain entity |
| `Roster` (internal concept) | Derived at runtime from mission team — internal only |
| `MissionControlRequest` / `MissionControlResponse` | MC infrastructure types, not domain entities |

---

## 4  User Journey

### 4.1  Roles

| Role | Can do | Cannot do |
|---|---|---|
| **Sysadmin** | Manage agent catalog, system prompts, tools, filesystem scopes, global config, user management | N/A (full access via admin site) |
| **Mission Owner** | Create missions, assemble teams, design workflows, configure schedules, run/monitor, edit user prompts | Edit system prompts, create agents, modify tools/scopes |
| **Mission Maintainer** | Run workflows, edit user prompts, monitor runs, use workshop | Create missions, manage team, modify schedules |
| **Mission Viewer** | View mission status, run history, outputs | Edit anything |

### 4.2  The journey

**Step 1 — Login**
User authenticates via the web frontend. Dashboard shows list of missions they have access to, recent runs across all missions, and cost summary.

**Step 2 — Create Mission**
User clicks "New Mission." Enters:
- **Name**: Human-readable slug (e.g., `daily-cti-brief`)
- **Brief**: The mission objective in natural language. This is the strategic directive that agents read to understand their purpose. Example: *"You are a collection of agents with a mission to gather cyber threat intelligence from the Internet and commercial sources every day, distill that information into a daily brief that is concise, informative, and actionable."*
- **Budget ceiling**: Optional USD cap across all workflow runs.
- **Repository**: Optional link to a code repository (for code-focused missions).

**Step 3 — Assemble Team**
The **Workflow Architect** (see §5.2) reads the mission brief and the full agent catalog, then recommends a team composition. The user sees:
- Recommended agents with explanations ("Research Agent — needed for gathering intelligence from external sources")
- The full catalog to browse and add/remove agents manually
- For each selected agent: the system prompt (read-only) and a user prompt text area (editable)

Auto-included agents (not removable):
- Workflow Architect (design-time only)
- Planning Agent (runtime orchestration)
- Verification Agent (quality checking)

The user writes mission-specific user prompts per agent. Example for the Report Writer: *"Write in executive bullet style. Always include a risk score 1-10. Maximum 2 pages. Cite all sources."*

**Step 4 — Design Workflow**
The user enters a chat conversation with the Workflow Architect. The Architect:
1. Reviews the mission brief + assembled team
2. Proposes a workflow as a visual graph (steps, dependencies, agent assignments)
3. The user sees the graph rendered in the right panel (using the existing DAG renderer)
4. The user suggests changes via chat: *"Add a QA step between writing and distribution"*
5. The Architect revises the graph and explains the change
6. The user reviews and clicks "Lock In" — the workflow is saved to the database

A mission can have multiple workflows:
- `daily-brief` — scheduled daily
- `incident-response` — triggered by event
- `weekly-deep-dive` — scheduled weekly

**Step 5 — Configure Schedule**
For each workflow, the user sets:
- **Trigger type**: on-demand, cron schedule, or event-triggered
- **Cron expression**: e.g., `0 5 * * *` (daily at 05:00)
- **Max iterations**: number or "unlimited" (with platform safety cap)
- **Budget per run**: USD ceiling per execution
- **Event trigger**: event type + match pattern (for event-driven workflows)

**Step 6 — Test Run**
The user manually triggers a workflow run. The center panel shows the real-time event stream:
- Agent thinking indicators
- Tool call cards (collapsible)
- Response bubbles (streamed)
- Plan DAG progress (steps light up as they complete)
- Cost tracking (running total)
- Gate modals (if gates are enabled for testing)

**Step 7 — Workshop**
The user clicks on any agent in the team sidebar. The Workshop panel shows:
- **System prompt** (read-only, sysadmin-locked)
- **User prompt** (editable, with version history)
- **Last output** from the most recent run (read-only)
- **"Test" button** — re-runs this single agent with cached upstream outputs from the previous run

The user iterates: tweak prompt → test → review output → tweak again. For output agents (report writers, email senders), a preview pane shows the rendered output.

**Step 8 — Go Live**
The user enables the schedule. The platform's scheduler starts executing the workflow at the configured times. The user receives notifications for:
- Completed runs (with cost summary)
- Failed runs (with error detail)
- Budget warnings (approaching ceiling)
- Gate requests (if human-in-the-loop is enabled)

**Step 9 — Ongoing Operations**
- Review daily outputs in run history
- Monitor costs across workflows
- Tweak agent prompts as needs evolve (Workshop)
- Add new workflows (back to Step 4)
- View the Mission Context Document (accumulated knowledge from all runs)

### 4.3  Admin site (separate)

The admin site is a separate interface accessible only to sysadmins. It provides:

- **Agent Catalog Management**: Create, edit, version, enable/disable agents
- **System Prompt Editor**: Edit system prompts with version history and diff view
- **Tool Registry**: Configure tool permissions, filesystem scopes, API access
- **Global Configuration**: Model pricing, limits, guardrails, feature flags
- **User Management**: Create users, assign roles, manage access
- **System Agents**: Health, code quality, architecture — platform self-maintenance
- **Platform Metrics**: Aggregate cost, usage, error rates across all missions

---

## 5  New Components

### 5.1  Agent Catalog (DB-backed)

The global agent registry moves from YAML-on-disk to database with YAML as seed data.

**Table: `agent_catalog`**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `agent_name` | VARCHAR(200) UNIQUE | e.g., `vertical.research.agent` |
| `agent_type` | VARCHAR(50) | `vertical`, `horizontal`, `system` |
| `version` | VARCHAR(20) | Semver, e.g., `1.0.0` |
| `description` | TEXT | Human-readable capability description |
| `system_prompt` | TEXT | The locked system prompt (sysadmin only) |
| `model_config` | JSON | `{name, temperature, max_tokens}` |
| `tools` | JSON | Array of tool identifiers |
| `scope` | JSON | `{read: [...], write: [...]}` filesystem access |
| `interface` | JSON | `{input: {field: type}, output: {field: type}}` |
| `constraints` | JSON | `{timeout_seconds, cost_ceiling_usd, retry_budget}` |
| `keywords` | JSON | Array of capability keywords |
| `enabled` | BOOLEAN | Sysadmin can disable without deleting |
| `visibility` | VARCHAR(20) | `public` (all users), `system` (sysadmins only) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

System agents (`system.health`, `system.code_quality`, etc.) have `visibility: system` and are never shown in the user-facing catalog.

**Seeding strategy**: On startup, if the `agent_catalog` table is empty, load from `config/agents/**/agent.yaml` + `config/prompts/agents/**/system.md`. Existing rows are never overwritten (DB is source of truth once seeded). A CLI command `cli.py admin seed-catalog --force` allows explicit re-seeding.

### 5.2  Workflow Architect (new horizontal agent)

A new horizontal agent that designs workflows conversationally.

**Location**: `modules/backend/agents/horizontal/architect/`

**Purpose**: Given a mission brief and the available agent team, propose a workflow graph (step sequence, dependencies, agent assignments, input/output wiring). Refine iteratively via chat with the user.

**System prompt context** (injected at runtime):
- The mission brief
- The team roster (agent names, descriptions, interfaces, capabilities)
- Available workflow patterns (sequential, fan-out/fan-in, pipeline)
- Constraints (budget, scheduling requirements)

**Output format**: Structured JSON matching `WorkflowSchema` so the output is directly saveable as a workflow definition.

**Tools**:
- `catalog_browser` — query the agent catalog for capabilities and interfaces
- `workflow_validator` — validate a proposed workflow (check interface compatibility, cycle detection, budget feasibility)
- `graph_renderer` — emit a graph structure the frontend can visualize

**Interaction model**: Conversational via the chat panel. The user sees the workflow graph update in the right panel as the Architect proposes changes. The Architect can explain its reasoning, propose alternatives, and accept or pushback on user suggestions.

**Distinction from Planning Agent**: The Architect works at design-time (strategic: "which agents, in what order, for what purpose?"). The Planning Agent works at runtime (tactical: "for this specific step, what tasks should the assigned agent execute?"). Different abstraction levels, different prompts, different tools.

### 5.3  Mission Team (per-mission agent configuration)

**Table: `mission_team_members`**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `mission_id` | FK → missions | |
| `agent_catalog_id` | FK → agent_catalog | |
| `user_prompt` | TEXT | User-editable per-mission prompt |
| `user_prompt_version` | INTEGER DEFAULT 1 | Current version (incremented on edit, matches prompt_versions) |
| `enabled` | BOOLEAN | Can be temporarily disabled |
| `display_order` | INTEGER | UI ordering |
| `custom_constraints` | JSON | Per-mission overrides (optional) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

**Unique constraint**: `(mission_id, agent_catalog_id)` — one entry per agent per mission.

**Runtime roster derivation**: When Mission Control needs a roster for a mission:
1. Load mission team members (enabled=true)
2. For each, join with agent_catalog to get system prompt, model, tools, constraints
3. Layer user prompt on top of system prompt
4. Construct runtime `Roster` object

### 5.4  Workflow Definitions (DB-stored)

**Table: `workflows`**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `mission_id` | FK → missions | |
| `name` | VARCHAR(200) | e.g., `daily-brief` |
| `description` | TEXT | |
| `version` | INTEGER | Monotonically increasing |
| `enabled` | BOOLEAN | |
| `objective` | JSON | `{statement, category, owner, priority}` |
| `steps` | JSON | Array of WorkflowStepSchema |
| `trigger_config` | JSON | `{type, schedule, event_type, match_patterns}` |
| `budget_config` | JSON | `{max_cost_usd, max_tokens}` |
| `context` | JSON | Static context data |
| `designed_by` | VARCHAR(200) | `architect:<agent_id>` or `user:<user_id>` |
| `locked_at` | TIMESTAMP | When the user confirmed the workflow |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

**Unique constraint**: `(mission_id, name)` — unique workflow names within a mission.

**New fields on `WorkflowStepSchema`** (additions to the existing step schema, per D5 and D6):

| Field | Type | Default | Description |
|---|---|---|---|
| `max_refinement_rounds` | `int` | `1` | Max internal retry/QA cycles per step (D5). Value of 1 = no retry. Gate RETRY mechanism drives the loop. |
| `termination` | `str` | `completion` | Step termination mode (D6). One of: `completion` (normal DAG finish), `budget_exhausted` (iterate until budget hit), `criteria_met` (iterate until quality criteria pass), `max_iterations` (fixed count). |
| `max_iterations` | `int \| None` | `None` | For `termination: max_iterations` — how many internal cycles. |

**System workflow templates**: Sysadmin-created workflows stored as YAML in `config/workflow_templates/`. Users can import a template when designing a new workflow (the Architect receives it as a starting point). Templates have `mission_id: NULL` — they're not bound to any mission.

### 5.5  Prompt Version History

**Table: `prompt_versions`**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `entity_type` | VARCHAR(50) | `agent_catalog` or `mission_team_member` |
| `entity_id` | UUID | FK to the owning entity |
| `prompt_type` | VARCHAR(20) | `system` or `user` |
| `content` | TEXT | The prompt content at this version |
| `version` | INTEGER | Monotonically increasing per entity |
| `changed_by` | VARCHAR(200) | User or agent that made the change |
| `change_reason` | TEXT | Optional explanation |
| `created_at` | TIMESTAMP | |

Every prompt edit creates a new row. Users can view history and roll back.

### 5.6  Workshop Endpoint

A new API endpoint for re-running a single agent with cached inputs.

**`POST /api/v1/missions/{mission_id}/workshop/{agent_catalog_id}/test`**

Request body:
```json
{
  "source_workflow_run_id": "uuid",
  "source_step_id": "step-3",
  "user_prompt_override": "optional temporary prompt for this test only"
}
```

Behaviour:
1. Load the execution outcome from the source workflow run's upstream step
2. Extract the outputs that would feed into the target agent's step
3. Run the agent with: system prompt + (override or saved user prompt) + cached inputs
4. Return the output without persisting as a real workflow run
5. Stream events via SSE so the frontend can show real-time progress

**First-run constraint**: Workshop requires at least one completed workflow run for the target step's upstream dependencies. If no cached data exists, the endpoint returns 409 Conflict with a message: "No cached inputs available. Run the workflow at least once first." The frontend shows this as a guided prompt to run a test workflow first.

---

## 6  Architecture Decisions

### D1: Mission replaces Project as the top-level entity

**Decision**: Rename `Project` → `Mission` across the entire codebase.

**Rationale**: The platform is called "Mission Control." Users create missions with a purpose (the brief), assemble a team, design workflows, and run them. "Project" is generic and creates a brand mismatch. "Mission" conveys intent, urgency, and alignment with the platform name.

### D2: The brief comes first, the Architect recommends the team

**Decision**: The user journey is brief → AI-recommended team → user adjusts → design workflow, not pick agents first → describe objective.

**Rationale**: AI-first design (P1). The user describes what they want to achieve, and the system recommends the team needed to achieve it. The user can always add/remove agents manually, but the starting point is AI-recommended. This reduces cognitive load and ensures the team is fit for purpose.

### D3: Two-phase planning — Architect (design-time) + Planner (runtime)

**Decision**: Workflow design and execution planning are separate agents with separate concerns.

**Rationale**: The Workflow Architect is creative/strategic (which agents, in what order, for what purpose?). The Planning Agent is operational/tactical (for this step, what specific tasks?). Combining them into one agent would overload context and conflate design-time reasoning with runtime planning. The Architect runs once (or when redesigning). The Planner runs every execution.

### D4: System prompts are sysadmin-locked, user prompts are per-mission

**Decision**: Two-layer prompt system. System prompts set by sysadmins (agent catalog), user prompts set by mission owners (mission team). Both are versioned.

**Rationale**: System prompts define agent behaviour and safety boundaries — they must not be user-modifiable. User prompts allow mission-specific customisation ("write in executive style," "focus on APT groups") without touching the agent's core instructions. The effective prompt at runtime is: `system_prompt + user_prompt + task_instructions`.

### D5: Refinement loops are step-internal, not workflow cycles

**Decision**: The workflow graph remains a DAG (no cycles). Refinement loops (QA rounds, code review cycles) are expressed as step-level configuration: `max_refinement_rounds: N`. The executor retries the step internally via the existing gate RETRY mechanism.

**Rationale**: Cycles in the workflow graph make execution semantics complex (termination guarantees, infinite loop protection, state management). The existing verification + gate RETRY infrastructure already supports iterative refinement within a step. Keeping the DAG clean preserves the simplicity of the execution model.

### D6: Open-ended execution uses budget-bounded steps

**Decision**: "Keep working until budget exhausted" is modeled as a single workflow step with `termination: budget_exhausted`. The step's agent iterates internally. Mission Control enforces the budget ceiling and terminates when hit.

**Rationale**: A DAG has a fixed number of nodes. Open-ended iteration is not a DAG problem — it's an execution loop within a single node. The workflow stays simple (one step), and the complexity is handled by Mission Control's existing budget enforcement.

### D7: YAML seeds the database, DB is source of truth

**Decision**: Agent catalog and system prompts are seeded from YAML files on first run. After seeding, the database is the source of truth. Editing happens via admin UI or direct DB updates.

**Rationale**: YAML files are convenient for development and version control (git). But runtime editing, versioning, and per-mission customisation require the database. The seed approach gives us the best of both: git-tracked initial state, DB-managed runtime state.

### D8: Workflows can trigger other workflows via events

**Decision**: A workflow step can emit typed events. Other workflows in the same mission (or across missions) can be triggered by matching events. This is event-driven workflow chaining.

**Rationale**: Real-world use cases require reactive workflows. Example: a threat detection workflow detects critical IOCs and emits `threat.critical.detected`. An IOC hunt workflow in the same mission has `trigger: {type: event, event_type: threat.critical.detected}` and kicks off automatically. The existing `WorkflowTriggerSchema` already supports `type: event` — this decision formalises its use.

---

## 7  Prompt Layering

The effective prompt for any agent at execution time is assembled in this order:

```
┌─────────────────────────────────────────────────┐
│ 1. System Prompt (from agent_catalog)           │  Locked. Sysadmin only.
│    Defines agent identity, capabilities, rules  │  "You are a Research Agent..."
├─────────────────────────────────────────────────┤
│ 2. Mission Brief (from missions.brief)          │  Shared across all agents in the mission.
│    Strategic context for the mission            │  "Gather CTI daily..."
├─────────────────────────────────────────────────┤
│ 3. User Prompt (from mission_team_members)      │  Per-agent per-mission. User editable.
│    Mission-specific instructions                │  "Focus on APT groups, use CVSS..."
├─────────────────────────────────────────────────┤
│ 4. Task Instructions (from TaskPlan)            │  Generated by Planning Agent at runtime.
│    Specific task within the current step        │  "Search for ransomware IOCs from..."
├─────────────────────────────────────────────────┤
│ 5. Mission Context (from MissionContext)         │  Accumulated knowledge from past runs.
│    Decisions, history, current state            │  "{domain: 'cti', decisions: [...]}"
└─────────────────────────────────────────────────┘
```

Layers 1-3 are static per run. Layers 4-5 vary per task within a run. The `assemble_instructions()` function in helpers.py is updated to compose all five layers.

---

## 8  Execution Hierarchy

```
Mission (persistent container)
  └── Workflow (recipe, DB-stored)
        └── WorkflowRun (single execution of the workflow)
              └── Execution (single step-level execution)
                    └── MissionControl orchestrates:
                          ├── PlanningAgent → TaskPlan DAG
                          ├── Dispatch → Agent execution
                          ├── Verification → Quality check
                          └── Gate → Review point (optional)
```

**Ad-hoc executions**: A user can send a message directly to an agent (chat mode) without going through a workflow. The `workflow_run_id` on the `executions` table remains nullable (as `playbook_run_id` is today). Ad-hoc executions have `workflow_run_id = NULL` — they are direct Mission Control invocations within a mission, not tied to any workflow. The execution pipeline is identical — it always flows through Mission Control.

**Iteration within a step**: The Execution has `max_refinement_rounds` (from workflow step config). Mission Control's dispatch loop runs the agent, verifies the output, and if verification fails, retries with feedback up to the configured limit. The gate RETRY action provides the feedback loop.

**Scheduled runs**: A background scheduler reads `workflows.trigger_config` for workflows with `type: schedule`. When the cron expression matches, it creates a new WorkflowRun and starts execution. Safety limits: platform-wide `max_scheduled_runs_per_day` prevents runaway costs.

---

## 9  DB Migration Plan

### 9.1  Table renames

**Migration ordering is critical.** The `missions` table name is used by both the old execution table and the new container table. The migration must execute in this order:

1. Rename `missions` → `executions` (free the `missions` name)
2. Rename `mission_decisions` (audit trail) → `execution_decisions` (free the `mission_decisions` name)
3. Rename `mission_records` → `execution_records` (parent of execution_decisions)
4. Rename `projects` → `missions` (claim the freed name)
5. Rename `project_decisions` → `mission_decisions` (claim the freed name)
6. Rename all other tables (no ordering constraint)

| Order | Old table | New table | Why this order |
|---|---|---|---|
| 1 | `missions` (current — executions) | `executions` | Free the `missions` name |
| 2 | `mission_decisions` (MC audit trail) | `execution_decisions` | Free the `mission_decisions` name |
| 3 | `mission_records` | `execution_records` | Parent of execution_decisions |
| 4 | `projects` | `missions` | Claim the freed `missions` name |
| 5 | `project_decisions` | `mission_decisions` | Claim the freed `mission_decisions` name |
| 6 | `project_members` | `mission_members` | |
| 7 | `project_contexts` | `mission_contexts` | |
| 8 | `context_changes` | `context_changes` (keep, update FK column names) | |
| 9 | `milestone_summaries` | `milestone_summaries` (keep, update FK column name) | |
| 10 | `playbook_runs` | `workflow_runs` | |
| 11 | `task_executions` | `task_executions` (keep, update FK column name) | |
| 12 | `task_attempts` | `task_attempts` (keep, no changes) | |

### 9.2  Column renames within tables

| Table (new name) | Old column | New column | Notes |
|---|---|---|---|
| `executions` (was missions) | `project_id` | `mission_id` | FK to missions (was projects) |
| `executions` (was missions) | `playbook_run_id` | `workflow_run_id` | |
| `executions` (was missions) | `playbook_step_id` | `workflow_step_id` | |
| `executions` (was missions) | `mission_outcome` | `execution_outcome` | |
| `workflow_runs` (was playbook_runs) | `project_id` | `mission_id` | FK to missions (was projects) |
| `workflow_runs` (was playbook_runs) | `playbook_name` | `workflow_name` | |
| `workflow_runs` (was playbook_runs) | `playbook_version` | `workflow_version` | |
| `execution_records` (was mission_records) | `project_id` | `mission_id` | FK to missions (was projects) |
| `execution_records` (was mission_records) | `mission_outcome_json` | `execution_outcome_json` | |
| `execution_records` (was mission_records) | `parent_mission_id` | `parent_execution_record_id` | Self-FK |
| `execution_decisions` (was mission_decisions in records) | `mission_record_id` | `execution_record_id` | FK to execution_records |
| `task_executions` | `mission_record_id` | `execution_record_id` | FK to execution_records |
| `context_changes` | `mission_id` (ref to old mission) | `execution_id` | |
| `milestone_summaries` | `project_id` | `mission_id` | FK to missions (was projects) |
| `mission_decisions` (PCD pruning) | `project_id` | `mission_id` | FK to missions (was projects) |
| `mission_decisions` (PCD pruning) | `mission_id` (ref to old execution) | `execution_id` | |
| `mission_contexts` (was project_contexts) | `project_id` | `mission_id` | FK to missions (was projects) |
| `mission_members` (was project_members) | `project_id` | `mission_id` | FK to missions (was projects) |
| `missions` (new, was projects) | — | Add `brief` (TEXT) | New column alongside `description` |

### 9.3  New tables

| Table | Purpose |
|---|---|
| `agent_catalog` | Global agent registry (seeded from YAML) |
| `mission_team_members` | Per-mission agent selection with user prompts |
| `workflows` | DB-stored workflow definitions |
| `prompt_versions` | Audit trail for prompt edits |
| `workflow_schedules` | Cron-based execution config |

---

## 10  Phasing

### Phase 1 — Foundation Rename ✅

Rename all entities and files. No new features. The codebase compiles, all tests pass, and the vocabulary is consistent. This is a mechanical, high-confidence change.

Steps:
1. Create DB migration for table/column renames (see §9 for ordering)
2. Rename model files and classes
3. Rename schema files and classes (including `schemas/playbook.py`, `schemas/mission_record.py`, `schemas/project_context.py`)
4. Rename repository files and classes
5. Rename service files and classes
6. Rename `config_schema.py` classes (`PlaybooksSchema`→`WorkflowsSchema`, `MissionsSchema`→`ExecutionsSchema`, `ProjectsSchema`→`MissionsSchema`) and `config.py` properties (same collision pattern as DB — rename `MissionsSchema` first)
7. Rename API endpoint files and routes
8. Rename CLI command groups and handlers
9. Update all imports across the codebase (use `rg` to find every reference)
10. Rename frontend files and components (before first commit)
11. Update TUI references
12. Rename config settings files (`playbooks.yaml`→`workflows.yaml`, `missions.yaml`→`executions.yaml`, `projects.yaml`→`missions.yaml`) and update all keys within
13. Rename `config/playbooks/` → `config/workflow_templates/` and files within
14. Update AGENTS.md, CODEMAP.md, all documentation
15. Run full test suite, fix all failures
16. Regenerate code map

### Phase 2 — DB Schema Expansion ✅

Add the new tables and seed infrastructure. Agent catalog, mission team, workflow definitions, prompt versioning.

Steps:
1. Create `agent_catalog` table + model + repository + service
2. Build YAML → DB seeder (load from `config/agents/` on first run)
3. Create `mission_team_members` table + model + repository + service
4. Create `workflows` table + model + repository + service
5. Create `prompt_versions` table + model + repository
6. Create `workflow_schedules` table + model + repository
7. Migrate `WorkflowService` (was `PlaybookService`) to load from DB (with YAML template import)
8. Update Mission model with `brief` field
9. Update roster derivation to use mission team + agent catalog
10. Update `assemble_instructions()` to include user prompt layer
11. Add API endpoints for new entities
12. Add CLI commands for new operations

### Phase 3 — Workflow Architect (Backend ✅ · Frontend → Plan 29)

Build the new horizontal agent that designs workflows conversationally.

Steps:
1. ✅ Create `modules/backend/agents/horizontal/architect/` module
2. ✅ Define system prompt with catalog awareness
3. ✅ Build tools: catalog browser, workflow validator, graph renderer
4. ✅ Implement conversational workflow design flow
5. ✅ Add "Lock In" mechanism (save to `workflows` table)
6. Frontend: chat panel + live graph rendering during design → Plan 29 §5.7
7. Frontend: workflow management UI (list, edit, delete, version) → Plan 29 §5.7

### Phase 4 — Workshop & Scheduling (Backend ✅ · Frontend → Plan 29)

Build the interactive agent-testing mode and the production scheduler.

Steps:
1. ✅ Workshop API endpoint (`/workshop/{agent_id}/test`)
2. ✅ Cached input extraction from previous workflow runs
3. ✅ Single-agent re-execution with temporary prompt override
4. Frontend: workshop panel with prompt editor + output preview → Plan 29 §5.9
5. ✅ Scheduler service: cron evaluation, workflow run creation
6. ✅ Schedule management API; UI → Plan 29 §5.7
7. ✅ Safety limits: max runs per day, cost circuit breakers
8. ✅ Notification system: run completion, failure alerts, budget warnings

### Phase 5 — Admin Site (Backend ✅ · Frontend → Plan 29)

Build the sysadmin-only interface for platform management.

Steps:
1. ✅ Separate admin routes with role-based auth (AdminRole dependency)
2. ✅ Agent catalog CRUD API with system prompt editor endpoint; UI → Plan 29 §5.12.1
3. Tool registry management (deferred — not yet needed)
4. ✅ Global configuration API; UI → Plan 29 §5.12.3
5. ✅ User/role management API; UI → Plan 29 §5.12.5
6. ✅ Platform metrics API; UI → Plan 29 §5.12.2
7. ✅ System health API; UI → Plan 29 §5.12.4

---

## 11  Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Rename breaks existing tests (130+ files) | High churn | Mechanical find-replace, not logic changes. Run test suite after each model rename. |
| Workflow Architect produces poor workflow designs | User frustration | Rich system prompt with catalog context. Architect proposes, user confirms. Fallback: manual workflow creation. |
| DB-stored workflows lose git version control | Config drift | Prompt version history table. Export-to-YAML for git backup. |
| Event-driven workflow chaining creates infinite loops | Runaway costs | Max chain depth config. Per-workflow cooldown period. Budget circuit breaker. |
| Scheduler creates excessive runs | Cost overrun | Platform-wide `max_scheduled_runs_per_day`. Per-workflow budget cap. Alerting. |
| Workshop cached inputs become stale | Misleading test results | Display cache timestamp. Warn if inputs are from a run older than N days. Option to run upstream first. |
| Team member removal orphans workflow step references | Broken workflow | Validate team against all mission workflows before removing an agent. If agent is referenced in any workflow step, require workflow update first or block removal with clear error. |

---

## 12  Dependencies on Existing Plans

| Plan | Relationship |
|---|---|
| Plan 12 (Session API) | Sessions remain the communication primitive. No changes needed. |
| Plan 13 (Dispatch) | Dispatch operates on Executions (renamed from Missions). Internal rename only. |
| Plan 14 (Verification) | Verification pipeline unchanged. Operates within Executions. |
| Plan 17 (Playbooks & Missions) | Superseded by this plan. Playbooks become Workflows, stored in DB. |
| Plan 18 (Project Context) | ProjectContext → MissionContext. Same semantics, renamed. |
| Plan 21 (Decouple Playbooks from Projects) | Absorbed. Workflows are mission-scoped by design (FK to missions). |
| Plan 22 (Step-Through Gate) | Gate mechanism unchanged. Operates within Executions. |
| Plan 25 (Streaming Events) | Event streaming unchanged. Events reference Executions. |
| Plan 27 (Web Frontend) | Frontend rename before first commit. UI concepts align with this plan. |

---

## 13  Success Criteria

1. The platform is consistently called "Mission Control" in all user-facing interfaces
2. Users create Missions (not Projects), design Workflows (not Playbooks), and monitor Runs
3. Agent catalog is DB-backed with system prompts versioned and sysadmin-locked
4. Mission teams provide per-agent user prompt customisation with version history
5. The Workflow Architect can propose a workflow from a brief + team and refine via chat
6. Workshop mode allows single-agent re-testing with cached inputs and prompt iteration
7. Scheduled workflows execute reliably with cost safety limits
8. The admin site is fully separated from the user-facing application
9. All existing tests pass after rename (no functional regression)
10. Code map and PQI scores are maintained or improved
