"""Deterministic Temporal workflow ids (Plan 88, contract 3.3.1)."""


def mission_run_workflow_id(mission_run_id: str) -> str:
    """The MissionRunWorkflow id for one mission run: one workflow per run."""
    return f"mission-run-{mission_run_id}"
