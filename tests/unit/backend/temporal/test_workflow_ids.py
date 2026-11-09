"""Tests for deterministic Temporal workflow ids (Plan 88 steps 88.0.3, 88.1.7)."""

import uuid

from modules.backend.temporal.workflow_ids import mission_run_workflow_id


def test_mission_run_workflow_id_uses_full_run_uuid():
    mission_run_id = str(uuid.uuid4())
    assert len(mission_run_id) == 36
    assert mission_run_workflow_id(mission_run_id) == "mission-run-" + mission_run_id
