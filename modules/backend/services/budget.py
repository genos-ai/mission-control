"""
Budget Service (Plan 88 step 88.4.1, contracts 3.5.1).

Caps live on the mission plan; spend is read from the LLM ledger
(``llm_calls`` plus ``llm_call_daily_aggregates``). Three caps apply:
per run, per UTC calendar month and an optional lifetime cap. Enforcement in
runs, claims and agent execution arrives in 88.4.6.
"""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.utils import utc_now
from modules.backend.models.mission import MissionPauseReason
from modules.backend.models.mission_plan import MissionPlan
from modules.backend.repositories.llm_ledger import LlmLedgerRepository
from modules.backend.repositories.mission_plan import MissionPlanRepository
from modules.backend.repositories.mission_run import MissionRunRepository
from modules.backend.schemas.budget import BudgetCapsUpdate, BudgetCheckResult, BudgetStatus
from modules.backend.services.base import BaseService


def _month_window(now: datetime) -> tuple[datetime, datetime]:
    """The UTC calendar month containing ``now`` as [start, next month's start)."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _breach(
    *,
    run_spent: float,
    run_cap: float,
    month_spent: float,
    per_month: float,
    lifetime_spent: float,
    lifetime: float | None,
) -> MissionPauseReason | None:
    """The first breached cap: run, then month, then lifetime."""
    if run_spent >= run_cap:
        return MissionPauseReason.BUDGET_RUN_CAP
    return _mission_breach(
        month_spent=month_spent,
        per_month=per_month,
        lifetime_spent=lifetime_spent,
        lifetime=lifetime,
    )


def _mission_breach(
    *, month_spent: float, per_month: float, lifetime_spent: float, lifetime: float | None
) -> MissionPauseReason | None:
    if month_spent >= per_month:
        return MissionPauseReason.BUDGET_MONTHLY_CAP
    if lifetime is not None and lifetime_spent >= lifetime:
        return MissionPauseReason.BUDGET_LIFETIME_CAP
    return None


class BudgetService(BaseService):
    """Mission budget caps and spend against them."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._plans = MissionPlanRepository(session)
        self._runs = MissionRunRepository(session)
        self._ledger = LlmLedgerRepository(session)

    async def _plan(self, mission_id: str) -> MissionPlan:
        return await self._plans.get_by_mission_id_required(mission_id, load_tasks=False)

    async def _mission_spend(self, mission_id: str) -> tuple[float, float]:
        """(month spend, lifetime spend) for the mission."""
        month_start, month_end = _month_window(utc_now())
        month = await self._ledger.sum_cost(mission_id, since=month_start, until=month_end)
        lifetime = await self._ledger.sum_cost(mission_id, since=None, until=None)
        return month, lifetime

    async def get_status(self, mission_id: str) -> BudgetStatus:
        """Caps, month, lifetime and active-run spend, and the first breached cap."""
        plan = await self._plan(mission_id)
        month_spent, lifetime_spent = await self._mission_spend(mission_id)
        active = await self._runs.get_active_for_mission(mission_id)
        # With no active run the spend is 0 against a positive cap: no run breach.
        run_spent = 0.0
        run_cap = plan.budget_per_run_usd
        if active is not None:
            run_spent = await self._ledger.sum_cost(
                mission_id, since=None, until=None, mission_run_id=active.id
            )
            run_cap = (
                active.budget_cap_usd
                if active.budget_cap_usd is not None
                else plan.budget_per_run_usd
            )
        breach = _breach(
            run_spent=run_spent,
            run_cap=run_cap,
            month_spent=month_spent,
            per_month=plan.budget_per_month_usd,
            lifetime_spent=lifetime_spent,
            lifetime=plan.budget_lifetime_usd,
        )
        return BudgetStatus(
            per_run_usd=plan.budget_per_run_usd,
            per_month_usd=plan.budget_per_month_usd,
            lifetime_usd=plan.budget_lifetime_usd,
            month_spent_usd=month_spent,
            lifetime_spent_usd=lifetime_spent,
            active_run_spent_usd=run_spent,
            breach=breach,
        )

    async def check_run(self, run_id: str) -> BudgetCheckResult:
        """This run's spend against coalesce(run cap snapshot, plan cap) and the mission caps."""
        run = await self._runs.get_by_id(run_id)
        mission_id = run.mission_id
        plan = await self._plan(mission_id)
        run_cap = run.budget_cap_usd if run.budget_cap_usd is not None else plan.budget_per_run_usd
        run_spent = await self._ledger.sum_cost(
            mission_id, since=None, until=None, mission_run_id=run_id
        )
        month_spent, lifetime_spent = await self._mission_spend(mission_id)
        candidates = [run_cap - run_spent, plan.budget_per_month_usd - month_spent]
        if plan.budget_lifetime_usd is not None:
            candidates.append(plan.budget_lifetime_usd - lifetime_spent)
        return BudgetCheckResult(
            run_spent_usd=run_spent,
            month_spent_usd=month_spent,
            lifetime_spent_usd=lifetime_spent,
            headroom_usd=max(0.0, min(candidates)),
            breach=_breach(
                run_spent=run_spent,
                run_cap=run_cap,
                month_spent=month_spent,
                per_month=plan.budget_per_month_usd,
                lifetime_spent=lifetime_spent,
                lifetime=plan.budget_lifetime_usd,
            ),
        )

    @staticmethod
    def mission_cap_breach(status: BudgetStatus) -> MissionPauseReason | None:
        """The breached monthly or lifetime cap, ignoring the run cap."""
        return _mission_breach(
            month_spent=status.month_spent_usd,
            per_month=status.per_month_usd,
            lifetime_spent=status.lifetime_spent_usd,
            lifetime=status.lifetime_usd,
        )

    @staticmethod
    def validate_caps(per_run: float, per_month: float, lifetime: float | None) -> None:
        """Raise ValidationError naming the first cap rule the values break."""
        limits = get_app_config().missions.budgets
        if not 0 < per_run <= limits.max_per_run_usd:
            raise ValidationError(
                f"per-run cap must be greater than 0 and at most {limits.max_per_run_usd:.2f} USD"
            )
        if per_month < per_run:
            raise ValidationError("per-month cap must be at least the per-run cap")
        if per_month > limits.max_per_month_usd:
            raise ValidationError(
                f"per-month cap must be at most {limits.max_per_month_usd:.2f} USD"
            )
        if lifetime is not None and lifetime <= 0:
            raise ValidationError("lifetime cap must be greater than 0 when set")

    async def update_caps(
        self, mission_id: str, data: BudgetCapsUpdate, user_id: str
    ) -> BudgetStatus:
        """Write the plan's caps and return the new status. Never resumes the mission."""
        self.validate_caps(data.per_run_usd, data.per_month_usd, data.lifetime_usd)
        plan = await self._plan(mission_id)
        plan.budget_per_run_usd = data.per_run_usd
        plan.budget_per_month_usd = data.per_month_usd
        plan.budget_lifetime_usd = data.lifetime_usd
        await self._session.commit()
        self._logger.info(
            "Mission budget caps updated",
            extra={
                "mission_id": mission_id,
                "user_id": user_id,
                "per_run_usd": data.per_run_usd,
                "per_month_usd": data.per_month_usd,
                "lifetime_usd": data.lifetime_usd,
            },
        )
        return await self.get_status(mission_id)
