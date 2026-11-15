"""write_run_digest's budget-aware narrator choice (Plan 88 step 88.4.6).

The digest agent narrates only when no cap is breached and the run's headroom
covers the digest agent's max_budget_usd; otherwise the digest is
DETERMINISTIC (narrator=None). RunMemoryService.write_digest is patched to
capture its kwargs; the session, budget service, registry and bus are patched.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from modules.backend.models.mission import MissionPauseReason
from modules.backend.schemas.budget import BudgetCheckResult
from modules.backend.temporal.mission_run_models import WriteDigestInput
from modules.backend.temporal.run_memory_activities import (
    generate_digest_narrative,
    write_run_digest,
)

_MOD = "modules.backend.temporal.run_memory_activities"
_DIGEST_MAX_BUDGET_USD = 0.25


def _check(headroom_usd: float, breach: MissionPauseReason | None = None) -> BudgetCheckResult:
    return BudgetCheckResult(
        run_spent_usd=1.0,
        month_spent_usd=1.0,
        lifetime_spent_usd=1.0,
        headroom_usd=headroom_usd,
        breach=breach,
    )


async def _narrator_for(check: BudgetCheckResult, *, force_deterministic: bool = False):
    @asynccontextmanager
    async def _session():
        yield SimpleNamespace(commit=AsyncMock())

    digest = SimpleNamespace(
        mission_id=str(uuid.uuid4()), id=str(uuid.uuid4()), generator="deterministic"
    )
    write_digest = AsyncMock(return_value=digest)
    budget = MagicMock()
    budget.return_value.check_run = AsyncMock(return_value=check)
    registry = MagicMock()
    registry.return_value.get.return_value = SimpleNamespace(max_budget_usd=_DIGEST_MAX_BUDGET_USD)
    with (
        patch(f"{_MOD}.get_async_session", _session),
        patch(f"{_MOD}.AsyncRedis.from_url", return_value=MagicMock(aclose=AsyncMock())),
        patch(f"{_MOD}.SessionEventBus"),
        patch(f"{_MOD}.BudgetService", budget),
        patch(f"{_MOD}.get_registry", registry),
        patch(f"{_MOD}.RunMemoryService") as memory,
        patch(f"{_MOD}.MissionLearningExtractor") as learnings,
    ):
        memory.return_value.write_digest = write_digest
        learnings.return_value.extract_for_mission = AsyncMock()
        await ActivityEnvironment().run(
            write_run_digest,
            WriteDigestInput(
                mission_run_id=str(uuid.uuid4()),
                status="succeeded",
                reason="objective_met",
                force_deterministic=force_deterministic,
            ),
        )
    return write_digest.await_args.kwargs["narrator"], budget


async def test_budget_breach_forces_deterministic():
    narrator, _ = await _narrator_for(_check(10.0, MissionPauseReason.BUDGET_MONTHLY_CAP))

    assert narrator is None


async def test_insufficient_headroom_forces_deterministic():
    narrator, _ = await _narrator_for(_check(_DIGEST_MAX_BUDGET_USD - 0.01))

    assert narrator is None


async def test_headroom_sufficient_passes_narrator():
    narrator, _ = await _narrator_for(_check(_DIGEST_MAX_BUDGET_USD))

    assert narrator is generate_digest_narrative


async def test_force_deterministic_skips_the_budget_read():
    narrator, budget = await _narrator_for(_check(10.0), force_deterministic=True)

    assert narrator is None
    budget.assert_not_called()
