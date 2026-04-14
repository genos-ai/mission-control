# Plan 54 — Unify All Scheduling Under Temporal, Remove Taskiq + FastStream

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-13 |
| **Depends on** | Plan 52 (Temporal Backbone — done), Plan 53 (Workflow DB — ready) |
| **Target** | Background tasks, workflow scheduling, event infrastructure, CLI, reference docs |

---

## 1  Problem

Three independent async infrastructure layers coexist for background work and events:

| System | Role | Actually used? |
|--------|------|----------------|
| **Temporal** | Mission execution, chat turns, plan dispatch, supervisor loop, crash recovery | **Yes** — production backbone |
| **Redis Pub/Sub** (`SessionEventBus`) | Real-time event streaming to SSE/TUI/CLI | **Yes** — production event bus |
| **Taskiq** (broker + scheduler + worker) | Background task queue + cron scheduler | **One real caller** — `evaluate_workflow_schedules` (cron every 1 min). All other tasks are stubs. |
| **FastStream** (Redis Streams event broker) | Durable event consumer framework | **Feature-flagged off** (`events_publish_enabled: false`). Zero runtime consumers. |

### Why this is a problem

1. **The only real Taskiq task is `evaluate_workflow_schedules`** — the bridge between cron-based `WorkflowSchedule` rows and `WorkflowRunService`. Every other Taskiq task (`send_notification`, `process_data`, `daily_cleanup`, `hourly_health_check`, `weekly_report`, `metrics_aggregation`, `cleanup_stale_environments`) is a stub that logs and returns a dict. Nothing in services, agents, or API ever calls `.kiq()`.

2. **Daily scheduled workflows depend on Taskiq.** A user who creates a `WorkflowSchedule` with `cron_expression="0 6 * * *"` (daily threat intel brief) relies on the Taskiq scheduler process running. If `admin.py scheduler` isn't started, schedules silently don't fire — no error, no alert.

3. **Temporal already solves the same problem better.** `ScheduledMissionCheckWorkflow` (Plan 52 Phase D) runs on a 5-second Temporal schedule, queries for ready plans, and starts child workflows. It has built-in deduplication, crash recovery, and distributed worker coordination — all things Taskiq warns you to handle manually ("Run only ONE scheduler instance").

4. **FastStream is dormant infrastructure.** The `events_publish_enabled` flag is `false`. `EventPublisher` in `session.py` is the only import, and it never fires. The actual event bus is `SessionEventBus` using raw Redis Pub/Sub.

5. **Cognitive overhead.** Anyone reading the codebase sees `tasks/broker.py`, `events/broker.py`, and `temporal/` and must figure out which is authoritative. The reference architecture doc (14-core-background-tasks.md) documents Taskiq as the standard, contradicting the actual runtime which is Temporal.

### Target state

Two systems only:

- **Temporal** = all durable/scheduled work (missions, chat, plan dispatch, workflow schedules, housekeeping)
- **Redis Pub/Sub** (`SessionEventBus`) = ephemeral real-time events (SSE, TUI, CLI streaming)

---

## 2  Design Decisions

### D1 — Workflow schedule evaluation moves to a Temporal scheduled workflow

A new `ScheduledWorkflowEvalWorkflow` runs on a configurable interval (default: 60 seconds). It calls the existing `WorkflowScheduleService.evaluate_due_schedules()` via a Temporal activity, then starts child `MissionRunWorkflow`s for each fired schedule — identical to how `ScheduledMissionCheckWorkflow` dispatches plan tasks.

**Why not merge into `ScheduledMissionCheckWorkflow`:** Separation of concerns. Plan dispatch (5-second poll, autonomous gate modes) and workflow schedule evaluation (1-minute poll, cron-based) have different intervals, different query logic, and different failure modes. Merging them would create coupling between unrelated features.

### D2 — Housekeeping tasks become Temporal activities called by a single housekeeping workflow

Container cleanup, stale environment cleanup, and future maintenance jobs become activities invoked by a `HousekeepingWorkflow` on a configurable cron (e.g., hourly). This replaces the Taskiq `daily_cleanup`, `hourly_health_check`, `cleanup_stale_environments`, and `metrics_aggregation` stubs — but only `cleanup_stale_environments` has real logic. The rest are deferred (no implementation exists to migrate).

### D3 — FastStream package removed entirely

No consumer code exists. The feature flag was never turned on. The `events/broker.py` FastStream wrapper and `events/middleware.py` observability middleware are unused. If durable consumer groups are needed in the future, they can be rebuilt — but `SessionEventBus` (Redis Pub/Sub + DB persistence) covers the current need.

### D4 — Reference architecture doc 14 updated

The background tasks standard must reflect Temporal as the scheduling/execution layer. The Taskiq examples and architecture diagrams are replaced.

### D5 — `admin.py worker` and `admin.py scheduler` commands removed

These started Taskiq processes. They are replaced by the existing Temporal worker (`services.py` already starts it). `admin.py event-worker` (FastStream) is also removed.

### D6 — Extract idempotent schedule registration helper

The existing `main.py` lifespan has a 20-line try/except/`ScheduleAlreadyRunningError` block for one schedule. Adding two more (workflow eval + housekeeping) would triple-duplicate it. Extract a `register_schedule()` helper in `modules/backend/temporal/schedule_helpers.py` and call it three times.

### D7 — Use child workflows, not blocking activities, for workflow runs

`WorkflowRunService.run_workflow_from_definition()` is **fully synchronous** — it blocks until all workflow steps complete across all waves. A $50-budget workflow can take 100+ minutes (budget × 120 seconds). An activity with a 30-minute timeout would be killed.

The correct pattern — already used by `ScheduledMissionCheckWorkflow` for plan dispatch — is to start child workflows with `ParentClosePolicy.ABANDON`. The parent (evaluation) workflow completes immediately; the child (workflow run) continues independently. This matches the existing architecture.

---

## 3  Phases

### Phase A — Migrate `evaluate_workflow_schedules` to Temporal

**Goal:** Workflow cron schedules fire via Temporal. Taskiq scheduler no longer required.

#### 3.1 New Temporal Activity: `evaluate_due_workflow_schedules`

**New file:** `modules/backend/temporal/workflow_schedule_activities.py`

One activity only — the evaluation query. Workflow runs are started as child workflows (see §3.2), not as activities, because `run_workflow_from_definition()` blocks until all steps complete and can exceed any reasonable activity timeout for high-budget workflows.

```python
"""Temporal activities for workflow schedule evaluation."""

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@activity.defn
async def evaluate_due_workflow_schedules() -> list[dict]:
    """Find due workflow schedules and return info for run creation.

    Calls WorkflowScheduleService.evaluate_due_schedules() which handles:
    - Cron next_fire_at comparison
    - Cooldown period enforcement
    - Daily run cap enforcement
    - Iteration limit enforcement
    - Recording fire + computing next_fire_at

    Returns a list of dicts with schedule_id, workflow_definition_id,
    mission_id, budget_per_run_usd for each fired schedule.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    async with get_async_session() as db:
        schedule_service = WorkflowScheduleService(db)
        fired = await schedule_service.evaluate_due_schedules()
        await db.commit()

    if fired:
        activity.logger.info(
            "Workflow schedules fired",
            extra={"count": len(fired), "schedule_ids": [f["schedule_id"] for f in fired]},
        )

    return fired
```

**Note:** No `execute_scheduled_workflow_run` activity. The workflow (§3.2) starts child workflows instead.

#### 3.2 New Temporal Workflow: `ScheduledWorkflowEvalWorkflow`

**New file:** `modules/backend/temporal/workflow_schedule_workflow.py`

Uses the same child-workflow pattern as `ScheduledMissionCheckWorkflow` (scheduled_workflow.py:75-84). Workflow runs are long-lived and blocking (`run_workflow_from_definition` awaits all steps to completion) — a $50-budget workflow can take 100+ minutes. Child workflows with `ParentClosePolicy.ABANDON` let the evaluation workflow complete immediately while runs continue independently.

```python
"""Scheduled Workflow Evaluation Workflow.

Replaces the Taskiq cron task that called evaluate_workflow_schedules().
Temporal handles timing, deduplication, and crash recovery.

Pattern: same as ScheduledMissionCheckWorkflow — short-lived parent
starts child workflows and completes. Children run independently.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.core.config import get_app_config
    from modules.backend.temporal import workflow_schedule_activities
    from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
    from modules.backend.temporal.models import MissionWorkflowInput


@workflow.defn
class ScheduledWorkflowEvalWorkflow:
    """Evaluate due workflow schedules and start runs as child workflows.

    Short-lived: queries DB for due schedules, starts a child
    MissionRunWorkflow for each, and completes. Children continue
    independently via ParentClosePolicy.ABANDON.

    A Temporal schedule fires this on a configurable interval (default 60s).
    Workflow ID dedup ensures only one evaluation runs at a time.
    """

    @workflow.run
    async def run(self) -> dict:
        config = get_app_config().temporal

        # Step 1: Find due schedules (fast DB query)
        fired_schedules = await workflow.execute_activity(
            workflow_schedule_activities.evaluate_due_workflow_schedules,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not fired_schedules:
            return {"checked": True, "dispatched": 0}

        # Step 2: Start a child workflow for each fired schedule.
        # ParentClosePolicy.ABANDON lets this parent complete
        # while the children run to completion independently.
        dispatched = 0

        for schedule_info in fired_schedules:
            try:
                input_data = MissionWorkflowInput(
                    mission_run_id=schedule_info["schedule_id"],
                    session_id=schedule_info["schedule_id"],
                    mission_brief=f"Scheduled workflow: {schedule_info['workflow_definition_id']}",
                    roster_name="default",
                    mission_budget_usd=schedule_info.get("budget_per_run_usd") or 10.0,
                    mission_id=schedule_info["mission_id"],
                    execution_mode="autonomous",
                )

                # Dedup: one run per schedule per fire. Schedule ID +
                # timestamp-based workflow ID prevents duplicate runs.
                workflow_id = f"workflow-sched-{schedule_info['schedule_id']}"

                await workflow.start_child_workflow(
                    MissionRunWorkflow.run,
                    input_data,
                    id=workflow_id,
                    task_queue=config.task_queue,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
                dispatched += 1
            except Exception as exc:
                workflow.logger.warning(
                    "Failed to start workflow run for schedule %s: %s",
                    schedule_info.get("schedule_id", "?"), exc,
                )

        return {"checked": True, "dispatched": dispatched}
```

**Why child workflows, not activities:** `run_workflow_from_definition()` (workflow_run.py:129-239) blocks until all steps complete via `await self._execute_steps()`. Each wave executes steps in parallel via `asyncio.gather`, but the method doesn't return until every wave finishes. The existing `MissionRunWorkflow` uses `budget * 120` seconds as timeout — a $50 workflow gets ~100 minutes. An activity call with any fixed timeout would be wrong. Child workflows inherit Temporal's durable execution guarantees and can run for the full `workflow_execution_timeout_days` (30 days).

#### 3.3 Register in Temporal Worker

**Modified file:** `modules/backend/temporal/worker.py`

Add imports and registrations:

```python
# Add imports
from modules.backend.temporal.workflow_schedule_activities import (
    evaluate_due_workflow_schedules,
)
from modules.backend.temporal.workflow_schedule_workflow import (
    ScheduledWorkflowEvalWorkflow,
)

# Add to workflows list in Worker():
workflows=[
    AgentMissionWorkflow,
    ChatTurnWorkflow,
    MissionRunWorkflow,
    ScheduledMissionCheckWorkflow,
    ScheduledWorkflowEvalWorkflow,      # NEW (Plan 54)
]

# Add to activities list in Worker():
activities=[
    # ... existing activities ...
    # Workflow schedule evaluation (Plan 54)
    evaluate_due_workflow_schedules,
]
```

**Note:** No `execute_scheduled_workflow_run` activity — the workflow starts child `MissionRunWorkflow`s directly (see §3.2).

#### 3.4 Extract Schedule Registration Helper

**New file:** `modules/backend/temporal/schedule_helpers.py`

The existing `main.py` lifespan has a 20-line try/except block for one schedule. Rather than copy-paste it for each new schedule, extract once and call N times.

```python
"""Helpers for idempotent Temporal schedule registration."""

from temporalio.client import Client, Schedule, ScheduleAlreadyRunningError

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def register_schedule(
    client: Client,
    schedule_id: str,
    schedule: Schedule,
) -> bool:
    """Register a Temporal schedule idempotently.

    Returns True if newly created, False if already existed.
    Logs errors but does not raise — startup continues.
    """
    try:
        await client.create_schedule(schedule_id, schedule)
        logger.info("Temporal schedule registered", extra={"schedule_id": schedule_id})
        return True
    except ScheduleAlreadyRunningError:
        logger.info("Temporal schedule already exists", extra={"schedule_id": schedule_id})
        return False
    except Exception:
        logger.error(
            "Failed to register Temporal schedule",
            extra={"schedule_id": schedule_id},
            exc_info=True,
        )
        return False
```

#### 3.5 Refactor Lifespan to Use Helper

**Modified file:** `modules/backend/main.py`

Replace the existing inline try/except block (lines 47-93) AND add the new workflow schedule. Both use the extracted `register_schedule()`.

```python
from modules.backend.temporal.schedule_helpers import register_schedule

# --- Existing plan dispatch schedule (refactored, not new) ---
await register_schedule(
    temporal_client,
    "mission-plan-dispatch-schedule",
    Schedule(
        action=ScheduleActionStartWorkflow(
            ScheduledMissionCheckWorkflow.run,
            id="scheduled-mission-check",
            task_queue=temporal_config.task_queue,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=_td(seconds=5))],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
        ),
    ),
)

# --- NEW: Workflow schedule evaluation (replaces Taskiq cron) ---
from modules.backend.temporal.workflow_schedule_workflow import (
    ScheduledWorkflowEvalWorkflow,
)

workflow_eval_interval = getattr(
    temporal_config, "workflow_schedule_interval_seconds", 60,
)
await register_schedule(
    temporal_client,
    "workflow-schedule-evaluation",
    Schedule(
        action=ScheduleActionStartWorkflow(
            ScheduledWorkflowEvalWorkflow.run,
            id="scheduled-workflow-eval",
            task_queue=temporal_config.task_queue,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=_td(seconds=workflow_eval_interval))],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
        ),
    ),
)
```

This eliminates the duplicated try/except pattern and makes adding future schedules (Phase B housekeeping) a single function call.

#### 3.6 Add Config for Interval

**Modified file:** `config/settings/temporal.yaml`

Add under the existing temporal config:

```yaml
# Workflow schedule evaluation interval (seconds).
# How often to check WorkflowSchedule rows for due cron triggers.
# Default: 60 (once per minute, matching the prior Taskiq cron).
workflow_schedule_interval_seconds: 60
```

**Modified file:** `modules/backend/core/config_schema.py`

Add `workflow_schedule_interval_seconds: int = 60` to `TemporalSchema`.

#### 3.7 Tests

**New file:** `tests/unit/backend/temporal/test_workflow_schedule_activities.py`

- Test `evaluate_due_workflow_schedules` calls `WorkflowScheduleService.evaluate_due_schedules()` and returns fired schedules
- Test empty result (no due schedules) returns empty list
- Test `register_schedule()` helper handles `ScheduleAlreadyRunningError` gracefully

**Acceptance:** Create a `WorkflowSchedule` with `cron_expression="* * * * *"` (every minute). Start only the Temporal worker (no Taskiq scheduler). Verify the schedule fires within 60-90 seconds and a child `MissionRunWorkflow` is started (visible in Temporal UI).

---

### Phase B — Housekeeping Workflow (Container Cleanup)

**Goal:** Move the one real housekeeping task (`cleanup_stale_environments`) to Temporal.

#### 3.7 New Temporal Activity: `cleanup_stale_environments`

**New file:** `modules/backend/temporal/housekeeping_activities.py`

Move the implementation from `modules/backend/tasks/scheduled.py::cleanup_stale_environments` into a Temporal activity. The logic is identical — find exited/idle/old Docker containers and remove them.

```python
@activity.defn
async def cleanup_stale_environments(
    idle_timeout_minutes: int = 60,
    max_lifetime_hours: int = 24,
) -> dict:
    """Clean up stale execution environment containers.

    Logic moved from tasks/scheduled.py. Three cleanup strategies:
    1. Exited containers — stopped/crashed, remove immediately
    2. Idle containers — running but no recent activity
    3. Old containers — past max_lifetime_hours

    Returns cleanup statistics.
    """
    # (Same implementation as tasks/scheduled.py::cleanup_stale_environments,
    #  with the @activity.defn decorator instead of Taskiq registration)
```

#### 3.8 New Temporal Workflow: `HousekeepingWorkflow`

**New file:** `modules/backend/temporal/housekeeping_workflow.py`

```python
@workflow.defn
class HousekeepingWorkflow:
    """Periodic housekeeping: container cleanup, future maintenance tasks.

    Short-lived: runs activities and completes. Temporal schedule
    fires it on a configurable interval (default: hourly).
    """

    @workflow.run
    async def run(self) -> dict:
        cleanup_result = await workflow.execute_activity(
            housekeeping_activities.cleanup_stale_environments,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return {"cleanup": cleanup_result}
```

#### 3.9 Register in Worker + Lifespan

Same pattern as Phase A:

- Add `HousekeepingWorkflow` and `cleanup_stale_environments` to `worker.py`
- Register via `register_schedule()` helper in `main.py` lifespan (one function call):

```python
from modules.backend.temporal.housekeeping_workflow import HousekeepingWorkflow

housekeeping_interval = getattr(temporal_config, "housekeeping_interval_seconds", 3600)
await register_schedule(
    temporal_client,
    "housekeeping-schedule",
    Schedule(
        action=ScheduleActionStartWorkflow(
            HousekeepingWorkflow.run,
            id="housekeeping",
            task_queue=temporal_config.task_queue,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=_td(seconds=housekeeping_interval))],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
        ),
    ),
)
```

- Add `housekeeping_interval_seconds: 3600` to `temporal.yaml` and `TemporalSchema`

#### 3.10 Tests

- Test `cleanup_stale_environments` activity (mock Docker client)
- Verify schedule registration is idempotent

**Acceptance:** Start the Temporal worker. Verify the housekeeping schedule exists in the Temporal UI (`http://localhost:8233`).

---

### Phase C — Remove Taskiq

**Goal:** Delete all Taskiq infrastructure. No code references remain.

#### 3.11 Delete Taskiq Files

| Action | File |
|--------|------|
| **Delete** | `modules/backend/tasks/broker.py` |
| **Delete** | `modules/backend/tasks/scheduler.py` |
| **Delete** | `modules/backend/tasks/example.py` |
| **Delete** | `modules/backend/tasks/scheduled.py` |
| **Delete** | `modules/backend/tasks/workflow_scheduler.py` |
| **Delete** | `modules/backend/tasks/__init__.py` |
| **Delete** | `modules/clients/cli/worker.py` |
| **Delete** | `modules/clients/cli/scheduler.py` |

If any other files exist in `modules/backend/tasks/`, delete those too. The entire `modules/backend/tasks/` directory should be removed.

#### 3.12 Remove CLI Commands

**Modified file:** `admin.py`

Remove these commands and their imports:

- `worker` command (~line 200-205) — started Taskiq worker
- `scheduler` command (~line 215-218) — started Taskiq scheduler

Update the help text docstring (line 49) to remove "worker, scheduler" from the Infrastructure list.

#### 3.13 Remove Dependencies

**Modified file:** `pyproject.toml`

Remove from `[project.dependencies]`:

```
"taskiq>=0.11.0",
"taskiq-redis>=1.0.0",
```

**Modified file:** `requirements.txt`

Remove `taskiq` and `taskiq-redis` lines if present.

Run `uv lock` to regenerate `uv.lock`.

#### 3.14 Remove Taskiq Config

**Modified file:** `config/settings/database.yaml`

Remove the `redis.broker` section (queue_name, result_expiry_seconds) if it exists. The Redis connection itself stays — it's used by `SessionEventBus`.

#### 3.15 Update USAGE.md

**Modified file:** `USAGE.md`

- Remove section "9. Background Services" references to `admin.py worker` and `admin.py scheduler`
- Remove references to Taskiq in the "Full Workflow Example"
- The Temporal worker is already managed by `services.py` and doesn't need a separate CLI command

#### 3.16 Tests

- Verify `pytest` still passes with Taskiq removed (no import errors)
- Grep the entire codebase for `taskiq` — should only appear in `uv.lock` (transitive, if any) and this plan document

**Acceptance:** `grep -ri taskiq modules/ admin.py services.py mc.py tui.py` returns zero results.

---

### Phase D — Remove FastStream

**Goal:** Delete all FastStream infrastructure. `SessionEventBus` (Redis Pub/Sub) is the event system.

#### 3.17 Delete FastStream Files

| Action | File |
|--------|------|
| **Delete** | `modules/backend/events/broker.py` |
| **Delete** | `modules/backend/events/middleware.py` |
| **Delete** | `modules/backend/events/publishers.py` |
| **Delete** | `modules/clients/cli/event_worker.py` |

**Keep:** `modules/backend/events/__init__.py`, `modules/backend/events/bus.py`, `modules/backend/events/types.py`, `modules/backend/events/schemas.py` — these are the real event system.

#### 3.18 Remove Event Worker CLI Command

**Modified file:** `admin.py`

Remove the `event-worker` command (~line 239-244).

#### 3.19 Clean Up Imports

**Modified file:** `modules/backend/events/__init__.py`

Remove the `EventPublisher` import if it references `publishers.py`.

**Modified file:** `modules/backend/services/session.py`

Remove the `from modules.backend.events.publishers import EventPublisher` import (~line 407) and any code that calls it. This code path was gated by `events_publish_enabled: false` and never executed.

#### 3.20 Remove Dependencies

**Modified file:** `pyproject.toml`

Remove from `[project.dependencies]`:

```
"faststream[redis]>=0.5.0",
```

**Modified file:** `requirements.txt`

Remove `faststream` line if present.

Run `uv lock` to regenerate `uv.lock`.

#### 3.21 Remove Feature Flag

**Modified file:** `config/settings/features.yaml`

Remove:

```yaml
events_publish_enabled: false
```

**Modified file:** `modules/backend/core/config_schema.py`

Remove `events_publish_enabled` from `FeaturesSchema` (or leave it as a no-op if other code checks it — grep first).

**Modified file:** `config/settings/events.yaml`

Remove FastStream-specific config (transport, DLQ settings). Keep any config that `SessionEventBus` reads (e.g., `persist_event_types`).

#### 3.22 Tests

- Remove `tests/unit/backend/events/test_publishers.py` if it tests FastStream publishers
- Verify no remaining imports of `EventPublisher`, `get_event_broker`, or `create_event_app`

**Acceptance:** `grep -ri faststream modules/ admin.py` returns zero results (except possibly `config_schema.py` if removing the flag is deferred).

---

### Phase E — Update Reference Documentation

**Goal:** Documentation reflects the actual architecture.

#### 3.23 Rewrite Reference Doc 14

**Modified file:** `docs/99-reference-architecture/14-core-background-tasks.md`

Replace the entire Taskiq-based document. New structure:

1. **Purpose** — Background work and scheduled execution
2. **Architecture** — Two systems: Temporal (durable), Redis Pub/Sub (ephemeral)
3. **Temporal Scheduled Workflows** — How to add a new scheduled job (activity + workflow + schedule registration)
4. **Temporal Activities** — How to write activities (idempotency, timeouts, retry policies)
5. **When to use Temporal vs Redis Pub/Sub** — Decision matrix
6. **Real-time Events** — `SessionEventBus` for SSE/WebSocket streaming
7. **Testing** — Activity unit tests, workflow integration tests
8. **Monitoring** — Temporal UI dashboard, schedule visibility
9. **Troubleshooting** — Common issues

Key sections to include:

**Decision matrix:**

| Need | Use | Why |
|------|-----|-----|
| Scheduled job (cron-like) | Temporal scheduled workflow | Dedup, crash recovery, distributed coordination |
| Long-running mission execution | Temporal workflow + activities | Durable, resumable, timeout handling |
| Fire-and-forget background work | Temporal activity (within a workflow) | Same guarantees as scheduled work |
| Real-time event streaming | `SessionEventBus` (Redis Pub/Sub) | Low-latency, ephemeral, fan-out to SSE/TUI/CLI |
| Event persistence for audit | `SessionEventBus._persist_event()` | DB write gated by `persist_event_types` config |

**How to add a new scheduled job:**

```
1. Write an activity in modules/backend/temporal/<domain>_activities.py
2. Write a workflow in modules/backend/temporal/<domain>_workflow.py
3. Register both in modules/backend/temporal/worker.py
4. Register the Temporal schedule in modules/backend/main.py lifespan
5. Add interval config to config/settings/temporal.yaml + config_schema.py
```

#### 3.24 Update Other Docs

Grep all docs for `taskiq`, `faststream`, `admin.py worker`, `admin.py scheduler`, `admin.py event-worker` and update or remove references:

- `docs/99-reference-architecture/03-core-backend-architecture.md` — Remove Taskiq from stack description
- `docs/99-reference-architecture/15-core-deployment-bare-metal.md` — Remove Taskiq worker/scheduler from process list
- `docs/99-reference-architecture/16-core-deployment-azure.md` — Same
- `docs/99-reference-architecture/28-opt-cli-architecture.md` — Remove worker/scheduler CLI commands
- `README.md` — Remove "Cache/Queue: Redis with Taskiq" from Architecture section. Replace with "Scheduling: Temporal"
- `docs/97-plans/10-plan-event-bus-[X].md` — Already marked [X] (completed). Add a note that FastStream was removed in Plan 54.

---

## 4  Files Changed (Summary)

| Phase | File | Action |
|-------|------|--------|
| A | `modules/backend/temporal/schedule_helpers.py` | **New** — `register_schedule()` idempotent helper (reused by all phases) |
| A | `modules/backend/temporal/workflow_schedule_activities.py` | **New** — `evaluate_due_workflow_schedules` activity |
| A | `modules/backend/temporal/workflow_schedule_workflow.py` | **New** — `ScheduledWorkflowEvalWorkflow` (starts child MissionRunWorkflows) |
| A | `modules/backend/temporal/worker.py` | **Modify** — register new workflow + activity |
| A | `modules/backend/main.py` | **Modify** — refactor existing schedule to use helper + add workflow eval schedule |
| A | `config/settings/temporal.yaml` | **Modify** — add `workflow_schedule_interval_seconds` |
| A | `modules/backend/core/config_schema.py` | **Modify** — add field to `TemporalSchema` |
| A | `tests/unit/backend/temporal/test_workflow_schedule_activities.py` | **New** — unit tests |
| B | `modules/backend/temporal/housekeeping_activities.py` | **New** — container cleanup activity |
| B | `modules/backend/temporal/housekeeping_workflow.py` | **New** — `HousekeepingWorkflow` |
| B | `modules/backend/temporal/worker.py` | **Modify** — register housekeeping |
| B | `modules/backend/main.py` | **Modify** — register housekeeping schedule |
| B | `config/settings/temporal.yaml` | **Modify** — add `housekeeping_interval_seconds` |
| C | `modules/backend/tasks/` (entire directory) | **Delete** |
| C | `modules/clients/cli/worker.py` | **Delete** |
| C | `modules/clients/cli/scheduler.py` | **Delete** |
| C | `admin.py` | **Modify** — remove `worker`, `scheduler` commands |
| C | `pyproject.toml` | **Modify** — remove `taskiq`, `taskiq-redis` |
| C | `requirements.txt` | **Modify** — remove taskiq lines |
| C | `config/settings/database.yaml` | **Modify** — remove broker section |
| C | `USAGE.md` | **Modify** — remove Taskiq references |
| D | `modules/backend/events/broker.py` | **Delete** |
| D | `modules/backend/events/middleware.py` | **Delete** |
| D | `modules/backend/events/publishers.py` | **Delete** |
| D | `modules/clients/cli/event_worker.py` | **Delete** |
| D | `admin.py` | **Modify** — remove `event-worker` command |
| D | `modules/backend/events/__init__.py` | **Modify** — remove `EventPublisher` import |
| D | `modules/backend/services/session.py` | **Modify** — remove `EventPublisher` import + dead code |
| D | `pyproject.toml` | **Modify** — remove `faststream[redis]` |
| D | `config/settings/features.yaml` | **Modify** — remove `events_publish_enabled` |
| D | `config/settings/events.yaml` | **Modify** — remove FastStream-specific config |
| D | `modules/backend/core/config_schema.py` | **Modify** — remove `events_publish_enabled` from features |
| D | `tests/unit/backend/events/test_publishers.py` | **Delete** |
| E | `docs/99-reference-architecture/14-core-background-tasks.md` | **Rewrite** — Temporal-based standard |
| E | `docs/99-reference-architecture/03-core-backend-architecture.md` | **Modify** — remove Taskiq reference |
| E | `docs/99-reference-architecture/15-core-deployment-bare-metal.md` | **Modify** — remove Taskiq processes |
| E | `docs/99-reference-architecture/16-core-deployment-azure.md` | **Modify** — remove Taskiq processes |
| E | `docs/99-reference-architecture/28-opt-cli-architecture.md` | **Modify** — remove worker/scheduler commands |
| E | `README.md` | **Modify** — update architecture description |

---

## 5  What Gets Deleted

| Item | Why |
|------|-----|
| `modules/backend/tasks/` (entire directory, 6 files) | All Taskiq infrastructure. `evaluate_workflow_schedules` migrated to Temporal activity. Stubs had no callers. |
| `modules/clients/cli/worker.py` | Started Taskiq worker process |
| `modules/clients/cli/scheduler.py` | Started Taskiq scheduler process |
| `modules/clients/cli/event_worker.py` | Started FastStream consumer process |
| `modules/backend/events/broker.py` | FastStream Redis broker (unused) |
| `modules/backend/events/middleware.py` | FastStream observability middleware (unused) |
| `modules/backend/events/publishers.py` | FastStream event publisher (feature-flagged off) |
| `tests/unit/backend/events/test_publishers.py` | Tests for deleted code |
| `taskiq` + `taskiq-redis` dependencies | No longer used |
| `faststream[redis]` dependency | No longer used |

---

## 6  Migration Notes

### For existing deployments

- **Before deploying Phase C:** Ensure the Temporal worker is running and the workflow schedule evaluation schedule is registered (Phase A). Verify at least one cron cycle has fired successfully via the Temporal UI.
- **Taskiq scheduler can be stopped after Phase A is verified.** The workflow schedule evaluation is now handled by Temporal.
- **No database migration needed.** The `WorkflowSchedule` table and its data are unchanged — only the trigger mechanism changes.

### Rollback

If Temporal schedule evaluation fails:
1. Re-add `evaluate_workflow_schedules` to Taskiq's `SCHEDULED_TASKS` (revert Phase C)
2. Start the Taskiq scheduler: `admin.py scheduler`
3. The `WorkflowScheduleService` logic is untouched — it works with either trigger

---

## 7  Exit Criteria

1. `WorkflowSchedule` rows with cron expressions fire on time via Temporal (no Taskiq process running)
2. Container cleanup runs hourly via Temporal `HousekeepingWorkflow`
3. `grep -ri taskiq modules/ admin.py services.py mc.py tui.py pyproject.toml` returns zero results
4. `grep -ri faststream modules/ admin.py pyproject.toml` returns zero results
5. `admin.py --help` does not show `worker`, `scheduler`, or `event-worker` commands
6. Reference doc 14 describes Temporal as the scheduling standard
7. All existing tests pass
8. Temporal UI shows three schedules: `mission-plan-dispatch-schedule`, `workflow-schedule-evaluation`, `housekeeping-schedule`

---

## 8  Estimated Effort

| Phase | Scope | Effort |
|-------|-------|--------|
| A | Workflow schedule Temporal migration | ~2 hours |
| B | Housekeeping workflow | ~1 hour |
| C | Delete Taskiq | ~1 hour |
| D | Delete FastStream | ~1 hour |
| E | Documentation updates | ~1 hour |
| **Total** | | **~6 hours** |

---

## 9  Risks

| Risk | Mitigation |
|------|------------|
| Temporal schedule interval drift vs Taskiq cron precision | `WorkflowScheduleService.evaluate_due_schedules()` uses `next_fire_at` DB column — the evaluation function is idempotent regardless of how often it's called. A 60-second Temporal interval will fire schedules within ±60s of their cron time, same as the prior Taskiq 1-minute cron. |
| Temporal server downtime blocks all scheduling | Same risk exists today for mission dispatch. Temporal's persistence means missed schedules will catch up on restart. `ScheduleOverlapPolicy.SKIP` prevents stampede. |
| Removing FastStream closes door on durable event consumers | `SessionEventBus` already persists important events to DB. If consumer groups are needed later, a Redis Streams wrapper can be added without FastStream (the framework added complexity without value). |

---

## 10  Quality Review Corrections (2026-04-13)

Three issues were found during code quality review and corrected in-place:

### 10.1 Duplicate schedule registration pattern (fixed: D6, §3.4)

**Problem:** The original plan proposed copying the 20-line try/except/`ScheduleAlreadyRunningError` block from `main.py` for each new schedule (workflow eval + housekeeping). Three copies of identical boilerplate.

**Fix:** Extract `register_schedule()` helper in `modules/backend/temporal/schedule_helpers.py`. Refactor the existing schedule registration in `main.py` to use it. All future schedules are one function call.

### 10.2 Activity timeout too short for blocking workflow runs (fixed: D7, §3.2)

**Problem:** The original plan proposed `execute_scheduled_workflow_run` as a Temporal activity with `start_to_close_timeout=timedelta(minutes=30)`. But `run_workflow_from_definition()` (workflow_run.py:129-239) is fully synchronous — it calls `await self._execute_steps()` which blocks until all waves complete. The existing `MissionRunWorkflow` uses `budget * 120` seconds as timeout (a $50 workflow → 100 minutes). The 30-minute activity timeout would kill high-budget workflows.

**Fix:** Replaced the activity-based pattern with child workflows using `ParentClosePolicy.ABANDON`, matching the existing `ScheduledMissionCheckWorkflow` pattern (scheduled_workflow.py:75-84). The parent evaluation workflow completes immediately; children run independently with Temporal's full durable execution guarantees.

### 10.3 Unnecessary activity removed

**Problem:** `execute_scheduled_workflow_run` was a new activity that duplicated orchestration logic already handled by `MissionRunWorkflow`.

**Fix:** Removed entirely. The workflow starts `MissionRunWorkflow` as a child workflow instead, reusing existing infrastructure.
