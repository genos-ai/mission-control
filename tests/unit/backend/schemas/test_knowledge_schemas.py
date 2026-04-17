"""
Unit tests for knowledge platform Pydantic schemas.

Pure validation tests — no database, no mocks.
"""

import pytest
from pydantic import ValidationError

from modules.backend.schemas.knowledge import Evidence, KnowledgeEntry
from modules.backend.schemas.mission_intent import MissionIntentCreate
from modules.backend.schemas.mission_learning import (
    MissionLearningCreate,
    MissionLearningFilter,
)


# ── Evidence ─────────────────────────────────────────────────


class TestEvidence:
    def test_defaults_empty(self):
        e = Evidence()
        assert e.task_attempt_ids == []
        assert e.execution_ids == []
        assert e.failure_tiers == []
        assert e.artifact_ids == []

    def test_with_data(self):
        e = Evidence(
            task_attempt_ids=["a", "b"],
            execution_ids=["c"],
            failure_tiers=[1, 2],
        )
        assert len(e.task_attempt_ids) == 2
        assert e.failure_tiers == [1, 2]

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            Evidence(task_attempt_ids=[], unknown_field="oops")

    def test_no_storage_cap(self):
        """Evidence is uncapped — render pagination is a UI concern."""
        ids = [f"id-{i}" for i in range(1000)]
        e = Evidence(task_attempt_ids=ids)
        assert len(e.task_attempt_ids) == 1000


# ── KnowledgeEntry ───────────────────────────────────────────


class TestKnowledgeEntry:
    def test_minimal(self):
        e = KnowledgeEntry(
            id="1", kind="learning", source_table="mission_learnings",
            title="test", body="body",
        )
        assert e.kind == "learning"
        assert e.confidence is None
        assert e.distance is None

    def test_with_optional_fields(self):
        e = KnowledgeEntry(
            id="1", kind="decision", source_table="mission_decisions",
            title="test", body="body", confidence=0.85, distance=0.123,
            domain_tags=["auth"], mission_id="m-1",
        )
        assert e.confidence == 0.85
        assert e.distance == 0.123


# ── MissionIntentCreate ──────────────────────────────────────


class TestMissionIntentCreate:
    def test_valid(self):
        i = MissionIntentCreate(
            intent="Build the auth module",
            source="user_cli",
            reason="Initial intent",
        )
        assert i.intent == "Build the auth module"

    def test_empty_intent_rejected(self):
        with pytest.raises(ValidationError):
            MissionIntentCreate(intent="", source="user_cli", reason="test")

    def test_scope_defaults_empty(self):
        i = MissionIntentCreate(
            intent="test", source="system", reason="test",
        )
        assert i.scope == {}

    def test_scope_with_data(self):
        i = MissionIntentCreate(
            intent="test", source="user_chat", reason="test",
            scope={"in": ["auth"], "out": ["frontend"]},
        )
        assert i.scope["in"] == ["auth"]

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            MissionIntentCreate(
                intent="test", source="system", reason="test",
                unknown="bad",
            )


# ── MissionLearningCreate ────────────────────────────────────


class TestMissionLearningCreate:
    def test_valid(self):
        l = MissionLearningCreate(
            kind="failure_pattern",
            title="Agent X fails on Y",
            body="Details here",
            recommendation="Use Z instead",
        )
        assert l.kind == "failure_pattern"
        assert l.confidence == 0.0
        assert l.occurrence_count == 1

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            MissionLearningCreate(
                kind="failure_pattern",
                title="t", body="b", recommendation="r",
                confidence=1.5,
            )

    def test_occurrence_count_minimum(self):
        with pytest.raises(ValidationError):
            MissionLearningCreate(
                kind="failure_pattern",
                title="t", body="b", recommendation="r",
                occurrence_count=0,
            )

    def test_evidence_default(self):
        l = MissionLearningCreate(
            kind="retry_strategy",
            title="t", body="b", recommendation="r",
        )
        assert l.evidence.task_attempt_ids == []


# ── MissionLearningFilter ────────────────────────────────────


class TestMissionLearningFilter:
    def test_defaults(self):
        f = MissionLearningFilter()
        assert f.kind is None
        assert f.status == "active"
        assert f.platform_only is False
        assert f.limit == 20
        assert f.offset == 0

    def test_limit_bounds(self):
        with pytest.raises(ValidationError):
            MissionLearningFilter(limit=200)

    def test_offset_nonnegative(self):
        with pytest.raises(ValidationError):
            MissionLearningFilter(offset=-1)
