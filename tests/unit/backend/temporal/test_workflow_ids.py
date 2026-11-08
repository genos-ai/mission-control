"""Tests for deterministic Temporal workflow ids (Plan 88 step 88.0.3)."""

import uuid

from modules.backend.temporal.workflow_ids import mission_run_workflow_id


def test_mission_run_workflow_id_uses_full_plan_uuid():
    plan_id = str(uuid.uuid4())
    assert len(plan_id) == 36
    assert mission_run_workflow_id(plan_id) == "mission-run-" + plan_id
