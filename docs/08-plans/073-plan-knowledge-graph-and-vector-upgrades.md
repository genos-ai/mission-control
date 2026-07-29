# Plan 73 — Knowledge Graph & Vector Search Upgrades

**Version:** 2.0
**Date:** 2026-05-12 (v2 revised 2026-05-12)
**Author:** Claude Opus 4.6
**Status:** Ready to implement
**Depends on:** Plan 57 (Knowledge Platform foundation — embeddings table, pgvector, learnings)
**Relates to:** Research doc `docs/98-research/000-steenberg_principles.md`

---

## 0. Problem Statement

Mission Control has several **implicit graph structures** scattered across JSON columns, self-referential FKs, and Python BFS code. These work at single-mission scale but will not scale to cross-mission queries or platform-level intelligence:

| Graph structure | Current storage | Current traversal |
|---|---|---|
| Task dependency DAGs | `mission_plans.task_plan_json` (JSON blob) | Python BFS in `mission_plan.py:552-623` |
| Execution re-plan chains | `execution_records.parent_execution_record_id` (self-FK) | Manual FK walks |
| Intent revision chains | `mission_intents.revised_from` (self-FK) | `ORDER BY created_at DESC LIMIT 1` |
| Learning contradictions | `mission_learnings.contradicts_id` (self-FK) | Single-hop lookup |
| Code reference graphs | In-memory `ReferenceGraph` | Python iteration in `code_map/graph.py` |
| Workflow step deps | `workflow_definitions.steps[].depends_on` (JSON) | JSON parsing |

Additionally, the **vector search layer** uses pgvector HNSW, which has a known issue with filtered queries silently returning too few results. Azure PG Flexible Server now offers `pg_diskann` (GA) which fixes this with Advanced Filtering.

**Consequences of inaction:**
- Cross-mission impact analysis requires loading all missions into Python and doing O(N*M) traversals
- `_transitive_dependencies()` and `_transitive_dependents()` make N round-trips (one per depth level) when called from async contexts
- Filtered vector search (the `hybrid_search` path) may miss relevant results due to HNSW recall degradation under filters
- No path to "which missions are affected if agent X changes?" without full table scans

### Why not Apache AGE?

The v1 draft of this plan proposed Apache AGE as a PoC graph layer. Research revealed significant risks:

1. **Project health** — Bitnine/AGEDB dismissed their entire AGE development team in October 2024. The project now runs on reduced volunteer Apache PMC resources with slow release cadence and PR approval delays.
2. **Upgrade blocker** — AGE blocks Azure's in-place major-version upgrade feature (dump/restore required).
3. **Data duplication** — AGE stores graph data in separate vertex/edge tables, requiring a sync layer to keep relational and graph data consistent.
4. **Python driver fragility** — The official driver has a dependency conflict with Python 3.13+ (`antlr4-python3-runtime==4.11.1`). The asyncpg driver is a recent, lightly-tested PR.
5. **SQL/PGQ is coming** — SQL Property Graph Queries (ISO SQL:2023) was **committed to PostgreSQL 19** on 2026-03-16. PG 19 GA targets September 2026. SQL/PGQ provides native graph pattern matching over existing relational tables — zero duplication, zero extensions, zero sync code.

**Decision:** Skip AGE entirely. Use raw SQL (recursive functions + views) for graph queries today. Design the schema for SQL/PGQ adoption when PG 19 ships on Azure (~Q1 2027).

---

## 1. Scope

### In scope

- **Phase A:** Upgrade embeddings index from HNSW to DiskANN (`pg_diskann`)
- **Phase B:** SQL views and recursive functions for DB-level graph traversal
- **Phase C:** Raw-SQL graph query service and agent tools (using Phase B infrastructure)
- **Phase D:** SQL/PGQ forward design — DDL blueprint ready for PG 19 adoption

### Out of scope

- Apache AGE (project health risks, upgrade blocker — see §0)
- Neo4j sidecar (not justified at current scale — see research doc Q4)
- Microsoft GraphRAG integration (offline indexer; revisit when 100+ missions exist)
- Frontend graph visualisation (future plan)

---

## 2. Current State

### Vector search

The `embeddings` table (`modules/backend/models/embedding.py`) stores `vector(1536)` data with a post-backfill HNSW index:

```sql
CREATE INDEX ix_embeddings_hnsw ON embeddings
  USING hnsw (embedding_data vector_cosine_ops);
```

All vector queries use raw SQL with the `<=>` cosine distance operator (`modules/backend/repositories/embedding.py:155-162`). The `hybrid_search` method (line 175-232) builds per-row `OR` conditions for the structured filter, then reranks by vector distance. This pattern does **not** benefit from HNSW's graph traversal and forces a sequential scan over the filtered subset.

### Transitive dependency computation

Two static methods in `modules/backend/services/mission_plan.py`:

- `_transitive_dependencies(task_plan, task_id)` (line 552-587): DFS backward through `task.dependencies`, returns deps in topological order. Used by `approve_task()` to auto-approve prerequisites.
- `_transitive_dependents(task_plan, task_id)` (line 589-623): BFS forward through reverse adjacency, returns all downstream tasks. Used by `reject_task()` to cascade cancellation.

Both operate on an in-memory `TaskPlan` Pydantic model deserialised from `mission_plans.task_plan_json`. They do **not** query the database — the plan JSON is loaded first, then traversed in Python.

### DAG dispatch

`modules/backend/agents/mission_control/dispatch/dag.py` provides:
- `topological_sort(plan)` — Kahn's algorithm, returns execution layers
- `resolve_upstream_inputs(task, completed_outputs)` — resolves `from_upstream` references

Both are pure functions with no DB access.

---

## 3. Design

### Phase A: DiskANN index upgrade

Replace the HNSW index on `embeddings.embedding_data` with a DiskANN index for better filtered-query recall.

#### 3A.1 Migration

File: `modules/backend/migrations/versions/2026xxxx_plan73a_diskann_index.py`

```python
"""Plan 73A: Replace HNSW with DiskANN on embeddings table.

pg_diskann provides Advanced Filtering that combines filter predicates
and graph traversal in one operation, fixing HNSW's known recall
degradation on filtered queries.

Requires: Azure Database for PostgreSQL Flexible Server with pg_diskann
extension enabled. Falls back to HNSW on non-Azure or unsupported
environments.
"""

import sqlalchemy as sa
from alembic import op

revision = "2026xxxx_plan73a"
down_revision = "<current_head>"  # fill at creation time
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Check if pg_diskann is available
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_available_extensions "
            "WHERE name = 'pg_diskann'"
        )
    )
    has_diskann = result.scalar() is not None

    if has_diskann:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_diskann")
        # Drop existing HNSW index (may or may not exist)
        op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")
        # Create DiskANN index with cosine ops
        op.execute(
            "CREATE INDEX ix_embeddings_diskann ON embeddings "
            "USING diskann (embedding_data vector_cosine_ops)"
        )
    else:
        # Non-Azure: keep HNSW, log warning
        print(
            "WARNING: pg_diskann not available. "
            "Keeping existing HNSW index. "
            "DiskANN is Azure PG Flex only."
        )


def downgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_available_extensions "
            "WHERE name = 'pg_diskann'"
        )
    )
    has_diskann = result.scalar() is not None

    if has_diskann:
        op.execute("DROP INDEX IF EXISTS ix_embeddings_diskann")
        # Restore HNSW
        op.execute(
            "CREATE INDEX ix_embeddings_hnsw ON embeddings "
            "USING hnsw (embedding_data vector_cosine_ops)"
        )
```

#### 3A.2 Repository changes

No changes needed to `modules/backend/repositories/embedding.py`. The `<=>` cosine distance operator works identically with both HNSW and DiskANN indexes. The query planner automatically uses the DiskANN index when available.

#### 3A.3 Verification

After migration, run on the target database:

```sql
-- Confirm DiskANN index exists
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'embeddings' AND indexdef LIKE '%diskann%';

-- Verify query uses DiskANN index
EXPLAIN (ANALYZE, BUFFERS)
SELECT source_table, source_id,
       embedding_data <=> CAST('[0.1,0.2,...]' AS vector) AS distance
FROM embeddings
WHERE mission_id = '<some_mission_id>'
ORDER BY embedding_data <=> CAST('[0.1,0.2,...]' AS vector)
LIMIT 20;
-- Should show "Index Scan using ix_embeddings_diskann"
```

---

### Phase B: SQL views and recursive functions for graph traversal

Create database views that extract graph edges from JSON, and SQL functions that compute transitive closure. These enable DB-level queries that join traversal results with other tables without round-tripping to Python.

**Important:** The existing Python methods in `mission_plan.py` operate on in-memory `TaskPlan` objects and will **not** be removed. The SQL layer serves a different purpose — DB-level joins for cross-mission analytics.

#### 3B.1 Migration

File: `modules/backend/migrations/versions/2026xxxx_plan73b_dependency_functions.py`

```python
"""Plan 73B: SQL views and functions for graph traversal.

Creates views that extract graph edges from JSON columns, plus
SQL functions for transitive closure computation. These complement
(do not replace) the Python BFS in mission_plan.py.

The views and functions are designed to map cleanly onto SQL/PGQ
CREATE PROPERTY GRAPH when PostgreSQL 19 ships (see Phase D).
"""

from alembic import op

revision = "2026xxxx_plan73b"
down_revision = "2026xxxx_plan73a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── View 1: Task dependency edges ──
    # Extracts (plan_id, task_id, dependency_id) from JSON.
    # COALESCE guards against tasks where 'dependencies' key is missing or null.
    op.execute("""
        CREATE OR REPLACE VIEW v_task_dependencies AS
        SELECT
            mp.id              AS plan_id,
            mp.mission_id      AS mission_id,
            t.value->>'task_id' AS task_id,
            d.value #>> '{}'   AS dependency_id
        FROM mission_plans mp,
             jsonb_array_elements(mp.task_plan_json->'tasks') AS t(value),
             jsonb_array_elements(
                 COALESCE(t.value->'dependencies', '[]'::jsonb)
             ) AS d(value)
        WHERE mp.task_plan_json IS NOT NULL
          AND jsonb_typeof(mp.task_plan_json->'tasks') = 'array'
    """)

    # ── View 2: All tasks (including those with no dependencies) ──
    op.execute("""
        CREATE OR REPLACE VIEW v_plan_tasks AS
        SELECT
            mp.id               AS plan_id,
            mp.mission_id       AS mission_id,
            t.value->>'task_id'  AS task_id,
            t.value->>'agent'    AS agent_name,
            t.value->>'title'    AS title
        FROM mission_plans mp,
             jsonb_array_elements(mp.task_plan_json->'tasks') AS t(value)
        WHERE mp.task_plan_json IS NOT NULL
          AND jsonb_typeof(mp.task_plan_json->'tasks') = 'array'
    """)

    # ── View 3: Execution re-plan edges ──
    op.execute("""
        CREATE OR REPLACE VIEW v_execution_edges AS
        SELECT
            id                          AS execution_id,
            mission_id,
            parent_execution_record_id  AS parent_id
        FROM execution_records
        WHERE parent_execution_record_id IS NOT NULL
    """)

    # ── View 4: Learning contradiction edges ──
    op.execute("""
        CREATE OR REPLACE VIEW v_learning_edges AS
        SELECT
            id              AS learning_id,
            mission_id,
            contradicts_id
        FROM mission_learnings
        WHERE contradicts_id IS NOT NULL
          AND status = 'ACTIVE'
    """)

    # ── View 5: Intent revision edges ──
    op.execute("""
        CREATE OR REPLACE VIEW v_intent_edges AS
        SELECT
            id            AS intent_id,
            mission_id,
            revised_from
        FROM mission_intents
        WHERE revised_from IS NOT NULL
    """)

    # ── Function: Transitive dependencies (all ancestors of a task) ──
    # Uses a function (not a view) so plan_id/task_id predicates are pushed
    # inside the recursive CTE anchor. Recursive CTEs in views are always
    # materialised in full before outer WHERE is applied.
    op.execute("""
        CREATE OR REPLACE FUNCTION transitive_dependencies(
            p_plan_id UUID,
            p_task_id TEXT
        )
        RETURNS TABLE(ancestor_id TEXT, depth INT, path TEXT[])
        LANGUAGE sql STABLE AS $$
            WITH RECURSIVE deps(ancestor_id, depth, path) AS (
                SELECT
                    dependency_id AS ancestor_id,
                    1             AS depth,
                    ARRAY[p_task_id, dependency_id] AS path
                FROM v_task_dependencies
                WHERE plan_id = p_plan_id
                  AND task_id = p_task_id

                UNION ALL

                SELECT
                    td.dependency_id AS ancestor_id,
                    d.depth + 1,
                    d.path || td.dependency_id
                FROM deps d
                JOIN v_task_dependencies td
                  ON td.plan_id = p_plan_id
                 AND td.task_id = d.ancestor_id
                WHERE td.dependency_id <> ALL(d.path)  -- cycle guard
                  AND d.depth < 20                      -- depth guard
            )
            SELECT ancestor_id, depth, path FROM deps
        $$
    """)

    # ── Function: Transitive dependents (all descendants of a task) ──
    op.execute("""
        CREATE OR REPLACE FUNCTION transitive_dependents(
            p_plan_id UUID,
            p_task_id TEXT
        )
        RETURNS TABLE(descendant_id TEXT, depth INT, path TEXT[])
        LANGUAGE sql STABLE AS $$
            WITH RECURSIVE deps(descendant_id, depth, path) AS (
                SELECT
                    task_id       AS descendant_id,
                    1             AS depth,
                    ARRAY[p_task_id, task_id] AS path
                FROM v_task_dependencies
                WHERE plan_id = p_plan_id
                  AND dependency_id = p_task_id

                UNION ALL

                SELECT
                    td.task_id AS descendant_id,
                    d.depth + 1,
                    d.path || td.task_id
                FROM deps d
                JOIN v_task_dependencies td
                  ON td.plan_id = p_plan_id
                 AND td.dependency_id = d.descendant_id
                WHERE td.task_id <> ALL(d.path)  -- cycle guard
                  AND d.depth < 20               -- depth guard
            )
            SELECT descendant_id, depth, path FROM deps
        $$
    """)

    # ── Function: Execution lineage (re-plan chain) ──
    op.execute("""
        CREATE OR REPLACE FUNCTION execution_lineage(
            p_execution_id UUID
        )
        RETURNS TABLE(ancestor_id UUID, depth INT)
        LANGUAGE sql STABLE AS $$
            WITH RECURSIVE chain(ancestor_id, depth, seen) AS (
                SELECT
                    parent_id    AS ancestor_id,
                    1            AS depth,
                    ARRAY[execution_id, parent_id] AS seen
                FROM v_execution_edges
                WHERE execution_id = p_execution_id

                UNION ALL

                SELECT
                    e.parent_id  AS ancestor_id,
                    c.depth + 1,
                    c.seen || e.parent_id
                FROM chain c
                JOIN v_execution_edges e
                  ON e.execution_id = c.ancestor_id
                WHERE e.parent_id <> ALL(c.seen)
                  AND c.depth < 50
            )
            SELECT ancestor_id, depth FROM chain
        $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS execution_lineage(UUID)")
    op.execute("DROP FUNCTION IF EXISTS transitive_dependents(UUID, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS transitive_dependencies(UUID, TEXT)")
    op.execute("DROP VIEW IF EXISTS v_intent_edges")
    op.execute("DROP VIEW IF EXISTS v_learning_edges")
    op.execute("DROP VIEW IF EXISTS v_execution_edges")
    op.execute("DROP VIEW IF EXISTS v_plan_tasks")
    op.execute("DROP VIEW IF EXISTS v_task_dependencies")
```

#### 3B.2 Repository methods

Add to `modules/backend/repositories/mission_plan.py`:

```python
async def transitive_dependencies_sql(
    self,
    plan_id: str,
    task_id: str,
) -> list[str]:
    """Return all ancestor task_ids using the SQL recursive function.

    Complements the Python _transitive_dependencies() for cases where
    we need DB-level joins (e.g. cross-mission impact queries).
    Predicates are pushed inside the CTE anchor for efficiency.
    """
    result = await self.session.execute(
        text(
            "SELECT ancestor_id "
            "FROM transitive_dependencies(:plan_id::uuid, :task_id) "
            "ORDER BY depth DESC"
        ).bindparams(plan_id=plan_id, task_id=task_id)
    )
    return [row[0] for row in result.fetchall()]


async def transitive_dependents_sql(
    self,
    plan_id: str,
    task_id: str,
) -> list[str]:
    """Return all descendant task_ids using the SQL recursive function."""
    result = await self.session.execute(
        text(
            "SELECT descendant_id "
            "FROM transitive_dependents(:plan_id::uuid, :task_id) "
            "ORDER BY depth ASC"
        ).bindparams(plan_id=plan_id, task_id=task_id)
    )
    return [row[0] for row in result.fetchall()]


async def agent_impact_across_missions(
    self,
    agent_name: str,
) -> list[dict]:
    """Find all tasks and their dependents across all missions for a given agent.

    Returns a list of dicts with mission_id, task_id, dependent_count.
    Useful for answering "what breaks if agent X is disabled?"
    """
    result = await self.session.execute(
        text(
            "SELECT vt.mission_id, vt.task_id, "
            "  (SELECT COUNT(*) "
            "   FROM transitive_dependents(vt.plan_id, vt.task_id) "
            "  ) AS dependent_count "
            "FROM v_plan_tasks vt "
            "WHERE vt.agent_name = :agent_name "
            "ORDER BY dependent_count DESC"
        ).bindparams(agent_name=agent_name)
    )
    return [
        {
            "mission_id": row[0],
            "task_id": row[1],
            "dependent_count": row[2],
        }
        for row in result.fetchall()
    ]
```

Add `from sqlalchemy import text` to the imports if not already present.

---

### Phase C: Graph query service and agent tools

Expose the Phase B SQL infrastructure through a service layer and as agent tools. All queries use standard SQL via asyncpg — zero extensions, zero extra dependencies.

#### 3C.1 Graph query service

File: `modules/backend/services/graph_query.py` (NEW)

```python
"""Graph query service — raw-SQL graph traversal for agents and API.

Uses the views and functions from Phase B (v_task_dependencies,
v_execution_edges, v_learning_edges, transitive_dependencies/dependents,
execution_lineage) to answer graph questions.

All queries use standard SQL via asyncpg — no extensions required.
Designed so that each method maps directly onto a SQL/PGQ GRAPH_TABLE
query when PostgreSQL 19 ships (see Phase D design doc).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class GraphQueryService:
    """Read-only graph traversal queries using raw SQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def task_dependency_chain(
        self,
        plan_id: str,
        task_id: str,
        direction: str = "upstream",
    ) -> list[dict]:
        """Get the full dependency chain for a task.

        Args:
            plan_id: Mission plan ID.
            task_id: Task ID within the plan.
            direction: "upstream" (ancestors) or "downstream" (dependents).

        Returns:
            List of dicts with task_id, depth, path.
        """
        if direction == "upstream":
            fn = "transitive_dependencies"
            id_col = "ancestor_id"
        else:
            fn = "transitive_dependents"
            id_col = "descendant_id"

        result = await self._session.execute(
            text(
                f"SELECT td.{id_col}, td.depth, "
                f"  vt.agent_name, vt.title "
                f"FROM {fn}(:plan_id::uuid, :task_id) td "
                f"LEFT JOIN v_plan_tasks vt "
                f"  ON vt.plan_id = :plan_id::uuid "
                f"  AND vt.task_id = td.{id_col} "
                f"ORDER BY td.depth"
            ).bindparams(plan_id=plan_id, task_id=task_id)
        )
        return [
            {
                "task_id": row[0],
                "depth": row[1],
                "agent": row[2],
                "title": row[3],
            }
            for row in result.fetchall()
        ]

    async def agent_impact(self, agent_name: str) -> list[dict]:
        """Find all missions and tasks that use a given agent.

        Returns list of dicts with mission_id, task_id, dependent_count.
        """
        result = await self._session.execute(
            text(
                "SELECT vt.mission_id, vt.task_id, "
                "  (SELECT COUNT(*) "
                "   FROM transitive_dependents(vt.plan_id, vt.task_id) "
                "  ) AS dependent_count "
                "FROM v_plan_tasks vt "
                "WHERE vt.agent_name = :agent_name "
                "ORDER BY dependent_count DESC"
            ).bindparams(agent_name=agent_name)
        )
        return [
            {
                "mission_id": row[0],
                "task_id": row[1],
                "dependent_count": row[2],
            }
            for row in result.fetchall()
        ]

    async def execution_lineage(self, execution_id: str) -> list[dict]:
        """Trace the re-plan chain for an execution record."""
        result = await self._session.execute(
            text(
                "SELECT ancestor_id, depth "
                "FROM execution_lineage(:eid::uuid) "
                "ORDER BY depth"
            ).bindparams(eid=execution_id)
        )
        return [
            {"execution_id": str(row[0]), "depth": row[1]}
            for row in result.fetchall()
        ]

    async def learning_contradictions(self, mission_id: str) -> list[dict]:
        """Get all active contradiction pairs for a mission."""
        result = await self._session.execute(
            text(
                "SELECT learning_id, contradicts_id "
                "FROM v_learning_edges "
                "WHERE mission_id = :mid"
            ).bindparams(mid=mission_id)
        )
        return [
            {"learning_id": str(row[0]), "contradicts_id": str(row[1])}
            for row in result.fetchall()
        ]

    async def intent_revision_chain(self, mission_id: str) -> list[dict]:
        """Get the intent revision history for a mission."""
        result = await self._session.execute(
            text(
                "SELECT intent_id, revised_from "
                "FROM v_intent_edges "
                "WHERE mission_id = :mid"
            ).bindparams(mid=mission_id)
        )
        return [
            {"intent_id": str(row[0]), "revised_from": str(row[1])}
            for row in result.fetchall()
        ]
```

#### 3C.2 Agent tools

Add to the Mission Director's tool set. File to modify: the appropriate tool registration file for the mission director agent.

```python
from modules.backend.services.graph_query import GraphQueryService


@agent.tool
async def query_dependency_chain(
    ctx: RunContext[MissionDirectorDeps],
    task_id: str,
    direction: str = "upstream",
) -> dict:
    """Traverse the task dependency graph.

    Use this to understand what a task depends on (upstream) or what
    depends on it (downstream). Useful for impact analysis before
    modifying or removing tasks.

    Args:
        task_id: The task identifier within the current plan.
        direction: "upstream" or "downstream".

    Returns:
        Dict with chain of related tasks and their properties.
    """
    service = GraphQueryService(ctx.deps.db_session)
    # Resolve plan_id from mission
    from modules.backend.repositories.mission_plan import MissionPlanRepository
    repo = MissionPlanRepository(ctx.deps.db_session)
    plan = await repo.get_by_mission_id(ctx.deps.mission_id)
    if not plan:
        return {"error": "No plan found for this mission"}
    chain = await service.task_dependency_chain(
        str(plan.id), task_id, direction=direction,
    )
    return {"direction": direction, "task_id": task_id, "chain": chain}


@agent.tool
async def query_agent_impact(
    ctx: RunContext[MissionDirectorDeps],
    agent_name: str,
) -> dict:
    """Find all missions and tasks that use a given agent.

    Use this before disabling or modifying an agent to understand
    the blast radius across the platform.

    Args:
        agent_name: The agent identifier (e.g. "security.scanner").

    Returns:
        Dict with list of affected missions and task counts.
    """
    service = GraphQueryService(ctx.deps.db_session)
    impact = await service.agent_impact(agent_name)
    return {"agent_name": agent_name, "impact": impact}


@agent.tool
async def query_execution_lineage(
    ctx: RunContext[MissionDirectorDeps],
    execution_id: str,
) -> dict:
    """Trace the re-plan chain for an execution.

    Use this to understand how many times a mission objective was
    re-planned and what the chain of attempts looks like.

    Args:
        execution_id: The execution record ID to trace.

    Returns:
        Dict with the chain of parent executions.
    """
    service = GraphQueryService(ctx.deps.db_session)
    lineage = await service.execution_lineage(execution_id)
    return {"execution_id": execution_id, "lineage": lineage}
```

---

### Phase D: SQL/PGQ forward design (PostgreSQL 19)

SQL/PGQ (ISO SQL:2023) was committed to PostgreSQL 19 on 2026-03-16. PG 19 GA targets **September 2026**. Azure PG Flex typically ships new major versions ~3-6 months after GA.

This section documents the `CREATE PROPERTY GRAPH` DDL that will replace the Phase B views and functions when PG 19 is available. **No code is written for Phase D now** — it is a design reference for the future migration.

#### 3D.1 Property graph definition

SQL/PGQ defines graphs over **existing relational tables** — zero data duplication.

```sql
-- This DDL will be created when PG 19 is available on Azure PG Flex.
-- It replaces v_task_dependencies, v_execution_edges, v_learning_edges,
-- v_intent_edges, and the transitive_dependencies/dependents functions.

CREATE PROPERTY GRAPH mission_graph

  VERTEX TABLES (
    missions
      LABEL Mission
      PROPERTIES (id, name, status),

    agent_catalog
      LABEL Agent
      PROPERTIES (agent_name, agent_type, enabled),

    -- Tasks extracted from JSON via the v_plan_tasks view
    v_plan_tasks
      LABEL Task
      PROPERTIES (plan_id, mission_id, task_id, agent_name, title),

    execution_records
      LABEL Execution
      PROPERTIES (id, mission_id, status, total_cost_usd),

    mission_learnings
      LABEL Learning
      PROPERTIES (id, mission_id, kind, title, status, confidence),

    mission_intents
      LABEL Intent
      PROPERTIES (id, mission_id, intent_summary, source)
  )

  EDGE TABLES (
    -- Task dependency edges (from v_task_dependencies view)
    v_task_dependencies
      SOURCE KEY (plan_id, task_id)     REFERENCES v_plan_tasks (plan_id, task_id)
      DESTINATION KEY (plan_id, dependency_id) REFERENCES v_plan_tasks (plan_id, task_id)
      LABEL DEPENDS_ON,

    -- Task → Agent assignment (from v_plan_tasks, self-join)
    v_plan_tasks AS task_agent_edges
      SOURCE KEY (plan_id, task_id)     REFERENCES v_plan_tasks (plan_id, task_id)
      DESTINATION KEY (agent_name)      REFERENCES agent_catalog (agent_name)
      LABEL EXECUTED_BY,

    -- Task → Mission membership
    v_plan_tasks AS task_mission_edges
      SOURCE KEY (plan_id, task_id)     REFERENCES v_plan_tasks (plan_id, task_id)
      DESTINATION KEY (mission_id)      REFERENCES missions (id)
      LABEL BELONGS_TO,

    -- Execution re-plan chain
    v_execution_edges
      SOURCE KEY (execution_id)         REFERENCES execution_records (id)
      DESTINATION KEY (parent_id)       REFERENCES execution_records (id)
      LABEL RE_PLANNED_FROM,

    -- Learning contradictions
    v_learning_edges
      SOURCE KEY (learning_id)          REFERENCES mission_learnings (id)
      DESTINATION KEY (contradicts_id)  REFERENCES mission_learnings (id)
      LABEL CONTRADICTS,

    -- Intent revision chain
    v_intent_edges
      SOURCE KEY (intent_id)            REFERENCES mission_intents (id)
      DESTINATION KEY (revised_from)    REFERENCES mission_intents (id)
      LABEL REVISED_FROM
  );
```

#### 3D.2 Example SQL/PGQ queries

These show what the Phase C `GraphQueryService` methods will look like after migration to SQL/PGQ:

```sql
-- Task dependency chain (replaces transitive_dependencies function)
SELECT * FROM GRAPH_TABLE (mission_graph
  MATCH (t IS Task WHERE t.task_id = 'task_0' AND t.plan_id = $1)
    -[d IS DEPENDS_ON *1..20]-> (ancestor IS Task)
  COLUMNS (ancestor.task_id, ancestor.agent_name, ancestor.title)
);

-- Agent impact analysis (replaces agent_impact_across_missions)
SELECT * FROM GRAPH_TABLE (mission_graph
  MATCH (a IS Agent WHERE a.agent_name = $1)
    <-[e IS EXECUTED_BY]- (t IS Task)
    -[b IS BELONGS_TO]-> (m IS Mission)
  COLUMNS (m.name AS mission_name, t.task_id, t.title)
);

-- Mixed-edge-type traversal (impossible with recursive CTEs)
-- "Find all learnings related to tasks that depend on a failing task"
SELECT * FROM GRAPH_TABLE (mission_graph
  MATCH (t IS Task WHERE t.task_id = $1)
    <-[d IS DEPENDS_ON *1..5]- (downstream IS Task)
    -[b IS BELONGS_TO]-> (m IS Mission)
    <-[bl IS BELONGS_TO]- (l IS Learning)
  COLUMNS (l.title AS learning, l.kind, downstream.task_id)
);

-- Execution lineage (replaces execution_lineage function)
SELECT * FROM GRAPH_TABLE (mission_graph
  MATCH (e IS Execution WHERE e.id = $1)
    -[r IS RE_PLANNED_FROM *1..50]-> (ancestor IS Execution)
  COLUMNS (ancestor.id AS ancestor_id, ancestor.status)
);
```

#### 3D.3 Migration plan (future — do not implement now)

When PG 19 ships on Azure PG Flex:

1. Upgrade PG instance to PG 19
2. Run migration: `CREATE PROPERTY GRAPH mission_graph ...` (DDL from §3D.1)
3. Rewrite `GraphQueryService` methods to use `GRAPH_TABLE` queries (§3D.2)
4. Drop the recursive functions (`transitive_dependencies`, `transitive_dependents`, `execution_lineage`) — SQL/PGQ replaces them
5. Keep the edge views (`v_task_dependencies`, `v_execution_edges`, etc.) — SQL/PGQ EDGE TABLES reference them
6. Keep Python BFS in `mission_plan.py` — still the hot path for in-memory dispatch

#### 3D.4 Why the Phase B views are SQL/PGQ-ready

The Phase B edge views (`v_task_dependencies`, `v_execution_edges`, `v_learning_edges`, `v_intent_edges`) are deliberately shaped as `(source_id, destination_id)` pairs — exactly the format SQL/PGQ `EDGE TABLES` expects. This means:

- **Zero schema changes** to the edge views when adopting SQL/PGQ
- The `CREATE PROPERTY GRAPH` DDL references the views directly
- The vertex tables are existing relational tables — also zero changes
- The only new code is the `GRAPH_TABLE` queries in `GraphQueryService`

---

## 4. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| pg_diskann not available in target Azure region | Phase A blocked; HNSW continues working | Migration detects availability and skips gracefully; no functional regression |
| JSON view extraction slow on large `task_plan_json` | Phase B functions degrade on plans with 100+ tasks | SQL functions push plan_id predicate into CTE anchor; add `LIMIT` in consuming queries |
| Corrupted plan JSON with missing `dependencies` key | `v_task_dependencies` view errors | `COALESCE(t.value->'dependencies', '[]'::jsonb)` guard in view definition |
| PG 19 delayed past September 2026 | Phase D postponed | Phase B+C provide full graph query capability without SQL/PGQ; no blocking dependency |
| Azure PG Flex ships PG 19 late (~Q1-Q2 2027) | Phase D further postponed | Same — Phase B+C are the production path; Phase D is an optimization |
| SQL/PGQ syntax changes before PG 19 GA | Phase D DDL needs updating | DDL in §3D.1 is a design reference, not committed code; update when PG 19 beta is testable |

---

## 5. Verification Checklist

### Phase A
- [ ] Migration runs cleanly on PG with pg_diskann
- [ ] Migration skips gracefully on PG without pg_diskann
- [ ] `EXPLAIN` on `semantic_search` shows DiskANN index scan
- [ ] `hybrid_search` returns same or better recall vs HNSW (compare top-20 result sets on test corpus)
- [ ] All existing embedding tests pass unchanged

### Phase B
- [ ] `v_task_dependencies` returns correct rows for a known plan
- [ ] `v_task_dependencies` returns zero rows for tasks with missing or null `dependencies` key (COALESCE guard)
- [ ] `v_execution_edges` returns correct parent chains
- [ ] `v_learning_edges` returns active contradiction pairs only
- [ ] `v_intent_edges` returns revision links
- [ ] `transitive_dependencies(plan_id, task_id)` matches Python `_transitive_dependencies()` output for same inputs
- [ ] `transitive_dependents(plan_id, task_id)` matches Python `_transitive_dependents()` output for same inputs
- [ ] `execution_lineage(execution_id)` returns correct re-plan chain
- [ ] Cycle guard prevents infinite recursion on circular dependencies (edge case: corrupted plan JSON)
- [ ] `agent_impact_across_missions` returns correct counts
- [ ] Downgrade drops all functions and views cleanly

### Phase C
- [ ] `GraphQueryService.task_dependency_chain()` returns correct chain with agent/title metadata
- [ ] `GraphQueryService.agent_impact()` returns mission/task counts matching manual verification
- [ ] `GraphQueryService.execution_lineage()` returns correct re-plan chain
- [ ] `GraphQueryService.learning_contradictions()` returns active pairs only
- [ ] Agent tool `query_dependency_chain` works end-to-end via Mission Director
- [ ] Agent tool `query_agent_impact` works end-to-end
- [ ] Agent tool `query_execution_lineage` works end-to-end

### Phase D
- [ ] DDL in §3D.1 reviewed against PG 19 beta SQL/PGQ syntax (when available)
- [ ] Edge views confirmed compatible with SQL/PGQ `EDGE TABLES` requirements

---

## 6. Testing Strategy

| Test | Type | What to assert |
|---|---|---|
| DiskANN migration up/down | integration | Index created/dropped; EXPLAIN shows correct index type |
| DiskANN migration fallback | integration (SQLite or non-Azure PG) | Migration completes without error; HNSW preserved |
| `v_task_dependencies` null guard | integration | Task with missing `dependencies` key → zero rows, no error |
| `v_execution_edges` correctness | integration | View matches manual FK query for 3 test executions with parent chains |
| `transitive_dependencies()` fn vs Python BFS | integration | SQL function returns same set as `_transitive_dependencies()` for 5 test plans |
| `transitive_dependents()` fn vs Python BFS | integration | SQL function returns same set as `_transitive_dependents()` for 5 test plans |
| `execution_lineage()` correctness | integration | 3-deep re-plan chain returns all ancestors in order |
| Cycle guard in recursive function | integration | Circular dep in JSON → finite result set, no hang |
| `GraphQueryService.task_dependency_chain` | integration | Returns enriched chain with agent names and titles |
| `GraphQueryService.agent_impact` | integration | Returns correct mission/task/dependent counts |
| `query_dependency_chain` agent tool | integration | Tool returns structured result; Mission Director can parse it |
| `query_agent_impact` agent tool | integration | Tool returns structured result |

---

## 7. Implementation Phases and Effort

### Phase ordering

```
Phase A (DiskANN)  ──────────────────┐
                                     ├──→  Phase C (Query service + tools)
Phase B (SQL views + functions) ─────┘

Phase D (SQL/PGQ design) ── document only, no code ── revisit when PG 19 ships
```

**Phases A and B are independent** — they can be implemented in parallel or in any order.

**Phase C depends on Phase B** — the service wraps the SQL functions/views.

**Phase D is a design document only** — no implementation until PG 19 is available on Azure PG Flex.

### Effort estimate

| Phase | Scope | Files | Effort |
|---|---|---|---|
| A | DiskANN migration + verification | 1 migration | 0.5 day |
| B | SQL views, functions, repository methods | 1 migration, 1 modified repo | 1 day |
| C | Graph query service + 3 agent tools | 1 new service, 1 modified tools file | 1 day |
| D | SQL/PGQ DDL design (document only) | 0 (already in this plan) | 0 |
| **Total** | | **5 files** | **2.5 days** |

### Blast radius

#### Migrations (2 files)
| File | Change |
|---|---|
| `migrations/versions/2026xxxx_plan73a_diskann_index.py` | **NEW** — DiskANN index swap |
| `migrations/versions/2026xxxx_plan73b_dependency_functions.py` | **NEW** — 5 views + 3 SQL functions |

#### New modules (1 file)
| File | Change |
|---|---|
| `modules/backend/services/graph_query.py` | **NEW** — raw-SQL graph query service |

#### Modified modules (2 files)
| File | Change |
|---|---|
| `modules/backend/repositories/mission_plan.py` | ADD 3 methods: `transitive_dependencies_sql`, `transitive_dependents_sql`, `agent_impact_across_missions` |
| Mission Director tools file | ADD 3 tools: `query_dependency_chain`, `query_agent_impact`, `query_execution_lineage` |

---

## 8. What This Enables

After Phases A-C (implementable now):

1. **Filtered vector search that works** — DiskANN Advanced Filtering fixes the HNSW recall issue for mission-scoped hybrid queries
2. **DB-level dependency traversal** — SQL functions enable joins between dependency chains and other tables without Python round-trips
3. **Cross-mission impact analysis** — "What breaks if agent X is disabled?" answered in one SQL query
4. **Execution lineage queries** — trace re-plan chains without manual FK walks
5. **Learning contradiction graphs** — surface active contradictions per mission
6. **Agent-accessible graph tools** — Mission Director can query all of the above

After Phase D (when PG 19 ships):

7. **Variable-length multi-edge-type path queries** — SQL/PGQ `MATCH (a)-[*1..5]->(b)` with mixed edge labels in one query
8. **Zero-duplication graph layer** — `CREATE PROPERTY GRAPH` over existing tables, no sync code needed
9. **ISO-standard graph syntax** — first-party PostgreSQL feature, maintained by core team

---

## 9. Anti-Patterns

- **Do not remove the Python BFS** in `mission_plan.py`. The SQL functions serve a different purpose (DB-level joins). The Python methods operate on in-memory TaskPlan objects and are used by the dispatch loop where they're faster than a DB round-trip.
- **Do not install Apache AGE.** The project has reduced maintainership, blocks Azure in-place PG upgrades, and requires data duplication with a sync layer. SQL/PGQ (PG 19) provides the same capabilities natively.
- **Do not create HNSW + DiskANN indexes simultaneously.** One or the other on the same column. The migration handles the swap atomically.
- **Do not implement Phase D code before PG 19 is available on Azure PG Flex.** The DDL in §3D.1 is a design reference. SQL/PGQ syntax may change between the commitfest patch and GA.

### Why two traversal implementations coexist

After Phases A-C, task dependency traversal is available via two paths. Each serves a distinct use case — this is intentional, not duplication:

| Implementation | Where | Use case | Why not the other |
|---|---|---|---|
| **Python BFS** (`mission_plan.py`) | Dispatch loop, `approve_task`, `reject_task` | Hot path operating on an already-loaded in-memory `TaskPlan` | Zero DB round-trips; fastest for single-plan operations |
| **SQL functions** (`transitive_dependencies/dependents`) | Cross-mission queries, DB-level joins, agent tools | "Which agents affect which missions?" — joins traversal results with other tables | Python BFS can't join across missions without loading all plans into memory |

When SQL/PGQ ships (Phase D), the SQL functions are replaced by `GRAPH_TABLE` queries — but the Python BFS remains as the in-memory hot path.
