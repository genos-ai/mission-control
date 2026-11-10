"""handle_mission's first parameter is a label, not a MissionRun id (Plan 88 step 88.1.7).

The real run id travels only as the separate keyword-only mission_run_id
(default None), which tags the run's LLM ledger rows for finalise.
"""

import inspect

from modules.backend.agents.mission_control.mission_dispatch import handle_mission


def test_handle_mission_takes_execution_label():
    parameters = inspect.signature(handle_mission).parameters
    assert list(parameters)[0] == "execution_label"
    run_id = parameters["mission_run_id"]
    assert run_id.kind is inspect.Parameter.KEYWORD_ONLY
    assert run_id.default is None
