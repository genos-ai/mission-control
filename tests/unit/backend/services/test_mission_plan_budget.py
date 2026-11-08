"""Tests for the remaining plan budget (Plan 88 step 88.0.7).

Every run starter passes the lifetime cap minus spend. A NULL ceiling means
the configured default cap, so it can be exhausted like any other ceiling.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.exceptions import ValidationError
from modules.backend.services import mission_plan_dispatch
from modules.backend.services.mission_plan import remaining_plan_budget_usd
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


@pytest.mark.parametrize("spent", [5.0, 6.0])
async def test_dispatch_approved_rejects_exhausted_null_ceiling(spent: float):
    plan = _plan(None, spent)
    orchestrator = SimpleNamespace(
        _repo=SimpleNamespace(get_by_id=AsyncMock(return_value=plan)),
        _session=SimpleNamespace(),
        _event_bus=MagicMock(),
    )

    with (
        patch(
            "modules.backend.services.mission_plan.get_default_budget_usd",
            return_value=5.0,
        ),
        patch(
            "modules.backend.services.mission_plan_crash_recovery.reconcile_orphaned_task_states",
            AsyncMock(),
        ),
        patch.object(
            mission_plan_dispatch.mission_plan_taskio,
            "materialize_task_plan",
            MagicMock(),
        ),
        pytest.raises(ValidationError, match="budget exhausted"),
    ):
        await mission_plan_dispatch.dispatch_approved(orchestrator, plan.id, str(uuid.uuid4()))


def test_plan_refine_input_budget_required():
    with pytest.raises(TypeError):
        PlanRefineInput(  # type: ignore[call-arg]
            mission_id=str(uuid.uuid4()),
            plan_id=str(uuid.uuid4()),
            instructions="refine it",
            user_id=str(uuid.uuid4()),
        )
