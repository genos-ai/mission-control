"""Unit tests for the Director's workflow and knowledge tool implementations.

Covers the logic that was previously unreachable inside
`register_workflow_tools` and `register_knowledge_tools`. No LLM and no
agent runtime is involved (P11).
"""

from __future__ import annotations

from datetime import datetime, timezone

from modules.backend.agents.mission.director.tool_helpers import CompactResult
from modules.backend.agents.mission.director.tools._fork import (
    BackgroundRecordRef,
    build_fork_workflow_id,
)
from modules.backend.agents.mission.director.tools.capture_mission_intent import build_scope
from modules.backend.agents.mission.director.tools.get_artifacts import _as_artifact
from modules.backend.agents.mission.director.tools.list_workflows import merge_with_precedence
from modules.backend.agents.mission.director.tools.run_workflow import strip_workflow_suffix


class _WorkflowDef:
    def __init__(self, name, description="does a thing", version=1, trigger="manual", steps=3):
        self.name = name
        self.description = description
        self.version = version
        self.trigger_type = trigger
        self.step_count = steps


class TestMergeWithPrecedence:
    def test_mission_workflow_shadows_the_system_template(self):
        """A mission defines a workflow of the same name to override the
        template, so the template must not also be listed."""
        merged = merge_with_precedence(
            [_WorkflowDef("ops.health-check")],
            [_WorkflowDef("ops.health-check"), _WorkflowDef("system.audit")],
        )
        names = [w["name"] for w in merged]
        assert names == ["ops.health-check", "system.audit"]
        assert merged[0]["scope"] == "mission"
        assert merged[1]["scope"] == "system"

    def test_lists_mission_workflows_first(self):
        merged = merge_with_precedence([_WorkflowDef("m1")], [_WorkflowDef("s1")])
        assert [w["scope"] for w in merged] == ["mission", "system"]

    def test_handles_no_mission_workflows(self):
        merged = merge_with_precedence([], [_WorkflowDef("s1")])
        assert len(merged) == 1
        assert merged[0]["scope"] == "system"

    def test_handles_nothing_at_all(self):
        assert merge_with_precedence([], []) == []

    def test_carries_the_descriptive_fields_through(self):
        merged = merge_with_precedence([_WorkflowDef("m1", "check health", 4, "cron", 7)], [])
        assert merged[0]["description"] == "check health"
        assert merged[0]["version"] == 4
        assert merged[0]["trigger_type"] == "cron"
        assert merged[0]["step_count"] == 7


class TestStripWorkflowSuffix:
    def test_strips_a_trailing_suffix(self):
        assert strip_workflow_suffix("system.platform-audit.workflow") == "system.platform-audit"

    def test_leaves_a_bare_name_alone(self):
        assert strip_workflow_suffix("system.platform-audit") == "system.platform-audit"

    def test_only_strips_from_the_end(self):
        assert strip_workflow_suffix("a.workflow.b") == "a.workflow.b"

    def test_strips_only_once(self):
        assert strip_workflow_suffix("a.workflow.workflow") == "a.workflow"


class TestBuildForkWorkflowId:
    def test_includes_the_lowercased_workflow_and_record_prefix(self):
        wid = build_fork_workflow_id("RunWorkflowWorkflow", "abcdef123456789")
        assert wid.startswith("tool-fork-runworkflowworkflow-abcdef123456-")

    def test_truncates_a_long_record_id(self):
        wid = build_fork_workflow_id("X", "0123456789abcdefghij")
        assert "0123456789ab-" in wid
        assert "cdefghij" not in wid

    def test_is_unique_per_call(self):
        """The random suffix keeps repeated forks of one record distinct."""
        a = build_fork_workflow_id("X", "rec")
        b = build_fork_workflow_id("X", "rec")
        assert a != b


class TestBackgroundRecordRef:
    def test_carries_only_the_id(self):
        """The ORM instance is detached after the service commits, so only
        the id can safely cross the boundary."""
        assert BackgroundRecordRef("rec-1").id == "rec-1"

    def test_is_frozen(self):
        ref = BackgroundRecordRef("rec-1")
        try:
            ref.id = "rec-2"
        except Exception:
            return
        raise AssertionError("BackgroundRecordRef should be immutable")


class TestBuildScope:
    def test_omits_both_sides_when_unset(self):
        """Absent is not the same as explicitly empty, so nothing is stored."""
        assert build_scope(None, None) == {}

    def test_omits_empty_lists(self):
        assert build_scope([], []) == {}

    def test_includes_only_the_side_given(self):
        assert build_scope(["auth"], None) == {"in": ["auth"]}
        assert build_scope(None, ["billing"]) == {"out": ["billing"]}

    def test_includes_both_sides(self):
        assert build_scope(["auth"], ["billing"]) == {"in": ["auth"], "out": ["billing"]}


class _Artifact:
    def __init__(self, content_text="body", created_at=None):
        self.id = "art-1"
        self.artifact_type = "research_report"
        self.title = "Findings"
        self.content_text = content_text
        self.created_at = created_at or datetime(2026, 9, 15, tzinfo=timezone.utc)


class TestAsArtifact:
    def test_truncates_the_body_to_the_preview_length(self):
        """Artifact bodies are full reports and would otherwise dominate
        the Director's context."""
        shaped = _as_artifact(_Artifact(content_text="x" * 5000))
        assert len(shaped["content_preview"]) == 2000

    def test_keeps_a_short_body_intact(self):
        assert _as_artifact(_Artifact(content_text="short"))["content_preview"] == "short"

    def test_tolerates_a_null_body(self):
        assert _as_artifact(_Artifact(content_text=None))["content_preview"] == ""

    def test_carries_identity_fields(self):
        shaped = _as_artifact(_Artifact())
        assert shaped["id"] == "art-1"
        assert shaped["artifact_type"] == "research_report"
        assert shaped["title"] == "Findings"


class TestNoArtifactsPayload:
    def test_absence_is_a_status_not_an_error(self):
        """get_artifacts reports "none found" under status/message rather
        than error, so the model does not treat it as a failure."""
        result = CompactResult({"status": "no_artifacts", "message": "No artifacts found."})
        assert "error" not in result.payload
        assert result.payload["status"] == "no_artifacts"
