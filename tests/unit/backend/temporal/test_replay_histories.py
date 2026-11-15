"""Replay recorded MissionRunWorkflow histories (Plan 88 step 88.2.9).

Every history under tests/fixtures/temporal_histories/mission_run is replayed
against the current workflow code with the sandboxed Replayer; a code change
that alters the command sequence fails here with a NondeterminismError. No
Temporal server is needed. Later patch steps add their ids to REQUIRED
(88.2.8 rule 5).
"""

from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from modules.backend.core.config import find_project_root
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow

HISTORY_DIR = find_project_root() / Path("tests/fixtures/temporal_histories/mission_run")
FILES = sorted(HISTORY_DIR.glob("*.json"))
REQUIRED = frozenset(
    {
        "two_layer_success",
        "wait_then_signal",
        "can_first_run",
        "can_carried_state_run",
        "verification_failed_continue",
        "cancelled_mid_layer",
        "max_duration_stop",
        "p88-run-memory",  # 88.3.8: the patched branch; the seven above replay the old one
        "p88-lifecycle-signals",  # 88.4.5: pause, resume and the run-end notification
    }
)


def test_histories_present() -> None:
    assert {f.stem for f in FILES} >= REQUIRED


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
async def test_replay(path: Path) -> None:
    history = WorkflowHistory.from_json(path.stem, path.read_text())
    await Replayer(workflows=[MissionRunWorkflow]).replay_workflow(history)
