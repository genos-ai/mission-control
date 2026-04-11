# Agentic Execution Environments: Change Specification

**Version:** 1.3.0
**Date:** 2026-04-01
**Author:** Herman (Group CISO, Icarus) + Architecture Review
**Status:** Phases 1–5 done (2026-04-11). Phases 6/7/9 extracted to [Plan 48](48-plan-convergence-loop-and-branch-automation.md). Phase 8 deferred per §5.
**Target:** BFA Reference Architecture v3.5.0
**Codebase alignment:** v1.1.0 — validated against mission-control repository 2026-04-01

---

## Close-out note (2026-04-11)

During [Plan 46 (Autonomous Mission Roadmap)](46-plan-autonomous-mission-roadmap.md)
Phase 1, a scope review surfaced that this plan bundled two logically separable
concerns:

1. **The execution environments foundation** (Phases 1–5): agent rename + tiers,
   platform missions, execution environment model, container backend, dispatch
   integration. All landed and verified on branch `plan/37-execution-environments`.
2. **Convergence loop + branch automation** (Phases 6, 7, 9): iterative QA cycles,
   `agent/*` branch strategy, final verification pattern. The plan itself notes
   *"The convergence loop is environment-agnostic — it works in local, container,
   or (later) worktree mode"* — it's a different capability riding on the same
   backend, not part of the isolation layer.

Rather than block Plan 46 Phase 1 on the convergence loop work, concerns #2 have
been extracted into their own plan doc ([Plan 48](48-plan-convergence-loop-and-branch-automation.md))
with the content of §5 Phases 6, 7, and 9 as its seed. Plan 48 is deliberately
**out of Plan 46's roadmap scope** — it will be picked up opportunistically after
the roadmap closes, or whenever the convergence loop becomes load-bearing for a
specific mission.

Phase 8 (Worktree Backend) remains deferred per §5: *"Only implement when agents
are running frequent lightweight code-only tasks (linting, type annotations,
config changes) and the 5–30s container overhead is a measurable bottleneck."*
It stays parked on this plan (not moved to Plan 48) because its prerequisite is
"agents are running enough to make it worth optimizing", not "we need the
convergence loop working".

**What this plan now owns from here forward:** Phases 1–5 as the execution
environments foundation, plus Phase 8 as a future optimization. Everything else
lives in Plan 48.

---

## 0. Codebase Alignment

> **This plan was originally authored outside the codebase.** This section maps every assumption to the actual code so implementers know exactly what exists, what to extend, and what to create.

### Existing Infrastructure (extend these)

| Plan Concept | Actual Location | What Exists | What to Add |
|-------------|----------------|-------------|-------------|
| `ExecutionEnvironment` enum | — | **Does not exist.** | New enum in `modules/backend/models/execution.py` alongside `ExecutionState`. |
| `MissionSpec` model | `modules/backend/models/mission.py:34` → `Mission` | `Mission` has `name`, `description`, `brief`, `status`, `owner_id`, `team_id`, `default_roster`, `budget_ceiling_usd`, `repo_url`, `repo_root`, `gate_mode`. | Add `execution_environment` (nullable, default `local`) column. `max_iterations` belongs on convergence loop task `input_data`, NOT on Mission (see Phase 4). Quality gate config goes in `brief` JSON or a new `quality_gate` JSON column. |
| `execution.mode` in agent YAML | `modules/backend/agents/config_schema.py:34-37` → `ExecutionSchema` | Schema has `mode: str`. All agent YAMLs set `mode: local`. | Extend `ExecutionSchema` with `prefer`, `template`, `branch_prefix`, `worktree_base_dir` fields. Add `Literal` validation for mode values. |
| Agent YAML configs | `config/agents/**/agent.yaml` (9 agents) | All have `execution: mode: local`. Comment header documents `local | container` but only `local` is used. | **Rename all agents per Section 4.8.1** (`code.*` → `software.*`, `horizontal.*` → `mission.*`/`system.*`, `system.*` → `platform.*`). Add `invocation` field. Move directories. Update comment headers. |
| Dispatch loop | `modules/backend/agents/mission_control/dispatch/loop.py:57` → `dispatch()` | Layer-by-layer task orchestration with topological sort, gate reviews, context injection, budget enforcement. | Wire execution environment resolution **before** `execute_with_step_events()`. The dispatch loop is the integration point for environment provisioning. |
| Dispatch adapter | `modules/backend/agents/mission_control/dispatch_adapter.py:25` → `MissionControlDispatchAdapter` | Wraps `handle_mission()` for `ExecutionService`. Routes by `complexity_tier` and `roster_ref`. | Add `execution_mode` parameter. Resolve environment before delegating to `handle_mission()`. |
| Retry handler | `modules/backend/agents/mission_control/dispatch/retry_handler.py:45` → `execute_with_retry()` | Single-task retry with 3-tier verification and gate review. Tracks `RetryHistoryEntry`. | This is **not** the convergence loop — it's task-level retry. The convergence loop is a new pattern that **wraps** the dispatch loop, not the retry handler. |
| Execution model | `modules/backend/models/execution.py:124` → `Execution` | Has `objective`, `roster_ref`, `complexity_tier`, `status`, `session_id`, `upstream_context`, `context`, costs, timestamps. | Add `execution_environment` column (string, default `local`). |
| Services directory | `modules/backend/services/` | 30+ services including `ExecutionService`, `MissionService`, `WorkflowService`. | New files: `worktree_backend.py`, `container_backend.py`, `execution_environment.py`. |
| `execution_environments` table | — | **Does not exist.** | New SQLAlchemy model in `modules/backend/models/execution_environment.py`. |
| Event types | `modules/backend/events/types.py` | Has `PlanCreatedEvent` and other session events. | Add `ConvergenceIterationEvent`, `ConvergenceCompletedEvent`, `FinalVerificationEvent`. |
| Task plan schema | `modules/backend/schemas/task_plan.py` → `TaskPlan` | DAG-based plan with topological sort support. | Add `convergence_loop` task type with loop config in `input_data`. |
| Reference arch doc 45 | `docs/99-reference-architecture/45-agentic-execution-environments.md` | Optional module. Defines `local`/`container`/`sandbox` modes, `ExecutionEnvironmentService` interface, container lifecycle. **No worktree mode.** | Add worktree backend section, git-aware container section, update architecture diagram. |
| Reference arch doc 47 | `docs/99-reference-architecture/47-agentic-module-organization.md:774` | Dimension 4 labeled "Future". Defines `local` and `container` only. | Add `worktree` and `auto` modes. Update access control matrix. |
| Workflow step schema | `modules/backend/schemas/workflow.py:87-89` | `environment` field with pattern `^(local\|container\|sandbox)$`. | Update pattern to include `worktree` and `auto`. |
| Temporal models | `modules/backend/temporal/models.py:13` → `MissionWorkflowInput` | Has `mission_brief`, `roster_name`, `mission_budget_usd`. No environment field. | Add `execution_mode: str \| None = None`. |
| Temporal activities | `modules/backend/temporal/activities.py` → `execute_mission` | Calls dispatch adapter. Temporal is fully implemented (not future). | Pass `execution_mode` through to dispatch adapter. |
| PQI service | `modules/backend/services/pqi/types.py` → `PQIResult` | `composite_score` (0-100), `quality_band` enum, `classify_band()`. Fully implemented. | Use as convergence condition for `quality_threshold` — do not reinvent scoring. |
| Agent invocation tier | — | **Does not exist.** No concept of who can invoke which agent. | New `InvocationSchema` in `config_schema.py` with `tier` (user/platform/system) + `required_role`. See Section 4.8.2. |
| Mission tier | — | **Does not exist.** All missions are equal. | New `MissionTier` enum + `tier` column on `Mission` model. Platform missions require admin. See Section 4.8.3. |
| Agent naming convention | `config/agents/` → `code/`, `horizontal/`, `system/` directories | Categories: `code` (domain), `horizontal` (profile), `system` (one agent). `agent_type` determines module path. | **Full rename per Section 4.8.1**: `software/`, `mission/`, `platform/`, `system/`. Category-based module path resolution. `horizontal` category eliminated. |
| Agent registry | `modules/backend/agents/mission_control/registry.py` → `AgentRegistry` | `list_all()`, `get()`, `get_by_keyword()`, `resolve_module_path()`. No tier filtering. | Add `tier` param to `list_all()`. Add `list_system()`. Simplify `resolve_module_path()` to category-based. |
| Platform director | — | **Does not exist.** | New agent: `platform.director.agent` — admin-only conversational agent for platform operations. |

### What Does NOT Exist (create from scratch)

| Component | Target Path | Notes |
|-----------|-------------|-------|
| `WorktreeBackend` service | `modules/backend/services/worktree_backend.py` | Git worktree lifecycle management |
| `ContainerBackend` service | `modules/backend/services/container_backend.py` | Docker container lifecycle (doc 45 defines the interface but no implementation exists) |
| `ExecutionEnvironmentService` | `modules/backend/services/execution_environment.py` | Facade over worktree + container backends |
| `ExecutionEnvironment` DB model | `modules/backend/models/execution_environment.py` | New table tracking environment instances |
| `resolve_execution_mode()` | `modules/backend/agents/mission_control/dispatch/environment.py` | Auto-resolution heuristics — lives near dispatch, not in a "coordinator" module |
| Convergence loop executor | `modules/backend/agents/mission_control/dispatch/convergence.py` | New loop pattern wrapping the existing dispatch loop |
| Branch management | `modules/backend/services/worktree_backend.py` | Part of `WorktreeBackend` — no separate module needed |
| `code-workspace.Dockerfile` | `config/dockerfiles/code-workspace.Dockerfile` | Container image for git-aware coding agents |
| `InvocationSchema` | `modules/backend/agents/config_schema.py` | Tier + required_role for agent invocation control |
| `MissionTier` enum | `modules/backend/models/mission.py` | User vs platform mission distinction |
| `platform.director.agent` | `config/agents/platform/director/agent.yaml` + `modules/backend/agents/platform/director/agent.py` | Admin-only conversational agent for platform operations |

### Terminology Corrections

The original plan references a **"Coordinator"** module (doc 41). In the actual codebase:
- There is no `coordinator/` module. Routing is handled by the dispatch adapter (`dispatch_adapter.py`) and the dispatch loop (`dispatch/loop.py`).
- The `resolve_execution_mode()` function should live in `modules/backend/agents/mission_control/dispatch/environment.py`, not `modules/backend/agents/coordinator/environment.py`.
- `CoordinatorRequest` does not exist. The entry point is `MissionControlDispatchAdapter.execute()` which receives `mission_brief`, `roster_ref`, `complexity_tier`, `upstream_context`, `cost_ceiling_usd`, `session_id`, `mission_id`, and `gate`.

### Quality Review Findings (2026-04-01)

**1. Dead parameter already exists — wire it, don't duplicate.**
`ExecutionService.create_execution_from_step()` at `modules/backend/services/execution.py:112` already accepts `environment: str = "local"` but **never passes it to the `Execution()` constructor** (line 129-144). Phase 1 must wire this existing parameter to the new `execution_environment` column rather than introducing a separate code path.

**2. `WorktreeBackend` must share an interface with `ContainerBackend`.**
Doc 45 defines `ContainerBackend(ABC)` at line 436. The plan's `WorktreeBackend` is a concrete class with no shared interface. This violates the strategy pattern — `ExecutionEnvironmentService` should dispatch to backends through a shared `Protocol` or `ABC`. Create an `ExecutionBackend(Protocol)` with the subset of operations both backends support (`execute`, `commit_changes`, `cleanup`), then have `WorktreeBackend` and `ContainerBackend` implement it.

**3. Convergence loop must integrate with existing gate system.**
The gate system (`modules/backend/agents/mission_control/gate.py`) already supports `GateAction.RETRY`, `ABORT`, `SKIP`, `MODIFY` at multiple decision points. The convergence loop should use `GateReviewer` for inter-cycle decisions (e.g., "QA found 3 issues after 4 cycles — human, should we continue?"). Don't create a parallel decision framework.

**4. Scheduled cleanup should follow existing Taskiq pattern.**
`modules/backend/tasks/scheduled.py` defines `daily_cleanup()`, `hourly_health_check()`. Worktree pruning (`prune_stale_worktrees`) should be a new scheduled task in this file, not a standalone background loop.

**5. Git operations should use `asyncio.create_subprocess_exec`, not `subprocess.run`.**
The codebase's only git call (`code_map/loader.py:155`) uses synchronous `subprocess.run`. All new git operations in `WorktreeBackend` must be async (`asyncio.create_subprocess_exec`) to avoid blocking the event loop.

**6. `execution_environment` on both Mission and Execution is intentional but needs clarity.**
Mission-level `execution_environment` is the **default** for all executions in that mission. Execution-level `execution_environment` is the **override** resolved at dispatch time. The plan should explicitly state this inheritance: `Execution.execution_environment = resolve_execution_mode() or Mission.execution_environment or "local"`.

### Quality Review — Second Pass (2026-04-01)

**7. `sandbox` mode inconsistency.**
The execution modes table (Section 4.2.4) lists 4 modes including `sandbox` (gVisor), but the `ExecutionEnvironment` enum defines only 3 values (LOCAL/WORKTREE/CONTAINER). **Decision:** Keep `sandbox` out of the enum for now. It's a container variant (same backend, different runtime flag `runtime: "runsc"`), not a separate backend. Add `SANDBOX` to the enum only when gVisor support is implemented. The modes table should note `sandbox` as a future container variant.

**8. `ExecutionResult` naming collision risk.**
The plan uses `ExecutionResult` as a return type for `WorktreeBackend.execute_in_worktree()`. The codebase already has:
- `ExecutionOutcome` (`agents/mission_control/outcome.py:1`) — dispatch result from Mission Control
- `MissionExecutionResult` (`temporal/models.py:27`) — Temporal activity result
Name the new type `EnvironmentExecutionResult` or `CommandResult` to avoid confusion.

**9. Temporal is already implemented — leverage it.**
The plan's architecture diagram shows "Temporal Worker" as if future. In reality, Temporal is fully integrated (`modules/backend/temporal/`) with workflows, activities, client, and worker. `MissionWorkflowInput` already carries `mission_brief`, `roster_name`, `mission_budget_usd`. **Add `execution_mode: str | None = None` to `MissionWorkflowInput`** so Temporal-triggered missions can specify environment. The `execute_mission` Activity should pass this to `MissionControlDispatchAdapter.execute()`.

**10. Workflow step schema already has `environment` field.**
`modules/backend/schemas/workflow.py:87-89` defines `environment: str` with pattern `^(local|container|sandbox)$`. **This must be updated** to `^(local|worktree|container|sandbox|auto)$` in Phase 1 — otherwise workflow steps can't specify worktree mode.

**11. `config/settings/environments.yaml` doesn't exist.**
The plan adds worktree/container config to this file, but the `config/settings/` directory has no `environments.yaml`. Options: (a) create it as a new file, or (b) add to existing `config/settings/executions.yaml` which is conceptually closer. **Decision:** Create `environments.yaml` — execution config is about _what_ runs, environment config is about _where_ it runs.

**12. `WorktreeBackend` class body in Section 4.2.1.**
Section 4.2.1 defines `WorktreeBackend` as a class with an `# implements ExecutionBackend(Protocol)` comment. When implemented in Phase 6, it must satisfy the `ExecutionBackend` protocol defined in Phase 2. The class definition in Section 4.2.1 is the spec — the protocol constraint is enforced at implementation time.

**13. PQI integration point unspecified.**
The convergence loop lists `quality_threshold` as a convergence condition with "PyQuality Index exceeds threshold." The actual interface is in `modules/backend/services/pqi/types.py`: `PQIResult.composite_score` (float 0-100), `PQIResult.quality_band` (enum), `classify_band()`. The convergence loop should call the PQI service directly, not reinvent scoring.

---

## 1. Executive Summary

This document specifies changes to the BFA Reference Architecture to introduce **git worktrees as a first-class execution primitive** for agentic coding workflows, **worktree-inside-container composition** for full-stack validation, and an **iterative QA convergence loop** as a standard plan pattern. These changes affect six existing documents and introduce no new documents.

The core insight: the current architecture (doc 45) jumps from "run in the platform process" (`local`) to "run in a Docker container" (`container`) with nothing in between. For coding agents performing refactors, linting fixes, type annotation passes, or documentation updates — tasks where the agent writes code but doesn't need to *execute* it — Docker is overkill. Git worktrees provide filesystem-level isolation (separate branch, separate working directory, shared object store) without any runtime overhead. The agent works on its own branch while the developer continues working on `main`, undisturbed.

Furthermore, the architecture lacks a pattern for the most natural agentic coding workflow: an iterative loop where a QA agent finds issues, a coder agent fixes them, and the cycle repeats until quality gates are met. This is not a linear plan or a DAG — it's a bounded convergence loop, and the plan management system needs to support it natively.

### What This Enables

1. **Parallel agent/human development** — Developer works on `main` while agents work on feature branches via worktrees. No stashing, no context switching, no interference.

2. **Two-tier execution model** — Worktrees for speed when the agent only needs to read/write files. Containers for safety when the agent needs to install packages, run tests, or access databases. The dispatch loop decides which tier based on task characteristics.

3. **Full end-to-end validation** — Ephemeral containers with worktrees inside them. Each mission starts from scratch: clone via worktree, `pip install`, run migrations, seed fixtures, execute QA cycle. If the install process or migrations are broken, you find out before the code hits `main`.

4. **Iterative quality improvement** — QA Agent → Coder Agent → QA Agent loop with bounded iterations, convergence conditions, per-cycle commits, and an optional final clean verification step.

---

## 2. Background: The Conversation That Produced These Changes

### 2.1 Starting Point: Git Worktrees for Agentic Development

The discussion began with the question: "How do git worktrees work, especially as it relates to agentic AI development in March 2026?"

**Git worktrees** allow multiple working directories from a single `.git` repository, each with its own checked-out branch, HEAD, index, and working tree. They share the same object store, refs, and history. The constraint: no two worktrees can have the same branch checked out simultaneously.

For agentic development, worktrees solve the **parallelism problem** for code-generating agents. Without worktrees, an agent and a developer working in the same checkout collide — the agent modifies files the developer is reading, test runners conflict, and builds interfere. Worktrees eliminate this by giving each agent its own isolated directory on its own branch.

The key mapping to the BFA architecture:
- **Mission = Branch** — each mission creates a feature branch
- **Agent = Worktree** — each agent operates in its own worktree on that branch
- **PR = Merge point** — when the mission completes, the branch goes through normal PR review

### 2.2 The Iterative QA Cycle

The second topic explored was an iterative QA/fix cycle:

```
QA Agent runs tests, static analysis, linting
    ↓ produces findings
Coder Agent reads findings, applies fixes
    ↓ commits to feature branch
QA Agent re-runs suite
    ↓ still failing? loop back to Coder
    ↓ passing? signal done
```

Key design decisions from the discussion:

1. **Shared branch, separate roles.** Both agents work on the same worktree and branch. A turn-based protocol (or Temporal workflow) coordinates them so they don't step on each other.

2. **Bounded iteration.** Always set a `max_iterations` (default: 5-6). An agent pair that can't converge has a deeper design problem that needs human eyes.

3. **Commit per cycle.** The Coder agent commits after each fix pass. This creates an auditable progression — if cycle 4 introduces a regression, you can diff between cycles.

4. **Quality gate as convergence condition.** Configurable: all tests pass, coverage threshold hit, PyQuality Index above threshold, zero critical linting violations.

### 2.3 Docker Container vs. Git Worktree — Not Either/Or

The discussion then explored whether to use Docker containers (full isolation with live DB, install verification) or worktrees (lightweight, fast). The conclusion: **use both, matched to the risk and scope of the change.**

**Worktree (lightweight, no runtime isolation):**
- Small refactors, renaming, restructuring
- Documentation updates, config changes
- Code style / linting fixes, adding type annotations
- Anything where the agent doesn't need to *run* the code

**Container + Worktree (full isolation, full validation):**
- New features touching the database
- Dependency changes, migration work
- API contract changes, auth/payment paths
- Large refactors spanning multiple modules
- PyQuality Index improvement sweeps

The deciding question: **does the agent need to execute the code to know if it's correct?** If yes → container. If static analysis and the agent's own reasoning suffice → worktree.

### 2.4 Ephemeral Containers for End-to-End Validation

The decision was made to use **ephemeral containers** rather than long-lived ones. Each mission spins up a fresh container, installs from scratch, runs migrations, seeds test data, and executes the QA cycle. This means the end-to-end process — install, migrations, dependency resolution — is tested as a side effect of the ephemeral model.

The optimal pattern that emerged:

1. **Ephemeral per mission** — container lives for the duration of all QA/fix cycles within one mission. Fresh from `main`, but loop iterations within share the running environment.

2. **Final clean verification** — as the very last step before opening the PR, spin up a completely fresh container, check out the branch, bootstrap from zero, and run the full test suite. If that passes, the branch is genuinely deployable.

### 2.5 The Two-Tier Decision as Coordinator Logic

The final convergence was that this becomes a **property of the Mission definition**:

```python
# modules/backend/models/execution.py — add alongside existing ExecutionState enum

class ExecutionEnvironment(str, Enum):
    LOCAL = "local"           # In-process, FileScope isolation
    WORKTREE = "worktree"     # Git isolation only
    CONTAINER = "container"   # Full runtime isolation (Docker + worktree inside)
```

The execution environment is stored on the `Mission` model (`modules/backend/models/mission.py:34`) as a new nullable column, and on each `Execution` record. The dispatch loop resolves the environment from task metadata. The agent never knows whether it's in a worktree, a container, or the main process.

> **Note:** The original plan defined a `MissionSpec(BaseModel)` — this does not exist. The actual model is `Mission` (SQLAlchemy, `modules/backend/models/mission.py:34`). Add `execution_environment` column to `Mission`. `max_iterations` belongs on the convergence loop task's `input_data` (Phase 4), NOT on Mission — a single mission may have multiple convergence loops with different limits. Quality gate configuration can be stored in the existing `brief` text field (as structured YAML/JSON within the brief) or as a new `quality_gate` JSON column.

---

## 3. Gap Analysis: What the Current Architecture Lacks

### 3.1 Gap: No Lightweight Isolation Between `local` and `container`

**Current state:** Doc 45 defines two execution modes — `local` (in-process, FileScope) and `container` (Docker). Doc 47 Dimension 4 mirrors this with `execution.mode: local | container`.

**Problem:** There's no middle ground. A coding agent doing a rename refactor doesn't need Docker — it needs its own branch and working directory. But `local` mode shares the developer's working tree, creating collision risk.

**Impact:** Agents are forced into containers for tasks that don't need runtime isolation, adding latency (container spin-up), complexity (Docker dependency), and cost (resource overhead) to lightweight operations.

### 3.2 Gap: No Git-Aware Container Pattern

**Current state:** Doc 45's containers are standalone — provision, execute commands, capture output. There's no concept of mounting the host's git object store or creating worktrees inside containers.

**Problem:** Without git awareness, containers must do a full `git clone` (duplicating the entire object history) or receive code as a volume mount (coupling the container to the host filesystem). Neither supports the branch-based workflow where the container works on a feature branch while the developer works on `main`.

**Impact:** Container-based agent work is disconnected from git workflow. There's no clean merge path back to `main`, no per-cycle commit history, and no branch-based PR review.

### 3.3 Gap: No Iterative Convergence Loop Plan Pattern

**Current state:** Doc 40 describes linear plans and DAGs. Doc 46 Section 4 covers mutable DAGs with dependency tracking. All plan patterns are acyclic.

**Problem:** The QA/fix cycle is inherently cyclic — QA finds issues, Coder fixes them, QA re-validates, loop until convergence. This doesn't map to a DAG (cycles are forbidden) or a linear sequence (the step count is unknown at planning time).

**Impact:** Implementing iterative QA cycles requires ad-hoc workarounds in the plan engine rather than being a first-class pattern with proper bounded iteration, convergence tracking, and cycle-level audit trails.

### 3.4 Gap: Execution Mode Resolution Not in Dispatch

**Current state:** The dispatch adapter (`dispatch_adapter.py`) routes based on `complexity_tier` and `roster_ref`. The execution environment is defined statically in agent YAML (doc 47) or playbook steps, but there's no dynamic resolution logic in the dispatch loop.

**Problem:** The same agent may need different execution environments depending on the task. A `code.coder.agent` doing a type annotation pass needs only a worktree. The same agent adding a new database model needs a container. Static configuration can't capture this.

**Impact:** Either every coding task runs in a container (wasteful) or every coding task runs locally/worktree (insufficient isolation for some tasks).

### 3.5 Gap: No Branch Strategy for Agent Work

**Current state:** Doc 12 defines branch naming (`feature/`, `hotfix/`) but has no convention for agent-created branches, no automated cleanup policy, and no PR workflow for agent output.

**Problem:** Agents creating worktrees or working in containers on feature branches need a consistent naming convention, a cleanup mechanism for stale branches/worktrees, and an automated path from "agent work complete" to "PR opened for review."

**Impact:** Without conventions, agent branches accumulate, naming is inconsistent, and the human review workflow is ad-hoc.

---

## 4. Detailed Change Specifications

### 4.1 Document: 47-agentic-module-organization.md

**Section affected:** "Access Control Model → Dimension 4: Execution Mode"

**Change type:** Update existing content

**Current content (to replace):**

The current Dimension 4 defines two modes: `local` and `container`. The YAML schema shows `execution.mode: local | container`.

**New content:**

Dimension 4 gains a third execution mode: `worktree`. The three modes form a graduated isolation hierarchy:

```yaml
execution:
  mode: local | worktree | container
```

| Mode | Isolation Level | Runtime | Branch Isolation | Install/Test | Overhead | When to Use |
|------|----------------|---------|-----------------|-------------|----------|-------------|
| `local` | Logical (FileScope) | In-process | No — shares developer's working tree | No | None | LLM calls, file analysis, code review, read-only tasks — agent doesn't write code or doesn't need isolation from developer activity |
| `worktree` | Filesystem (git branch + separate working directory) | In-process | Yes — own branch, own directory, shared `.git` object store | No — agent cannot run `pip install`, `pytest`, or access DB | Low (~100ms setup) | Small refactors, linting fixes, type annotations, config changes, documentation updates — agent writes code but doesn't need to execute it |
| `container` | Physical (Docker namespace: PID, mount, network) | Container process | Yes — worktree created inside container from mounted `.git` | Yes — full environment: install, migrate, test, access DB | Medium (~5-30s setup) | New features, dependency changes, migrations, API changes, large refactors, anything requiring code execution for validation |

**Key properties of `worktree` mode:**

1. **Git worktree created per mission** — branch named `agent/{mission-id}/{task-type}`, worktree in a sibling directory (e.g., `../agent-workspaces/{mission-id}/`)
2. **Shared `.git` object store** — no clone overhead, instant branching, minimal disk usage
3. **Agent sees a normal directory** — the worktree is transparent to the agent. It reads and writes files as if it were in the main checkout. The execution environment service manages the git operations.
4. **Branch is the continuity mechanism** — when the mission completes, the branch exists as a normal feature branch. PR workflow is identical regardless of whether the branch was created by a worktree or a container.
5. **No two worktrees share a branch** — git enforces this constraint. Each mission gets its own branch.
6. **Worktree cleanup** — the lifecycle maintenance task (doc 45) cleans up worktrees when missions complete or branches are merged/pruned.

**Deciding between modes:**

The execution mode can be set statically in agent YAML or resolved dynamically by the dispatch loop based on task characteristics:

```yaml
# Static: agent always uses worktree mode
execution:
  mode: worktree

# Dynamic: dispatch loop resolves based on task
execution:
  mode: auto   # NEW — dispatch loop decides at runtime
  prefer: worktree   # Hint: prefer worktree unless task requires container
```

When `mode: auto`, the dispatch loop applies these rules (see Section 4.5 changes below):
- Task requires package installation → `container`
- Task modifies database schemas or migrations → `container`
- Task runs tests or builds → `container`
- Task only reads/writes source files → `worktree`
- Task doesn't touch code → `local`

**Access Control Matrix update:**

Add a column for the new mode to the existing access control matrix:

| Agent | Tier | Execution Mode | Rationale |
|-------|------|---------------|-----------|
| `software.quality.agent` (scan only) | user | `local` | Reads files, runs static analysis in-process — no writes |
| `software.quality.agent` (scan + fix) | user | `worktree` | Writes fixes to files but doesn't need to run tests |
| `software.quality.agent` (full cycle) | user | `container` | Needs to run `pytest` after fixes, verify nothing broke |
| `software.coder.agent` (refactor) | user | `worktree` | Restructures code but doesn't change behavior — static validation sufficient |
| `software.coder.agent` (new feature) | user | `container` | Needs install, migrations, test execution |
| `mission.director.agent` | user | `local` | Conversational — reads context, delegates, no code changes |
| `mission.workflow.agent` | user | `local` | Designs workflows — reads docs, no code changes |
| `platform.health.agent` | platform | `local` | Reads logs and config, calls health endpoints — admin only |
| `platform.director.agent` | platform | `local` | Admin conversational entry point — delegates to platform agents |
| `system.planning.agent` | system | `local` | Dispatch infrastructure — creates TaskPlans |
| `system.verification.agent` | system | `local` | Dispatch infrastructure — verifies task outputs |

**Pydantic schema update** (`modules/backend/agents/config_schema.py:34-37`):

The current `ExecutionSchema` has only `mode: str`. Extend it:

```python
# modules/backend/agents/config_schema.py — update ExecutionSchema

class ExecutionSchema(_StrictBase):
    """Agent execution environment."""
    mode: Literal["local", "worktree", "container", "auto"] = "local"
    prefer: Literal["local", "worktree", "container"] | None = None  # hint for auto mode
    template: str | None = None          # container template (doc 45), used when mode=container
    branch_prefix: str = "agent"         # prefix for worktree branch names
    worktree_base_dir: str = "../agent-workspaces"  # where worktrees are created
```

**YAML schema update for agent config** (`config/agents/{category}/{name}/agent.yaml`):

```yaml
execution:
  mode: worktree | container | local | auto   # auto = dispatch resolves
  prefer: worktree                             # hint for auto mode
  template: code-workspace                     # container template (doc 45), used when mode=container
  branch_prefix: agent                         # prefix for worktree branch names
  worktree_base_dir: ../agent-workspaces       # where worktrees are created (relative to repo root)
```

> **Note:** All 9 existing agent YAMLs currently have `execution: mode: local`. The comment header in each YAML documents `local | container` — update this to `local | worktree | container | auto`. No agent needs a mode change until the backends are implemented.

---

### 4.2 Document: 45-agentic-execution-environments.md

**Change type:** Major update — add Worktree Backend section, add Git-Aware Container section, update architecture diagram

#### 4.2.1 New Section: "Worktree Backend" (insert before "Container Lifecycle" section)

**Rationale:** This section defines the worktree execution primitive — how worktrees are created, managed, cleaned up, and how the agent interacts with them. It sits at the same level as the Docker content.

```markdown
## Worktree Execution Mode

### What It Is

A git worktree is a separate working directory checked out from the same `.git` repository. It has its own branch, its own HEAD, its own index — but shares the object store with the main checkout. Creating a worktree is near-instant (milliseconds) because no data is copied — it's a lightweight pointer into the shared object store.

For agent execution, a worktree means: the agent gets its own branch and its own directory to work in, while the developer (or other agents) continue working on `main` (or their own branches) undisturbed. When the agent is done, its branch is a normal feature branch that can be reviewed and merged via standard PR workflow.

### What It Is Not

- **Not process isolation.** The agent runs in the main platform process. A worktree gives filesystem separation, not security boundaries. If untrusted code execution is involved, use `container` mode.
- **Not a clone.** Cloning duplicates the entire object store. A worktree shares it. For a 500MB repo, a clone takes seconds and uses 500MB. A worktree takes milliseconds and uses ~1KB.
- **Not a replacement for containers.** Worktrees cannot install packages, run test suites against databases, or provide network isolation. They are for tasks where the agent only needs to read and write source files.

### When to Use Worktrees

| Use Case | Why Worktree Works |
|----------|-------------------|
| Code refactoring (rename, restructure) | Agent writes files, no execution needed to validate |
| Linting fixes, formatting corrections | Static analysis tools run in-process on the worktree files |
| Adding type annotations | Agent reads code structure, adds annotations — no runtime validation |
| Documentation updates (inline docs, README) | Pure file writes |
| Configuration changes (YAML, env files) | File changes only, validation is structural |
| Dependency version bumps (requirements.txt) | File edit only — testing the install belongs in a container |
| Code style standardization | Automated formatting, consistent patterns |
| Adding logging statements, error handling | Code changes validated by agent reasoning, not execution |

### When NOT to Use Worktrees

| Use Case | Why Container Needed |
|----------|---------------------|
| New feature with database model | Agent must run migrations, seed data, test queries |
| API endpoint changes | Agent must run the server and test HTTP responses |
| Dependency installation | `pip install` must run in an isolated environment |
| Running test suites | `pytest` needs a running database, Redis, etc. |
| Build pipeline changes | Build must execute to validate |
| Migration scripts | Must run against a real database to verify |
| Any task involving `subprocess`, `os.system`, or external commands | Process isolation required |

### WorktreeBackend

The `WorktreeBackend` implements the same abstract interface as `ContainerBackend` (with a subset of operations) so the `ExecutionEnvironmentService` can manage worktrees through the same lifecycle.

```python
# NEW FILE: modules/backend/services/worktree_backend.py
# Follows the service pattern established by ExecutionService, MissionService, etc.
# in modules/backend/services/

class WorktreeBackend:  # implements ExecutionBackend(Protocol)
    """Git worktree management backend.

    Implements the ExecutionBackend protocol (defined in
    modules/backend/services/execution_environment.py). Both
    WorktreeBackend and ContainerBackend implement this protocol
    so ExecutionEnvironmentService can dispatch through a uniform
    interface (strategy pattern).

    All git subprocess calls use asyncio.create_subprocess_exec,
    NOT subprocess.run (avoid blocking the event loop).

    Unlike ContainerBackend, this does not provide:
    - Process isolation
    - Network isolation
    - Resource limits
    - Package installation capability

    Use for tasks where the agent reads/writes source files but does
    not need to execute them.
    """

    async def create_worktree(
        self,
        repo_root: Path,
        worktree_path: Path,
        branch_name: str,
        base_branch: str = "main",
    ) -> WorktreeHandle:
        """Create a new worktree on a new branch.

        Creates branch from base_branch and checks it out in worktree_path.
        The worktree shares the .git object store with repo_root.

        Args:
            repo_root: Path to the main repository
            worktree_path: Where to create the worktree directory
            branch_name: Name for the new branch (e.g., agent/m-abc123/refactor)
            base_branch: Branch to create from (default: main)

        Returns:
            WorktreeHandle with path and branch info

        Raises:
            WorktreeCreationError if branch already exists or path is occupied
        """
        ...

    async def execute_in_worktree(
        self,
        handle: WorktreeHandle,
        command: list[str],
        timeout_seconds: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> CommandResult:
        """Execute a command with the worktree as working directory.

        The command runs in the main platform process (not isolated).
        Use only for safe operations: static analysis tools, file
        operations, git commands.

        For arbitrary code execution, use container mode.
        """
        ...

    async def commit_changes(
        self,
        handle: WorktreeHandle,
        message: str,
        author: str = "BFA Agent <agent@bfa.local>",
    ) -> str:
        """Commit all changes in the worktree. Returns commit hash."""
        ...

    async def push_branch(
        self,
        handle: WorktreeHandle,
        remote: str = "origin",
    ) -> None:
        """Push the worktree's branch to the remote."""
        ...

    async def cleanup_worktree(
        self,
        handle: WorktreeHandle,
        delete_branch: bool = False,
    ) -> None:
        """Remove the worktree directory and optionally the branch.

        The branch is NOT deleted by default — it persists for PR review.
        Set delete_branch=True only after the branch has been merged or
        explicitly abandoned.
        """
        ...

    async def prune_stale_worktrees(
        self,
        repo_root: Path,
        max_age_days: int = 7,
    ) -> list[str]:
        """Remove worktrees whose branches have been merged or are stale.

        Called by the lifecycle maintenance scheduled task.
        Returns list of pruned worktree paths.
        """
        ...
```

**Data types:**

```python
@dataclass
class WorktreeHandle:
    """Lightweight handle for a git worktree."""
    worktree_path: Path
    branch_name: str
    base_branch: str
    repo_root: Path
    created_at: datetime

@dataclass
class WorktreeInfo:
    """Status information for a worktree."""
    path: Path
    branch: str
    head_commit: str
    is_clean: bool           # No uncommitted changes
    ahead_count: int         # Commits ahead of base branch
    last_commit_at: datetime
```

### Worktree Lifecycle

```
create_worktree()
    │
    ▼
ACTIVE (agent works in worktree directory)
    │
    ├── commit_changes() — agent commits after each work cycle
    │
    ├── push_branch() — push to remote for PR
    │
    ▼
cleanup_worktree(delete_branch=False)
    │
    ▼
BRANCH PERSISTS (for PR review)
    │
    ├── Human merges PR → branch deleted by PR workflow
    │
    └── Branch stale → prune_stale_worktrees() deletes branch and worktree
```

### Configuration

```yaml
# config/settings/environments.yaml — add worktree section

worktree:
  enabled: true
  base_dir: "../agent-workspaces"          # Relative to repo root
  branch_prefix: "agent"                    # Branches named: agent/{mission-id}/{task-type}
  default_base_branch: "main"               # Branch to create from
  max_concurrent_worktrees: 10              # Per repository
  stale_branch_ttl_days: 7                  # Auto-prune branches with no activity
  commit_author_name: "BFA Agent"
  commit_author_email: "agent@bfa.local"
  cleanup_interval_minutes: 60              # Scheduled task frequency
```

### Database Table

Worktrees are tracked in the same `execution_environments` table as containers, with `mode = 'worktree'`. No separate table needed.

Additional columns or JSON metadata fields for worktree-specific data:

| Field | Storage | Purpose |
|-------|---------|---------|
| branch_name | `metadata` JSON | The git branch associated with this worktree |
| base_branch | `metadata` JSON | The branch it was created from |
| worktree_path | `metadata` JSON | Filesystem path to the worktree directory |
| commit_count | `task_count` (reused) | Number of commits made in this worktree |
| last_commit_hash | `metadata` JSON | HEAD commit of the worktree |
| is_pushed | `metadata` JSON | Whether the branch has been pushed to remote |
| pr_url | `metadata` JSON | URL of the PR opened for this branch (null if not yet opened) |
```

#### 4.2.2 New Section: "Git-Aware Container Environments" (insert after Worktree section)

**Rationale:** This defines the composition pattern where a worktree is created *inside* a container, combining git-level branch isolation with Docker runtime isolation. This is the pattern for full end-to-end validation.

```markdown
## Git-Aware Container Environments

### The Composition Pattern

For tasks requiring both branch isolation AND runtime isolation (install, test, migrate), the platform creates a worktree inside a Docker container. The container mounts the host's `.git` object store (read-only) and creates a worktree from it. This gives the agent:

- **Branch isolation** — working on its own branch, not `main`
- **Runtime isolation** — its own filesystem, process tree, network namespace
- **Shared git history** — no full clone needed, instant worktree creation
- **Commit capability** — agent commits to its branch from inside the container
- **PR workflow** — same branch-based merge path as worktree-only mode

```
┌──────────────────────────────────────────────────┐
│  Docker Container (runtime isolation)             │
│                                                   │
│  ┌─────────────────────────────────────────┐     │
│  │  /repo/.git  (read-only volume mount)   │     │
│  │  (host's .git object store)             │     │
│  └──────────────┬──────────────────────────┘     │
│                 │                                  │
│                 │  git worktree add               │
│                 │  /workspace feature/mission-xyz │
│                 ▼                                  │
│  ┌─────────────────────────────────────────┐     │
│  │  /workspace  (worktree working dir)     │     │
│  │  - pip install -r requirements.txt      │     │
│  │  - alembic upgrade head                 │     │
│  │  - pytest                               │     │
│  │  - agent reads/writes code here         │     │
│  └─────────────────────────────────────────┘     │
│                                                   │
│  /output  (results extracted by platform)         │
│                                                   │
└──────────────────────────────────────────────────┘
```

### Environment Template

Add a `git_aware` flag and `git_mount` path to environment templates:

```yaml
# config/settings/environments.yaml — new template

templates:
  code-workspace:
    description: "Python workspace with git worktree support for coding agents"
    dockerfile: "code-workspace.Dockerfile"
    git_aware: true                          # Enables worktree-in-container
    git_mount: "/repo/.git"                  # Read-only mount of host .git
    workspace_dir: "/workspace"              # Worktree created here
    cpu_limit: 2.0
    memory_limit_mb: 2048
    long_lived: false                        # Ephemeral per mission
    auto_stop_after_seconds: 3600
    auto_destroy_after_seconds: 7200
    volumes:
      workspace:
        mount: "/workspace"
        persist: false                       # Fresh per mission
      pip_cache:
        mount: "/root/.cache/pip"
        persist: true                        # Cache pip downloads across missions
    network:
      egress_allowlist:
        - "pypi.org"
        - "files.pythonhosted.org"
        - "github.com"
```

### Container Startup Sequence (Git-Aware)

When `git_aware: true`, the `ExecutionEnvironmentService` performs these additional steps after container creation:

1. Mount host `.git` directory as read-only volume at `git_mount` path
2. Inside the container: `git worktree add {workspace_dir} {branch_name}`
3. Verify the worktree is on the correct branch and at the expected commit
4. Agent task execution proceeds in `workspace_dir`

After task completion:
1. Agent commits are on the branch inside the container
2. The platform pushes the branch to the remote from inside the container
3. Container is destroyed (ephemeral) or stopped (long-lived)
4. The worktree reference in the host's `.git` is cleaned up via `git worktree prune`

### The Ephemeral-with-Final-Verification Pattern

For maximum confidence that a branch is deployable:

```
Mission Start
    │
    ▼
Ephemeral Container #1 (for iterative QA cycle)
    ├── Create worktree on feature branch
    ├── pip install, migrate, seed data
    ├── QA/Coder loop (N iterations)
    ├── Each cycle: commit to branch
    ├── Push branch on convergence
    └── Destroy container
    │
    ▼
Ephemeral Container #2 (final clean verification)
    ├── Create worktree on SAME branch
    ├── pip install from scratch
    ├── Migrate from scratch
    ├── Run full test suite
    ├── If pass → open PR
    ├── If fail → flag for human review
    └── Destroy container
```

This pattern proves the branch is deployable from zero — the install process, the migrations, and the test suite all work on a clean machine. The iterative cycle (Container #1) stays fast because the environment persists across iterations. The final verification (Container #2) provides the clean-slate guarantee.
```

#### 4.2.3 Update: Architecture Diagram

The architecture diagram at the top of doc 45 should be updated to show three execution paths:

```
                    Platform Process (FastAPI + Workers)
                    ────────────────────────────────────
    ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
    │   Coordinator   │  │ Temporal Worker  │  │  Taskiq Worker   │
    └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘
             │                    │                     │
             │ resolve execution mode                   │
             │                                          │
        ┌────┴──────────────┬───────────────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   ┌─────────┐     ┌──────────────┐    ┌────────────────────┐
   │  LOCAL   │     │  WORKTREE    │    │    CONTAINER        │
   │          │     │              │    │  (git-aware)        │
   │ In-proc  │     │ Own branch,  │    │                     │
   │ FileScope│     │ own workdir  │    │  Docker + worktree  │
   │          │     │ shared .git  │    │  full isolation     │
   └─────────┘     └──────────────┘    └────────────────────┘
```

#### 4.2.4 Update: Execution Modes Table

The existing "Execution Modes" section should be updated with the three-tier table:

| Mode | Where task runs | Isolation | Git branch | Can install/test | Overhead | When to use |
|------|----------------|-----------|-----------|-----------------|----------|-------------|
| `local` | In the platform process | Logical (FileScope) | No (shares developer's checkout) | No | None | Default. LLM calls, file analysis, code review — no code changes or changes that don't need isolation |
| `worktree` | In the platform process, worktree directory | Filesystem (own branch, own working dir) | Yes (own branch, shared object store) | No | ~100ms | Small refactors, linting, type annotations, config changes — agent writes code but doesn't need to run it |
| `container` | In a Docker container | Physical (namespace boundary) | Yes (worktree inside container when `git_aware: true`) | Yes (full environment) | ~5-30s | New features, dependencies, migrations, testing — agent needs to execute code |
| `sandbox` _(future — container variant, not a separate backend)_ | In a hardened Docker container (gVisor) | Physical (user-space kernel) | Yes (worktree inside container) | Yes | ~10-60s | Untrusted code execution, third-party scripts. Uses `ContainerBackend` with `runtime: "runsc"`. Add `SANDBOX` to enum when gVisor support is implemented. |

---

### 4.3 Document: 40-agentic-architecture.md

**Section affected:** "Orchestration: Phase-by-Phase Behavior → Phase 2: Plan"

**Change type:** Add new plan pattern

> **Codebase note:** The convergence loop is a **new dispatch pattern**, not an extension of the existing retry handler. The retry handler (`dispatch/retry_handler.py:45 → execute_with_retry()`) handles single-task retry with verification feedback. The convergence loop coordinates **two different agents** (evaluation + remediation) across multiple cycles. Implementation target: `modules/backend/agents/mission_control/dispatch/convergence.py`, called from `dispatch/loop.py` when a task has `type=convergence_loop`. The existing `TaskPlan` schema (`modules/backend/schemas/task_plan.py`) needs a new task type.

#### New Subsection: "Convergence Loop Pattern"

Insert after the existing "Phase 2: Plan" content:

```markdown
### Convergence Loop Pattern

Some workflows are inherently cyclic: an evaluation agent identifies issues, a remediation agent fixes them, and the cycle repeats until quality gates are met. This pattern is distinct from a DAG (which forbids cycles) and from a simple retry (which repeats the same agent on the same task).

**Structure:**

```
┌──────────────────────────────────────────────────────┐
│  CONVERGENCE LOOP                                     │
│                                                       │
│  Evaluation Agent: run suite, produce findings        │
│     ↓                                                │
│  Convergence condition met? ──→ EXIT (success)        │
│     ↓ (not met)                                      │
│  Iteration limit exceeded? ──→ EXIT (escalate)        │
│     ↓                                                │
│  Remediation Agent: read findings, apply fixes        │
│     ↓ commit changes                                 │
│  Loop back to Evaluation Agent                        │
│                                                       │
│  Optional: Final Clean Verification on exit           │
│     Fresh environment, bootstrap from zero, run suite │
│     Pass → open PR. Fail → flag for human review.    │
└──────────────────────────────────────────────────────┘
```

**Configuration:**

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `max_iterations` | int | 5 | Hard cap on loop iterations. Prevents infinite cycling. |
| `convergence_condition` | ConvergenceCondition | all_tests_pass | What "done" means — see conditions below |
| `commit_per_cycle` | bool | true | Whether the remediation agent commits after each fix pass |
| `final_verification` | bool | false | Whether to run a clean-environment verification before PR |
| `evaluation_agent` | str | — | Agent type for the evaluation role (e.g., code.qa.agent) |
| `remediation_agent` | str | — | Agent type for the fix role (e.g., code.coder.agent) |

**Convergence conditions:**

| Condition | Description |
|-----------|-------------|
| `all_tests_pass` | `pytest` returns exit code 0 |
| `zero_critical_findings` | Evaluation agent reports no findings with severity ≥ critical |
| `zero_findings` | Evaluation agent reports no findings at any severity |
| `quality_threshold` | A composite metric (e.g., PyQuality Index) exceeds a configured threshold |
| `custom` | A callable that receives the evaluation output and returns bool |

**Task records for a convergence loop:**

A loop with 3 iterations produces these AgentTask/TaskExecution records:

```
Plan Task: "QA Convergence Loop" (type=convergence_loop)
  ├── Cycle 1
  │   ├── Evaluation: QA Agent run (findings: 12)
  │   └── Remediation: Coder Agent run (fixes: 10, commit: abc123)
  ├── Cycle 2
  │   ├── Evaluation: QA Agent run (findings: 4)
  │   └── Remediation: Coder Agent run (fixes: 4, commit: def456)
  ├── Cycle 3
  │   ├── Evaluation: QA Agent run (findings: 0) → CONVERGED
  │   └── (no remediation needed)
  └── Final Verification (optional): clean environment, full suite → PASS
```

Each cycle's evaluation and remediation are standard AgentTask records with `parent_task_id` pointing to the loop task. The loop task's `reasoning` JSON tracks: cycle count, findings per cycle, convergence metric per cycle, and the final convergence decision.

**Execution environment for convergence loops:**

The convergence loop pattern composes with the execution environment model:

| Execution Mode | Loop Behavior |
|----------------|--------------|
| `worktree` | Both agents work in the same worktree. Coder commits after each cycle. Evaluation re-reads files from the worktree. |
| `container` | Both agents work in the same container's worktree. Container persists across cycles (ephemeral per mission, not per cycle). Coder commits inside the container. |
| `container` + `final_verification` | After convergence, a NEW ephemeral container is spun up. It checks out the same branch, installs from scratch, runs the full suite. This proves the branch is deployable from zero. |

**When to use convergence loops vs. linear plans:**

| Use Case | Pattern | Why |
|----------|---------|-----|
| Known sequence of steps | Linear/DAG plan | Steps are defined at planning time |
| Issue discovery → remediation | Convergence loop | Don't know how many cycles needed until convergence |
| Test failure → fix → retest | Convergence loop | Inherently cyclic with unknown iteration count |
| Code review → revision → re-review | Convergence loop | Same pattern: evaluate, fix, re-evaluate |
| Build → deploy → smoke test | Linear plan | Steps are always the same |
```

---

### 4.4 Document: 46-agentic-event-session-architecture.md

**Section affected:** Section 2 (Event Bus) — add new event types. Section 4 (Plan Management) — add loop task type.

**Change type:** Add content

#### New Event Types (add to Section 2, EVENT_TYPE_MAP):

```python
# Convergence loop events
class ConvergenceIterationEvent(SessionEvent):
    event_type: str = "plan.convergence.iteration"
    plan_id: UUID
    loop_task_id: UUID
    cycle_number: int
    findings_count: int
    fixes_applied: int
    convergence_metric: float | None       # e.g., PyQuality Index score
    converged: bool

class ConvergenceCompletedEvent(SessionEvent):
    event_type: str = "plan.convergence.completed"
    plan_id: UUID
    loop_task_id: UUID
    total_cycles: int
    final_metric: float | None
    outcome: str                           # "converged", "max_iterations", "error"
    branch_name: str | None                # Git branch with the changes
    pr_url: str | None                     # PR URL if auto-opened

class FinalVerificationEvent(SessionEvent):
    event_type: str = "plan.verification.completed"
    plan_id: UUID
    loop_task_id: UUID
    passed: bool
    test_summary: str                      # "47 passed, 0 failed" or error details
    environment_mode: str                  # "container" — always runs in fresh container
```

#### Plan Schema Update (Section 4):

Add `convergence_loop` as a task type in the `tasks` table. The loop configuration is stored in `input_data`:

```sql
-- A convergence loop task's input_data contains:
{
    "loop_config": {
        "max_iterations": 5,
        "convergence_condition": "zero_critical_findings",
        "convergence_threshold": null,
        "commit_per_cycle": true,
        "final_verification": true,
        "evaluation_agent": "code.qa.agent",
        "remediation_agent": "code.coder.agent",
        "evaluation_config": { ... },
        "remediation_config": { ... }
    }
}

-- Loop execution state is tracked in output_data (updated per cycle):
{
    "cycles": [
        {
            "cycle_number": 1,
            "evaluation_task_id": "uuid",
            "remediation_task_id": "uuid",
            "findings_count": 12,
            "fixes_applied": 10,
            "commit_hash": "abc123",
            "convergence_metric": 0.72
        },
        ...
    ],
    "converged": true,
    "total_cycles": 3,
    "final_verification_passed": true
}
```

---

### 4.5 Document: 41-agentic-pydanticai.md

**Section affected:** Dispatch adapter, execution mode resolution

**Change type:** Update existing content

> **Codebase note:** The plan originally referenced a `CoordinatorRequest` model and `coordinator/` module. These do not exist. The actual entry point is `MissionControlDispatchAdapter.execute()` in `modules/backend/agents/mission_control/dispatch_adapter.py:38`. The dispatch adapter receives `mission_brief`, `roster_ref`, `complexity_tier`, `upstream_context`, `cost_ceiling_usd`, `session_id`, `mission_id`, and `gate`.

#### Dispatch Adapter Update

Add `execution_mode` parameter to `MissionControlDispatchAdapter.execute()`:

```python
# modules/backend/agents/mission_control/dispatch_adapter.py — update execute() signature

async def execute(
    self,
    mission_brief: str,
    roster_ref: str = "default",
    complexity_tier: str = "simple",
    upstream_context: dict | None = None,
    cost_ceiling_usd: float | None = None,
    session_id: str | None = None,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    execution_mode: str | None = None,      # NEW — "local", "worktree", "container", or None (auto-resolve)
) -> dict:
```

#### Execution Mode Resolution (new module in dispatch)

```python
# NEW FILE: modules/backend/agents/mission_control/dispatch/environment.py

def resolve_execution_mode(
    task_definition: dict,
    agent_config: dict,
) -> str:
    """Resolve the execution mode for a task.

    Priority order:
    1. Explicit mode in task definition (from playbook step)
    2. Explicit mode in agent YAML config
    3. Auto-resolution based on task characteristics

    Auto-resolution rules:
    - Task requires package installation → container
    - Task modifies database schemas/migrations → container
    - Task runs tests or builds → container
    - Task only reads/writes source files → worktree
    - Task doesn't touch code → local
    """
    # Check explicit overrides
    task_mode = task_definition.get("execution_environment")
    if task_mode and task_mode != "auto":
        return task_mode

    agent_mode = agent_config.get("execution", {}).get("mode", "local")
    if agent_mode != "auto":
        return agent_mode

    # Auto-resolution heuristics
    tools = set(agent_config.get("tools", []))
    has_execution_tools = bool(tools & {
        "code.run_tests", "code.build", "system.install_packages",
        "system.run_migrations", "system.exec_command",
    })
    has_write_tools = bool(tools & {
        "filesystem.write_file", "code.apply_fix",
        "filesystem.create_file", "filesystem.delete_file",
    })

    if has_execution_tools:
        return "container"
    elif has_write_tools:
        return agent_config.get("execution", {}).get("prefer", "worktree")
    else:
        return "local"
```

> **Integration point:** `resolve_execution_mode()` is called from `dispatch/loop.py` at the start of `_execute_layer()`, before `execute_with_step_events()`. The resolved mode is passed to `ExecutionEnvironmentService.resolve_or_create()` which provisions the worktree or container. The agent receives a working directory path — it never knows which backend created it.

---

### 4.6 Document: 12-core-development-workflow.md

**Section affected:** "Version Control → Branch Strategy"

**Change type:** Add new subsection

#### New Subsection: "Agent Branches"

```markdown
### Agent Branches

Agents create branches when working in `worktree` or `container` execution mode. These branches follow a distinct naming convention and lifecycle.

**Branch naming:**

```
agent/{mission-id}/{task-type}

Examples:
agent/m-abc123/qa-cycle
agent/m-def456/refactor-auth
agent/m-ghi789/add-type-annotations
```

The `mission-id` is the short form of the mission UUID. The `task-type` is a human-readable slug derived from the task description. The `agent/` prefix distinguishes agent branches from human branches (`feature/`, `hotfix/`).

**Branch from:** Always `main` (or the configured `default_base_branch` in `environments.yaml`). Agents never branch from `develop` — they work against the production-ready code.

**Merge target:** Always `main` via PR. Agent branches merge through the same PR review process as human branches. No direct pushes to `main`.

**Commit messages from agents:**

```
[AGENT:{agent-name}] Short description (max 72 chars)

Mission: {mission-id}
Task: {task-id}
Cycle: {cycle-number} (for convergence loops)
Agent: {agent-name}

- Detailed changes
- Files modified
```

**Cleanup policy:**

| Condition | Action | Trigger |
|-----------|--------|---------|
| Branch merged via PR | Delete branch and worktree | Post-merge webhook or PR workflow |
| Mission completed, PR not yet opened | Keep branch, open PR automatically | Mission completion handler |
| Mission failed | Keep branch for debugging, tag as `agent/failed/` | Mission failure handler |
| Branch stale (no activity for `stale_branch_ttl_days`) | Delete branch and worktree | Scheduled maintenance task |
| Worktree exists but branch was deleted externally | Prune worktree | `git worktree prune` in maintenance task |

The cleanup is managed by the lifecycle maintenance scheduled task defined in doc 45, which runs periodically (default: every 60 minutes) via Taskiq.

**PR automation:**

When an agent mission completes successfully (convergence loop converged, or single-pass task completed), the platform:
1. Pushes the branch to the remote
2. Opens a PR with a generated description containing: mission objective, agent(s) used, number of iterations (for convergence loops), files changed, convergence metrics
3. Assigns the project owner as reviewer (from the Project entity, doc 48)
4. Labels the PR with `agent-generated`

The human reviews the PR like any other. The agent's per-cycle commits provide an auditable history of how the code evolved.
```

---

### 4.7 Document: 00-overview.md

**Change type:** Update changelog and version

Add to changelog:

```
- 3.5.0 (2026-03-15): Added git worktree execution mode to 47-agentic-module-organization.md (Dimension 4: three-tier execution — local/worktree/container); added Worktree Backend and Git-Aware Container sections to 45-agentic-execution-environments.md; added Convergence Loop plan pattern to 40-agentic-architecture.md; added convergence loop events and schema to 46-agentic-event-session-architecture.md; added execution mode resolution to 41-agentic-pydanticai.md coordinator; added agent branch strategy to 12-core-development-workflow.md
```

Update version to `3.5.0`.

---

### 4.8 Agent Naming Convention & Invocation Tiers

**Change type:** Rename agents, add invocation tier model, add platform missions

This section defines the agent naming convention, the invocation tier system, and the platform mission concept. These changes affect doc 47 (agent module organization), the agent registry, the mission model, and all agent YAML configs.

#### 4.8.1 Naming Convention

**Agent name format:** `{category}.{role}.agent`

The first segment indicates who the agent serves. The second is its functional role. No compound names.

**Categories:**

| Category | Serves | Catalog visibility | Execution visibility | Added to mission | Managed by |
|----------|--------|-------------------|---------------------|-----------------|------------|
| `software.*` | The codebase | User catalog — selectable | Visible | User picks | User |
| `infrastructure.*` | Deployment/DevOps | User catalog — selectable | Visible | User picks | User |
| `security.*` | Security posture | User catalog — selectable | Visible | User picks | User |
| `data.*` | Data engineering | User catalog — selectable | Visible | User picks | User |
| `mission.*` | The mission | Visible but not selectable | Visible | **Default — always present** | Nobody (auto) |
| `platform.*` | The platform | Admin only | Visible to admin only | Admin selects | Sysadmin |
| `system.*` | The dispatch engine | **Not in catalog** | **Visible read-only** — costs, errors, logs shown to user. User cannot add, remove, or configure. | **Default — always present** | Sysadmin configures |

**Full agent map (current + planned):**

| Current name | New name | Category | Profile |
|-------------|----------|----------|---------|
| `code.quality.agent` | `software.quality.agent` | software | vertical |
| `code.architecture.agent` | `software.architecture.agent` | software | vertical |
| `horizontal.mission_director.agent` | `mission.director.agent` | mission | horizontal |
| `horizontal.workflow_architect.agent` | `mission.workflow.agent` | mission | horizontal |
| `system.health.agent` | `platform.health.agent` | platform | vertical |
| — | `platform.director.agent` | platform | horizontal |
| `horizontal.planning.agent` | `system.planning.agent` | system | horizontal |
| `horizontal.verification.agent` | `system.verification.agent` | system | horizontal |
| `horizontal.synthesis.agent` | `system.synthesis.agent` | system | horizontal |
| `horizontal.summarization.agent` | `system.summarization.agent` | system | horizontal |

**Future agents (slot in naturally):**

| Name | Category | Profile |
|------|----------|---------|
| `software.coder.agent` | software | vertical |
| `infrastructure.deploy.agent` | infrastructure | vertical |
| `infrastructure.monitor.agent` | infrastructure | vertical |
| `security.scanner.agent` | security | vertical |
| `security.audit.agent` | security | vertical |
| `data.analyst.agent` | data | vertical |
| `data.pipeline.agent` | data | vertical |
| `platform.db_admin.agent` | platform | vertical |

**Directory structure:**

```
config/agents/
  software/                      # user selects — software engineering
    quality/agent.yaml           #   software.quality.agent
    architecture/agent.yaml      #   software.architecture.agent
  mission/                       # always present — mission-level agents
    director/agent.yaml          #   mission.director.agent
    workflow/agent.yaml          #   mission.workflow.agent
  platform/                      # admin only — platform operations
    health/agent.yaml            #   platform.health.agent
    director/agent.yaml          #   platform.director.agent
  system/                        # always present, hidden — dispatch infrastructure
    planning/agent.yaml          #   system.planning.agent
    verification/agent.yaml      #   system.verification.agent
    synthesis/agent.yaml         #   system.synthesis.agent
    summarization/agent.yaml     #   system.summarization.agent
```

**The `horizontal` category and `agent_type` field:**

The `horizontal` directory goes away. Its agents split by who they serve:
- User-facing horizontals → `mission.*`
- Internal horizontals → `system.*`
- Admin horizontals → `platform.*`

The `agent_type: vertical | horizontal` field stays in config as an implementation detail — it determines the deps class (whether the agent has delegation authority via `HorizontalAgentDeps`). It's just no longer a naming concern.

#### 4.8.2 Invocation Tier Model

**New config field:**

```python
# modules/backend/agents/config_schema.py — add to AgentConfigSchema

class InvocationSchema(_StrictBase):
    """Who can invoke this agent."""
    tier: Literal["user", "platform", "system"] = "user"
    required_role: Literal["admin", "user"] | None = None
```

**Schema validation rules:**

| Rule | Enforced by |
|------|------------|
| `platform.*` agents must have `tier: platform` | Schema validator |
| `platform.*` agents must have `required_role: admin` | Schema validator |
| `platform.*` agents must have `execution.mode: local` | Schema validator |
| `system.*` agents must have `tier: system` | Schema validator |
| Non-`platform.*` agents cannot claim `tier: platform` | Schema validator |
| Non-`system.*` agents cannot claim `tier: system` | Schema validator |

**Registry behavior:**

| Method | Returns | Used by |
|--------|---------|---------|
| `list_all(tier="user")` | `software.*` + `mission.*` agents | User-facing catalog API (selectable agents) |
| `list_all(tier="platform")` | `software.*` + `mission.*` + `platform.*` agents | Admin catalog API |
| `list_system()` | `system.*` agents only | Dispatch loop (loading pipeline agents) |

> **Note:** `system.*` agents are excluded from the catalog (not selectable) but **visible in execution logs, cost breakdowns, and error displays**. Users see what system agents did and what they cost — they just can't add, remove, or configure them. This is read-only visibility, not hidden.

#### 4.8.3 Platform Missions (Option 5)

**Mission tier — one new column:**

```python
# modules/backend/models/mission.py — add to Mission class

class MissionTier(str, enum.Enum):
    USER = "user"
    PLATFORM = "platform"

tier: Mapped[str] = mapped_column(
    Enum(MissionTier, native_enum=False),
    default=MissionTier.USER,
    nullable=False,
    comment="Mission tier: user (standard) or platform (admin-only)",
)
```

**How it works:**

| Step | User mission | Platform mission |
|------|-------------|-----------------|
| Creation | Any authenticated user | Admin role required |
| `system.*` agents | Auto-added, hidden | Auto-added, hidden |
| `mission.*` agents | Auto-added, visible | Auto-added, visible |
| Director | `mission.director.agent` | `platform.director.agent` |
| Agent catalog | `software.*`, `data.*`, `security.*`, `infrastructure.*` | All of the above + `platform.*` |
| Roster | User picks from catalog | Admin picks from full catalog |

**Director selection:**

```python
# dispatch_adapter.py — when resolving chat/director agent
director = (
    "platform.director.agent" if mission.tier == "platform"
    else "mission.director.agent"
)
```

**API validation:**

```python
# missions endpoint — at creation time
if mission_create.tier == "platform" and current_user.role != "admin":
    raise HTTPException(403, "Platform missions require admin role")
```

**Roster validation:**

```python
# roster assignment — prevent users from adding platform agents
agent_config = registry.get(agent_name)
if agent_config.invocation.tier == "platform" and mission.tier != "platform":
    raise ValidationError("Platform agents can only be added to platform missions")
```

#### 4.8.4 Director Context Scoping

The two directors are the same pattern (conversational horizontal agent) but with fundamentally different context boundaries. This is enforced through **tools and deps injected at runtime**, not through the agent's reasoning.

| | `mission.director.agent` | `platform.director.agent` |
|--|--------------------------|--------------------------|
| **Sees missions** | Its own mission only | All missions across the platform |
| **Sees context** | Mission brief, execution history, task results for that mission | All mission briefs, all execution history, platform-wide patterns |
| **Sees costs** | Cost for this mission | Cost across all missions, per-user, per-agent |
| **Sees errors** | Errors in this mission's executions | All errors, platform health, failure patterns |
| **Sees config** | Its mission's roster, workflows | Platform config, all agent configs, all rosters |
| **Sees logs** | Its mission's execution logs | Platform logs, service health, system agent performance |
| **Can delegate to** | User-tier agents in its roster | User-tier + platform-tier agents |
| **Invoked by** | Any user on that mission | Admin only |

**Enforcement mechanism:**

- `mission.director.agent` receives deps with `mission_id`-scoped queries — its tools physically cannot query other missions' data
- `platform.director.agent` receives deps with unscoped queries + platform tools (health checks, config access, cross-mission analytics)

The LLM doesn't decide what it can see — the tool implementations enforce the boundary. A prompt injection in the mission director cannot escalate to platform access because the platform tools don't exist in its schema.

**Implementation:** Both directors use the same `HorizontalAgentDeps` base class. The difference is which tools are registered via `@agent.tool` and what scope the deps carry:

```python
# modules/backend/agents/mission/director/agent.py
# Tools: mission_context, mission_status, mission_history, delegate_to_agent
# Deps: mission_id (scoped), allowed_agents (user-tier only)

# modules/backend/agents/platform/director/agent.py
# Tools: all of the above (unscoped) + platform_health, platform_config,
#         cross_mission_analytics, system_agent_status
# Deps: no mission_id scope, allowed_agents (user + platform tier)
```

#### 4.8.5 Impact on `resolve_module_path()`

The current registry derives Python import paths from `agent_type`:
- `vertical` → `modules.backend.agents.vertical.{category}.{name}.agent`
- `horizontal` → `modules.backend.agents.horizontal.{name}.agent`

With the new naming, this becomes:
- All agents → `modules.backend.agents.{category}.{name}.agent`

```python
# registry.py — simplified
def resolve_module_path(self, agent_name: str) -> str:
    parts = agent_name.replace(".agent", "").split(".")
    category = parts[0]   # software, mission, platform, system
    name = parts[1]       # quality, director, planning, etc.
    return f"modules.backend.agents.{category}.{name}.agent"
```

The `modules/backend/agents/` directory mirrors `config/agents/`:

```
modules/backend/agents/
  software/
    quality/agent.py
    architecture/agent.py
  mission/
    director/agent.py
    workflow/agent.py
  platform/
    health/agent.py
    director/agent.py
  system/
    planning/agent.py
    verification/agent.py
    synthesis/agent.py
    summarization/agent.py
```

The current `modules/backend/agents/vertical/` and `modules/backend/agents/horizontal/` directories are replaced by category-based directories.

---

## 5. Implementation Sequence

### Resequencing Rationale (v1.1.0)

The original sequence placed worktrees (Phase 2) before containers (Phase 4). After adversarial review, the sequence is reversed:

1. **Agents don't write files directly.** They use tools (`filesystem.read_file`, `code.apply_fix`) mediated by FileScope. A worktree is solving a problem that doesn't exist yet.
2. **Containers solve a real problem.** When agents need to run tests, install packages, or verify migrations — that requires real isolation that Docker provides natively.
3. **Worktrees introduce unresolved complexity.** FileScope path resolution breaks when worktrees live in sibling directories (adversarial finding B1). Crash recovery requires idempotent git operations (B2). Concurrent worktrees deadlock on `.git/index.lock` (S1). All solvable, but not needed yet.
4. **Worktrees are an optimization, not a foundation.** They become valuable when agents run 50+ lightweight tasks/day and the 5-30s container overhead matters. That's Phase 6, not Phase 2.

Containers first → ship value (real test execution in isolation), defer complexity (FileScope, lock contention, crash recovery), and the `ExecutionBackend(Protocol)` still ensures worktrees plug in cleanly later.

These changes should be implemented in this order, as each phase builds on the previous:

### Phase 1: Agent Rename + Invocation Tiers

Naming is foundational — everything else builds on these names and paths. Pure refactor, no new runtime behavior.

1. Add `InvocationSchema` to `modules/backend/agents/config_schema.py` — `tier` (user/platform/system) + `required_role` fields
2. Add `invocation` field to `AgentConfigSchema`
3. Add schema validators enforcing tier constraints (`platform.*` must be `tier: platform`, etc.)
4. Rename all agent YAMLs and directories per Section 4.8.1 rename map (`code.*` → `software.*`, `horizontal.*` → `mission.*`/`system.*`, `system.health` → `platform.health`)
5. Rename all agent Python modules — move from `modules/backend/agents/vertical/` and `modules/backend/agents/horizontal/` to `modules/backend/agents/{category}/{name}/`
6. Update all imports, tests, and references across the codebase
7. Update `AgentRegistry.resolve_module_path()` — simplified category-based resolution (Section 4.8.5)
8. Add `list_system()` method to `AgentRegistry` for dispatch-internal agents
9. Add `tier` parameter to `AgentRegistry.list_all()` for catalog filtering
10. Update doc 47 agent naming convention and access control matrix

**Deliverable:** All agents renamed. Registry supports tier-based filtering. `system.*` agents visible read-only in execution logs but not in catalog. No new runtime behavior — all agents still run `local`.

### Phase 2: Platform Missions + Platform Director

Depends on Phase 1 (naming must be done). Unlocks admin workflows.

1. Add `MissionTier` enum and `tier` column to `Mission` model (`modules/backend/models/mission.py`)
2. Add API validation — platform missions require admin role
3. Add roster validation — platform agents only in platform missions
4. Add director selection logic — `mission.director.agent` vs `platform.director.agent` based on `mission.tier`
5. Create `platform.director.agent` YAML config + agent implementation with platform-scoped tools and unscoped context access (Section 4.8.4)
6. Add auto-assignment logic — `system.*` and `mission.*` agents added to every new mission by default
7. Generate Alembic migration for `tier` column

**Deliverable:** Sysadmins can create platform missions with admin-only access. Platform director provides conversational access to platform-wide context, costs, errors, and health. User missions unchanged.

### Phase 3: Execution Environment Model

Schema/model work for execution environments. Independent of Phases 1-2 but logically follows.

1. Add `ExecutionEnvironment` enum to `modules/backend/models/execution.py` (alongside `ExecutionState`)
2. Add `execution_environment` column to `Execution` model (`modules/backend/models/execution.py:124`)
3. **Wire the dead `environment` parameter** in `ExecutionService.create_execution_from_step()` (`services/execution.py:112`) — it already accepts `environment: str = "local"` but never passes it to `Execution()`. Fix this.
4. Add `execution_environment` column to `Mission` model as the default for its executions. Inheritance: `Execution.execution_environment = resolve_execution_mode() or Mission.execution_environment or "local"`.
5. **Validate `repo_root` at environment resolution time** — if `mission.repo_root` is null and mode resolves to `worktree` or `container`, raise a clear validation error at plan creation, not at execution time. If mode is `auto`, fall back to `local`.
6. Extend `ExecutionSchema` in `modules/backend/agents/config_schema.py` with `prefer`, `template`. Defer `branch_prefix` and `worktree_base_dir` to Phase 8.
7. Update workflow step schema (`modules/backend/schemas/workflow.py:87-89`) — change environment pattern from `^(local|container|sandbox)$` to `^(local|worktree|container|sandbox|auto)$`
8. Add `execution_mode: str | None = None` to `MissionWorkflowInput` (`modules/backend/temporal/models.py:13`)
9. Create `ExecutionEnvironmentModel` in new file `modules/backend/models/execution_environment.py`
10. Create `config/settings/environments.yaml` (new file)
11. Generate Alembic migration for all new columns and tables
12. Update doc 47 Dimension 4 with three execution modes

**Deliverable:** Data model supports three execution modes. All migrations safe (nullable with defaults). No new runtime behavior — all agents still run `local`.

> **Note:** `max_iterations` is NOT added to Mission. It belongs on the convergence loop task's `input_data` (Phase 6), not the mission — a single mission may have multiple convergence loops with different limits, or none at all.

### Phase 4: Container Backend

1. Define `ExecutionBackend(Protocol)` in `modules/backend/services/execution_environment.py` — shared interface for all backends (`create`, `execute`, `commit_changes`, `cleanup`). Follow the codebase's Protocol pattern (`core/protocols.py`, `agents/mission_control/models.py`).
2. Create `modules/backend/services/container_backend.py` — `ContainerBackend` implementing `ExecutionBackend` and doc 45's `ContainerBackend(ABC)` interface. Uses `docker-py` for Docker Engine interaction.
3. Add `git_aware` template option — when `git_aware: true`, mount host's `.git` read-only, create worktree inside container via `git worktree add`.
4. Create `config/dockerfiles/code-workspace.Dockerfile` — Python workspace image with git, pip cache volume.
5. Create `modules/backend/services/execution_environment.py` — `ExecutionEnvironmentService` facade dispatching to backends via `ExecutionBackend` protocol.
6. Wire `ExecutionEnvironmentService` into FastAPI dependency injection (following pattern of existing services in `modules/backend/services/`).
7. Add container configuration to `config/settings/environments.yaml` (templates, resource limits, network policy).
8. Add `cleanup_stale_environments` as a scheduled task in `modules/backend/tasks/scheduled.py` (follow existing `daily_cleanup` / `hourly_health_check` pattern). Handles stopped containers, orphaned volumes.
9. Update doc 45 with Git-Aware Container section.
10. Test: container mounts `.git`, creates worktree inside, agent commits, branch is pushable.

**Deliverable:** Containers provide full runtime isolation with git-aware branch management. `ExecutionBackend(Protocol)` ensures worktrees (Phase 8) plug in cleanly. Docker handles crash recovery and cleanup natively — no idempotency/lock concerns.

### Phase 5: Dispatch Integration

1. Create `modules/backend/agents/mission_control/dispatch/environment.py` — `resolve_execution_mode()` function
2. Add `execution_mode` parameter to `MissionControlDispatchAdapter.execute()` (`dispatch_adapter.py:38`)
3. Wire environment resolution into `dispatch/loop.py` before `execute_with_step_events()`. When mode is `container`, call `ExecutionEnvironmentService.resolve_or_create()` and pass the container's workspace path as `project_root` to the agent. This solves the FileScope path resolution issue — `project_root` is always the agent's working directory, whether that's the main repo or a container workspace.
4. Add `execution_mode` to `Execution` creation in `modules/backend/services/execution.py`

**Deliverable:** The dispatch loop dynamically selects container vs. local based on task characteristics. Agents are unaware of their execution environment. FileScope works correctly because `project_root` is set to the container workspace.

### Phase 6: Convergence Loop Pattern

1. Create `modules/backend/agents/mission_control/dispatch/convergence.py` — loop executor. `max_iterations` is configured per-loop in task `input_data`, not on Mission.
2. Add `convergence_loop` task type to `modules/backend/schemas/task_plan.py`
3. Add convergence events to `modules/backend/events/types.py`
4. Wire convergence loop into `dispatch/loop.py` (when task type is `convergence_loop`, delegate to `convergence.py` instead of `execute_with_step_events`)
5. Integrate with existing gate system (`gate.py`): use `GateReviewer` for inter-cycle decisions. After each evaluation cycle, invoke gate at `"convergence_cycle"` checkpoint — reviewer can `CONTINUE` (next cycle), `ABORT` (stop loop), or `MODIFY` (adjust convergence condition). Do NOT create a parallel decision framework.
6. Use PQI service directly for `quality_threshold` convergence condition (`modules/backend/services/pqi/types.py` → `PQIResult.composite_score`). Do not reinvent scoring.

> **Note:** The convergence loop is environment-agnostic — it works in `local`, `container`, or (later) `worktree` mode. It can be shipped and used independently of execution environments.

**Deliverable:** The plan engine supports iterative QA/fix cycles with configurable convergence conditions, max iterations, per-cycle audit trails, and gate integration for human/AI override at cycle boundaries.

### Phase 7: Branch Strategy & PR Automation

1. Implement agent branch naming convention (`agent/{mission-id}/{task-type}`) in `ContainerBackend` git operations
2. Implement cleanup policy in lifecycle maintenance scheduled task
3. Implement PR automation (push, open PR, assign reviewer, label)

**Deliverable:** Agent branches follow `agent/{mission-id}/{task-type}` convention. PRs are opened automatically when missions complete. Stale branches are pruned.

### Phase 8: Worktree Backend (optimization)

> **Prerequisite:** Only implement when agents are running frequent lightweight code-only tasks (linting, type annotations, config changes) and the 5-30s container overhead is a measurable bottleneck.

1. Create `modules/backend/services/worktree_backend.py` — `WorktreeBackend` implementing `ExecutionBackend(Protocol)`. All git operations must use `asyncio.create_subprocess_exec`.
2. **Solve FileScope path resolution** — when provisioning a worktree, set `project_root` to the worktree path (same pattern as container mode from Phase 5).
3. **Idempotent worktree creation** — `create_worktree()` must check if branch/worktree already exists and reuse. Add `recover_worktrees()` method called on platform startup to reconcile DB records with filesystem state.
4. **Git lock retry** — all git subprocess calls retry with exponential backoff (3 retries, 100ms/500ms/2s) on `index.lock` errors. `prune_stale_worktrees()` detects and removes stale lock files (`.git/index.lock` older than 60s).
5. Add `branch_prefix` and `worktree_base_dir` to `ExecutionSchema` (deferred from Phase 3).
6. Add worktree configuration to `config/settings/environments.yaml`
7. Update doc 45 with Worktree Backend section

**Deliverable:** `WorktreeBackend` provides fast (~100ms) branch isolation for code-only agent tasks. Crash-safe, lock-contention-resilient, and FileScope-compatible. Plugs into existing `ExecutionEnvironmentService` via `ExecutionBackend` protocol with zero dispatch changes.

### Phase 9: Final Verification Pattern

1. Implement the "ephemeral per mission + final clean verification" pattern in `convergence.py`
2. After convergence loop completes, optionally spin up a fresh container, check out the branch, bootstrap from zero, run full suite
3. If pass → open PR. If fail → flag for human review.

**Deliverable:** The platform can prove a branch is deployable from zero before any human sees the PR.

---

## 6. Cross-Reference: Which Existing Content to Preserve

These changes are additive. No existing content is deleted. Specific preservation notes:

| Document | Existing Content | Status |
|----------|-----------------|--------|
| 45 (Execution Environments) | Container lifecycle, DockerBackend, network isolation, gVisor, Temporal integration | **Unchanged** — worktree content is added alongside, not replacing |
| 47 (Module Organization) | Dimensions 1-3 (tool access, filesystem scope, delegation authority) | **Unchanged** — only Dimension 4 is updated |
| 40 (Agentic Architecture) | Linear plans, DAG plans, phase descriptions | **Unchanged** — convergence loop is added as a new pattern |
| 46 (Event Session Architecture) | All existing event types, plan schema, memory architecture | **Unchanged** — new events and schema additions only |
| 41 (Agentic PydanticAI) | Dispatch adapter, routing, entry points, middleware, testing | **Unchanged** — execution mode resolution is added to the dispatch loop |
| 12 (Development Workflow) | Git strategy, CI/CD, dependency management | **Unchanged** — agent branch section is added |

---

## 7. Testing Strategy for These Changes

### Unit Tests

| Component | Test |
|-----------|------|
| `WorktreeBackend.create_worktree()` | Creates worktree on new branch, verifies branch exists, verifies worktree directory exists |
| `WorktreeBackend.cleanup_worktree()` | Removes worktree directory, optionally deletes branch |
| `WorktreeBackend.prune_stale_worktrees()` | Identifies and removes worktrees older than TTL |
| `resolve_execution_mode()` | Returns correct mode for various tool/config combinations |
| Convergence loop iteration | Tracks cycle count, applies convergence condition, respects max_iterations |
| Convergence loop events | Correct event types emitted at each stage |

### Integration Tests

| Test | Requires |
|------|----------|
| Create worktree, write file, commit, push, verify branch on remote | Real git repository |
| Create container with `git_aware: true`, mount `.git`, create worktree inside, verify commits | Docker daemon |
| Full convergence loop: QA finds issues → Coder fixes → QA re-validates → converges | Real git repo + Docker (for container mode) or worktree |
| Final verification: fresh container, checkout branch, install, test | Docker daemon |
| Stale branch cleanup | Real git repository with aged branches |

### CI Considerations

- Worktree tests require a real git repository (create temp repo in test fixtures)
- Container tests require Docker daemon (tagged `@pytest.mark.integration`)
- Convergence loop tests with real agents require `TestModel` (no LLM calls)
- Branch cleanup tests require a git remote (can use bare repo as test fixture)

---

## 8. Glossary of New Terms

| Term | Definition |
|------|-----------|
| **Worktree** | A git working directory checked out from a shared `.git` object store. Has its own branch, HEAD, and index. Near-instant creation. |
| **Git-aware container** | A Docker container that mounts the host's `.git` object store and creates a worktree inside for branch-isolated code execution with full runtime isolation. |
| **Convergence loop** | An iterative plan pattern where an evaluation agent and a remediation agent alternate until a quality gate is met or a maximum iteration count is reached. |
| **Convergence condition** | The quality gate that determines when a convergence loop has succeeded: all tests pass, zero findings, metric threshold, etc. |
| **Final clean verification** | An optional step after convergence where a fresh ephemeral container bootstraps from zero (install, migrate, test) to prove the branch is deployable. |
| **Execution mode resolution** | The dispatch loop's process of determining whether a task runs in `local`, `worktree`, or `container` mode, based on task characteristics, agent config, and explicit overrides. |
| **Agent branch** | A git branch created by the platform for agent work, following the naming convention `agent/{mission-id}/{task-type}`. |
| **Ephemeral per mission** | Container lifecycle where the container exists for the duration of all iterations within one mission, then is destroyed. Loop iterations share the running environment; each new mission gets a fresh container. |

---

## 9. Open Questions for Architecture Review

1. **Worktree path location:** Should worktrees be created in a sibling directory (`../agent-workspaces/`) or in a subdirectory within the repo (`.agent-workspaces/`, gitignored)? Sibling is cleaner for git but may surprise users who `ls` the parent directory.

2. **Concurrent worktree limit:** What's the right default for `max_concurrent_worktrees`? The conversation suggested 5-10 concurrent agents. Git itself has no limit, but filesystem and process resources are finite.

3. **Submodule handling:** Git worktrees and submodules interact poorly — each worktree needs its own submodule initialization. Should the architecture explicitly prohibit submodules in BFA projects, or document the workaround?

4. **Lock cleanup:** If an agent process dies uncleanly, stale lock files may prevent worktree operations. Should the maintenance task include `git worktree prune` and stale lock detection?

5. **Container image caching:** For the `code-workspace` template, how aggressively should Docker layer caching be used? Caching pip downloads saves ~30s per mission but can serve stale packages.

6. **PR automation scope:** Should the platform open PRs automatically for all agent work, or only for convergence loops? Single-pass worktree tasks (e.g., "add type annotations to this file") might be too small for a full PR workflow.

---

## 10. New Design Principles

These changes introduce two new principles that must be added to the architecture. They are grounded in existing BFA project principles P2 (Deterministic Over Non-Deterministic) and P13 (No Agent Self-Evaluation) from `docs/03-principles/01-project-principles.md`.

### Principle #29: Separation of Evaluation and Execution (doc 40)

**Add to:** `40-agentic-architecture.md`, Design Principles table, Phase 1.

> An agent that produces output must not evaluate the quality of that output. Evaluation and remediation must be performed by different agent instances with different system prompts, different filesystem scope, and ideally different models. This is the agentic equivalent of separation of duties — the same control that prevents the person who writes a cheque from approving it.

**Rationale:** LLMs are systematically biased toward their own output. An agent that writes code and then declares it correct has a single point of failure in its reasoning. Two separate agents with different prompts, different models, and different filesystem access create an adversarial dynamic that catches more errors. Self-correction loops (retrying on syntax errors) are acceptable for mechanical failures. Judgment calls (quality, correctness, completeness) require an external evaluator.

**Enforcement mechanism:** Filesystem scope (doc 47 Dimension 2). An agent with write access to `modules/` cannot have tools that evaluate code quality. An agent with evaluation tools cannot have write access to `modules/`. The access control matrix structurally prevents self-evaluation — it is not a convention, it is a configuration constraint.

**Relationship to project principles:**
- Extends P13 (No Agent Self-Evaluation) from project principles into the reference architecture
- Complements P2 (Deterministic Over Non-Deterministic) — deterministic tools handle the mechanical evaluation (test runners, linters), agents handle only the judgment that requires reasoning

### Principle #30: Deterministic Infrastructure, Non-Deterministic at the Edges (doc 40)

**Add to:** `40-agentic-architecture.md`, Design Principles table, Phase 1.

> Platform infrastructure — environment provisioning, plan dispatch, budget enforcement, state machine transitions, branch management, PR automation — is deterministic code. Agents are invoked only at the edges where reasoning is required: task decomposition, code generation, quality judgment, and failure recovery. Never use an agent where a script, a tool, or a state machine will produce the same or better result.

**Rationale:** An LLM call is non-deterministic, slow, and expensive. A bash script running `pip install` is deterministic, fast, and free. The line between "infrastructure" and "intelligence" is sharp: infrastructure does the same thing every time from the same inputs; intelligence reasons about ambiguous situations with unknown structure. Crossing this line in the wrong direction (using an agent for deterministic work) wastes money and introduces non-determinism where reproducibility is needed.

**Relationship to project principles:**
- Direct implementation of P2 (Deterministic Over Non-Deterministic)
- Reinforces P6 (Mission Control Is Infrastructure, Not Intelligence) — mission control is deterministic orchestration code, not an agent

---

## 11. Agent Roster for the Convergence Loop

This section defines the complete agent roster for a QA convergence loop, the access control constraints that enforce separation of duties, and the deterministic platform steps that bookend the agent work.

### 11.1 The Roster

The convergence loop requires **four core agents** plus **two optional agents** and **three deterministic platform steps**. The distinction between agent and platform code follows P2: if it requires reasoning, it's an agent. If it's the same sequence every time, it's platform code.

#### Platform Step: Environment Provisioning (deterministic)

This is NOT an agent. It is `ExecutionEnvironmentService` code that executes a deterministic sequence from the environment template.

| Concern | Value |
|---------|-------|
| What it does | Create worktree or container, `pip install`, run migrations, seed fixtures, verify all exit codes |
| Why not an agent | Same commands every time for a given project. No judgment. No ambiguity. P2 says use a tool. |
| When it runs | Once, before the loop starts |
| Failure handling | If any step fails → invoke `system.env.agent` for recovery (see below) |

The provisioning sequence for a git-aware container:

```
1. docker create (from template)              ← deterministic
2. docker start                               ← deterministic
3. git worktree add /workspace {branch}       ← deterministic
4. pip install -r requirements.txt            ← deterministic
5. alembic upgrade head                       ← deterministic
6. python -m pytest --co -q (collect only)    ← deterministic (verify tests discoverable)
7. seed test fixtures                         ← deterministic
8. verify: all exit codes == 0                ← deterministic
```

No LLM touches this sequence. It's a script.

#### Agent 1: `code.planner.agent` — The Architect

Looks at the mission objective and produces the TaskPlan. Decides what needs to happen. Never touches code. Runs once before the loop.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet or Opus — needs strong reasoning for task decomposition |
| **Filesystem read** | `docs/`, `config/`, Code Map (doc 49), PCD (doc 48) |
| **Filesystem write** | None |
| **Tools** | `plan.create_plan`, `plan.revise_plan`, `filesystem.read_file`, `filesystem.list_files` |
| **Execution mode** | `local` — reads project structure, no code modification |
| **Role in loop** | Pre-loop only. Produces the plan. May be consulted mid-loop if the Coder escalates or the plan needs revision (P8). |
| **Separation of duties** | Plans the work but never executes it. Cannot see test results or code changes. |
| **P2 alignment** | The Planner uses LLM reasoning because task decomposition is inherently ambiguous — it requires understanding intent, assessing complexity, and making scope judgments. A deterministic tool cannot do this. |

#### Agent 2: `code.coder.agent` — The Developer

Reads findings from the QA agent, applies fixes, commits. Writes code but **never runs tests and never evaluates its own changes**.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs strong coding capability |
| **Filesystem read** | `modules/`, `config/` (source code only) |
| **Filesystem write** | `modules/`, `config/` |
| **Explicitly excluded** | `tests/` — cannot read test assertions. `docs/` — cannot read specifications. |
| **Tools** | `filesystem.read_file`, `filesystem.write_file`, `filesystem.list_files`, `filesystem.search_files`, `code.apply_fix`, `git.commit` |
| **Execution mode** | `worktree` or `container` (depending on mission) |
| **Role in loop** | Receives findings → reads affected files → applies fixes → commits. One cycle per iteration. |
| **Separation of duties** | Writes code but cannot evaluate it. Has no access to test files (cannot game tests). Has no access to docs (cannot expand scope beyond targeted fixes). |
| **P2 alignment** | Applying code fixes from structured findings requires reasoning about code structure, naming, patterns, and side effects. A deterministic tool cannot do this — it's the core creative act. |
| **P13 alignment** | Cannot run tests. Cannot assess quality. Must hand back to QA for evaluation. |

**Why exclude `tests/` and `docs/`?** Two critical constraints:

1. **No `tests/` access prevents test gaming.** If the Coder can read test assertions, it can write code that satisfies the specific assertion rather than fixing the underlying issue. By denying access to tests, the Coder must fix the root cause based on the QA findings, not the symptoms based on test expectations.

2. **No `docs/` access constrains scope.** The Coder's job is to fix what QA flagged — nothing more. If it can read documentation, it may decide to "improve" things beyond the findings, expanding scope and introducing unplanned changes. The findings are the Coder's work order. Nothing else.

#### Agent 3: `code.tester.agent` — The Test Engineer

Writes and updates tests. Has the **inverse access pattern** to the Coder — reads `docs/` and `tests/` but **cannot see or modify source code**.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs to understand both documentation intent and test patterns |
| **Filesystem read** | `docs/`, `tests/`, `config/` |
| **Filesystem write** | `tests/` only |
| **Explicitly excluded** | `modules/` — cannot see source code implementation |
| **Tools** | `filesystem.read_file`, `filesystem.write_file`, `filesystem.list_files`, `code.run_tests` |
| **Execution mode** | `worktree` or `container` |
| **Role in loop** | Optional. Pre-loop: reviews whether existing tests cover the mission objective, adds tests if needed. Post-loop: adds regression tests for issues found during the cycle. |
| **Separation of duties** | Writes tests but cannot write source code. Tests are derived from documentation (intent), not from implementation (current behavior). |
| **P2 alignment** | Understanding documentation intent and translating it into test assertions requires reasoning about specifications, edge cases, and coverage gaps. Deterministic tools cannot do this. |
| **P13 alignment** | The Tester does not evaluate whether the source code is correct — it defines what "correct" means in test form. The QA agent evaluates by running those tests. |

**Why exclude `modules/` from the Tester?** This is the most powerful constraint in the roster. By denying the Tester access to implementation, it writes tests that verify **what the system should do** (from docs), not **what the code currently does** (from implementation). This prevents the tautological test problem where tests merely assert current behavior — including bugs — rather than correct behavior.

A test written from documentation catches implementation bugs. A test written from implementation enshrines them.

#### Agent 4: `code.qa.agent` — The Quality Gate

Runs the test suite, static analysis, linting, and composite quality metrics. Produces structured findings. **Cannot modify any code.** Pure evaluator.

| Dimension | Value |
|-----------|-------|
| **Model** | Haiku — fast and cheap. Runs predefined checks, not creative reasoning. |
| **Filesystem read** | Everything: `modules/`, `tests/`, `config/`, `docs/` (full visibility needed to evaluate) |
| **Filesystem write** | None — zero write access anywhere |
| **Tools** | `code.run_tests`, `code.lint`, `compliance.scan_*`, `filesystem.read_file`, `filesystem.list_files` |
| **Execution mode** | Same as the Coder (operates in the same worktree/container) |
| **Role in loop** | The evaluation half of the convergence loop. Runs suite → produces structured findings → hands to Coder. Every iteration. |
| **Separation of duties** | Can observe everything but change nothing. This makes it a trustworthy evaluator — it has no ability to hide its own mistakes because it cannot make any. |
| **P2 alignment** | The individual checks (pytest, flake8, mypy) are deterministic tools invoked by the agent. The agent's role is interpreting composite results, prioritizing findings by severity, and deciding whether convergence criteria are met. The mechanical execution is P2-compliant (tools do the scanning); the judgment layer is where the LLM adds value. |
| **P13 alignment** | The QA agent never wrote the code it's evaluating. It has no authorship bias. |

#### Agent 5 (Optional): `code.reviewer.agent` — The Code Reviewer

Post-loop qualitative review of the entire diff. Catches things automated QA misses: logic errors that pass tests, misleading naming, architectural drift.

| Dimension | Value |
|-----------|-------|
| **Model** | Opus — needs the strongest judgment for qualitative assessment |
| **Filesystem read** | Everything: `modules/`, `tests/`, `docs/`, `config/` |
| **Filesystem write** | None |
| **Tools** | `filesystem.read_file`, `git.diff`, `git.log` |
| **Execution mode** | `local` — reviewing a diff, not executing code |
| **Role in loop** | Post-loop only. Runs once after convergence, before PR. Produces: approve, request changes, or escalate to human. If it requests changes, findings feed back to the Coder for one more iteration. |
| **Separation of duties** | Reviews but does not write. Different model (Opus) from the Coder (Sonnet) ensures different reasoning patterns. |
| **P2 alignment** | Qualitative code review — "is this the right abstraction? will this scale? does this naming communicate intent?" — is inherently non-deterministic. It requires judgment, experience, and reasoning about implications. This is the correct use of an LLM. |

#### Agent 6 (Invoked on failure): `system.env.agent` — Infrastructure Recovery

NOT part of the happy path. Invoked only when deterministic provisioning fails. Reads error output, diagnoses the problem, applies a fix, and returns retry instructions.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs to read error messages and reason about fixes |
| **Filesystem read** | Everything — needs to inspect `requirements.txt`, `Makefile`, `pyproject.toml`, `docker-compose.yml`, migration files, error logs |
| **Filesystem write** | `config/`, environment template files, Dockerfiles — can fix environment configuration |
| **Tools** | `filesystem.read_file`, `filesystem.list_files`, `system.exec_command`, `system.read_logs`, `system.install_packages` |
| **Execution mode** | Runs INSIDE the container (fixing the environment it's standing in) |
| **Role in loop** | Not part of the QA convergence loop. Upstream. Called only when provisioning fails. |
| **Separation of duties** | Can fix the environment but cannot evaluate whether it's correct. Correctness is structural: did the commands exit 0? That's a deterministic check. |
| **P2 alignment** | Diagnosing "why did `pip install` fail?" requires reading error output, understanding dependency conflicts, and reasoning about system library requirements. This is non-deterministic by nature. But it's at the edge — the recovery agent is invoked only when deterministic automation hits something it can't handle. The happy path never touches an LLM. |

### 11.2 The Access Control Matrix

This is the enforcement mechanism for Principle #29 (Separation of Evaluation and Execution). No single agent can both modify the system AND declare it correct.

| Agent | Read `modules/` | Write `modules/` | Read `tests/` | Write `tests/` | Read `docs/` | Run tests | Evaluate quality | Fix code |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `code.planner` | — | — | — | — | ✓ | — | — | — |
| `code.coder` | ✓ | **✓** | — | — | — | — | — | **✓** |
| `code.tester` | — | — | ✓ | **✓** | ✓ | ✓ | — | — |
| `code.qa` | ✓ | — | ✓ | — | ✓ | **✓** | **✓** | — |
| `code.reviewer` | ✓ | — | ✓ | — | ✓ | — | **✓** | — |
| `system.env` | ✓ | — | — | — | ✓ | — | — | — |

**Three structural constraints enforced by this matrix:**

1. **The Coder cannot run tests.** It cannot verify its own fixes. It must hand back to QA.
2. **The QA agent cannot write code.** It cannot fix what it finds. It must hand to the Coder.
3. **The Tester cannot see source code.** It writes tests from documentation intent, not from implementation reality.

No single agent can both modify the system AND declare it correct. This is not a convention — it is enforced by the `scope` configuration in each agent's YAML (doc 47, Dimension 2).

### 11.3 The Full Flow with Deterministic/Non-Deterministic Boundaries

Every step is explicitly labeled as **deterministic platform code** (P2: tool/script) or **non-deterministic agent** (reasoning required). The boundary between the two is sharp and intentional.

```
code.planner.agent ← NON-DETERMINISTIC (task decomposition requires reasoning)
    │ Produces: TaskPlan + file manifests + convergence criteria
    │ Access: docs/, config/, Code Map, PCD (read-only)
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (same sequence every time from template)
    │ Provision execution environment:
    │   create worktree/container → pip install → migrate → seed → verify exit codes
    │
    │ ── ALL EXIT CODES 0? → proceed
    │ ── ANY FAILURE? ─────→ system.env.agent ← NON-DETERMINISTIC (diagnose + fix)
    │                              │                  (edge case: reasoning about errors)
    │                              └→ retry provisioning (deterministic)
    │
    ▼
code.tester.agent (optional) ← NON-DETERMINISTIC (translating doc intent to test assertions)
    │ Reviews: do existing tests cover the mission objective?
    │ Writes: new/updated tests in tests/ only
    │ Access: docs/ + tests/ (cannot see modules/)
    │
    ▼
┌─── CONVERGENCE LOOP ─────────────────────────────────────────────────────┐
│                                                                          │
│   code.qa.agent ← PARTIALLY DETERMINISTIC                               │
│     │ Tools (deterministic): pytest, flake8, mypy, compliance scanners  │
│     │ Agent (non-deterministic): interpret composite results, prioritize │
│     │ Produces: structured findings with severity                        │
│     │ Access: everything (READ-ONLY — zero writes)                       │
│     │                                                                    │
│     │ PLATFORM CODE (deterministic): check convergence condition         │
│     │   ├── Converged? (all tests pass / zero criticals / metric > N)   │
│     │   │   → EXIT LOOP (success)                                       │
│     │   ├── Max iterations exceeded?                                     │
│     │   │   → EXIT LOOP (escalate to human)                             │
│     │   └── Continue                                                     │
│     │                                                                    │
│     ▼                                                                    │
│   code.coder.agent ← NON-DETERMINISTIC (applying code fixes)            │
│     │ Reads: findings + source code in modules/                          │
│     │ Writes: fixes to modules/, config/                                 │
│     │ Cannot see: tests/, docs/                                          │
│     │                                                                    │
│     │ PLATFORM CODE (deterministic): git commit                          │
│     │   commit message follows template, no LLM needed                  │
│     │                                                                    │
│     └──→ LOOP BACK TO QA                                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
    │
    ▼
code.tester.agent (optional) ← NON-DETERMINISTIC
    │ Adds: regression tests for issues found during loop
    │ Access: docs/ + tests/ (cannot see modules/)
    │
    ▼
code.reviewer.agent (optional) ← NON-DETERMINISTIC (qualitative judgment)
    │ Reviews: the full diff (branch vs main)
    │ Produces: approve / request changes / escalate
    │ Access: everything (READ-ONLY)
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (same verification every time)
    │ Final Clean Verification:
    │   fresh container → checkout branch → pip install → migrate → pytest
    │   All exit codes checked. No LLM involved.
    │   Pass → continue. Fail → escalate to human.
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (git + API calls)
    │ Push branch → open PR → assign reviewer → add labels
    │ PR description generated from mission metadata (template, not LLM)
    │
    ▼
DONE — human reviews PR
```

### 11.4 Why Each Non-Deterministic Step Requires an Agent

Per P2, every LLM call must justify itself. Here's the justification for each agent invocation:

| Agent | Why a deterministic tool cannot do this |
|-------|----------------------------------------|
| `code.planner` | Task decomposition requires understanding intent, assessing complexity, identifying dependencies, and scoping work. There is no algorithm that decomposes "improve the authentication module" into specific file-level tasks. |
| `code.coder` | Applying code fixes from structured findings requires understanding code context, choosing the right abstraction, maintaining naming consistency, and avoiding side effects. A regex find-replace can handle trivial cases; a refactor requires reasoning. |
| `code.tester` | Translating documentation intent ("the system should validate email format") into test assertions (`assert service.validate("bad@@email") raises ValidationError`) requires understanding specifications, identifying edge cases, and writing idiomatic test code. |
| `code.qa` | Individual tools (pytest, flake8) are deterministic and invoked as tools — not via LLM. The agent adds value by interpreting *composite* results: "15 test failures, 3 linting warnings, and a type error — what's the root cause? What should the Coder fix first?" That prioritization requires reasoning. |
| `code.reviewer` | Qualitative review — "is this the right abstraction? will this scale? does this naming communicate intent?" — is inherently non-deterministic. It requires judgment about code quality that no static analysis tool can provide. |
| `system.env` | Diagnosing provisioning failures ("pip install failed because lxml needs libxml2-dev on this platform") requires reading error output, understanding system dependencies, and reasoning about fixes. But this is the edge case — the happy path is fully deterministic. |

### 11.5 What Stays Deterministic (Per P2)

These operations are **never** routed through an agent, even if an agent could theoretically do them:

| Operation | Why It's Deterministic | Implementation |
|-----------|----------------------|----------------|
| Create worktree / container | Same template → same result every time | `ExecutionEnvironmentService` |
| `pip install` | Lockfile-driven, no reasoning needed | Bash in container |
| `alembic upgrade head` | Migrations are versioned scripts | Bash in container |
| Run pytest | Command execution, exit code check | Tool: `code.run_tests` |
| Run flake8 / mypy | Command execution, parse output | Tool: `compliance.scan_*` |
| Check convergence condition | Compare metric to threshold | Platform code: `if metric >= threshold` |
| Git commit | Template-driven message, no reasoning | Platform code: `git.commit` |
| Git push + open PR | API calls with template data | Platform code |
| Worktree/branch cleanup | Age-based pruning | Scheduled Taskiq task |
| Budget enforcement | Compare accumulated cost to cap | Platform code: `if cost > budget` |
| State machine transitions | Plan status changes | Platform code: `update task set status = ...` |

---

## 12. Changes Required to Existing Principles Documents

### 12.1 Reference Architecture: doc 40 (Agentic Architecture)

**Add to Design Principles table:**

| # | Principle | Phase |
|---|-----------|-------|
| 29 | Separation of Evaluation and Execution — the agent that produces output must not evaluate it. Different agents, different prompts, different filesystem scope, different models. Enforced by access control configuration, not convention. | 1 |
| 30 | Deterministic Infrastructure, Non-Deterministic at the Edges — platform infrastructure is deterministic code. Agents are invoked only where reasoning is required. Never use an agent where a script or tool will produce the same or better result. | 1 |

### 12.2 Reference Architecture: doc 47 (Agent Module Organization)

**Add to "Access Control Model" section** (after the existing access control matrix):

A new subsection: "Worked Example: Convergence Loop Access Control"

This should contain the full access control matrix from Section 11.2 of this document, with the explanation of why each constraint exists. This serves as the canonical example of how filesystem scope enforces separation of duties in a multi-agent workflow.

**Add to "Anti-Patterns" table:**

| Anti-pattern | Why prohibited |
|-------------|---------------|
| Agent evaluates its own output | Violates P29 (Separation of Evaluation and Execution). LLMs are biased toward their own output. Evaluation and remediation must be different agents with different scope. |
| Agent has both write access and evaluation tools | Structurally enables self-evaluation. If an agent can write code AND run tests, it can game the tests. Scope must prevent this. |
| Using an LLM for deterministic operations | Violates P30 (Deterministic Infrastructure). `pip install`, `pytest`, `git commit`, state machine transitions, and budget checks are deterministic. Using an agent adds cost, latency, and non-determinism for zero benefit. |
| Coding agent with access to test files | Enables test gaming — the agent writes code to satisfy specific assertions rather than fixing the underlying issue. Coder scope must exclude `tests/`. |
| Test agent with access to source code | Produces tautological tests that assert current behavior (including bugs) rather than correct behavior. Tester scope must exclude `modules/`. |

### 12.3 Project Principles: docs/03-principles/01-project-principles.md

P13 (No Agent Self-Evaluation) is already present. Two additions:

**Strengthen P13 with enforcement mechanism:**

Add to P13's "This means" section:
- Filesystem scope (doc 47) structurally prevents self-evaluation. An agent with write access to `modules/` cannot have tools that run tests. An agent with evaluation tools cannot have write access to `modules/`. This is configuration-enforced, not convention-based.
- In convergence loops: the Coder agent cannot see `tests/` (prevents test gaming). The Tester agent cannot see `modules/` (prevents tautological tests). The QA agent cannot write anything (prevents self-remediation).

**Add cross-reference between P2 and P13:**

P2 (Deterministic Over Non-Deterministic) and P13 (No Agent Self-Evaluation) together define the boundaries of the convergence loop:
- P2 determines which steps are agents (reasoning) vs. platform code (deterministic)
- P13 determines which agents are distinct (no self-evaluation across the evaluation/execution boundary)

---

## 13. Agent YAML Configuration Examples

These examples show the concrete YAML for each agent in the convergence loop roster, following the schema from doc 47.

### code.coder.agent

```yaml
# config/agents/code/coder/agent.yaml
agent_name: code.coder.agent
agent_type: vertical
description: "Applies code fixes based on structured findings from QA agents"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 2.00
max_input_length: 32000

keywords:
  - fix code
  - apply fix
  - refactor
  - implement

tools:
  - filesystem.read_file
  - filesystem.write_file
  - filesystem.list_files
  - filesystem.search_files
  - code.apply_fix
  - git.commit

# CRITICAL: No tests/, no docs/ — P13 enforcement
scope:
  read:
    - "modules/"
    - "config/"
  write:
    - "modules/"
    - "config/"

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.tester.agent

```yaml
# config/agents/code/tester/agent.yaml
agent_name: code.tester.agent
agent_type: vertical
description: "Writes and updates tests based on documentation intent, not implementation"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 1.00
max_input_length: 32000

keywords:
  - write tests
  - test coverage
  - add tests
  - regression test

tools:
  - filesystem.read_file
  - filesystem.write_file
  - filesystem.list_files
  - code.run_tests

# CRITICAL: No modules/ — P13 enforcement (tests from intent, not implementation)
scope:
  read:
    - "docs/"
    - "tests/"
    - "config/"
  write:
    - "tests/"

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.qa.agent

```yaml
# config/agents/code/qa/agent.yaml
agent_name: code.qa.agent
agent_type: vertical
description: "Evaluates code quality via test execution, linting, and static analysis"
enabled: true
model: anthropic:claude-haiku-4-5-20251001
max_budget_usd: 0.50
max_input_length: 32000

keywords:
  - qa
  - quality
  - audit
  - check code
  - compliance
  - run tests

tools:
  - code.run_tests
  - code.lint
  - compliance.scan_imports
  - compliance.scan_datetime
  - compliance.scan_hardcoded
  - compliance.scan_file_sizes
  - filesystem.read_file
  - filesystem.list_files

# CRITICAL: Read everything, write nothing — pure evaluator
scope:
  read:
    - "modules/"
    - "tests/"
    - "config/"
    - "docs/"
  write: []

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.reviewer.agent

```yaml
# config/agents/code/reviewer/agent.yaml
agent_name: code.reviewer.agent
agent_type: vertical
description: "Qualitative code review of diffs — catches what automated QA misses"
enabled: true
model: anthropic:claude-opus-4-20250514
max_budget_usd: 3.00
max_input_length: 64000

keywords:
  - review
  - code review
  - review diff
  - review changes

tools:
  - filesystem.read_file
  - filesystem.list_files
  - git.diff
  - git.log

# Read everything, write nothing — reviewer does not modify code
scope:
  read:
    - "modules/"
    - "tests/"
    - "config/"
    - "docs/"
  write: []

execution:
  mode: local
```

### system.env.agent

```yaml
# config/agents/system/env/agent.yaml
agent_name: system.env.agent
agent_type: vertical
description: "Diagnoses and recovers from execution environment provisioning failures"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 1.00
max_input_length: 32000

keywords:
  - environment
  - install failed
  - pip error
  - migration error
  - setup failed

tools:
  - filesystem.read_file
  - filesystem.list_files
  - system.exec_command
  - system.read_logs
  - system.install_packages

scope:
  read:
    - "*"
  write:
    - "config/"

execution:
  mode: container
```

---

*End of change specification.*
