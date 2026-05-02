"""Unit tests for PlanBuildingSession — incremental plan assembly."""

import pytest

from modules.backend.agents.mission.planning.build_session import (
    PlanBuildingSession,
    semantic_check,
)
from modules.backend.agents.mission_control.roster import (
    Roster,
    RosterAgentEntry,
    RosterConstraintsSchema,
    RosterInterfaceSchema,
    RosterModelSchema,
)


def _entry(name: str, version: str = "1.0.0") -> RosterAgentEntry:
    return RosterAgentEntry(
        agent_name=name,
        agent_version=version,
        description=f"Test agent {name}",
        model=RosterModelSchema(name="test:model"),
        interface=RosterInterfaceSchema(),
        constraints=RosterConstraintsSchema(),
    )


def _roster(*names: str) -> Roster:
    return Roster(agents=[_entry(n) for n in names])


WASA_ROSTER = _roster(
    "security.webapp.scanner.agent",
    "security.webapp.triage.agent",
    "security.webapp.reporter.agent",
)


def _session(**kwargs) -> PlanBuildingSession:
    defaults = {
        "mission_id": "test-001",
        "version": 1,
        "roster": WASA_ROSTER,
        "budget_usd": 10.0,
    }
    defaults.update(kwargs)
    return PlanBuildingSession(**defaults)


class TestAddTask:
    def test_adds_task_with_generated_id(self):
        s = _session()
        result = s.add_task(
            description="Scan codebase",
            agent="security.webapp.scanner.agent",
            instructions="Run all scanners",
        )
        assert result["task_id"] == "v1-task-001"
        assert result["status"] == "proposed"
        assert "v1-task-001" in s.tasks

    def test_sequential_ids(self):
        s = _session()
        r1 = s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        r2 = s.add_task(description="B", agent="security.webapp.triage.agent", instructions="B")
        assert r1["task_id"] == "v1-task-001"
        assert r2["task_id"] == "v1-task-002"

    def test_rejects_unknown_agent(self):
        s = _session()
        result = s.add_task(
            description="Bad", agent="nonexistent.agent", instructions="X",
        )
        assert "error" in result
        assert "not found in roster" in result["error"]

    def test_rejects_unknown_dependency(self):
        s = _session()
        result = s.add_task(
            description="Bad", agent="security.webapp.scanner.agent",
            instructions="X", dependencies=["v1-task-999"],
        )
        assert "error" in result
        assert "not found in plan" in result["error"]

    def test_valid_dependency(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        r2 = s.add_task(
            description="B", agent="security.webapp.triage.agent",
            instructions="B", dependencies=["v1-task-001"],
        )
        assert "error" not in r2
        assert s.tasks["v1-task-002"]["dependencies"] == ["v1-task-001"]

    def test_domain_tags(self):
        s = _session()
        s.add_task(
            description="A", agent="security.webapp.scanner.agent",
            instructions="A", domain_tags=["security", "scan"],
        )
        assert s.tasks["v1-task-001"]["domain_tags"] == ["security", "scan"]


class TestUpdateTask:
    def test_update_description(self):
        s = _session()
        s.add_task(description="Old", agent="security.webapp.scanner.agent", instructions="X")
        result = s.update_task(task_id="v1-task-001", description="New")
        assert "description" in result["updated_fields"]
        assert s.tasks["v1-task-001"]["description"] == "New"

    def test_update_agent(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="X")
        result = s.update_task(task_id="v1-task-001", agent="security.webapp.triage.agent")
        assert "agent" in result["updated_fields"]
        assert s.tasks["v1-task-001"]["agent"] == "security.webapp.triage.agent"

    def test_rejects_unknown_task(self):
        s = _session()
        result = s.update_task(task_id="v1-task-999", description="X")
        assert "error" in result

    def test_rejects_unknown_agent(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="X")
        result = s.update_task(task_id="v1-task-001", agent="bad.agent")
        assert "error" in result


class TestRemoveTask:
    def test_removes_task(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="X")
        result = s.remove_task(task_id="v1-task-001")
        assert result["task_id"] == "v1-task-001"
        assert "v1-task-001" not in s.tasks

    def test_cascades_to_dependents(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.add_task(
            description="B", agent="security.webapp.triage.agent",
            instructions="B", dependencies=["v1-task-001"],
        )
        result = s.remove_task(task_id="v1-task-001")
        assert "v1-task-002" in result["cancelled_dependents"]
        assert len(s.tasks) == 0

    def test_rejects_unknown_task(self):
        s = _session()
        result = s.remove_task(task_id="v1-task-999")
        assert "error" in result


class TestSetUpstreamInput:
    def test_sets_upstream(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.add_task(
            description="B", agent="security.webapp.triage.agent",
            instructions="B", dependencies=["v1-task-001"],
        )
        result = s.set_upstream_input(
            task_id="v1-task-002", input_name="sarif",
            source_task="v1-task-001", source_field="merged_sarif",
        )
        assert result["input_name"] == "sarif"
        upstream = s.tasks["v1-task-002"]["inputs"]["from_upstream"]
        assert upstream["sarif"]["source_task"] == "v1-task-001"

    def test_rejects_non_dependency_source(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.add_task(description="B", agent="security.webapp.triage.agent", instructions="B")
        result = s.set_upstream_input(
            task_id="v1-task-002", input_name="sarif",
            source_task="v1-task-001", source_field="output",
        )
        assert "error" in result
        assert "must be in dependencies" in result["error"]


class TestSetStaticInput:
    def test_sets_value(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.set_static_input(task_id="v1-task-001", key="target_path", value="/workspace/target")
        assert s.tasks["v1-task-001"]["inputs"]["static"]["target_path"] == "/workspace/target"


class TestSetFileManifest:
    def test_sets_manifest(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.set_file_manifest(
            task_id="v1-task-001",
            read_first=[{"path": "main.py", "reason": "entry point"}],
            modify=[{"path": "fix.py", "reason": "target"}],
        )
        manifest = s.tasks["v1-task-001"]["inputs"]["file_manifest"]
        assert len(manifest["read_first"]) == 1
        assert len(manifest["modify"]) == 1

    def test_enforces_limits(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.set_file_manifest(
            task_id="v1-task-001",
            read_for_pattern=[{"path": f"f{i}.py", "reason": "r"} for i in range(10)],
        )
        manifest = s.tasks["v1-task-001"]["inputs"]["file_manifest"]
        assert len(manifest["read_for_pattern"]) == 2  # max 2


class TestSetVerification:
    def test_sets_tier_1(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.set_verification(
            task_id="v1-task-001", tier=1,
            config={"schema_validation": True, "required_output_fields": ["result"]},
        )
        assert s.tasks["v1-task-001"]["verification"]["tier_1"]["required_output_fields"] == ["result"]

    def test_rejects_invalid_tier(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        result = s.set_verification(task_id="v1-task-001", tier=4, config={})
        assert "error" in result


class TestFinalise:
    def _build_wasa_plan(self, s: PlanBuildingSession) -> None:
        s.add_task(
            description="Scan", agent="security.webapp.scanner.agent",
            instructions="Run scanners", domain_tags=["security"],
        )
        s.add_task(
            description="Triage", agent="security.webapp.triage.agent",
            instructions="Filter FPs", dependencies=["v1-task-001"],
        )
        s.add_task(
            description="Report", agent="security.webapp.reporter.agent",
            instructions="Write report", dependencies=["v1-task-002"],
        )

    def test_valid_plan_passes(self):
        s = _session()
        self._build_wasa_plan(s)
        result = s.finalise(summary="WASA scan", estimated_cost_usd=5.0, estimated_duration_seconds=120)
        assert result["valid"] is True
        assert s.finalised_plan is not None
        assert len(s.finalised_plan["tasks"]) == 3

    def test_empty_plan_fails(self):
        s = _session()
        result = s.finalise(summary="Empty", estimated_cost_usd=0, estimated_duration_seconds=0)
        assert result["valid"] is False
        assert "no tasks" in result["errors"][0].lower()

    def test_cycle_detected(self):
        s = _session()
        s.add_task(description="A", agent="security.webapp.scanner.agent", instructions="A")
        s.add_task(
            description="B", agent="security.webapp.triage.agent",
            instructions="B", dependencies=["v1-task-001"],
        )
        # Manually create a cycle
        s.tasks["v1-task-001"]["dependencies"] = ["v1-task-002"]
        result = s.finalise(summary="Cycle", estimated_cost_usd=1, estimated_duration_seconds=60)
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])

    def test_negative_cost_fails(self):
        s = _session()
        self._build_wasa_plan(s)
        result = s.finalise(summary="Bad", estimated_cost_usd=-1.0, estimated_duration_seconds=60)
        assert result["valid"] is False


class TestRefinementMode:
    def test_seeds_from_existing_plan(self):
        existing = {
            "tasks": [
                {"task_id": "v1-task-001", "agent": "security.webapp.scanner.agent",
                 "description": "Scan", "instructions": "Run scanners"},
                {"task_id": "v1-task-002", "agent": "security.webapp.triage.agent",
                 "description": "Triage", "instructions": "Filter"},
            ]
        }
        s = _session(current_plan=existing)
        assert len(s.tasks) == 2
        assert "v1-task-001" in s.tasks

    def test_new_tasks_continue_sequence(self):
        existing = {
            "tasks": [
                {"task_id": "v1-task-001", "agent": "security.webapp.scanner.agent",
                 "description": "Scan", "instructions": "X"},
            ]
        }
        s = _session(current_plan=existing)
        r = s.add_task(
            description="New", agent="security.webapp.triage.agent", instructions="Y",
        )
        assert r["task_id"] == "v1-task-002"


class TestRenderPlanSummary:
    def test_empty_plan(self):
        s = _session()
        assert "empty" in s.render_plan_summary().lower()

    def test_with_tasks(self):
        s = _session()
        s.add_task(description="Scan codebase", agent="security.webapp.scanner.agent", instructions="X")
        summary = s.render_plan_summary()
        assert "v1-task-001" in summary
        assert "scanner" in summary
