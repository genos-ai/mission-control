# Plan 64 — Database Integrity & Performance Hardening

**Version:** 3.0.0
**Date:** 2026-04-26
**Author:** Herman + Data Architecture Review + Adversarial Review Pass + Full Schema Review (Opus 4.6)
**Status:** Partially complete — see v3.0 changelog
**Depends on:** None (all changes are additive migrations + model edits)
**Unlocks:** Safe mission deletion without raw SQL, JSONB GIN indexes, query performance at scale, correct cost accounting

### v3.0 changelog (2026-04-26 — post UUID v7 migration audit)

**Completed by UUID v7 migration (commits 4fee116, 5bf5f68):**
- All 93 varchar/varchar(36) ID columns converted to native PostgreSQL UUID type
- All 41 FK constraints dropped and re-created with correct ondelete rules
- UUIDMixin switched from uuid4() to uuid7() (Python 3.14 native)
- System account string IDs ("system:cli" etc.) replaced with deterministic UUID v5
- Empty string values in nullable columns cleaned to NULL
- Notes table dropped (legacy BFF artifact)

**Phase status update after audit:**
- **Phase A (CASCADE delete):** PARTIALLY DONE — 13/33 FKs use CASCADE, 11 SET NULL, 2 RESTRICT. Strategy is reasonable; document it.
- **Phase B (JSONB):** CHECK — needs re-audit after UUID migration.
- **Phase C (Indexes):** NOT STARTED — 7 new indexes still needed.
- **Phase D+K (Missing FKs):** CRITICAL — 5 bare UUID columns still lack FK constraints: `Execution.workflow_run_id`, `WorkflowRun.session_id`, `Execution.session_id`, `ExecutionRecord.session_id`, `ContextChange.mission_id`. These were never FKs in the old schema and the UUID migration didn't add them.
- **Phase E (Timestamp types in models):** NOT STARTED.
- **Phase F (Column renames):** NOT STARTED.
- **Phase G (env.py imports):** MOSTLY DONE — Note removed. Still missing: LlmCall, ModelPricing, MissionPlan, PlanTaskState, SessionFollowup, MissionArtifact, MissionLearning, MissionIntent, Embedding, ExecutionEnvironment.
- **Phase H (Float → Numeric):** NOT STARTED — 21 monetary columns remain Float across 9 models.
- **Phase I (Timezone timestamps):** NOT STARTED — TimestampMixin uses naive DateTime. Only ModelPricing has timezone=True.
- **Phase J (Status column storage):** NOT STARTED — MissionPlan.status and PlanTaskState.status use String(20), not Enum(native_enum=False). Session.status same.
- **Phase K:** Merged with Phase D above.
- **Phase L (Misc fixes):** NOT STARTED.

**Recommended implementation order:**
1. Phase G (env.py imports) — 30 seconds, zero risk
2. Phase D+K (5 missing FKs) — one migration, low risk
3. Phase H (Float → Numeric) — one migration, fixes cost rounding
4. Phase J (Status Enum consistency) — one migration, prevents silent bugs
5. Phase C (Indexes) — one migration, performance
6. Phase I (Timezone timestamps) — one migration, affects 25+ tables
7. Phase A (CASCADE audit) — documentation + targeted changes
8. Phases B, E, F, L — lower priority cleanup

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

### v2.0 changelog (full schema review)

1. **Added Phase G** — Fix Alembic `env.py` model imports. 12 models are missing from
   `env.py`, making `alembic autogenerate` blind to schema drift on those tables. Critical
   finding — 30-second fix.
2. **Added Phase H** — Float → Numeric for all 22 monetary columns across 8 models.
   IEEE 754 floats cause rounding errors in cost accounting. Changes to `Numeric(12, 6)`.
3. **Added Phase I** — Timezone-aware timestamps in `TimestampMixin`. The mixin uses
   naive `DateTime` (no timezone). Only `ModelPricing` uses `DateTime(timezone=True)`.
   Affects every table that uses the mixin (~25 tables).
4. **Added Phase J** — Standardise status column storage. Two incompatible patterns:
   `Enum(X, native_enum=False)` stores uppercase NAME, `String(20)` with `.value`
   default stores lowercase value. Cross-table queries silently return wrong results.
5. **Added Phase K** — Additional bare-string FK columns not covered by Phase D:
   `Execution.workflow_run_id`, `WorkflowRun.session_id`, `Execution.session_id`,
   `ContextChange.mission_id`.
6. **Added Phase L** — Miscellaneous model fixes: `Embedding.created_at` type annotation,
   `MissionArtifact.artifact_type` enum enforcement, missing FK indexes on
   `PlanTaskState`, `SessionMessage`/`SessionChannel` timestamp convention.

---

## 0. Problem Statement

A full architectural review of the 30-table schema identified seven categories of
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

4. **Alembic `env.py` blind spot** — 12 models are not imported in the migration
   environment, making `alembic autogenerate` and `alembic check` unable to detect
   schema drift on those tables. Production may already have diverged.

5. **Float for money** — All 22 monetary columns (`cost_usd`, `budget_ceiling_usd`,
   `price_per_mtok_*`, etc.) use IEEE 754 `Float`. Rounding errors accumulate across
   thousands of LLM calls and will cause cost dashboards and budget enforcement to
   report incorrect values.

6. **Naive timestamps** — `TimestampMixin` uses `DateTime` without `timezone=True`,
   propagating naive timestamps to every table. Only `ModelPricing` correctly uses
   timezone-aware columns. Workers in different timezone contexts will produce
   inconsistent timestamps.

7. **Status storage split** — Two incompatible patterns for status columns:
   `Enum(X, native_enum=False)` stores the uppercase NAME (`ACTIVE`), while
   `String(20)` with `.value` default stores the lowercase value (`active`).
   Cross-table queries silently return wrong results.

Additionally: inconsistent timestamp storage (6 columns use `String(30)` instead of
`DateTime`), `MilestoneSummary.mission_ids` is a misleading name (stores execution
record IDs), and the `Execution` table duplicates fields already present on
`ExecutionRecord`.

**Risk of doing nothing:** silent data corruption from orphaned rows, unbounded
query latency on growing tables, incorrect cost accounting, timezone bugs as the
system scales to containers and workers, and an ever-expanding manual delete cascade
that is one missed table away from a broken mission deletion.

---

## 1. Success Criteria

- [ ] All child FK constraints have explicit `ondelete` (CASCADE or SET NULL)
- [ ] `delete_mission()` reduced from ~30 raw SQL statements to ~5
- [ ] All 12 model files use `sqlalchemy.JSON` (not `sqlalchemy.dialects.sqlite.JSON`)
- [ ] 4 new composite indexes added for hot query patterns (+ 3 deferred)
- [ ] `Mission.owner_id`, `Session.mission_id`, `Session.user_id` have FK constraints
- [ ] All `String(30)` timestamp columns converted to `DateTime(timezone=True)`
- [ ] `MilestoneSummary.mission_ids` renamed to `execution_ids`
- [ ] Alembic `env.py` imports all models (no blind spots for autogenerate)
- [ ] All 22 monetary columns use `Numeric(12, 6)` instead of `Float`
- [ ] `TimestampMixin` uses `DateTime(timezone=True)` for `created_at`/`updated_at`
- [ ] Status columns use a single consistent storage pattern across all tables
- [ ] Additional bare-string FK columns (`Execution.workflow_run_id`, etc.) constrained
- [ ] `Embedding.created_at` type annotation fixed; `MissionArtifact.artifact_type` enforced
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
| **G** | Fix Alembic `env.py` model imports | ~5 min | Zero — import-only change, no schema change |
| **H** | Float → Numeric for monetary columns | ~2 hours | Medium — type change migration, service layer updates |
| **I** | Timezone-aware timestamps in `TimestampMixin` | ~3 hours | Medium — touches ~25 tables via mixin, data migration |
| **J** | Standardise status column storage pattern | ~2 hours | Medium — data migration to normalise casing |
| **K** | Additional bare-string FK constraints | ~1 hour | Low — same pattern as Phase D |
| **L** | Type annotations, enum enforcement, missing FK indexes | ~1 hour | Low — model-only changes + 1 migration |

**Total:** ~17 hours across 12 phases. Phases A–F and G–L are independently orderable.
Phase G should be done first (30-second fix, highest-severity finding).

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

## Phase G — Fix Alembic `env.py` Model Imports

**Goal:** Ensure all ORM models are imported in the Alembic migration environment so
`alembic autogenerate` and `alembic check` can detect schema drift on every table.

**Severity:** Critical — this is a 30-second fix for the highest-severity finding.

### G.1 The problem

**File:** `modules/backend/migrations/env.py`, lines 20-44

`env.py` imports 18 models individually. The schema has 30+ models. The following 12
are missing — `alembic autogenerate` cannot detect drift on these tables:

| # | Model | Table |
|---|-------|-------|
| 1 | `MissionEvent` | `mission_events` |
| 2 | `MissionIntent` | `mission_intents` |
| 3 | `MissionLearning` | `mission_learnings` |
| 4 | `MissionPlan` | `mission_plans` |
| 5 | `PlanTaskState` | `plan_task_states` |
| 6 | `MissionArtifact` | `mission_artifacts` |
| 7 | `SessionFollowup` | `session_followups` |
| 8 | `LlmCall` | `llm_calls` |
| 9 | `ModelPricing` | `model_pricing` |
| 10 | `Embedding` | `embeddings` |
| 11 | `ExecutionEnvironmentModel` | `execution_environments` |
| 12 | `ContextMilestone` | `context_milestones` |

### G.2 Fix

Replace the 24 individual imports with a single package import. `models/__init__.py`
already imports and re-exports every model, so this registers them all on
`Base.metadata`:

**File:** `modules/backend/migrations/env.py`

```python
# Before (lines 17-44): 24 individual model imports

# After: single import that registers all models
from modules.backend.models.base import Base
import modules.backend.models  # noqa: F401 — registers all models on Base.metadata
```

### G.3 Verification

- [ ] **G.3.1** `alembic check` reports no unexpected drift (or reports real drift that was previously invisible)
- [ ] **G.3.2** `python -c "from modules.backend.migrations.env import target_metadata; print(len(target_metadata.tables))"` returns 30+
- [ ] **G.3.3** All existing tests pass

---

## Phase H — Float → Numeric for Monetary Columns

**Goal:** Replace all `Float` columns storing USD values or per-million-token prices
with `Numeric(12, 6)` to eliminate IEEE 754 rounding errors in cost accounting.

### H.1 Columns to change (22 columns across 8 models)

| # | Model file | Table | Column | Current |
|---|------------|-------|--------|---------|
| 1 | `execution.py:115` | `workflow_runs` | `total_cost_usd` | `Float` |
| 2 | `execution.py:118` | `workflow_runs` | `budget_usd` | `Float` |
| 3 | `execution.py:196` | `executions` | `total_cost_usd` | `Float` |
| 4 | `execution.py:199` | `executions` | `cost_ceiling_usd` | `Float` |
| 5 | `execution_record.py:139` | `execution_records` | `total_cost_usd` | `Float` |
| 6 | `execution_record.py:271` | `task_executions` | `cost_usd` | `Float` |
| 7 | `execution_record.py:277` | `task_executions` | `duration_seconds` | `Float` |
| 8 | `execution_record.py:383` | `task_attempts` | `cost_usd` | `Float` |
| 9 | `session.py:75` | `sessions` | `total_cost_usd` | `Float` |
| 10 | `session.py:77` | `sessions` | `cost_budget_usd` | `Float` |
| 11 | `session.py:177` | `session_messages` | `cost_usd` | `Float` |
| 12 | `mission.py:76` | `missions` | `budget_ceiling_usd` | `Float` |
| 13 | `mission_plan.py:147` | `mission_plans` | `budget_usd_ceiling` | `Float` |
| 14 | `mission_plan.py:153` | `mission_plans` | `total_spent_usd` | `Float` |
| 15 | `mission_plan.py:293` | `plan_task_states` | `cost_usd` | `Float` |
| 16 | `mission_plan.py:296` | `plan_task_states` | `duration_seconds` | `Float` |
| 17 | `mission_learning.py:82` | `mission_learnings` | `confidence` | `Float` |
| 18 | `workflow_schedule.py:58` | `workflow_schedules` | `budget_per_run_usd` | `Float` |
| 19 | `llm_call.py:71` | `llm_calls` | `cost_usd` | `Float` |
| 20-22 | `model_pricing.py:34-46` | `model_pricing` | `price_per_mtok_*` (5 cols) | `Float` |

**Note:** `duration_seconds` (rows 7, 16) and `confidence` (row 17) are not monetary.
They can stay as `Float` since sub-microsecond precision and 0-1 confidence don't
require exact decimal representation. **Exclude them from the migration.** This
reduces the scope to 19 monetary columns.

### H.2 Migration

**File:** `modules/backend/migrations/versions/plan64_006_float_to_numeric.py`

```python
import sqlalchemy as sa
from alembic import op

# (model, table, column) tuples — monetary columns only
MONETARY_COLUMNS = [
    ("workflow_runs", "total_cost_usd"),
    ("workflow_runs", "budget_usd"),
    ("executions", "total_cost_usd"),
    ("executions", "cost_ceiling_usd"),
    ("execution_records", "total_cost_usd"),
    ("task_executions", "cost_usd"),
    ("task_attempts", "cost_usd"),
    ("sessions", "total_cost_usd"),
    ("sessions", "cost_budget_usd"),
    ("session_messages", "cost_usd"),
    ("missions", "budget_ceiling_usd"),
    ("mission_plans", "budget_usd_ceiling"),
    ("mission_plans", "total_spent_usd"),
    ("plan_task_states", "cost_usd"),
    ("workflow_schedules", "budget_per_run_usd"),
    ("llm_calls", "cost_usd"),
]

PRICING_COLUMNS = [
    ("model_pricing", "price_per_mtok_input"),
    ("model_pricing", "price_per_mtok_output"),
    ("model_pricing", "price_per_mtok_cache_write_5m"),
    ("model_pricing", "price_per_mtok_cache_write_1h"),
    ("model_pricing", "price_per_mtok_cache_read"),
]


def upgrade() -> None:
    for table, col in MONETARY_COLUMNS:
        op.alter_column(
            table, col,
            type_=sa.Numeric(12, 6),
            existing_type=sa.Float(),
        )
    for table, col in PRICING_COLUMNS:
        op.alter_column(
            table, col,
            type_=sa.Numeric(12, 8),
            existing_type=sa.Float(),
        )


def downgrade() -> None:
    for table, col in MONETARY_COLUMNS + PRICING_COLUMNS:
        op.alter_column(
            table, col,
            type_=sa.Float(),
            existing_type=sa.Numeric(),
        )
```

### H.3 Model changes

Update each model to use `Numeric`:

```python
from sqlalchemy import Numeric

# Before
total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

# After
total_cost_usd: Mapped[float] = mapped_column(
    Numeric(12, 6), default=0.0, nullable=False,
)
```

For pricing columns, use `Numeric(12, 8)` (prices are per-million-token, need
sub-cent precision).

**Note:** `Mapped[float]` type hint remains `float` — SQLAlchemy returns `Decimal`
from `Numeric` columns, but `Decimal` is float-compatible for all practical purposes.
If strict typing is desired, change to `Mapped[Decimal]` and update service code.

### H.4 Service layer impact

Search for any code that compares cost values with `==`:

```bash
rg "cost_usd ==" modules/backend/services/ --type py
rg "total_cost ==" modules/backend/services/ --type py
```

`Numeric` comparison with `==` works correctly (unlike Float). No service changes
expected unless code explicitly assumes `float` type via `isinstance()`.

### H.5 Verification

- [ ] **H.5.1** Migration succeeds; existing float values are preserved
- [ ] **H.5.2** `SELECT pg_typeof(cost_usd) FROM llm_calls LIMIT 1` returns `numeric`
- [ ] **H.5.3** Cost dashboard shows same totals before and after (within rounding)
- [ ] **H.5.4** All existing tests pass

---

## Phase I — Timezone-Aware Timestamps in `TimestampMixin`

**Goal:** Change `TimestampMixin.created_at` and `updated_at` from naive `DateTime`
to `DateTime(timezone=True)` so all timestamps are stored as `TIMESTAMPTZ`.

### I.1 The problem

**File:** `modules/backend/models/base.py`, lines 25-35

```python
# Current — naive DateTime (no timezone info stored)
created_at: Mapped[datetime] = mapped_column(DateTime, ...)
updated_at: Mapped[datetime] = mapped_column(DateTime, ...)
```

Every table inheriting `TimestampMixin` (~25 tables) stores naive timestamps.
`ModelPricing` is the only table that correctly uses `DateTime(timezone=True)`.

### I.2 Model change

**File:** `modules/backend/models/base.py`

```python
# After
class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
```

### I.3 Migration

**File:** `modules/backend/migrations/versions/plan64_007_timestamptz.py`

All tables using `TimestampMixin` need their `created_at` and `updated_at` columns
converted. PostgreSQL handles `TIMESTAMP → TIMESTAMPTZ` by assuming the current
`timezone` setting (default UTC), so no data loss if the server is UTC.

```python
TIMESTAMPED_TABLES = [
    "notes", "missions", "mission_members", "mission_contexts",
    "context_changes", "context_milestones", "mission_decisions",
    "milestone_summaries", "sessions", "execution_records",
    "task_executions", "task_attempts", "execution_decisions",
    "workflow_runs", "executions", "agent_catalog",
    "mission_team_members", "prompt_versions", "workflow_definitions",
    "workflow_schedules", "users", "api_keys", "mission_plans",
    "plan_task_states", "session_followups", "mission_events",
    "mission_intents", "mission_learnings", "mission_artifacts",
    "llm_calls", "execution_environments", "embeddings",
]


def upgrade() -> None:
    for table in TIMESTAMPED_TABLES:
        for col in ("created_at", "updated_at"):
            op.execute(
                f"ALTER TABLE {table} "
                f"ALTER COLUMN {col} TYPE TIMESTAMPTZ "
                f"USING {col} AT TIME ZONE 'UTC'"
            )
```

**Note:** `SessionMessage`, `SessionChannel`, `MissionIntent`, and `Embedding` define
their own `created_at`/`updated_at` outside the mixin. These are handled in the same
migration by including their tables in the list above. The `USING ... AT TIME ZONE 'UTC'`
clause ensures existing naive timestamps are interpreted as UTC.

### I.4 Tables with custom timestamp columns

These tables also have `DateTime` columns outside the mixin that should be converted:

| Table | Column | Notes |
|-------|--------|-------|
| `execution_records` | `started_at`, `completed_at` | Already `DateTime` (naive) |
| `task_executions` | `started_at`, `completed_at` | Already `DateTime` (naive) |
| `workflow_runs` | `started_at`, `completed_at` | Converted from String in earlier migration |
| `executions` | `started_at`, `completed_at` | Converted from String in earlier migration |
| `sessions` | `last_activity_at`, `expires_at` | Already `DateTime` (naive) |
| `api_keys` | `expires_at`, `revoked_at`, `last_used_at` | Already `DateTime` (naive) |
| `users` | `last_login_at` | Already `DateTime` (naive) |
| `plan_task_states` | `approved_at`, `last_attempt_at`, `veto_expires_at` | Already `DateTime` (naive) |
| `session_followups` | `expires_at`, `consumed_at` | Already `DateTime` (naive) |
| `session_channels` | `bound_at` | Already `DateTime` (naive) |
| `mission_learnings` | `promoted_at` | Already `DateTime` (naive) |

Include all of these in the migration. Total: ~50 columns across 30 tables.

### I.5 Verification

- [ ] **I.5.1** `SELECT pg_typeof(created_at) FROM missions LIMIT 1` returns `timestamp with time zone`
- [ ] **I.5.2** New rows have `+00` suffix in `created_at`
- [ ] **I.5.3** Existing timestamps are preserved (interpreted as UTC)
- [ ] **I.5.4** All existing tests pass (SQLite ignores timezone parameter)

---

## Phase J — Standardise Status Column Storage Pattern

**Goal:** Ensure all status/enum columns use a single storage pattern so cross-table
queries and application code don't need to know per-table casing rules.

### J.1 The problem

Two incompatible patterns exist:

**Pattern A** — `Enum(X, native_enum=False)`: Stores the enum **name** (uppercase).
Used by: `Mission.status`, `WorkflowRun.status`, `Execution.status`,
`ExecutionRecord.status`, `TaskExecution.status`, `TaskAttempt.status`,
`ExecutionDecision.decision_type`, `ContextChange.change_type`,
`ExecutionEnvironmentModel.status`, `MissionMember.role`, `TaskAttempt.failure_tier`.

**Pattern B** — `String(N)` with `default=EnumClass.VALUE.value`: Stores the enum
**value** (lowercase). Used by: `Session.status`, `MissionPlan.status`,
`PlanTaskState.status`, `MissionDecision.status`, `MissionLearning.status`,
`MissionArtifact.artifact_type`, `MissionArtifact.content_type`.

### J.2 Recommended standard: Pattern B (String with lowercase values)

Rationale:
- More portable — no SQLAlchemy `Enum` type negotiation
- Lowercase values are what the API serializes, so no casing translation needed
- Easier to add new values (no migration to alter the enum type)
- Already used by the newer tables (Plan 42, Plan 43, Plan 51)

### J.3 Migration strategy

For each Pattern A column, the existing database values are uppercase (e.g., `ACTIVE`).
Convert to lowercase:

**File:** `modules/backend/migrations/versions/plan64_008_status_lowercase.py`

```python
ENUM_COLUMNS = [
    # (table, column, {old_name: new_value})
    ("missions", "status", {"ACTIVE": "active", "PAUSED": "paused", "ARCHIVED": "archived"}),
    ("workflow_runs", "status", {"PENDING": "pending", "RUNNING": "running", "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}),
    ("executions", "status", {"PENDING": "pending", "RUNNING": "running", "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}),
    ("execution_records", "status", {"PENDING": "pending", "RUNNING": "running", "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled", "TIMED_OUT": "timed_out"}),
    ("task_executions", "status", {"COMPLETED": "completed", "FAILED": "failed", "SKIPPED": "skipped"}),
    ("task_attempts", "status", {"PASSED": "passed", "FAILED": "failed"}),
    ("execution_decisions", "decision_type", {"RETRY": "retry", "FAIL": "fail", "PASS": "pass", "RE_PLAN": "re_plan", "SKIP": "skip", "ESCALATE": "escalate", "POST_RUN_SUPERVISOR": "post_run_supervisor"}),
    ("context_changes", "change_type", {"ADD": "add", "REPLACE": "replace", "REMOVE": "remove", "PRUNE": "prune", "ARCHIVE": "archive"}),
    ("execution_environments", "status", {"CREATING": "creating", "RUNNING": "running", "STOPPED": "stopped", "FAILED": "failed", "DESTROYED": "destroyed"}),
    ("mission_members", "role", {"OWNER": "owner", "MAINTAINER": "maintainer", "VIEWER": "viewer"}),
    ("task_attempts", "failure_tier", {"TIER_1_STRUCTURAL": "tier_1_structural", "TIER_2_QUALITY": "tier_2_quality", "TIER_3_INTEGRATION": "tier_3_integration", "AGENT_ERROR": "agent_error", "TIMEOUT": "timeout"}),
]


def upgrade() -> None:
    for table, column, mapping in ENUM_COLUMNS:
        # Step 1: Convert column from VARCHAR-backed Enum to plain String
        op.alter_column(table, column, type_=sa.String(50), existing_type=sa.String(50))
        # Step 2: Update values
        for old, new in mapping.items():
            op.execute(
                sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                {"old": old, "new": new},
            )
```

### J.4 Model changes

Convert Pattern A columns from `Enum(X, native_enum=False)` to `String` with `.value`
defaults. Example:

```python
# Before
status: Mapped[str] = mapped_column(
    Enum(MissionStatus, native_enum=False),
    default=MissionStatus.ACTIVE,
    nullable=False,
)

# After
status: Mapped[str] = mapped_column(
    String(20),
    default=MissionStatus.ACTIVE.value,
    nullable=False,
)
```

**Files to change:**
- [ ] **J.4.1** `mission.py` — `Mission.status`, `MissionMember.role`
- [ ] **J.4.2** `execution.py` — `WorkflowRun.status`, `Execution.status`
- [ ] **J.4.3** `execution_record.py` — `ExecutionRecord.status`, `TaskExecution.status`,
  `TaskAttempt.status`, `TaskAttempt.failure_tier`, `ExecutionDecision.decision_type`
- [ ] **J.4.4** `mission_context.py` — `ContextChange.change_type`
- [ ] **J.4.5** `execution_environment.py` — `ExecutionEnvironmentModel.status`

### J.5 Service layer impact

Search for any code that compares status values using the enum NAME:

```bash
rg "\.ACTIVE\b|\.PENDING\b|\.RUNNING\b|\.COMPLETED\b|\.FAILED\b" \
    modules/backend/services/ --type py
```

These comparisons will still work because `MissionStatus.ACTIVE` is `"active"` (the
`str, enum.Enum` value). The change is in what SQLAlchemy writes to the database,
not in what the Python code compares against. **However**, any raw SQL queries that
filter by `status = 'ACTIVE'` (uppercase) will break and must be updated.

### J.6 Verification

- [ ] **J.6.1** `SELECT DISTINCT status FROM missions` returns lowercase values
- [ ] **J.6.2** `SELECT DISTINCT status FROM executions` returns lowercase values
- [ ] **J.6.3** No raw SQL queries filter by uppercase status values
- [ ] **J.6.4** All existing tests pass

---

## Phase K — Additional Bare-String FK Constraints

**Goal:** Add FK constraints to 4 remaining FK-like columns not covered by Phase D.

### K.1 Columns

| # | Model file | Table | Column | FK target | `ondelete` |
|---|------------|-------|--------|-----------|------------|
| 1 | `execution.py:153` | `executions` | `workflow_run_id` | `workflow_runs.id` | `SET NULL` |
| 2 | `execution.py:181` | `executions` | `session_id` | `sessions.id` | `SET NULL` |
| 3 | `execution.py:103` | `workflow_runs` | `session_id` | `sessions.id` | `SET NULL` |
| 4 | `mission_context.py:136` | `context_changes` | `mission_id` | `missions.id` | `CASCADE` |

### K.2 Migration

**File:** `modules/backend/migrations/versions/plan64_009_additional_fks.py`

```python
def upgrade() -> None:
    # Pre-check: null out orphans
    for table, col, parent_table in [
        ("executions", "workflow_run_id", "workflow_runs"),
        ("executions", "session_id", "sessions"),
        ("workflow_runs", "session_id", "sessions"),
    ]:
        conn = op.get_bind()
        conn.execute(sa.text(
            f"UPDATE {table} SET {col} = NULL "
            f"WHERE {col} IS NOT NULL "
            f"AND {col} NOT IN (SELECT id FROM {parent_table})"
        ))

    # context_changes.mission_id — delete orphans (CASCADE semantics)
    conn.execute(sa.text(
        "DELETE FROM context_changes "
        "WHERE mission_id IS NOT NULL "
        "AND mission_id NOT IN (SELECT id FROM missions)"
    ))

    # Add FK constraints
    op.create_foreign_key(
        "fk_executions_workflow_run_id",
        "executions", "workflow_runs",
        ["workflow_run_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_executions_session_id",
        "executions", "sessions",
        ["session_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflow_runs_session_id",
        "workflow_runs", "sessions",
        ["session_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_context_changes_mission_id",
        "context_changes", "missions",
        ["mission_id"], ["id"],
        ondelete="CASCADE",
    )
```

### K.3 Model changes

- [ ] **K.3.1** `execution.py:153` — add `ForeignKey("workflow_runs.id", ondelete="SET NULL")`
- [ ] **K.3.2** `execution.py:181` — add `ForeignKey("sessions.id", ondelete="SET NULL")`
- [ ] **K.3.3** `execution.py:103` — add `ForeignKey("sessions.id", ondelete="SET NULL")`
- [ ] **K.3.4** `mission_context.py:136` — add `ForeignKey("missions.id", ondelete="CASCADE")`

### K.4 Verification

- [ ] **K.4.1** Migration succeeds on a database with existing data
- [ ] **K.4.2** Deleting a session sets `executions.session_id` to NULL
- [ ] **K.4.3** Deleting a mission cascades to `context_changes` via `mission_id`

---

## Phase L — Type Annotations, Enum Enforcement, Missing FK Indexes

**Goal:** Fix miscellaneous model-level issues found in the full schema review.

### L.1 `Embedding.created_at` type annotation

**File:** `modules/backend/models/embedding.py`, line 69

```python
# Before — type annotation says str, column is DateTime
created_at: Mapped[str] = mapped_column(DateTime, ...)

# After
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)
```

Also add `from datetime import datetime` if not already imported (it's imported via
`utc_now` but should be explicit for the type hint).

### L.2 `MissionArtifact.artifact_type` — enforce via CHECK constraint

**File:** `modules/backend/models/mission_artifact.py`, lines 127-132

The `ArtifactType` enum exists but the column is `String(50)` with no enforcement.
Add a `CheckConstraint`:

```python
from sqlalchemy import CheckConstraint

__table_args__ = (
    CheckConstraint(
        "artifact_type IN ('research_report', 'vulnerability_report', "
        "'quality_audit', 'architecture_review', 'report', 'code', 'data')",
        name="ck_mission_artifacts_type",
    ),
)
```

**Migration:** Add the CHECK constraint in a migration:

```python
op.create_check_constraint(
    "ck_mission_artifacts_type",
    "mission_artifacts",
    "artifact_type IN ('research_report', 'vulnerability_report', "
    "'quality_audit', 'architecture_review', 'report', 'code', 'data')",
)
```

### L.3 Missing FK indexes on `PlanTaskState`

**File:** `modules/backend/models/mission_plan.py`, lines 249-269

Two FK columns lack indexes:

```python
# Add index=True to these columns:
approved_by_user_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("users.id", ondelete="RESTRICT"),
    nullable=True,
    index=True,  # <-- add
)
task_execution_id: Mapped[str | None] = mapped_column(
    String(36),
    ForeignKey("task_executions.id", ondelete="SET NULL"),
    nullable=True,
    index=True,  # <-- add
)
```

**Migration:**

```python
op.create_index("ix_plan_task_states_approved_by", "plan_task_states", ["approved_by_user_id"])
op.create_index("ix_plan_task_states_task_execution", "plan_task_states", ["task_execution_id"])
```

### L.4 `Mission.owner_id` column width

**File:** `modules/backend/models/mission.py`, line 67

```python
# Before — 200 chars for a UUID
owner_id: Mapped[str] = mapped_column(String(200), ...)

# After — Phase D already changes this to String(36) + FK
# No additional action needed if Phase D is implemented.
```

### L.5 Verification

- [ ] **L.5.1** `Embedding.created_at` returns `datetime` objects, not strings
- [ ] **L.5.2** Inserting a `MissionArtifact` with `artifact_type='invalid'` raises `IntegrityError`
- [ ] **L.5.3** `\di+ ix_plan_task_states_*` shows the two new indexes
- [ ] **L.5.4** All existing tests pass

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
| **G** | `migrations/env.py` | 0 |
| **H** | 8 model files (`execution.py`, `execution_record.py`, `session.py`, `mission.py`, `mission_plan.py`, `workflow_schedule.py`, `llm_call.py`, `model_pricing.py`) | 1 migration |
| **I** | `models/base.py`, + ~10 models with custom DateTime columns | 1 migration |
| **J** | `mission.py`, `execution.py`, `execution_record.py`, `mission_context.py`, `execution_environment.py` | 1 migration |
| **K** | `execution.py`, `mission_context.py` | 1 migration |
| **L** | `embedding.py`, `mission_artifact.py`, `mission_plan.py` | 1 migration |

**Total:** ~40 files modified, 10 migration files created.

---

## 4. Migration Dependency Chain

All migrations chain from the current head:

```
widen_artifact_type
  └── plan64_001_fk_cascades              (Phase A)
        └── plan64_002_composite_indexes  (Phase C)
              └── plan64_003_soft_ref_fks     (Phase D)
                    └── plan64_004_timestamp_types  (Phase E)
                          └── plan64_005_rename_column    (Phase F)
                                └── plan64_006_float_to_numeric  (Phase H)
                                      └── plan64_007_timestamptz       (Phase I)
                                            └── plan64_008_status_lowercase  (Phase J)
                                                  └── plan64_009_additional_fks  (Phase K)
                                                        └── plan64_010_misc_fixes      (Phase L)
```

Phases B and G require no migration (import/model-only changes) and can be done at
any time. Phase G should be done **first** regardless of migration ordering.

---

## 5. Rollback Strategy

Every migration has a `downgrade()` function that reverses the change:
- FK cascades: drop and re-create without `ondelete`
- Indexes: `op.drop_index()`
- FK constraints: `op.drop_constraint()`
- Timestamp conversion: `ALTER COLUMN ... TYPE VARCHAR(30) USING to_char(column, 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`
- Column rename: `op.alter_column(..., new_column_name="mission_ids")`
- Numeric → Float: `op.alter_column(..., type_=sa.Float(), existing_type=sa.Numeric())`
- TIMESTAMPTZ → TIMESTAMP: `ALTER COLUMN ... TYPE TIMESTAMP WITHOUT TIME ZONE`
- Status lowercase → uppercase: reverse the UPDATE mapping
- CHECK constraints: `op.drop_constraint()`

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
- [ ] `alembic check` detects no unexpected drift (verifies Phase G)
- [ ] Cost values are exact: `SELECT total_cost_usd FROM sessions` returns `numeric` type
- [ ] Timestamps are timezone-aware: `SELECT pg_typeof(created_at) FROM missions` returns `timestamptz`
- [ ] Status values are lowercase: `SELECT DISTINCT status FROM missions` returns `active`, `paused`, `archived`
- [ ] No raw SQL queries use uppercase status strings: `rg "'ACTIVE'|'PENDING'|'RUNNING'" modules/backend/`
