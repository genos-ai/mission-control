"""handle_mission's first parameter is a label, not a MissionRun id (Plan 88 step 88.1.7)."""

import inspect

from modules.backend.agents.mission_control.mission_dispatch import handle_mission


def test_handle_mission_takes_execution_label():
    parameters = list(inspect.signature(handle_mission).parameters)
    assert parameters[0] == "execution_label"
    assert "mission_run_id" not in parameters
