# Plan 64 — Database Integrity & Performance Hardening

**Version:** 1.1.0
**Date:** 2026-04-25
**Author:** Herman + Data Architecture Review + Adversarial Review Pass
**Status:** Ready to implement
**Depends on:** None (all changes are additive migrations + model edits)
**Unlocks:** Safe mission deletion without raw SQL, query performance at scale

### v1.1 changelog (adversarial review)

1. **Fixed Phase B risk assessment** — tests use in-memory SQLite (`tests/conftest.py`
   line 98-105, `is_sqlite()` helper). Switching from `sqlalchemy.dialects.sqlite.JSON`
   to `sqlalchemy.JSON` is safe because generic `JSON` maps to SQLite's JSON type
   transparently — **but** added a verification step to run SQLite tests explicitly.
2. **Removed 2 duplicate indexes from Phase C** — `ix_mission_intents_mission_created`
   already exists in `20260410_plan42_mission_plans.py` migration (line 58-62), and
   `ix_plan_task_states_plan_status` already exists (line 220-224). Reduced from 9 to
   7 new indexes.
3. **Added `expires_at` to session_followups index** — `fire_matching` filters on
   `consumed_at IS NULL AND expires_at > now`, so the composite needs 3 columns, not 2.
4. **Downgraded 3 indexes from "must add" to "defer"** — `ix_mission_events_mission_created`,
   `ix_context_changes_context_version`, and `ix_mission_learnings_mission_status` are
   cold-path queries with low cardinality. Added only if table exceeds 10k rows.
5. **Fixed Phase E service impact** — identified exact write locations for all 6
   timestamp columns (all write ISO strings via `utc_now().isoformat()`). Listed
   specific files and lines to update.
6. **Fixed Phase F scope** — `MilestoneSummary.mission_ids` has only 2 write sites
   (both in `summarization.py`) and 1 read site (`__repr__`). No code reads the
   column for business logic, so rename is low-risk.
7. **Corrected `Execution` table assessment** — `Execution` is NOT legacy read-only.
   It's actively written to by `execution_dispatch.py` and `execution.py` service
   (`create_execution_from_step`, `create_adhoc_execution`). Removed "retire" language;
   replaced with deprecation note and consolidation analysis.
8. **Added `context_changes.mission_id` to Phase A discussion** — this column is
   denormalised (no FK), but `delete_mission()` already handles it in the Level 1
   direct-children loop. No action needed beyond documenting it.

---

## 0. Problem Statement

A full architectural review of the 28-table schema identified three categories of
technical debt that will cause increasing pain as data volume and concurrency grow:

1. **Missing FK cascade rules** — 8 foreign keys lack explicit `ondelete` behaviour,
   defaulting to `RESTRICT`. This forces `mission.py::delete_mission()` to issue ~30
   sequential raw-SQL DELETE statements (lines 232-313) instead of relying on the
   database to cascade. Every new child table added to a mission requires a manual
   addition to this fragile list.

2. **JSON dialect mismatch** — 12 model files import `JSON` from
   `sqlalchemy.dialects.sqlite` while the production database is PostgreSQL. This
   blocks future JSONB features (GIN indexes, containment operators). SQLAlchemy's
   generic `JSON` type handles both Postgres and SQLite transparently, so the
   dialect-specific import is unnecessary.

3. **Missing indexes & soft references** — Several high-traffic query patterns lack
   composite indexes, and 3 FK-like columns (`Mission.owner_id`, `Session.mission_id`,
   `Session.user_id`) are bare strings with no referential constraint.

Additionally: inconsistent timestamp storage (6 columns use `String(30)` instead of
`DateTime`), `MilestoneSummary.mission_ids` is a misleading name (stores execution
record IDs), and the `Execution` table duplicates fields already present on
`ExecutionRecord`.

**Risk of doing nothing:** silent data corruption from orphaned rows, unbounded
query latency on growing tables, and an ever-expanding manual delete cascade that
is one missed table away from a broken mission deletion.

---

## 1. Success Criteria

- [ ] All child FK constraints have explicit `ondelete` (CASCADE or SET NULL)
- [ ] `delete_mission()` reduced from ~30 raw SQL statements to ~5
- [ ] All 12 model files use `sqlalchemy.JSON` (not `sqlalchemy.dialects.sqlite.JSON`)
- [ ] 4 new composite indexes added for hot query patterns (+ 3 deferred)
- [ ] `Mission.owner_id`, `Session.mission_id`, `Session.user_id` have FK constraints
- [ ] All `String(30)` timestamp columns converted to `DateTime(timezone=True)`
- [ ] `MilestoneSummary.mission_ids` renamed to `execution_ids`
- [ ] All existing tests pass after migration (both SQLite and Postgres)
- [ ] `alembic upgrade head` succeeds from current head (`widen_artifact_type`)

---

## 2. Phasing

| Phase | Goal | Effort | Risk |
|-------|------|--------|------|
| **A** | Fix FK cascade rules + simplify `delete_mission()` | ~3 hours | Low — additive migration, behaviour-preserving |
| **B** | Fix JSON dialect import across 12 model files | ~30 min | Low — generic `JSON` works on both SQLite and Postgres |
| **C** | Add missing composite indexes | ~1 hour | Zero — additive, no table locks on Postgres |
| **D** | Add FK constraints on soft references | ~1 hour | Low — migration adds constraints; backfill fixes orphans |
| **E** | Standardise `String(30)` timestamps to `DateTime` | ~2 hours | Medium — data migration required for existing rows |
| **F** | Rename `mission_ids` column + `Execution` deprecation note | ~1 hour | Low |

**Total:** ~8.5 hours across 6 independent phases (can be parallelised).

---

## Phase A — FK Cascade Rules & Mission Deletion Simplification

**Goal:** Add `ondelete="CASCADE"` to all child FKs that currently lack it, then
replace the 30-statement raw SQL cascade in `delete_mission()` with a minimal
set of queries.

### A.1 Migration: Add `ondelete` to 8 FK constraints

**File:** `modules/backend/migrations/versions/plan64_001_fk_cascades.py`

Each FK change requires dropping and re-creating the constraint. On PostgreSQL this
is a metadata-only operation (no table rewrite) and takes a brief `ACCESS EXCLUSIVE`
lock per table.

**FK changes:**

| Model file | Table | Column | FK target | Current | New |
|------------|-------|--------|-----------|---------|-----|
| `execution_record.py:163` | `execution_records` | `parent_execution_record_id` | `execution_records.id` | (none) | `CASCADE` |
| `execution_record.py:236` | `task_executions` | `execution_record_id` | `execution_records.id` | (none) | `CASCADE` |
| `execution_record.py:339` | `task_attempts` | `task_execution_id` | `task_executions.id` | (none) | `CASCADE` |
| `execution_record.py:412` | `execution_decisions` | `execution_record_id` | `execution_records.id` | (none) | `CASCADE` |
| `session.py:130` | `session_channels` | `session_id` | `sessions.id` | (none) | `CASCADE` |
| `session.py:163` | `session_messages` | `session_id` | `sessions.id` | (none) | `CASCADE` |
| `mission_intent.py:60` | `mission_intents` | `revised_from` | `mission_intents.id` | (none) | `SET NULL` |
| `mission_learning.py:102` | `mission_learnings` | `contradicts_id` | `mission_learnings.id` | (none) | `SET NULL` |

**Constraint naming:** All FKs in the codebase use SQLAlchemy's automatic naming
convention (no explicit `name=` parameter). Postgres defaults to
`{table}_{column}_fkey`. Verified: no explicit constraint names in any migration.

**Migration pattern** (repeat per FK):

```python
def upgrade() -> None:
    # Drop old constraint, re-create with ondelete
    op.drop_constraint(
        "task_executions_execution_record_id_fkey",
        "task_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "task_executions_execution_record_id_fkey",
        "task_executions",
        "execution_records",
        ["execution_record_id"],
        ["id"],
        ondelete="CASCADE",
    )
```

**Safety note:** No ORM relationships use `passive_deletes=True`, so adding
DB-level cascades won't conflict with ORM-level cascade behaviour. The ORM
cascade (`cascade="all, delete-orphan"`) already exists on `ExecutionRecord →
TaskExecution`, `TaskExecution → TaskAttempt`, etc. — adding `ondelete` to the FK
makes the DB enforce the same rule.

### A.2 Model file changes (8 files)

Update each `ForeignKey(...)` call to include the `ondelete` parameter. Example:

**File:** `modules/backend/models/execution_record.py`, line 236

```python
# Before
ForeignKey("execution_records.id"),

# After
ForeignKey("execution_records.id", ondelete="CASCADE"),
```

Full list of model edits:

- [ ] **A.2.1** `execution_record.py:163` — `parent_execution_record_id`: add `ondelete="CASCADE"`
- [ ] **A.2.2** `execution_record.py:236` — `task_executions.execution_record_id`: add `ondelete="CASCADE"`
- [ ] **A.2.3** `execution_record.py:339` — `task_attempts.task_execution_id`: add `ondelete="CASCADE"`
- [ ] **A.2.4** `execution_record.py:412` — `execution_decisions.execution_record_id`: add `ondelete="CASCADE"`
- [ ] **A.2.5** `session.py:130` — `session_channels.session_id`: add `ondelete="CASCADE"`
- [ ] **A.2.6** `session.py:163` — `session_messages.session_id`: add `ondelete="CASCADE"`
- [ ] **A.2.7** `mission_intent.py:60` — `mission_intents.revised_from`: add `ondelete="SET NULL"`
- [ ] **A.2.8** `mission_learning.py:102` — `mission_learnings.contradicts_id`: add `ondelete="SET NULL"`

### A.3 Simplify `delete_mission()` in `MissionService`

**File:** `modules/backend/services/mission.py`, lines 232-313

**Before:** 30+ sequential `text()` DELETE statements handling 3 levels of FK depth.

**After:** With child FKs cascading, most of the manual cascade is eliminated. However,
several tables have denormalised `mission_id` columns that are **not FK-constrained**
and therefore cannot cascade automatically. These must remain as explicit deletes
until Phase D adds FKs to them.

**Tables with denormalised `mission_id` (no FK constraint):**

| Table | Column | FK status | Phase D will fix? |
|-------|--------|-----------|-------------------|
| `context_changes` | `mission_id` | No FK (ownership via `context_id → mission_contexts`) | No — redundant, kept as query shortcut |
| `llm_calls` | `mission_id` | No FK | Yes |
| `session_followups` | `mission_id` | No FK | Yes |

**Simplified delete_mission():**

```python
async def delete_mission(self, mission_id: str) -> str:
    mission = await self._get_mission_or_raise(mission_id)
    mission_name = mission.name

    # Clean up Docker containers (external side-effect, not DB-cascadable)
    self._cleanup_mission_containers(mission_id)

    # SET NULL on user.current_mission_id before cascade
    await self._session.execute(
        text("UPDATE users SET current_mission_id = NULL "
             "WHERE current_mission_id = :mid"),
        {"mid": mission_id},
    )

    # Clean up denormalised mission_id columns (no FK constraint)
    for table in ["llm_calls", "session_followups", "context_changes"]:
        await self._session.execute(
            text(f"DELETE FROM {table} WHERE mission_id = :mid"),
            {"mid": mission_id},
        )

    # Single delete — DB cascades handle all FK-constrained children
    await self._session.execute(
        text("DELETE FROM missions WHERE id = :mid"),
        {"mid": mission_id},
    )
    await self._session.flush()

    self._log_operation(
        "Mission deleted",
        mission_id=mission_id,
        mission_name=mission_name,
    )
    return mission_name
```

**Key change:** Reduced from ~30 sequential DELETEs to 5 statements. After Phase D
adds FKs to `llm_calls` and `session_followups`, this drops to 3 statements
(users update, context_changes cleanup, mission delete).

### A.4 Update `DatabaseAdminService` table lists

**File:** `modules/backend/services/database_admin.py`

Add tables missing from the admin service's table lists:

```python
# Tables currently missing from ALL_TABLES / RUN_TABLES:
# mission_events, mission_intents, mission_learnings, mission_plans,
# plan_task_states, mission_artifacts, mission_team_members,
# execution_environments, prompt_versions, workflow_definitions,
# agent_catalog, embeddings, llm_calls, model_pricing,
# session_followups, context_milestones
```

These tables exist in the database but are invisible to the admin service's
`get_table_row_counts()` and `truncate_tables()` operations. Update `ALL_TABLES`
to include them in correct dependency order.

### A.5 Verification

- [ ] **A.5.1** `alembic upgrade head` succeeds
- [ ] **A.5.2** Create a mission with sessions, execution records, task executions,
      and task attempts. Delete the mission. Verify all child rows are gone.
- [ ] **A.5.3** Verify `users.current_mission_id` is set to NULL after mission deletion
- [ ] **A.5.4** All existing tests pass (`pytest tests/unit/backend/`)

---

## Phase B — Fix JSON Dialect Import

**Goal:** Replace `from sqlalchemy.dialects.sqlite import JSON` with
`from sqlalchemy import JSON` across all 12 model files.

This is a pure import change — no schema migration needed. SQLAlchemy's generic
`JSON` type maps to `JSONB` on PostgreSQL and `JSON` on SQLite transparently.

**Risk note:** Tests use in-memory SQLite (`tests/conftest.py` line 98-105, via
`is_sqlite()` helper). The generic `sqlalchemy.JSON` type works on both Postgres
and SQLite — it's the standard recommended approach. The `dialects.sqlite.JSON`
import was likely used as a convenience and is not required for SQLite compatibility.
Three model files (`api_key.py`, `session.py`, `session_followup.py`) already use
`from sqlalchemy import JSON` successfully, confirming this is safe.

### B.1 Files to change (12 files)

- [ ] **B.1.1** `models/execution.py:18`
- [ ] **B.1.2** `models/execution_environment.py:12`
- [ ] **B.1.3** `models/execution_record.py:17`
- [ ] **B.1.4** `models/workflow_definition.py:12`
- [ ] **B.1.5** `models/mission_context.py:13`
- [ ] **B.1.6** `models/mission_history.py:13`
- [ ] **B.1.7** `models/mission_event.py:10`
- [ ] **B.1.8** `models/agent_catalog.py:13`
- [ ] **B.1.9** `models/mission_intent.py:12`
- [ ] **B.1.10** `models/mission_team.py:10`
- [ ] **B.1.11** `models/mission_learning.py:12`
- [ ] **B.1.12** `models/mission_plan.py:29`

**Change pattern** (each file):

```python
# Before
from sqlalchemy.dialects.sqlite import JSON

# After — merge JSON into the existing sqlalchemy import
from sqlalchemy import ..., JSON, ...
# (remove the dialects.sqlite import line entirely)
```

**Merge strategy:** Most files already import from `sqlalchemy` (e.g., `String`,
`Text`, `ForeignKey`). Add `JSON` to that existing import and delete the
`dialects.sqlite` line. Three files (`api_key.py`, `session.py`,
`session_followup.py`) already do this — follow their pattern.

### B.2 Verification

- [ ] **B.2.1** `python -c "from modules.backend.models import Base; print('OK')"` succeeds
- [ ] **B.2.2** `alembic check` reports no new autogenerated changes (generic `JSON`
      and SQLite `JSON` are equivalent for Alembic's type comparison)
- [ ] **B.2.3** All existing unit tests pass (these run on SQLite)
- [ ] **B.2.4** No `sqlalchemy.dialects.sqlite` imports remain:
      `rg "dialects.sqlite" modules/backend/models/`

---

## Phase C — Add Missing Composite Indexes

**Goal:** Add composite indexes for verified hot query patterns.

**File:** `modules/backend/migrations/versions/plan64_002_composite_indexes.py`

### C.1 Indexes to add (4 — verified hot paths)

| # | Table | Columns | Rationale | Verified query location |
|---|-------|---------|-----------|------------------------|
| 1 | `mission_artifacts` | `(mission_id, artifact_type)` | Filtered artifact listing per mission | `mission_artifact.py` service |
| 2 | `llm_calls` | `(mission_id, created_at)` | Cost dashboard aggregation by mission + time range | `token_economics.py` service |
| 3 | `session_followups` | `(mission_id, consumed_at, expires_at)` | `fire_matching` scans unconsumed, unexpired followups per mission — called on **every event emission** | `session_followup.py` repo lines 88-92 |
| 4 | `execution_records` | `(mission_id, status, created_at)` | Common 3-column filter in history + cost queries | `execution_persistence.py` service |

### C.2 Indexes that already exist (DO NOT create)

| Table | Columns | Migration where created |
|-------|---------|----------------------|
| `mission_intents` | `(mission_id, created_at DESC)` | `20260410_plan42_mission_plans.py` line 58-62 |
| `plan_task_states` | `(mission_plan_id, status)` | `20260410_plan42_mission_plans.py` line 220-224 |

### C.3 Deferred indexes (add when table exceeds 10k rows)

These are cold-path queries with low cardinality. Not worth the write overhead now:

| Table | Columns | Rationale for deferral |
|-------|---------|----------------------|
| `mission_events` | `(mission_id, created_at)` | Narrative reads are cold path; events are append-only |
| `context_changes` | `(context_id, version)` | Version is append-only; `context_id` already indexed |
| `mission_learnings` | `(mission_id, status)` | Low cardinality; existing single-column indexes on `mission_id` + separate `(platform_promoted, status)` composite sufficient |

### C.4 Migration

```python
def upgrade() -> None:
    op.create_index(
        "ix_mission_artifacts_mission_type",
        "mission_artifacts",
        ["mission_id", "artifact_type"],
    )
    op.create_index(
        "ix_llm_calls_mission_created",
        "llm_calls",
        ["mission_id", "created_at"],
    )
    op.create_index(
        "ix_session_followups_mission_consumed_expires",
        "session_followups",
        ["mission_id", "consumed_at", "expires_at"],
    )
    op.create_index(
        "ix_execution_records_mission_status_created",
        "execution_records",
        ["mission_id", "status", "created_at"],
    )
```

### C.5 Verification

- [ ] **C.5.1** `alembic upgrade head` succeeds
- [ ] **C.5.2** `\di+ ix_mission_artifacts_*` in psql shows the new index
- [ ] **C.5.3** `EXPLAIN ANALYZE` on `SELECT * FROM session_followups WHERE mission_id = '...' AND consumed_at IS NULL AND expires_at > now()` shows index scan

---

## Phase D — Add FK Constraints on Soft References

**Goal:** Convert 3 bare-string columns into proper FK-constrained references,
plus 2 denormalised columns that `delete_mission()` manually cleans.

**File:** `modules/backend/migrations/versions/plan64_003_soft_ref_fks.py`

### D.1 `Mission.owner_id` → `users.id`

**File:** `modules/backend/models/mission.py:67-68`

```python
# Before
owner_id: Mapped[str] = mapped_column(
    String(200), nullable=False, index=True,
)

# After
owner_id: Mapped[str] = mapped_column(
    String(36),
    ForeignKey("users.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
```

**Migration pre-check:** Before adding the FK, verify no orphan `owner_id` values:

```python
def upgrade() -> None:
    conn = op.get_bind()
    # Fix orphan owner_ids — set to first admin user
    orphans = conn.execute(sa.text(
        "SELECT m.id FROM missions m "
        "LEFT JOIN users u ON m.owner_id = u.id "
        "WHERE u.id IS NULL"
    )).fetchall()
    if orphans:
        admin = conn.execute(sa.text(
            "SELECT id FROM users WHERE system_role = 'admin' LIMIT 1"
        )).scalar()
        if admin:
            conn.execute(sa.text(
                "UPDATE missions SET owner_id = :admin_id "
                "WHERE id IN (SELECT m.id FROM missions m "
                "LEFT JOIN users u ON m.owner_id = u.id "
                "WHERE u.id IS NULL)"
            ), {"admin_id": admin})

    # Resize column from String(200) to String(36) for UUID
    op.alter_column("missions", "owner_id", type_=sa.String(36))

    # Add FK constraint
    op.create_foreign_key(
        "fk_missions_owner_id_users",
        "missions", "users",
        ["owner_id"], ["id"],
        ondelete="RESTRICT",
    )
```

### D.2 `Session.mission_id` → `missions.id`

**File:** `modules/backend/models/session.py:54-56`

```python
# Before
mission_id: Mapped[str | None] = mapped_column(
    String(36), nullable=True, index=True
)

# After
mission_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("missions.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
```

**Migration pre-check:** Null out any orphan session mission_ids before adding FK:

```python
conn.execute(sa.text(
    "UPDATE sessions SET mission_id = NULL "
    "WHERE mission_id IS NOT NULL "
    "AND mission_id NOT IN (SELECT id FROM missions)"
))
```

**Test impact:** Verified that all tests creating sessions use real `test_mission`
fixtures — no tests set `session.mission_id` to fake values. Adding the FK will not
break existing tests.

### D.3 `Session.user_id` → `users.id`

**File:** `modules/backend/models/session.py:53`

```python
# Before
user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

# After
user_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("users.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
```

**Migration pre-check:** Same pattern — null out orphan user_ids.

### D.4 `LlmCall.mission_id` and `SessionFollowup.mission_id`

These are deliberately denormalised (documented in model comments). Adding FKs here
lets mission deletion auto-cascade instead of requiring manual `DELETE FROM` in
`delete_mission()`.

- `LlmCall.mission_id` — add `ForeignKey("missions.id", ondelete="CASCADE")`
- `SessionFollowup.mission_id` — add `ForeignKey("missions.id", ondelete="CASCADE")`

**After this phase:** Remove the explicit `DELETE FROM llm_calls/session_followups`
queries from the simplified `delete_mission()` (Phase A.3), reducing it from 5
statements to 3.

### D.5 Verification

- [ ] **D.5.1** Migration succeeds on a database with existing data
- [ ] **D.5.2** Attempting to create a mission with a non-existent `owner_id` raises IntegrityError
- [ ] **D.5.3** Deleting a user with `current_mission_id` set works (SET NULL)
- [ ] **D.5.4** Deleting a mission nulls out `sessions.mission_id` for linked sessions
- [ ] **D.5.5** Deleting a mission cascades `llm_calls` and `session_followups` rows

---

## Phase E — Standardise String Timestamps to DateTime

**Goal:** Convert 6 `String(30)` timestamp columns to `DateTime(timezone=True)`.

**File:** `modules/backend/migrations/versions/plan64_004_timestamp_types.py`

### E.1 Columns to convert

| # | Model file | Table | Column | Current type |
|---|------------|-------|--------|-------------|
| 1 | `mission_history.py:109` | `milestone_summaries` | `period_start` | `String(30)` |
| 2 | `mission_history.py:112` | `milestone_summaries` | `period_end` | `String(30)` |
| 3 | `execution_environment.py:69` | `execution_environments` | `last_execution_at` | `String(30)` |
| 4 | `workflow_schedule.py:74` | `workflow_schedules` | `last_fired_at` | `String(30)` |
| 5 | `workflow_schedule.py:78` | `workflow_schedules` | `next_fire_at` | `String(30)` |
| 6 | `workflow_definition.py:73` | `workflow_definitions` | `locked_at` | `String(30)` |

### E.2 Migration strategy

PostgreSQL can cast ISO-8601 strings to `TIMESTAMPTZ` directly. For small tables
(all 4 tables above are low-volume), use the simpler direct `ALTER COLUMN`:

```python
def upgrade() -> None:
    tables_columns = [
        ("milestone_summaries", "period_start"),
        ("milestone_summaries", "period_end"),
        ("execution_environments", "last_execution_at"),
        ("workflow_schedules", "last_fired_at"),
        ("workflow_schedules", "next_fire_at"),
        ("workflow_definitions", "locked_at"),
    ]
    for table, column in tables_columns:
        op.execute(
            sa.text(f'ALTER TABLE {table} '
                    f'ALTER COLUMN "{column}" TYPE TIMESTAMPTZ '
                    f'USING "{column}"::timestamptz')
        )
```

This holds a brief `ACCESS EXCLUSIVE` lock per table but is safe for these
low-volume tables.

### E.3 Model changes

Update each model to use `DateTime(timezone=True)` instead of `String(30)`:

- [ ] **E.3.1** `mission_history.py:108-113` — `period_start`, `period_end`: `String(30)` → `DateTime(timezone=True)`
- [ ] **E.3.2** `execution_environment.py:68-71` — `last_execution_at`: `String(30)` → `DateTime(timezone=True)`
- [ ] **E.3.3** `workflow_schedule.py:73-80` — `last_fired_at`, `next_fire_at`: `String(30)` → `DateTime(timezone=True)`
- [ ] **E.3.4** `workflow_definition.py:72-75` — `locked_at`: `String(30)` → `DateTime(timezone=True)`

Also update `Mapped[str | None]` type hints to `Mapped[datetime | None]` and add
`from datetime import datetime` if not already imported.

### E.4 Service layer changes (verified write locations)

All 6 columns are written as ISO strings via `utc_now().isoformat()`. Each must
change to write `datetime` objects directly:

| Column | File | Line | Current pattern | Fix |
|--------|------|------|-----------------|-----|
| `last_fired_at` | `repositories/workflow_schedule.py` | 81 | `schedule.last_fired_at = fired_at_iso` | `= fired_at` (datetime) |
| `next_fire_at` | `repositories/workflow_schedule.py` | 83 | `schedule.next_fire_at = next_fire_at_iso` | `= next_fire_at` (datetime) |
| `next_fire_at` | `services/workflow_schedule.py` | 76 | `next_dt.replace(tzinfo=None).isoformat()` | `next_dt` (datetime, keep tzinfo) |
| `last_execution_at` | `services/execution_environment.py` | 535 | `utc_now().isoformat()` | `utc_now()` |
| `last_execution_at` | `services/execution_environment.py` | 555 | `utc_now().isoformat()` (raw SQL) | `utc_now()` |
| `period_start/end` | `services/summarization.py` | 242-243 | ISO strings from `completed_dates` list | Convert to `datetime` |
| `period_end` | `services/summarization.py` | 162 | `utc_now().isoformat()` | `utc_now()` |
| `locked_at` | `services/workflow_definition.py` | 135 | `utc_now().isoformat()` | `utc_now()` |

### E.5 `MissionEvent.timestamp` — deferred

`MissionEvent.timestamp` is also `String(30)` but is populated exclusively from
`SessionEvent.timestamp` (a `datetime` field) via `event.timestamp.isoformat()` in
`events/bus.py` line 102-104. Converting this is straightforward but touches the
event bus serialisation path. **Defer to a follow-up to avoid scope creep.**

### E.6 Verification

- [ ] **E.6.1** Migration succeeds; existing string timestamps are correctly parsed
- [ ] **E.6.2** `SELECT last_fired_at, pg_typeof(last_fired_at) FROM workflow_schedules LIMIT 1` returns `timestamp with time zone`
- [ ] **E.6.3** Service code that writes to these columns works without error
- [ ] **E.6.4** All existing tests pass

---

## Phase F — Naming Fix & Execution Table Deprecation Note

### F.1 Rename `MilestoneSummary.mission_ids` → `execution_ids`

**File:** `modules/backend/models/mission_history.py:99`

The column stores a JSON array of `ExecutionRecord.id` values, not mission IDs.
The name is misleading because the model already has a `mission_id` FK column.

**Verified impact (only 3 references):**

| File | Line | Usage |
|------|------|-------|
| `services/summarization.py` | 159 | `mission_ids=[]` (init empty) |
| `services/summarization.py` | 231 | `mission_ids = [r.id for r in batch]` (batch = ExecutionRecords) |
| `models/mission_history.py` | 118 | `f"missions={len(self.mission_ids)})>"` (\_\_repr\_\_) |

No code reads `MilestoneSummary.mission_ids` for business logic — it's write-only
(populated in summarization) and displayed in `__repr__`. This rename is low-risk.

**Model change:**

```python
# Before
mission_ids: Mapped[list] = mapped_column(
    JSON, default=list, nullable=False,
)

# After
execution_ids: Mapped[list] = mapped_column(
    JSON, default=list, nullable=False,
    comment="ExecutionRecord IDs that were compressed into this milestone",
)
```

**Migration:**

```python
op.alter_column(
    "milestone_summaries",
    "mission_ids",
    new_column_name="execution_ids",
)
```

**Service changes:**

- [ ] **F.1.1** `services/summarization.py:159` — `mission_ids=[]` → `execution_ids=[]`
- [ ] **F.1.2** `services/summarization.py:231` — `mission_ids = [...]` → `execution_ids = [...]`
- [ ] **F.1.3** `models/mission_history.py:118` — update `__repr__` to `execution_ids`

### F.2 `Execution` vs `ExecutionRecord` — deprecation note (no code change)

The `Execution` table is **actively written to** by:
- `services/execution.py:133` — `create_execution_from_step()` (workflow pipeline)
- `services/execution.py:203` — `create_adhoc_execution()` (ad-hoc runs)
- `services/execution_dispatch.py` — status transitions

It is NOT legacy read-only. Retiring it would require refactoring the entire
`WorkflowRun → Execution` pipeline. **Do not retire now.**

Add a deprecation comment to flag for future consolidation:

```python
class Execution(UUIDMixin, TimestampMixin, Base):
    """A runtime execution — a discrete objective with bounded scope.

    NOTE: This table overlaps significantly with ExecutionRecord (shared
    fields: mission_id, session_id, status, total_cost_usd, started_at,
    completed_at). New features should use ExecutionRecord. This table
    remains for backward compatibility with the workflow run pipeline
    (WorkflowRun -> Execution). See Plan 64 section F.2 for consolidation
    analysis.
    """
```

### F.3 Verification

- [ ] **F.3.1** `MilestoneSummary.execution_ids` works in all service/repo code
- [ ] **F.3.2** `rg "mission_ids" modules/backend/models/mission_history.py` returns zero matches
- [ ] **F.3.3** `rg "\.mission_ids" modules/backend/services/summarization.py` returns zero matches

---

## 3. Files Changed Summary

| Phase | Files modified | Files created |
|-------|---------------|---------------|
| **A** | `execution_record.py`, `session.py`, `mission_intent.py`, `mission_learning.py`, `mission.py` (service), `database_admin.py` | 1 migration |
| **B** | 12 model files (import change only) | 0 |
| **C** | 0 model files (indexes via migration only) | 1 migration |
| **D** | `mission.py` (model), `session.py` (model), `llm_call.py`, `session_followup.py`, `mission.py` (service) | 1 migration |
| **E** | `mission_history.py`, `execution_environment.py`, `workflow_schedule.py`, `workflow_definition.py`, + 4 service files | 1 migration |
| **F** | `mission_history.py`, `summarization.py`, `execution.py` (comment only) | 1 migration |

**Total:** ~24 files modified, 5 migration files created.

---

## 4. Migration Dependency Chain

All migrations chain from the current head:

```
widen_artifact_type
  └── plan64_001_fk_cascades              (Phase A)
        └── plan64_002_composite_indexes  (Phase C — no dependency on B)
              └── plan64_003_soft_ref_fks     (Phase D)
                    └── plan64_004_timestamp_types  (Phase E)
                          └── plan64_005_rename_column    (Phase F)
```

Phase B requires no migration (import-only change) and can be done at any time.

---

## 5. Rollback Strategy

Every migration has a `downgrade()` function that reverses the change:
- FK cascades: drop and re-create without `ondelete`
- Indexes: `op.drop_index()`
- FK constraints: `op.drop_constraint()`
- Timestamp conversion: `ALTER COLUMN ... TYPE VARCHAR(30) USING to_char(column, 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`
- Column rename: `op.alter_column(..., new_column_name="mission_ids")`

If a migration fails mid-apply, Alembic's transaction wrapping ensures atomicity
(all-or-nothing per migration step).

---

## 6. Testing Checklist

- [ ] Unit tests pass: `pytest tests/unit/backend/ -x`
- [ ] Integration test: create mission → populate children → delete mission → verify cascade
- [ ] Alembic round-trip: `upgrade head` then `downgrade -1` for each migration
- [ ] Service smoke test: `mc db status` shows all tables with correct row counts
- [ ] No `sqlalchemy.dialects.sqlite` imports remain: `rg "dialects.sqlite" modules/backend/models/`
- [ ] SQLite test suite passes (verifies Phase B didn't break test infra)
