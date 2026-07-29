# Plan 33 — Backend Gaps for BFF Compliance

| Field | Value |
|-------|-------|
| **Status** | Complete |
| **Created** | 2026-03-25 |
| **Depends on** | Plan 28 (Platform Architecture), Plan 32 (TUI Frontend Design) |
| **Affects** | `modules/backend/services/`, `modules/clients/tui/services/service_bridge.py`, `modules/clients/web/` |

---

## 1  Objective

Resolve the backend service gaps identified in Plan 32 §15.5. Each gap represents a
place where the TUI bridge (or web API) is forced to perform cross-service orchestration,
data aggregation, or business logic that belongs in the backend service layer.

**Principle:** One bridge method = one backend service method. Any multi-service call in
a client is a BFF violation that this plan resolves.

Closing these gaps also benefits the web frontend (Plan 29) — the same backend methods
will be consumed by both clients.

---

## 2  Gap Inventory

### 2.1  Mission Stats Aggregation — HIGH

**Current state:** No `MissionService.get_stats(mission_id)` method. The TUI bridge
would need to call `MissionTeamService`, `WorkflowService`, and
`ExecutionPersistenceService` separately and aggregate results.

**Fix:** Add `MissionService.get_stats(mission_id) -> dict` that returns:
```python
{
    "team_count": int,
    "workflow_count": int,
    "execution_count": int,
    "total_cost_usd": float,
    "last_run_at": str | None,
    "last_run_status": str | None,
}
```

**Files:**
- `modules/backend/services/mission.py` — add `get_stats()` method
- `modules/clients/tui/services/service_bridge.py` — add `get_mission_stats()` pass-through
- `modules/clients/tui/tabs/overview.py` — consume stats for quick summary

---

### 2.2  Add Team Member by Name — HIGH

**Current state:** `MissionTeamService.add_agent()` requires `agent_catalog_id` (UUID),
not `agent_name` (string). The bridge currently resolves name → ID via
`AgentCatalogService.get_by_name()` then calls `add_agent()` — two service calls.

**Fix:** Add `MissionTeamService.add_agent_by_name(mission_id, agent_name) -> MissionTeamMember`
that internally resolves the catalog ID.

**Files:**
- `modules/backend/services/mission_team.py` — add `add_agent_by_name()` method
- `modules/clients/tui/services/service_bridge.py` — simplify `add_team_member()` to single call

---

### 2.3  Schedule Service — HIGH

**Current state:** No `ScheduleService` exists. Workflow schedules are defined in YAML
but there is no backend service for CRUD operations, no database table for schedule state,
and no scheduler runtime.

**Fix:** Create a full schedule subsystem:

1. **Database migration:** `workflow_schedules` table (id, workflow_name, mission_id,
   cron_expression, enabled, last_run_at, next_run_at, created_by, created_at, updated_at)
2. **Service:** `ScheduleService` with methods:
   - `list_schedules(mission_id) -> list[WorkflowSchedule]`
   - `create_schedule(mission_id, workflow_name, cron_expression, ...) -> WorkflowSchedule`
   - `update_schedule(schedule_id, ...) -> WorkflowSchedule`
   - `delete_schedule(schedule_id) -> None`
   - `get_next_run(mission_id) -> dict | None`
3. **Bridge methods:** 5 pass-through methods in `service_bridge.py`

**Files:**
- `modules/backend/models/schedule.py` — new model
- `modules/backend/repositories/schedule.py` — new repository
- `modules/backend/services/schedule.py` — new service
- Alembic migration for `workflow_schedules` table
- `modules/clients/tui/services/service_bridge.py` — add schedule methods
- `modules/clients/tui/tabs/workflows.py` — enable schedule UI

**Note:** This is the largest gap. The scheduler runtime (cron executor) is out of scope
for this plan — this plan only covers the CRUD and state tracking. A separate plan should
cover the scheduler daemon.

---

### 2.4  AI Team Recommendation — MEDIUM

**Current state:** No `WorkflowArchitectService.recommend_team(mission_id)` method.
The bridge would need to construct a recommendation prompt, call `.chat()`, and parse
the AI response — all business logic.

**Fix:** Add `WorkflowArchitectService.recommend_team(mission_id) -> list[dict]` that:
1. Loads the mission brief
2. Queries the agent catalog
3. Constructs a recommendation prompt
4. Calls the LLM
5. Parses and returns a ranked list of recommended agents

**Files:**
- `modules/backend/services/workflow_architect.py` — add `recommend_team()` method
- `modules/clients/tui/services/service_bridge.py` — add `get_team_recommendation()` pass-through
- `modules/clients/tui/tabs/team.py` — add "[Get AI Recommendation]" button

---

### 2.5  User Prompt Version History — LOW

**Current state:** `MissionTeamService` does not track prompt versions for user prompts.
Only `AgentCatalogService.get_prompt_history()` exists for system prompts. The TeamTab
"History" button is disabled.

**Fix:**
1. **Database migration:** `team_member_prompt_versions` table (id, team_member_id,
   content, version, changed_by, change_reason, created_at)
2. **Service:** Add `MissionTeamService.get_prompt_history(member_id, limit) -> list`
3. **Auto-versioning:** `update_user_prompt()` creates a version record before updating

**Files:**
- `modules/backend/models/mission_team.py` — add `TeamMemberPromptVersion` model
- `modules/backend/repositories/mission_team.py` — add version repository methods
- `modules/backend/services/mission_team.py` — add `get_prompt_history()`, update `update_user_prompt()`
- Alembic migration for `team_member_prompt_versions` table
- `modules/clients/tui/services/service_bridge.py` — add `get_user_prompt_history()` pass-through
- `modules/clients/tui/tabs/team.py` — enable "History" button

---

### 2.6  Date-Windowed Cost Summary — LOW

**Current state:** `PlatformMetricsService.get_cost_summary()` returns all-time aggregates.
No date range parameter. Dashboard displays "Total" instead of "30d".

**Fix:** Add optional `since: datetime | None` parameter to `get_cost_summary()`:
```python
async def get_cost_summary(self, *, since: datetime | None = None) -> dict[str, Any]
```

**Files:**
- `modules/backend/services/platform_metrics.py` — add `since` filter to query
- `modules/clients/tui/screens/dashboard.py` — pass `since=30 days ago`

---

### 2.7  Context Milestones — LOW

**Current state:** `MissionContextManager` has no milestone concept. ContextTab omits
milestones section entirely.

**Fix:**
1. **Database migration:** `context_milestones` table (id, mission_id, title,
   description, version_snapshot, created_at, created_by)
2. **Service:** Add `MissionContextManager.create_milestone()`, `list_milestones()`

**Files:**
- `modules/backend/models/mission_context.py` — add `ContextMilestone` model
- `modules/backend/services/mission_context.py` — add milestone methods
- Alembic migration for `context_milestones` table
- `modules/clients/tui/tabs/context.py` — add milestones section

---

### 2.8  Next Scheduled Run — LOW

**Current state:** No `ScheduleService.get_next_run()` method. OverviewTab omits
"Next scheduled" line.

**Dependency:** Blocked by §2.3 (Schedule Service). Once the schedule service exists,
`get_next_run()` is a simple query. No separate work item needed.

---

## 3  Implementation Order

| Priority | Gap | Effort | Dependencies |
|----------|-----|--------|-------------|
| 1 | §2.2 Add team member by name | Small (1 method) | None |
| 2 | §2.1 Mission stats aggregation | Small (1 method) | None |
| 3 | §2.6 Date-windowed cost summary | Small (1 param) | None |
| 4 | §2.4 AI team recommendation | Medium (1 method + LLM) | None |
| 5 | §2.5 User prompt version history | Medium (migration + service) | None |
| 6 | §2.3 Schedule service | Large (new subsystem) | None |
| 7 | §2.7 Context milestones | Medium (migration + service) | None |
| 8 | §2.8 Next scheduled run | Trivial | §2.3 |

Items 1-3 can be done in a single PR. Items 4-5 are independent. Item 6 is a
standalone effort. Items 7-8 are lowest priority.

---

## 4  Out of Scope

- **Scheduler daemon/runtime** — executing scheduled workflows on cron. Requires a
  separate plan for the scheduler worker process.
- **Notification SSE endpoint** — not needed. TUI uses in-process `TuiEventBus`.
  Web frontend may need SSE, but that's Plan 29's concern.
- **New UI features** — this plan only adds backend methods. The TUI/web bridge
  updates are minimal pass-throughs.
