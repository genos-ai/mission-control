"""Plan 88 step 88.2.2: chat, plan-refine and tool-fork inputs require a timeouts snapshot."""

import pytest

from modules.backend.temporal.chat_models import ChatTurnInput
from modules.backend.temporal.plan_refine_models import PlanRefineInput
from modules.backend.temporal.tool_fork_models import (
    DesignWorkflowInput,
    RunWorkflowInput,
)

_CASES = [
    (ChatTurnInput, {"session_id": "s", "mission_id": "m", "message": "hi"}),
    (
        PlanRefineInput,
        {
            "mission_id": "m",
            "plan_id": "p",
            "instructions": "i",
            "user_id": "u",
            "mission_budget_usd": 1.0,
        },
    ),
    (
        DesignWorkflowInput,
        {
            "mission_id": "m",
            "session_id": "s",
            "execution_record_id": "r",
            "workflow_name": "w",
            "description": "d",
            "instructions": "i",
        },
    ),
    (
        RunWorkflowInput,
        {
            "mission_id": "m",
            "session_id": None,
            "execution_record_id": "r",
            "workflow_name": "w",
        },
    ),
]


@pytest.mark.parametrize(("cls", "kwargs"), _CASES, ids=lambda c: getattr(c, "__name__", ""))
def test_inputs_require_timeouts(cls: type, kwargs: dict) -> None:
    with pytest.raises(TypeError, match="timeouts"):
        cls(**kwargs)
