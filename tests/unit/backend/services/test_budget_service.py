"""Plan 88 step 88.4.1: BudgetService (real db_session, frozen clock)."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from modules.backend.core.exceptions import ValidationError
from modules.backend.models.mission import MissionPauseReason
from modules.backend.schemas.budget import BudgetCapsUpdate, BudgetStatus
from modules.backend.services.budget import BudgetService
from tests.unit.backend.services.budget_fixtures import call, mission_with_plan, run

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
THIS_MONTH = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
LAST_MONTH = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock():
    with patch("modules.backend.services.budget.utc_now", return_value=NOW):
        yield


def _status(**overrides) -> BudgetStatus:
    values = {
        "per_run_usd": 1.0,
        "per_month_usd": 2.0,
        "lifetime_usd": None,
        "month_spent_usd": 0.0,
        "lifetime_spent_usd": 0.0,
        "active_run_spent_usd": 0.0,
        "breach": None,
    }
    return BudgetStatus(**(values | overrides))


async def test_month_window_is_utc_calendar_month(db_session, test_user):
    mission_id, _ = await mission_with_plan(db_session, test_user.id)
    await call(db_session, mission_id, 1.0, datetime(2026, 10, 31, 23, 59, tzinfo=UTC))
    await call(db_session, mission_id, 2.0, datetime(2026, 11, 1, 0, 0, tzinfo=UTC))
    await call(db_session, mission_id, 4.0, datetime(2026, 12, 1, 0, 0, tzinfo=UTC))

    status = await BudgetService(db_session).get_status(mission_id)

    assert status.month_spent_usd == pytest.approx(2.0)
    assert status.lifetime_spent_usd == pytest.approx(7.0)


async def test_breach_precedence_run_then_month_then_lifetime(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(
        db_session, test_user.id, per_run=1.0, per_month=2.0, lifetime=2.5
    )
    run_id = await run(db_session, mission_id, plan_id, cap=1.0)
    await call(db_session, mission_id, 3.0, THIS_MONTH, run_id=run_id)

    service = BudgetService(db_session)
    status = await service.get_status(mission_id)
    check = await service.check_run(run_id)

    assert status.breach == MissionPauseReason.BUDGET_RUN_CAP
    assert status.active_run_spent_usd == pytest.approx(3.0)
    assert check.breach == MissionPauseReason.BUDGET_RUN_CAP


async def test_month_then_lifetime_breach_without_active_run(db_session, test_user):
    mission_id, _ = await mission_with_plan(
        db_session, test_user.id, per_run=1.0, per_month=2.0, lifetime=2.5
    )
    await call(db_session, mission_id, 2.0, LAST_MONTH)
    await call(db_session, mission_id, 1.0, THIS_MONTH)

    status = await BudgetService(db_session).get_status(mission_id)

    assert status.active_run_spent_usd == 0.0
    assert status.breach == MissionPauseReason.BUDGET_LIFETIME_CAP


def test_mission_cap_breach_ignores_run_cap():
    both = _status(active_run_spent_usd=5.0, month_spent_usd=2.0)
    run_only = _status(active_run_spent_usd=5.0)
    lifetime = _status(lifetime_usd=3.0, lifetime_spent_usd=3.0)

    assert BudgetService.mission_cap_breach(both) == MissionPauseReason.BUDGET_MONTHLY_CAP
    assert BudgetService.mission_cap_breach(run_only) is None
    assert BudgetService.mission_cap_breach(lifetime) == MissionPauseReason.BUDGET_LIFETIME_CAP


async def test_headroom_is_min_of_three_and_never_negative(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(
        db_session, test_user.id, per_run=4.0, per_month=10.0, lifetime=2.5
    )
    run_id = await run(db_session, mission_id, plan_id, cap=4.0)
    await call(db_session, mission_id, 1.0, THIS_MONTH, run_id=run_id)
    service = BudgetService(db_session)

    check = await service.check_run(run_id)
    assert check.headroom_usd == pytest.approx(1.5)
    assert check.breach is None

    await call(db_session, mission_id, 5.0, THIS_MONTH, run_id=run_id)
    check = await service.check_run(run_id)
    assert check.headroom_usd == 0.0
    assert check.run_spent_usd == pytest.approx(6.0)
    assert check.breach == MissionPauseReason.BUDGET_RUN_CAP


async def test_lifetime_none_ignored(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(
        db_session, test_user.id, per_run=4.0, per_month=10.0, lifetime=None
    )
    await call(db_session, mission_id, 500.0, LAST_MONTH)
    run_id = await run(db_session, mission_id, plan_id, cap=4.0)
    await call(db_session, mission_id, 1.0, THIS_MONTH, run_id=run_id)

    check = await BudgetService(db_session).check_run(run_id)

    assert check.lifetime_spent_usd == pytest.approx(501.0)
    assert check.headroom_usd == pytest.approx(3.0)
    assert check.breach is None


async def test_check_run_uses_plan_cap_when_snapshot_null(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(
        db_session, test_user.id, per_run=2.0, per_month=10.0
    )
    run_id = await run(db_session, mission_id, plan_id, cap=None)
    await call(db_session, mission_id, 0.5, THIS_MONTH, run_id=run_id)

    check = await BudgetService(db_session).check_run(run_id)

    assert check.headroom_usd == pytest.approx(1.5)


async def test_update_caps_writes_plan_and_returns_status(db_session, test_user):
    mission_id, _ = await mission_with_plan(db_session, test_user.id)

    status = await BudgetService(db_session).update_caps(
        mission_id,
        BudgetCapsUpdate(per_run_usd=3.0, per_month_usd=30.0, lifetime_usd=None),
        test_user.id,
    )

    assert (status.per_run_usd, status.per_month_usd, status.lifetime_usd) == (3.0, 30.0, None)


async def test_update_caps_rejects_month_below_run(db_session, test_user):
    mission_id, _ = await mission_with_plan(db_session, test_user.id)

    with pytest.raises(ValidationError, match="per-month cap must be at least the per-run cap"):
        await BudgetService(db_session).update_caps(
            mission_id,
            BudgetCapsUpdate(per_run_usd=5.0, per_month_usd=4.0, lifetime_usd=None),
            test_user.id,
        )


async def test_update_caps_rejects_above_configured_max(db_session, test_user):
    mission_id, _ = await mission_with_plan(db_session, test_user.id)
    service = BudgetService(db_session)

    with pytest.raises(ValidationError, match="per-run cap"):
        await service.update_caps(
            mission_id,
            BudgetCapsUpdate(per_run_usd=100.01, per_month_usd=200.0, lifetime_usd=None),
            test_user.id,
        )
    with pytest.raises(ValidationError, match="per-month cap must be at most"):
        await service.update_caps(
            mission_id,
            BudgetCapsUpdate(per_run_usd=5.0, per_month_usd=2000.01, lifetime_usd=None),
            test_user.id,
        )
