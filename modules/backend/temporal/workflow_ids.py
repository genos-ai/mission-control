"""Deterministic Temporal workflow ids (Plan 88, contract 3.3.1)."""


def mission_run_workflow_id(plan_id: str) -> str:
    """Phase 0: one MissionRunWorkflow per plan. 88.1.7 changes the parameter to mission_run_id."""
    return f"mission-run-{plan_id}"
