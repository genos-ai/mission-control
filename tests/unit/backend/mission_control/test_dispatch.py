"""Tests for the dispatch loop — topological sort, parallel execution, verification."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import delete

from modules.backend.agents.mission_control.dispatch import (
    dispatch,
    resolve_upstream_inputs,
    topological_sort,
    verify_task,
)
from modules.backend.agents.mission_control.gate import GateAction, GateDecision
from modules.backend.agents.mission_control.outcome import ExecutionStatus, TaskStatus
from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)
from modules.backend.core.protocols import NoOpEventBus
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.task import Task
from modules.backend.models.task import TaskStatus as DbTaskStatus
from modules.backend.schemas.task_plan import TaskPlan


def _entry(name: str) -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name=name,
        agent_version="1.0.0",
        description=f"Agent {name}",
        model=RosterModelSchema(name="test-model"),
        interface=RosterInterfaceSchema(
            input={"query": "string"},
            output={"result": "string", "confidence": "float"},
        ),
        constraints=RosterConstraintsSchema(
            timeout_seconds=10,
            cost_ceiling_usd=1.0,
            retry_budget=1,
        ),
    )


def _plan(tasks: list[dict], **kw) -> TaskPlan:
    return TaskPlan.model_validate(
        {
            "version": "1.0.0",
            "mission_id": "test",
            "summary": "Test",
            "estimated_cost_usd": 1.0,
            "estimated_duration_seconds": 60,
            "tasks": tasks,
            **kw,
        }
    )


def _mock_curator(project_context: dict | None = None) -> MagicMock:
    """Build a mock ContextCurator satisfying ContextCuratorProtocol."""
    curator = MagicMock()
    curator.get_mission_context = AsyncMock(return_value=project_context or {})
    curator.apply_task_updates = AsyncMock(return_value=(2, []))
    return curator


def _task(
    task_id: str,
    agent: str = "agent_a",
    deps: list[str] | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "agent": agent,
        "agent_version": "1.0.0",
        "description": "Test",
        "instructions": "Do it",
        "dependencies": deps or [],
        "verification": {
            "tier_1": {
                "schema_validation": True,
                "required_output_fields": ["result"],
            },
            "tier_2": {"deterministic_checks": []},
            "tier_3": {"requires_ai_evaluation": False},
        },
    }


# ---------------------------------------------------------------------------
# DB-backed dispatch helpers (Plan 72)
#
# Task ids live in a native Postgres UUID column and dispatch() blocks each
# layer until its tasks are APPROVED in the `tasks` table. Tests keep the
# readable symbolic names ("t1", "a") and map them to stable UUIDs via _uid.
# ---------------------------------------------------------------------------

_UID_NS = UUID("00000000-0000-0000-0000-0000000d15b0")


def _uid(name: str) -> str:
    """Map a symbolic task name ('t1', 'a') to a stable UUID string."""
    return str(uuid5(_UID_NS, name))


def _db_plan(tasks: list[dict], **kw) -> TaskPlan:
    """Build a TaskPlan for dispatch() tests, mapping symbolic ids to UUIDs.

    Rewrites task_id, dependencies, from_upstream.source_task and
    execution_hints.critical_path through _uid so the plan is valid against
    the UUID-typed tasks table. Pure in-memory tests keep using _plan.
    """
    mapped = []
    for raw in tasks:
        t = {**raw, "task_id": _uid(raw["task_id"])}
        t["dependencies"] = [_uid(d) for d in raw.get("dependencies") or []]
        inputs = raw.get("inputs")
        if inputs:
            t["inputs"] = {
                **inputs,
                "from_upstream": {
                    key: {**spec, "source_task": _uid(spec["source_task"])}
                    for key, spec in (inputs.get("from_upstream") or {}).items()
                },
            }
        mapped.append(t)
    hints = kw.get("execution_hints")
    if hints and hints.get("critical_path"):
        kw = {
            **kw,
            "execution_hints": {
                **hints,
                "critical_path": [_uid(x) for x in hints["critical_path"]],
            },
        }
    return _plan(mapped, **kw)


async def _seed_approved(factory, plan: TaskPlan) -> str:
    """Commit APPROVED Task rows (+ mission/plan parents) for every plan task.

    dispatch() waits on task approval by reading the `tasks` table through
    sessions it opens from the session factory, so the rows must be
    COMMITTED — data added via the rollback-wrapped db_session fixture is
    invisible to those sessions. Returns the mission id for cleanup.
    """
    mission_id = str(uuid4())
    plan_id = str(uuid4())
    async with factory() as session:
        session.add(
            Mission(
                id=mission_id,
                name=f"dispatch-test-{mission_id}",
                description="Dispatch loop test mission",
                owner_id=str(uuid4()),
            )
        )
        session.add(MissionPlan(id=plan_id, mission_id=mission_id, gate_mode=GateMode.AUTONOMOUS))
        for task in plan.tasks:
            session.add(
                Task(
                    id=task.task_id,
                    mission_id=mission_id,
                    plan_id=plan_id,
                    agent=task.agent,
                    description=task.description,
                    status=DbTaskStatus.APPROVED,
                )
            )
        await session.commit()
    return mission_id


async def _dispatch_seeded(factory, plan: TaskPlan, *args, **kwargs):
    """Run dispatch() against seeded, committed APPROVED tasks; clean up after.

    Passes session_factory=factory so the approval wait queries the test
    database. Afterwards deletes the seeded mission (cascading to plan and
    tasks) so the deterministic _uid task ids can be reused by later tests —
    the test schema is only reset once per pytest session.
    """
    mission_id = await _seed_approved(factory, plan)
    kwargs.setdefault("event_bus", NoOpEventBus())
    try:
        return await dispatch(plan, *args, session_factory=factory, **kwargs)
    finally:
        async with factory() as session:
            await session.execute(delete(Mission).where(Mission.id == mission_id))
            await session.commit()


class TestTopologicalSort:
    def test_no_deps_single_layer(self):
        plan = _plan([_task("a"), _task("b")])
        layers = topological_sort(plan)
        assert len(layers) == 1
        assert set(layers[0]) == {"a", "b"}

    def test_linear_chain(self):
        plan = _plan(
            [
                _task("a"),
                _task("b", deps=["a"]),
                _task("c", deps=["b"]),
            ]
        )
        layers = topological_sort(plan)
        assert len(layers) == 3
        assert layers[0] == ["a"]
        assert layers[1] == ["b"]
        assert layers[2] == ["c"]

    def test_diamond_pattern(self):
        plan = _plan(
            [
                _task("a"),
                _task("b", deps=["a"]),
                _task("c", deps=["a"]),
                _task("d", deps=["b", "c"]),
            ]
        )
        layers = topological_sort(plan)
        assert len(layers) == 3
        assert layers[0] == ["a"]
        assert set(layers[1]) == {"b", "c"}
        assert layers[2] == ["d"]


class TestResolveUpstreamInputs:
    def test_static_only(self):
        task = _plan(
            [
                {
                    **_task("t1"),
                    "inputs": {"static": {"key": "value"}, "from_upstream": {}},
                }
            ]
        ).tasks[0]
        result = resolve_upstream_inputs(task, {})
        assert result == {"key": "value"}

    def test_upstream_resolution(self):
        task = _plan(
            [
                {
                    **_task("t2", deps=["t1"]),
                    "inputs": {
                        "static": {},
                        "from_upstream": {
                            "data": {"source_task": "t1", "source_field": "result"},
                        },
                    },
                }
            ]
        ).tasks[0]
        completed = {"t1": {"result": "hello", "confidence": 0.9}}
        result = resolve_upstream_inputs(task, completed)
        assert result["data"] == "hello"

    def test_missing_upstream_raises(self):
        task = _plan(
            [
                {
                    **_task("t2", deps=["t1"]),
                    "inputs": {
                        "static": {},
                        "from_upstream": {
                            "data": {"source_task": "t1", "source_field": "result"},
                        },
                    },
                }
            ]
        ).tasks[0]
        with pytest.raises(KeyError):
            resolve_upstream_inputs(task, {})


class TestVerifyTask:
    @pytest.mark.asyncio
    async def test_all_fields_present_passes(self):
        task = _plan([_task("t1")]).tasks[0]
        entry = _entry("agent_a")
        output = {"result": "hello", "confidence": 0.9}
        result = await verify_task(task=task, output=output, roster_entry=entry)
        assert result.passed is True
        assert result.tier_1.status.value == "pass"

    @pytest.mark.asyncio
    async def test_missing_field_fails(self):
        task = _plan([_task("t1")]).tasks[0]
        entry = _entry("agent_a")
        output = {"result": "hello"}  # missing 'confidence'
        result = await verify_task(task=task, output=output, roster_entry=entry)
        assert result.passed is False
        assert "confidence" in result.tier_1.details


class TestDispatch:
    @pytest.mark.asyncio
    async def test_simple_plan_succeeds(self, db_session_factory):
        """Single task, agent returns valid output."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.95,
                "_meta": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                },
            }

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS
        assert len(outcome.task_results) == 1
        assert outcome.task_results[0].status == TaskStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_parallel_execution(self, db_session_factory):
        """Two independent tasks run concurrently."""
        plan = _db_plan([_task("a"), _task("b")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            await asyncio.sleep(0.01)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS
        assert len(outcome.task_results) == 2

    @pytest.mark.asyncio
    async def test_upstream_resolution_in_dispatch(self, db_session_factory):
        """Task B receives output from Task A via from_upstream."""
        tasks = [
            _task("a"),
            {
                **_task("b", deps=["a"]),
                "inputs": {
                    "static": {},
                    "from_upstream": {
                        "data": {"source_task": "a", "source_field": "result"},
                    },
                },
            },
        ]
        plan = _db_plan(tasks)
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "from_a", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_tier1_failure_triggers_retry(self, db_session_factory):
        """Agent output missing required fields triggers retry."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"result": "done", "_meta": {}}  # missing confidence
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS
        assert outcome.task_results[0].retry_count == 1

    @pytest.mark.asyncio
    async def test_timeout_handled(self, db_session_factory):
        """Agent exceeding timeout is handled gracefully."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.timeout_seconds = 1
        entry.constraints.retry_budget = 0
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            await asyncio.sleep(10)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_partial_success(self, db_session_factory):
        """Partial success when threshold met and critical path succeeded."""
        tasks = [
            {**_task("a"), "instructions": "task_a"},
            {**_task("b"), "instructions": "task_b"},
        ]
        plan = _db_plan(
            tasks,
            execution_hints={"min_success_threshold": 0.5, "critical_path": ["a"]},
        )
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 0
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            if "task_b" in instructions:
                raise RuntimeError("Agent b failed")
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_execution_failure_on_critical_path_failure(self, db_session_factory):
        """Execution fails when critical path task fails."""
        tasks = [
            {**_task("a"), "instructions": "task_a"},
            {**_task("b"), "instructions": "task_b"},
        ]
        plan = _db_plan(
            tasks,
            execution_hints={"min_success_threshold": 0.5, "critical_path": ["a"]},
        )
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 0
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            if "task_a" in instructions:
                raise RuntimeError("Agent a (critical) failed")
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.FAILED

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, db_session_factory):
        """Total cost is aggregated from all tasks."""
        plan = _db_plan([_task("a"), _task("b")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "_meta": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.05},
            }

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.total_cost_usd == pytest.approx(0.1, abs=0.001)
        assert outcome.total_tokens.input == 200
        assert outcome.total_tokens.output == 100

    @pytest.mark.asyncio
    async def test_timeout_retry_then_exhaustion(self, db_session_factory):
        """Timeout retries up to retry_budget then reports TIMEOUT status."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.timeout_seconds = 1
        entry.constraints.retry_budget = 2
        roster = Roster(agents=[entry])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(10)  # always timeout

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.TIMEOUT
        assert call_count == 3  # initial + 2 retries
        # Every attempt is recorded, the final failing one included (88.2.3b).
        assert len(outcome.task_results[0].retry_history) == 3

    @pytest.mark.asyncio
    async def test_execution_error_retries_then_fails(self, db_session_factory):
        """Execution errors retry up to budget, then fail with history."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 2
        roster = Roster(agents=[entry])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"Error on attempt {call_count}")

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.FAILED
        assert call_count == 3  # initial + 2 retries
        # Every attempt is recorded, the final failing one included (88.2.3b).
        assert len(outcome.task_results[0].retry_history) == 3
        assert "Error on attempt 1" in outcome.task_results[0].retry_history[0].failure_reason

    @pytest.mark.asyncio
    async def test_verification_failure_exhausts_retry_budget(self, db_session_factory):
        """Verification failure retries, then fails with verification outcome."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 1
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            # Always missing 'confidence' — tier 1 always fails
            return {"result": "done", "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.FAILED
        assert outcome.task_results[0].retry_count == 1
        assert outcome.task_results[0].verification_outcome is not None

    @pytest.mark.asyncio
    async def test_timeout_retry_then_success(self, db_session_factory):
        """Task recovers after timeout on first attempt."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.timeout_seconds = 1
        entry.constraints.retry_budget = 1
        roster = Roster(agents=[entry])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(10)  # timeout first attempt
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.SUCCESS
        assert outcome.task_results[0].retry_count == 1
        assert len(outcome.task_results[0].retry_history) == 1

    @pytest.mark.asyncio
    async def test_agent_not_in_roster_fails_task(self):
        """Task referencing unknown agent is marked failed."""
        plan = _plan([_task("t1", agent="unknown_agent")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await dispatch(plan, roster, mock_execute, 10.0, event_bus=NoOpEventBus())
        assert outcome.status == ExecutionStatus.FAILED
        assert outcome.task_results[0].status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_failed_upstream_skips_dependent(self, db_session_factory):
        """Downstream task fails when upstream has no output."""
        tasks = [
            {**_task("a"), "instructions": "task_a"},
            {
                **_task("b", deps=["a"]),
                "inputs": {
                    "static": {},
                    "from_upstream": {
                        "data": {"source_task": "a", "source_field": "result"},
                    },
                },
            },
        ]
        plan = _db_plan(tasks)
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 0
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            if "task_a" in instructions:
                raise RuntimeError("Agent a failed")
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.FAILED
        # Both tasks should fail — a from error, b from missing upstream
        assert all(r.status == TaskStatus.FAILED for r in outcome.task_results)

    @pytest.mark.asyncio
    async def test_retry_records_feedback_in_history(self, db_session_factory):
        """Retry history records failure reason and feedback."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 1
        roster = Roster(agents=[entry])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First attempt failed")
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.SUCCESS
        assert call_count == 2
        assert len(outcome.task_results[0].retry_history) == 1
        history_entry = outcome.task_results[0].retry_history[0]
        assert "First attempt failed" in history_entry.failure_reason
        assert history_entry.feedback_provided is not None

    # ---- Pre-Phase 0 tests ----

    @pytest.mark.asyncio
    async def test_budget_enforcement_cancels_remaining_tasks(self, db_session_factory):
        """P0.1: Budget exceeded after first layer cancels remaining tasks."""
        tasks = [
            _task("a"),
            _task("b", deps=["a"]),
        ]
        plan = _db_plan(tasks)
        roster = Roster(agents=[_entry("agent_a")])
        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            return {
                "result": "done",
                "confidence": 0.9,
                "_meta": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.06},
            }

        outcome = await _dispatch_seeded(
            db_session_factory, plan, roster, mock_execute, mission_budget_usd=0.05
        )
        assert outcome.status == ExecutionStatus.FAILED
        # Only first task should execute — budget exceeded after layer 1
        assert call_count == 1
        assert outcome.total_cost_usd == pytest.approx(0.06, abs=0.001)

    @pytest.mark.asyncio
    async def test_budget_zero_allows_all_tasks(self, db_session_factory):
        """P0.1: Budget of 0 means no budget enforcement."""
        plan = _db_plan([_task("a"), _task("b")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "_meta": {"cost_usd": 5.0},
            }

        outcome = await _dispatch_seeded(
            db_session_factory, plan, roster, mock_execute, mission_budget_usd=0
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        assert len(outcome.task_results) == 2

    @pytest.mark.asyncio
    async def test_retry_feedback_delivered_to_agent(self, db_session_factory):
        """P0.2: Enriched instructions with feedback are delivered on retry."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 1
        roster = Roster(agents=[entry])
        received_instructions = []

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            received_instructions.append(instructions)
            if len(received_instructions) == 1:
                raise RuntimeError("First attempt failed")
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.SUCCESS
        assert len(received_instructions) == 2
        # Second call should have feedback appended
        assert "FEEDBACK FROM PREVIOUS ATTEMPT" in received_instructions[1]
        assert "First attempt failed" in received_instructions[1]

    @pytest.mark.asyncio
    async def test_execution_id_assigned_per_task(self, db_session_factory):
        """P0.6: Each task gets a unique non-empty execution_id."""
        plan = _db_plan([_task("a"), _task("b")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert len(outcome.task_results) == 2
        ids = [r.execution_id for r in outcome.task_results]
        # All non-empty
        assert all(eid for eid in ids)
        # All unique
        assert len(set(ids)) == 2

    @pytest.mark.asyncio
    async def test_execution_id_on_failed_task(self, db_session_factory):
        """P0.6: Failed tasks also get an execution_id."""
        plan = _db_plan([_task("t1")])
        entry = _entry("agent_a")
        entry.constraints.retry_budget = 0
        roster = Roster(agents=[entry])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            raise RuntimeError("fail")

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].status == TaskStatus.FAILED
        assert outcome.task_results[0].execution_id != ""

    # ---- Sub-Phase 3 tests: Agent Contract ----

    @pytest.mark.asyncio
    async def test_context_updates_extracted_from_output(self, db_session_factory):
        """3.1/3.3: context_updates are extracted from agent output into TaskResult."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "context_updates": [
                    {
                        "op": "add",
                        "path": "identity.tech_stack",
                        "value": ["python"],
                        "reason": "discovered",
                    },
                ],
                "_meta": {},
            }

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS
        assert len(outcome.task_results[0].context_updates) == 1
        assert outcome.task_results[0].context_updates[0]["op"] == "add"

    @pytest.mark.asyncio
    async def test_context_updates_not_in_output_reference(self, db_session_factory):
        """3.3: context_updates are popped from output_reference (not leaked)."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "context_updates": [{"op": "add", "path": "x", "value": 1, "reason": "y"}],
                "_meta": {},
            }

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert "context_updates" not in outcome.task_results[0].output_reference

    @pytest.mark.asyncio
    async def test_context_updates_empty_by_default(self, db_session_factory):
        """3.1: TaskResult has empty context_updates when agent returns none."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.task_results[0].context_updates == []

    @pytest.mark.asyncio
    async def test_context_curator_called_on_success(self, db_session_factory):
        """3.3: ContextCurator.apply_task_updates called after successful task."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        mock_curator = _mock_curator()

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "context_updates": [
                    {"op": "add", "path": "x", "value": 1, "reason": "test"},
                ],
                "_meta": {},
            }

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_curator=mock_curator,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        mock_curator.apply_task_updates.assert_called_once()
        call_args = mock_curator.apply_task_updates.call_args
        assert call_args[0][0] == "proj-1"
        assert call_args[0][1][0]["op"] == "add"

    @pytest.mark.asyncio
    async def test_context_curator_not_called_without_mission_id(self, db_session_factory):
        """3.3: No curator calls when mission_id is None."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        mock_curator = _mock_curator()

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "context_updates": [
                    {"op": "add", "path": "x", "value": 1, "reason": "test"},
                ],
                "_meta": {},
            }

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            context_curator=mock_curator,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        mock_curator.apply_task_updates.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_curator_failure_does_not_fail_task(self, db_session_factory):
        """3.3: ContextCurator failure is non-fatal — task still succeeds."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        mock_curator = _mock_curator()
        mock_curator.apply_task_updates = AsyncMock(
            side_effect=RuntimeError("DB error"),
        )

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "context_updates": [
                    {"op": "add", "path": "x", "value": 1, "reason": "test"},
                ],
                "_meta": {},
            }

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_curator=mock_curator,
        )
        assert outcome.status == ExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_project_context_injected_into_inputs(self, db_session_factory):
        """3.4: PCD is passed to agents as project_context in inputs."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        received_inputs = []

        mock_curator = _mock_curator(
            project_context={
                "identity": {"name": "test-project"},
                "version": 1,
            }
        )

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            received_inputs.append(inputs)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_curator=mock_curator,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        assert "project_context" in received_inputs[0]
        assert received_inputs[0]["project_context"]["identity"]["name"] == "test-project"

    @pytest.mark.asyncio
    async def test_no_project_context_without_curator(self, db_session_factory):
        """3.4: No project_context in inputs when curator is None."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        received_inputs = []

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            received_inputs.append(inputs)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)
        assert outcome.status == ExecutionStatus.SUCCESS
        assert "project_context" not in received_inputs[0]

    # ---- Sub-Phase 4 tests: Context Assembly ----

    @pytest.mark.asyncio
    async def test_assembler_builds_full_context_packet(self, db_session_factory):
        """4.4: When assembler is provided, agents receive assembled context."""
        plan = _db_plan([{**_task("t1"), "domain_tags": ["api"]}])
        roster = Roster(agents=[_entry("agent_a")])
        received_inputs = []

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(
            return_value={
                "project_context": {"identity": {"name": "proj"}},
                "task": {"task_id": "t1"},
                "inputs": {},
                "history": {"recent_failures": []},
            }
        )

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            received_inputs.append(inputs)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_assembler=mock_assembler,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        # Assembler output replaces simple PCD injection
        assert "project_context" in received_inputs[0]
        assert "project_history" in received_inputs[0]
        mock_assembler.build.assert_called_once()

    @pytest.mark.asyncio
    async def test_assembler_receives_domain_tags(self, db_session_factory):
        """4.4: Assembler is called with domain_tags from task definition."""
        plan = _db_plan([{**_task("t1"), "domain_tags": ["auth", "api"]}])
        roster = Roster(agents=[_entry("agent_a")])

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(return_value={"project_context": {}})

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_assembler=mock_assembler,
        )
        call_kwargs = mock_assembler.build.call_args
        assert call_kwargs.kwargs.get("domain_tags") == ["auth", "api"]

    @pytest.mark.asyncio
    async def test_assembler_fallback_to_pcd_on_failure(self, db_session_factory):
        """4.4: When assembler fails, falls back to raw PCD from curator."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])
        received_inputs = []

        mock_curator = _mock_curator(
            project_context={
                "identity": {"name": "fallback-project"},
            }
        )
        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(side_effect=RuntimeError("DB error"))

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            received_inputs.append(inputs)
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_curator=mock_curator,
            context_assembler=mock_assembler,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        # Should fall back to raw PCD
        assert received_inputs[0]["project_context"]["identity"]["name"] == "fallback-project"

    @pytest.mark.asyncio
    async def test_assembler_not_called_without_mission_id(self, db_session_factory):
        """4.4: Assembler is not called when mission_id is None."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock()

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            context_assembler=mock_assembler,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        mock_assembler.build.assert_not_called()

    @pytest.mark.asyncio
    async def test_assembler_failure_does_not_fail_task(self, db_session_factory):
        """4.4: Assembler failure is non-fatal — task still executes."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(side_effect=RuntimeError("timeout"))

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_assembler=mock_assembler,
        )
        assert outcome.status == ExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_domain_tags_empty_passed_as_none(self, db_session_factory):
        """4.4: Empty domain_tags are passed as None to assembler."""
        plan = _db_plan([_task("t1")])  # no domain_tags
        roster = Roster(agents=[_entry("agent_a")])

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(return_value={"project_context": {}})

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_assembler=mock_assembler,
        )
        call_kwargs = mock_assembler.build.call_args
        assert call_kwargs.kwargs.get("domain_tags") is None

    @pytest.mark.asyncio
    async def test_assembler_not_entered_concurrently_within_a_layer(self, db_session_factory):
        """88.2.3: the assembler shares one AsyncSession, so a layer's tasks assemble in turn."""
        plan = _db_plan(
            [
                {**_task("t1"), "domain_tags": ["auth"]},
                {**_task("t2"), "domain_tags": ["api"]},
            ]
        )
        roster = Roster(agents=[_entry("agent_a")])
        in_build = False

        async def build(**kwargs):
            nonlocal in_build
            if in_build:
                raise AssertionError("context assembler entered concurrently")
            in_build = True
            try:
                await asyncio.sleep(0.01)
                return {"project_context": {"identity": {"name": "proj"}}}
            finally:
                in_build = False

        mock_assembler = MagicMock()
        mock_assembler.build = AsyncMock(side_effect=build)

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        outcome = await _dispatch_seeded(
            db_session_factory,
            plan,
            roster,
            mock_execute,
            10.0,
            mission_id="proj-1",
            context_assembler=mock_assembler,
        )
        assert outcome.status == ExecutionStatus.SUCCESS
        assert mock_assembler.build.await_count == 2


# ---------------------------------------------------------------------------
# A.3 — Workflow task dispatch (Plan 53 Phase B)
# ---------------------------------------------------------------------------


class TestWorkflowTaskDispatch:
    """Tests for workflow:* agent routing through dispatch()."""

    @pytest.mark.asyncio
    async def test_workflow_task_routes_to_service(self, db_session_factory):
        """Plan containing agent='workflow:deploy' routes to WorkflowRunService."""
        plan = _db_plan([_task("t1", agent="workflow:deploy-staging")])
        roster = Roster(agents=[])  # no roster needed for workflow tasks

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            pytest.fail("Standard executor should NOT be called for workflow tasks")

        # Mock the WorkflowRunService.factory context manager
        mock_run = MagicMock()
        mock_run.id = "run-123"
        mock_run.status = "completed"
        mock_run.execution_record_id = "er-456"
        mock_run.result_summary = "Deployed successfully"
        mock_run.total_cost_usd = 0.25
        mock_run.started_at = None
        mock_run.completed_at = None

        mock_svc = MagicMock()
        mock_svc.run_workflow = AsyncMock(return_value=mock_run)

        mock_factory = MagicMock()
        mock_factory.__aenter__ = AsyncMock(return_value=mock_svc)
        mock_factory.__aexit__ = AsyncMock(return_value=False)

        from unittest.mock import patch

        with patch(
            "modules.backend.services.workflow_run.WorkflowRunService.factory",
            return_value=mock_factory,
        ):
            outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)

        assert len(outcome.task_results) == 1
        result = outcome.task_results[0]
        assert result.agent_name == "workflow:deploy-staging"
        assert result.status == TaskStatus.SUCCESS
        assert result.cost_usd == 0.25
        assert result.output_reference["workflow_run_id"] == "run-123"

    @pytest.mark.asyncio
    async def test_workflow_task_failure_captured(self, db_session_factory):
        """WorkflowRunService raising an exception returns FAILED result."""
        plan = _db_plan([_task("t1", agent="workflow:broken-flow")])
        roster = Roster(agents=[])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            pytest.fail("Should not be called")

        mock_svc = MagicMock()
        mock_svc.run_workflow = AsyncMock(
            side_effect=RuntimeError("Workflow definition not found"),
        )

        mock_factory = MagicMock()
        mock_factory.__aenter__ = AsyncMock(return_value=mock_svc)
        mock_factory.__aexit__ = AsyncMock(return_value=False)

        from unittest.mock import patch

        with patch(
            "modules.backend.services.workflow_run.WorkflowRunService.factory",
            return_value=mock_factory,
        ):
            outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)

        result = outcome.task_results[0]
        assert result.status == TaskStatus.FAILED
        assert "not found" in result.failure.summary

    @pytest.mark.asyncio
    async def test_mixed_plan_standard_and_workflow(self, db_session_factory):
        """Plan with both a standard agent task and a workflow task."""
        plan = _db_plan(
            [
                _task("t1", agent="agent_a"),
                _task("t2", agent="workflow:lint-check"),
            ]
        )
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "_meta": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                },
            }

        mock_run = MagicMock()
        mock_run.id = "run-789"
        mock_run.status = "completed"
        mock_run.execution_record_id = "er-abc"
        mock_run.result_summary = "Lint passed"
        mock_run.total_cost_usd = 0.05
        mock_run.started_at = None
        mock_run.completed_at = None

        mock_svc = MagicMock()
        mock_svc.run_workflow = AsyncMock(return_value=mock_run)

        mock_factory = MagicMock()
        mock_factory.__aenter__ = AsyncMock(return_value=mock_svc)
        mock_factory.__aexit__ = AsyncMock(return_value=False)

        from unittest.mock import patch

        with patch(
            "modules.backend.services.workflow_run.WorkflowRunService.factory",
            return_value=mock_factory,
        ):
            outcome = await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0)

        assert outcome.status == ExecutionStatus.SUCCESS
        assert len(outcome.task_results) == 2
        agents = {r.agent_name for r in outcome.task_results}
        assert "agent_a" in agents
        assert "workflow:lint-check" in agents


# ---------------------------------------------------------------------------
# A.4 — Retry handler edge cases
# ---------------------------------------------------------------------------


class TestRetryModifyAction:
    """Tests for GateAction.MODIFY in verification failure path."""

    @pytest.mark.asyncio
    async def test_modify_action_accepts_output_as_is(self, db_session_factory):
        """MODIFY gate action accepts the task output without re-running."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        call_count = 0

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            nonlocal call_count
            call_count += 1
            # Return output missing required "confidence" field → verification fails
            return {
                "result": "partial",
                "_meta": {
                    "input_tokens": 50,
                    "output_tokens": 20,
                    "cost_usd": 0.005,
                },
            }

        # Gate that returns MODIFY on verification_failed
        modify_gate = MagicMock()
        modify_gate.review = AsyncMock(
            return_value=GateDecision(
                action=GateAction.MODIFY,
                reason="Accept partial output",
            )
        )

        outcome = await _dispatch_seeded(
            db_session_factory, plan, roster, mock_execute, 10.0, gate=modify_gate
        )

        # MODIFY means: accept the output as-is (status=SUCCESS), no retry
        assert len(outcome.task_results) == 1
        result = outcome.task_results[0]
        assert result.status == TaskStatus.SUCCESS
        # Agent was called only once (no retry)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_modified_instructions_override_feedback(self, db_session_factory):
        """Gate providing modified_instructions overrides standard retry feedback."""
        plan = _db_plan(
            [
                {
                    **_task("t1"),
                    "verification": {
                        "tier_1": {
                            "schema_validation": True,
                            "required_output_fields": ["result", "confidence"],
                        },
                        "tier_2": {"deterministic_checks": []},
                        "tier_3": {"requires_ai_evaluation": False},
                    },
                }
            ]
        )
        roster = Roster(agents=[_entry("agent_a")])

        call_instructions = []

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            call_instructions.append(instructions)
            # First call: missing confidence → verification fails →
            # gate says CONTINUE with modified_instructions
            # Second call: all fields present → passes
            if len(call_instructions) == 1:
                return {"result": "partial", "_meta": {}}
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        gate_calls = []

        async def mock_review(context):
            gate_calls.append(context.gate_type)
            if context.gate_type == "verification_failed":
                return GateDecision(
                    action=GateAction.CONTINUE,
                    reason="Try again",
                    modified_instructions="USE THESE EXACT INSTRUCTIONS INSTEAD",
                )
            return GateDecision(action=GateAction.CONTINUE, reason="ok")

        gate = MagicMock()
        gate.review = mock_review

        await _dispatch_seeded(db_session_factory, plan, roster, mock_execute, 10.0, gate=gate)

        # Agent called twice (original + retry)
        assert len(call_instructions) == 2
        # Second call should use the gate's modified instructions
        assert call_instructions[1] == "USE THESE EXACT INSTRUCTIONS INSTEAD"


class TestPostTaskGatePqi:
    """Tests for PQI extraction in the post-task gate path."""

    @pytest.mark.asyncio
    async def test_pqi_extracted_into_context_updates(self, db_session_factory):
        """Output containing pqi dict gets extracted into context_updates."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {
                "result": "done",
                "confidence": 0.9,
                "pqi": {
                    "composite": 78.5,
                    "quality_band": "good",
                    "dimensions": {
                        "maintainability": {"score": 82},
                        "security": {"score": 75},
                    },
                    "file_count": 42,
                    "line_count": 3500,
                },
                "_meta": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01},
            }

        # Use a gate that returns CONTINUE at post_task so the PQI path runs
        async def mock_review(context):
            return GateDecision(action=GateAction.CONTINUE, reason="ok")

        gate = MagicMock()
        gate.review = mock_review

        outcome = await _dispatch_seeded(
            db_session_factory, plan, roster, mock_execute, 10.0, gate=gate
        )

        result = outcome.task_results[0]
        assert result.status == TaskStatus.SUCCESS
        # PQI should be extracted into context_updates
        pqi_updates = [
            u for u in result.context_updates if u.get("path") == "current_state.pqi_score"
        ]
        assert len(pqi_updates) == 1
        assert pqi_updates[0]["value"]["composite"] == 78.5
        assert pqi_updates[0]["value"]["quality_band"] == "good"

    @pytest.mark.asyncio
    async def test_missing_pqi_no_context_update(self, db_session_factory):
        """Output without pqi dict produces no PQI context update."""
        plan = _db_plan([_task("t1")])
        roster = Roster(agents=[_entry("agent_a")])

        async def mock_execute(agent_name, instructions, inputs, usage_limits):
            return {"result": "done", "confidence": 0.9, "_meta": {}}

        async def mock_review(context):
            return GateDecision(action=GateAction.CONTINUE, reason="ok")

        gate = MagicMock()
        gate.review = mock_review

        outcome = await _dispatch_seeded(
            db_session_factory, plan, roster, mock_execute, 10.0, gate=gate
        )

        result = outcome.task_results[0]
        pqi_updates = [
            u for u in result.context_updates if u.get("path", "").startswith("current_state.pqi")
        ]
        assert len(pqi_updates) == 0
