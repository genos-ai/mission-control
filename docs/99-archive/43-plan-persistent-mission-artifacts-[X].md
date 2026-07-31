# Plan 43 — Persistent Mission Artifacts

| Field | Value |
|-------|-------|
| **Status** | **Done (2026-04-11)** |
| **Created** | 2026-04-11 |
| **Closed** | 2026-04-11 — commits `2e21874` (design doc), `c42ae8c` (backend phases A–D + verification), `73d5859` (frontend phase E) |
| **Graduated from** | `TODO.md` "Persistent mission artifacts (Plan 43 candidate)" |
| **Depends on** | Plan 15 (Plan Persistence — done), Plan 42 (Mission Backlog Model — done) |
| **Part of** | [Plan 46 — Autonomous Mission Roadmap](../08-plans/046-plan-autonomous-mission-roadmap.md) Phase 2 (Durable output) |
| **Target** | `modules/backend/models/`, `modules/backend/services/`, `modules/backend/agents/mission_control/persistence_bridge.py`, `modules/backend/api/v1/endpoints/`, `modules/frontend/src/hooks/`, `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` |

---

## Close-out note (2026-04-11)

All §5 exit criteria are observably met. `scripts/verify_artifacts_persistence.py`
reports 7/7 checks passing against the real DB, covering direct service insert,
enum validation, content cap, end-to-end `persist_mission_results` extraction with
the full FK chain (mission ⋈ execution_record ⋈ task_execution), list queries, type
filter, and invalid-filter rejection. Frontend typecheck / lint / build all clean.

Landed in three commits (one design doc, one backend chain, one frontend chain):

- `2e21874` — Plan 43 design doc graduated from TODO
- `c42ae8c` — Phases A–D (migration, model, repo, service, schema, extraction
  wiring, API endpoint) + Phase F verification script
- `73d5859` — Phase E frontend ArtifactsPanel rewrite (react-query hook + SSE
  invalidation + Zustand `artifacts` slice removal + empty-state copy update)

What this unlocks: [Plan 46 Phase 2 DoD item 4](../08-plans/046-plan-autonomous-mission-roadmap.md) —
"every run produces artifacts that survive page refresh, session end, and backend
restart" — is now observably satisfied end-to-end. A returning user can open a
mission after an overnight autonomous run and actually see what the agents produced.

Phase 2 continues with work units 2 (per-task cost/duration columns on
`plan_task_states`), 3 (Run History drawer), and 4 (narrative feed reconciliation).

---

## §1 Why this plan exists

Today, artifacts (agent reports, findings, summaries) are a **live-only feature**. The emission path works like this:

1. An agent completes in [`agent_executor.py`](../../modules/backend/agents/mission_control/helpers/agent_executor.py#L178-L195). If the agent's output dict has a `summary` or `result` string field, a `MissionArtifactFoundEvent` is emitted via Redis pubsub with `artifact_type="report"`, title derived from agent name, content capped at 3000 chars.
2. The frontend SSE consumer in [`workspace.ts`](../../modules/frontend/src/stores/workspace.ts#L196-L207) pushes an `ArtifactEntry` onto an in-memory Zustand list capped at 50.
3. The artifacts render in the right-panel `ArtifactsPanel` inside the Chat tab ([`chat-tab.tsx:632`](../../modules/frontend/src/pages/mission/tabs/chat-tab.tsx#L632)).

Problems:

- **Page refresh wipes them.** The in-memory list is per-browser-tab. Open the mission the next day, the artifacts are gone.
- **Backend restart wipes them.** No DB row survives a process boot.
- **Autonomous mode makes this catastrophic.** Plan 42's daemon dispatches runs overnight. By morning, the plan kanban shows "completed" cards but the actual output of those runs has vanished. The user has no way to see what the agents produced.
- **No retrieval API.** There's no way to query "show me all artifacts for this mission" — the only source of truth is the live SSE feed.
- **Sentinel message** already placed in the empty state: *"Post-run artifacts are not yet persisted — see the Runs tab for the full agent output of completed runs."* That's a stopgap, and it points users at `task_executions.output_data` which is raw JSON, not a readable report.

This is **the first user-visible payoff of Plan 46's Phase 2 — Durable output**. A returning user can open a mission in the morning and actually see what happened overnight.

---

## §2 Current state — what exists vs what's broken

### What already exists (we're not recreating this)

| Piece | Where | Notes |
|---|---|---|
| `MissionArtifactFoundEvent` event class | [`events/types.py:347`](../../modules/backend/events/types.py#L347) | Has `mission_id`, `agent_id`, `artifact_type`, `title`, `content`, `content_type`, `language`. We reuse the shape for the persisted model. |
| Event emission site | [`agent_executor.py:178-195`](../../modules/backend/agents/mission_control/helpers/agent_executor.py#L178-L195) | One event per agent task, triggered when output has `summary`/`result` text. **Keep firing for live preview** — adds no cost and the streaming UX needs it. |
| `task_executions.output_data` column | [`services/execution_persistence.py`](../../modules/backend/services/execution_persistence.py) | Already stores the full agent output JSON per task. The artifact *text* is already on disk, just not in a queryable shape. |
| `persist_mission_results` | [`persistence_bridge.py`](../../modules/backend/agents/mission_control/persistence_bridge.py) | Best-effort persistence called after every run. This is the extraction hook point. |
| Frontend `ArtifactsPanel` | [`chat-tab.tsx:632`](../../modules/frontend/src/pages/mission/tabs/chat-tab.tsx#L632) | Reads from `useWorkspaceStore((s) => s.artifacts)`. Already has a "live streaming" path for in-flight previews via `streamingArtifact`. Rewrite to read from the new API + SSE invalidation. |
| `ArtifactEntry` interface | [`workspace.ts:14`](../../modules/frontend/src/stores/workspace.ts#L14) | `{id, agentId, title, content, artifactType, timestamp}`. The persisted model is a superset — the frontend can stop using this Zustand-local shape and use the API response type instead. |

### What doesn't exist (this plan creates it)

- `mission_artifacts` table
- `MissionArtifact` SQLAlchemy model
- `MissionArtifactRepository`
- `MissionArtifactService` (thin — CRUD + list for mission)
- Extraction logic inside `persist_mission_results`
- `GET /api/v1/missions/{mission_id}/artifacts` endpoint
- Frontend `useMissionArtifacts(missionId)` react-query hook
- Verification script

---

## §3 Design

### 3.1 Schema

```sql
CREATE TABLE mission_artifacts (
    id VARCHAR(36) PRIMARY KEY,

    -- Ownership + linkage. mission_id is the primary scope; execution_record_id
    -- and task_execution_id let us drill from a run or a task to its artifacts.
    mission_id VARCHAR(36) NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    execution_record_id VARCHAR(36) REFERENCES execution_records(id) ON DELETE SET NULL,
    task_execution_id VARCHAR(36) REFERENCES task_executions(id) ON DELETE SET NULL,

    -- Who produced it (denormalised for fast filter without a join)
    agent_id VARCHAR(200) NOT NULL DEFAULT '',

    -- Shape
    artifact_type VARCHAR(20) NOT NULL DEFAULT 'report',
        -- CHECK ('report', 'finding', 'code', 'data', 'file')
    title VARCHAR(500) NOT NULL,
    content_type VARCHAR(20) NOT NULL DEFAULT 'markdown',
        -- CHECK ('text', 'markdown', 'json', 'code')
    language VARCHAR(50),  -- For code artifacts

    -- Content. TEXT for v1 text artifacts. storage_url is the v2 extension
    -- point for file artifacts (blob / filesystem / object store decision
    -- deferred until we actually have file artifacts to deal with).
    content_text TEXT,
    storage_url VARCHAR(1000),  -- NULL in v1

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Fast filters
    INDEX idx_mission_artifacts_mission_id (mission_id),
    INDEX idx_mission_artifacts_execution_record_id (execution_record_id),
    INDEX idx_mission_artifacts_task_execution_id (task_execution_id)
);
```

Notes:

- `execution_record_id` and `task_execution_id` are **SET NULL on delete**, not CASCADE. This means: if a task execution is archived/cleaned up, the artifact survives (linked only to the mission), because the artifact is the thing the user cares about. Mission cascade is the only hard delete path.
- `agent_id` is denormalised. Agents are strings today (from `agent_catalog` rows), not a hard FK — matches the existing convention in `plan_task_states.task_id`.
- Content-type enum and artifact-type enum match the existing `MissionArtifactFoundEvent` so the extraction layer is a straight copy.
- No size limit on `content_text` (PostgreSQL TEXT is unlimited). The API applies limits on read, not the DB.
- No uniqueness constraint. The same agent can legitimately produce multiple artifacts from one task (rare but not disallowed), and cross-run deduplication is explicitly out of scope — each run's output is its own artifact, even if the text is identical.
- `storage_url` is the placeholder for future file artifacts. In v1 it's always NULL.

### 3.2 Model

```python
# modules/backend/models/mission_artifact.py

import enum
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from modules.backend.models.base import Base, TimestampMixin, UUIDMixin


class ArtifactType(str, enum.Enum):
    REPORT = "report"
    FINDING = "finding"
    CODE = "code"
    DATA = "data"
    FILE = "file"  # Reserved for v2


class ArtifactContentType(str, enum.Enum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    CODE = "code"


VALID_ARTIFACT_TYPES = frozenset(t.value for t in ArtifactType)
VALID_CONTENT_TYPES = frozenset(t.value for t in ArtifactContentType)


class MissionArtifact(UUIDMixin, TimestampMixin, Base):
    """A durable artifact produced by an agent during a mission run.

    Artifacts live as long as the mission does. When an ExecutionRecord or
    TaskExecution they were linked to is archived/deleted, the link column
    goes NULL but the artifact itself survives — the mission is the owner
    of record.
    """

    __tablename__ = "mission_artifacts"
    __table_args__ = (
        Index("idx_mission_artifacts_mission_id", "mission_id"),
        Index("idx_mission_artifacts_execution_record_id", "execution_record_id"),
        Index("idx_mission_artifacts_task_execution_id", "task_execution_id"),
    )

    mission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("execution_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_execution_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("task_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    agent_id: Mapped[str] = mapped_column(
        String(200), default="", server_default="", nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(20),
        default=ArtifactType.REPORT.value,
        server_default=ArtifactType.REPORT.value,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(20),
        default=ArtifactContentType.MARKDOWN.value,
        server_default=ArtifactContentType.MARKDOWN.value,
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)

    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
```

### 3.3 Extraction logic

The extraction happens inside `persist_mission_results` after the `ExecutionRecord` + `TaskExecution` rows are saved (so we have valid FKs to link). Walk each `task_result`:

```python
# persistence_bridge.py — additions inside persist_mission_results

from modules.backend.services.mission_artifact import MissionArtifactService

# Extract per-task artifacts from the agent output.
artifact_svc = MissionArtifactService(db_session)
for task_result in outcome.task_results:
    output = task_result.output_reference or {}
    # The same heuristic the emission site uses: summary first, then result.
    content: str | None = None
    if isinstance(output.get("summary"), str) and output["summary"].strip():
        content = output["summary"]
    elif isinstance(output.get("result"), str) and output["result"].strip():
        content = output["result"]

    if content:
        await artifact_svc.create_artifact(
            mission_id=mission_id,
            execution_record_id=record.id,
            task_execution_id=execution.id,  # from the TaskExecution save above
            agent_id=task_result.agent_name,
            artifact_type="report",
            title=f"{task_result.agent_name} — result",
            content_text=content,
            content_type="markdown",
        )
```

Swallowed by the outer `try/except (OSError, ValueError, RuntimeError)` in `persist_mission_results` — artifact extraction is best-effort, same as the outer persistence call. A failure to extract an artifact must never block the execution record itself from landing.

### 3.4 API

```python
# modules/backend/api/v1/endpoints/missions_artifacts.py (new file)

@router.get(
    "/{mission_id}/artifacts",
    response_model=ApiResponse,
    summary="List persisted artifacts for a mission",
)
async def list_mission_artifacts(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    limit: int = Query(50, ge=1, le=500),
    artifact_type: str | None = Query(None),
) -> ApiResponse:
    """Return the persisted artifacts for a mission, newest first.

    Pagination is by limit only for v1 — no cursor, because the expected
    volume per mission is small (tens to low hundreds) and the frontend
    pre-caps at 50. Larger missions can increase limit up to 500.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionArtifactService(db)
    artifacts = await service.list_for_mission(
        mission_id=mission_id,
        limit=limit,
        artifact_type=artifact_type,
    )
    return ApiResponse(
        success=True,
        data={
            "mission_id": mission_id,
            "artifacts": [
                MissionArtifactResponse.model_validate(a).model_dump()
                for a in artifacts
            ],
            "count": len(artifacts),
        },
        metadata={"request_id": request_id},
    )
```

Route mounted at `/api/v1/missions/{mission_id}/artifacts` via the v1 router.

### 3.5 Frontend rewrite

New hook `useMissionArtifacts(missionId)` in `modules/frontend/src/hooks/use-mission-artifacts.ts`:

```typescript
export interface MissionArtifactRow {
  id: string
  mission_id: string
  execution_record_id: string | null
  task_execution_id: string | null
  agent_id: string
  artifact_type: string
  title: string
  content_type: string
  language: string | null
  content_text: string | null
  storage_url: string | null
  created_at: string
}

export const artifactKeys = {
  list: (missionId: string) => ['missions', missionId, 'artifacts'] as const,
}

export function useMissionArtifacts(missionId: string | undefined) {
  return useQuery({
    queryKey: artifactKeys.list(missionId!),
    queryFn: async () => {
      const resp = await api.get<{
        mission_id: string
        artifacts: MissionArtifactRow[]
        count: number
      }>(`/missions/${missionId}/artifacts`)
      return resp.artifacts
    },
    enabled: !!missionId,
    staleTime: 30_000,  // 30s — SSE invalidation is the primary refresh path
  })
}
```

`ArtifactsPanel` rewrite in `chat-tab.tsx`:

```typescript
function ArtifactsPanel({ onClose }: { onClose: () => void }) {
  const { id } = useParams<{ id: string }>()
  const { data: artifacts = [] } = useMissionArtifacts(id)
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  // ... render identically, but from `artifacts` instead of the Zustand slice
}
```

SSE invalidation wiring in `MissionLayout` (the outer layout that owns the SSE consumer). Add a new branch:

```typescript
if (ev.event_type === 'mission.artifact.found' && id) {
  queryClient.invalidateQueries({ queryKey: artifactKeys.list(id) })
}
```

Remove from `workspace.ts`:

- The `artifacts: ArtifactEntry[]` slice
- The `mission.artifact.found` handler that pushes onto the list
- The `ArtifactEntry` type itself — API response type replaces it

Keep in `workspace.ts`:

- `streamingArtifact` slice and its `agent.response.chunk` / `agent.response.complete` handlers — that's the live-preview path, unrelated to durable storage.

### 3.6 Dual-write lifecycle

This is the critical interaction between live events and durable state:

```
[ run executes ]
    │
    ├─ per task: agent completes
    │      ├─ emit MissionArtifactFoundEvent (SSE → frontend)
    │      │      └─ frontend: streamingArtifact clears, artifact card appears
    │      │          (reads from live query OR the old ephemeral pathway)
    │      └─ (no DB write yet)
    │
[ run completes ]
    │
    ├─ persist_mission_results() runs
    │      ├─ save ExecutionRecord, TaskExecutions, attempts (existing)
    │      ├─ NEW: extract artifacts from task_results, persist to
    │      │       mission_artifacts table
    │      └─ commit
    │
    └─ done
```

The frontend's react-query invalidation on `mission.artifact.found` refetches the list. On the FIRST emission (before `persist_mission_results` has run), the refetch returns nothing (the row isn't persisted yet). The live-preview path via `streamingArtifact` covers that window. On the FINAL event after persistence lands, the refetch picks up the persisted rows.

This means there's a brief window where an in-flight artifact is visible via `streamingArtifact` but not yet in the query. That's correct — the streaming preview is a real-time UX, the query is the durable truth. When the user refreshes mid-run, the streaming preview vanishes (expected — Redis pubsub is lossy on reconnect) but all prior completed tasks' artifacts are still there via the query. On next page load, completed artifacts persist and streaming restarts from zero.

### 3.7 What we deliberately DO NOT build in v1

| Feature | Why deferred |
|---|---|
| File artifacts (binary, images, large blobs) | No current agent produces them. Storage decision (DB blob / filesystem / object store) is premature — park until a real use case emerges. `storage_url` column is the extension point. |
| Artifact editing / versioning | The current agent emission model is append-only — every run produces its own artifacts. Editing is a UX feature with no clear user story. |
| Full-text search | Postgres tsvector is cheap to add later but not needed for mission-scale lists. Defer. |
| Cross-mission artifact library | No user story. Artifacts are mission-scoped by design. |
| Artifact export (download as file) | `content_text` is already addressable by API; the frontend can offer a "copy" / "save as .md" button in a future pass. Not blocking Phase 2 exit. |
| Rich structured artifacts (findings lists with severity/CVE/evidence) | The current emission site produces text only. Structured findings belong to a future plan that teaches the software.quality agent to emit structured output instead of prose. |
| Artifact-level access control | Mission-level access control already protects the list endpoint. Per-artifact ACL is out of scope. |
| Deduplication across runs | Each run's artifact is legitimately its own. Collapsing duplicates is a UX decision for a future artifact viewer. |

---

## §4 Implementation sequence

Five focused commits, each independently buildable and revertable. Every commit message footer is `Phase 2 — Plan 43 <phase>` for discoverability.

### Phase A — Migration + model

1. Create Alembic migration `plan43_001_mission_artifacts` with the schema from §3.1.
2. Create `modules/backend/models/mission_artifact.py` with `MissionArtifact`, `ArtifactType`, `ArtifactContentType` enums, `VALID_*` frozensets.
3. Register the model in `models/__init__.py` so Alembic auto-detection picks it up.

Exit criterion: `alembic upgrade head` succeeds, creates the table, and the row count is zero. Model imports cleanly from a fresh Python process.

### Phase B — Repository + service

1. Create `modules/backend/repositories/mission_artifact.py` with `MissionArtifactRepository` (BaseRepository subclass). Methods: `create`, `list_for_mission`, `list_for_execution_record`, `list_for_task_execution`, `delete_for_mission` (admin path only).
2. Create `modules/backend/services/mission_artifact.py` with `MissionArtifactService`. Methods: `create_artifact` (validation + insert), `list_for_mission`.
3. Create `modules/backend/schemas/mission_artifact.py` with `MissionArtifactResponse` Pydantic model matching the DB row.

Exit criterion: `conda run -n mission-control python -c "from modules.backend.services.mission_artifact import MissionArtifactService; print('ok')"` clean. Unit-level sanity test (in the verification script below) creates an artifact row via the service and reads it back.

### Phase C — Extraction wiring

1. Modify `persist_mission_results` in `persistence_bridge.py` to iterate `outcome.task_results`, check for `summary`/`result` text, and call `MissionArtifactService.create_artifact` inside the existing try/except. Failure is logged at warning level and does NOT block the execution record.
2. Verify by running a real mission end-to-end (or by feeding a synthetic outcome through the bridge in a test).

Exit criterion: after dispatching a mission with an agent that produces a summary, `SELECT * FROM mission_artifacts WHERE mission_id = '...'` returns the extracted row.

### Phase D — API endpoint

1. Create `modules/backend/api/v1/endpoints/missions_artifacts.py` with the `GET /missions/{id}/artifacts` endpoint from §3.4.
2. Mount under `/api/v1/missions/` (not a new `/artifacts/` prefix — the resource is mission-scoped).
3. Add the artifact_type enum validation (reject invalid types with 422).
4. Wire admin access helper (reuse `_require_mission_access` pattern from `missions_plan.py`).

Exit criterion: `curl -H "Authorization: Bearer ..." http://localhost:8100/api/v1/missions/{id}/artifacts` returns a valid ApiResponse with the expected artifacts list.

### Phase E — Frontend rewrite

1. Create `modules/frontend/src/hooks/use-mission-artifacts.ts` with the `useMissionArtifacts` hook from §3.5.
2. Rewrite `ArtifactsPanel` in `chat-tab.tsx` to read from `useMissionArtifacts(id)` instead of `workspaceStore.artifacts`.
3. Add `mission.artifact.found` invalidation to `MissionLayout` (next to the existing `mission_plan.*` invalidation).
4. Remove `artifacts` + `ArtifactEntry` + the artifact-push handler from `stores/workspace.ts`. Keep `streamingArtifact`.
5. Update the empty state copy in `ArtifactsPanel` — delete the "Post-run artifacts are not yet persisted" sentinel, replace with a generic "No artifacts yet" message.
6. Typecheck + lint + build must stay clean.

Exit criterion: `npm run build` succeeds. A fresh page load against a mission with prior artifacts shows them via the API. Running a new mission produces a live-streaming preview, then a persisted card post-completion.

### Phase F — Verification script

1. Create `scripts/verify_artifacts_persistence.py` that:
   - Finds an existing mission in the DB.
   - Creates an `ExecutionRecord` + `TaskExecution` directly via the service layer (bypasses dispatch loop — that's tested by the Plan 47 isolation verifier separately).
   - Synthesises an `ExecutionOutcome` with a `task_result` containing `output_reference={'summary': 'test artifact content'}`.
   - Calls `persist_mission_results` directly.
   - Reads back via `MissionArtifactService.list_for_mission`, asserts exactly one artifact with the expected content.
   - Cleans up the test rows (delete the artifact + task_execution + execution_record).
2. Runs in conda env, exits 0 on success, prints clear pass/fail summary.

Exit criterion: `conda run -n mission-control python scripts/verify_artifacts_persistence.py` exits 0.

---

## §5 Exit criteria for the whole plan

All of these must be observably true before Plan 43 can be marked Done:

1. `mission_artifacts` table exists with the schema from §3.1 and the migration is idempotent (`alembic downgrade -1 && alembic upgrade head` succeeds).
2. A real mission dispatching a software.quality agent (or any agent that emits a `summary` field) produces exactly one `mission_artifacts` row per task, with non-empty `content_text`.
3. `GET /api/v1/missions/{id}/artifacts` returns the persisted rows for an existing mission, newest-first, respecting the `limit` and `artifact_type` query params.
4. After a backend restart, the row is still there. **This is the Plan 46 Phase 2 DoD item 4** ("every run produces artifacts that survive page refresh, session end, and backend restart").
5. The frontend `ArtifactsPanel` in the Chat tab loads historical artifacts on mount via the API, not from an ephemeral Zustand slice.
6. Live-streaming artifact preview still works during an active run (the `streamingArtifact` slice and its SSE handlers are untouched).
7. The `mission.artifact.found` SSE event triggers a react-query invalidation that refetches the list, so newly-persisted artifacts appear without a page refresh.
8. `workspace.ts` no longer has an `artifacts` slice, `ArtifactEntry` type, or push handler for `mission.artifact.found`. Grep confirms zero references.
9. The "Post-run artifacts are not yet persisted" sentinel text is removed from the empty state.
10. `scripts/verify_artifacts_persistence.py` exits 0 from a clean state and cleans up after itself.
11. Plan 43 is marked "Done" in its own header with the commit range.

---

## §6 What this plan does NOT do

Reiterating for clarity — these are scope cuts, not future work commitments:

- **No file artifacts.** v1 is text-only. `storage_url` is the future extension point.
- **No artifact editing, versioning, or deletion** beyond the mission-level cascade.
- **No artifact search** (full-text or otherwise).
- **No cross-mission artifact library.**
- **No structured-artifact parsing** (severity, CVE, evidence). Content is opaque text.
- **No changes to the emission site** — `agent_executor.py` keeps firing the SSE event exactly as it does today. The persistence pass reads the same `summary`/`result` fields from the same place; we just store the result instead of throwing it away.
- **No changes to Plan 42 plan task state** (`plan_task_states.cost_usd` / `duration_seconds` is **Phase 2 work unit #2**, a separate plan-46 item).
- **No changes to the Run History drawer** (Phase 2 work unit #3, separate).
- **No narrative feed reconciliation** (Phase 2 work unit #4, separate).

---

## §7 References

### Plan docs

- [Plan 46 — Autonomous Mission Roadmap](../08-plans/046-plan-autonomous-mission-roadmap.md) §4 Phase 2 — the parent phase this plan graduates under.
- [Plan 42 — Mission Backlog Model](042-plan-mission-backlog-model-[SUPERSEDED].md) — the ownership / cascade semantics (CASCADE on mission delete, SET NULL on execution/task_execution delete) mirror this plan's linkage pattern.
- [Plan 15 — Plan Persistence](15-plan-plan-persistence-[X].md) (done) — `ExecutionRecord` + `TaskExecution` tables we FK against.

### Files touched

Backend (new):
- `modules/backend/migrations/versions/plan43_001_mission_artifacts.py`
- `modules/backend/models/mission_artifact.py`
- `modules/backend/repositories/mission_artifact.py`
- `modules/backend/services/mission_artifact.py`
- `modules/backend/schemas/mission_artifact.py`
- `modules/backend/api/v1/endpoints/missions_artifacts.py`

Backend (modified):
- `modules/backend/agents/mission_control/persistence_bridge.py` — extraction pass
- `modules/backend/api/v1/__init__.py` — mount the new endpoint
- `modules/backend/models/__init__.py` — register the new model

Frontend (new):
- `modules/frontend/src/hooks/use-mission-artifacts.ts`

Frontend (modified):
- `modules/frontend/src/pages/mission/tabs/chat-tab.tsx` — rewrite `ArtifactsPanel`
- `modules/frontend/src/pages/mission/layout.tsx` — add SSE invalidation branch
- `modules/frontend/src/stores/workspace.ts` — remove `artifacts` slice

Verification:
- `scripts/verify_artifacts_persistence.py`

### Graduation source

- `TODO.md` "Persistent mission artifacts (Plan 43 candidate)" — graduated to this plan doc on 2026-04-11.
