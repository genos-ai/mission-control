"""Tests for the remaining plan budget (Plan 88 step 88.0.7).

Every run starter passes the lifetime cap minus spend. A NULL ceiling means
the configured default cap, so it can be exhausted like any other ceiling.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.backend.services.mission_plan import remaining_plan_budget_usd
from modules.backend.temporal.config_snapshots import build_workflow_timeouts_snapshot
from modules.backend.temporal.plan_refine_models import PlanRefineInput


def _plan(ceiling: float | None, spent: float) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        mission_id=str(uuid.uuid4()),
        budget_usd_ceiling=ceiling,
        total_spent_usd=spent,
        gate_mode="autonomous",
    )


def test_remaining_uses_ceiling_minus_spent():
    assert remaining_plan_budget_usd(_plan(10.0, 7.0)) == 3.0


def test_remaining_null_ceiling_uses_default_minus_spent():
    with patch("modules.backend.services.mission_plan.get_default_budget_usd", return_value=5.0):
        assert remaining_plan_budget_usd(_plan(None, 2.0)) == 3.0


def test_plan_refine_input_budget_required():
    with pytest.raises(TypeError, match="mission_budget_usd"):
        PlanRefineInput(  # type: ignore[call-arg]
            mission_id=str(uuid.uuid4()),
            plan_id=str(uuid.uuid4()),
            instructions="refine it",
            user_id=str(uuid.uuid4()),
            timeouts=build_workflow_timeouts_snapshot(),
        )
