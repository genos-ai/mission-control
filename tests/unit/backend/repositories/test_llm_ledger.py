"""Plan 88 step 88.4.1: LlmLedgerRepository.sum_cost over raw rows and daily aggregates."""

from datetime import UTC, date, datetime

import pytest

from modules.backend.repositories.llm_ledger import LlmLedgerRepository
from tests.unit.backend.services.budget_fixtures import aggregate, call, mission_with_plan, run

NOV = datetime(2026, 11, 1, tzinfo=UTC)
DEC = datetime(2026, 12, 1, tzinfo=UTC)


async def test_sum_cost_filters_by_run_and_window(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(db_session, test_user.id)
    other_id, _ = await mission_with_plan(db_session, test_user.id)
    run_id = await run(db_session, mission_id, plan_id)
    await call(db_session, mission_id, 0.25, datetime(2026, 10, 31, 23, 59, tzinfo=UTC))
    await call(db_session, mission_id, 0.50, NOV, run_id=run_id)
    await call(db_session, mission_id, 1.00, datetime(2026, 11, 20, tzinfo=UTC))
    await call(db_session, mission_id, 2.00, DEC)
    await call(db_session, other_id, 8.00, NOV)
    repo = LlmLedgerRepository(db_session)

    assert await repo.sum_cost(mission_id, since=None, until=None) == pytest.approx(3.75)
    assert await repo.sum_cost(mission_id, since=NOV, until=DEC) == pytest.approx(1.5)
    assert await repo.sum_cost(
        mission_id, since=None, until=None, mission_run_id=run_id
    ) == pytest.approx(0.5)
    assert await repo.sum_cost(
        mission_id, since=DEC, until=None, mission_run_id=run_id
    ) == pytest.approx(0.0)


async def test_sum_cost_adds_aggregates_only_without_run(db_session, test_user):
    mission_id, plan_id = await mission_with_plan(db_session, test_user.id)
    run_id = await run(db_session, mission_id, plan_id)
    await call(db_session, mission_id, 0.50, NOV, run_id=run_id)
    await aggregate(db_session, mission_id, date(2026, 10, 31), 1.0)
    await aggregate(db_session, mission_id, date(2026, 11, 2), 2.0)
    await aggregate(db_session, mission_id, date(2026, 12, 1), 4.0)
    await aggregate(db_session, None, date(2026, 11, 2), 16.0)
    repo = LlmLedgerRepository(db_session)

    assert await repo.sum_cost(mission_id, since=None, until=None) == pytest.approx(7.5)
    assert await repo.sum_cost(mission_id, since=NOV, until=DEC) == pytest.approx(2.5)
    assert await repo.sum_cost(
        mission_id, since=None, until=None, mission_run_id=run_id
    ) == pytest.approx(0.5)
