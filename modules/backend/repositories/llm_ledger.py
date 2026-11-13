"""
LLM Ledger Repository (Plan 88, contract 3.5.2).

Cost sums over the LLM call ledger: raw ``llm_calls`` rows plus, for
mission-wide windows, the ``llm_call_daily_aggregates`` rollup (3.1.11).
88.5.3 adds the rollup methods.
"""

from datetime import datetime

from sqlalchemy import func, select

from modules.backend.models.llm_call import LlmCall
from modules.backend.models.llm_call_daily_aggregate import LlmCallDailyAggregate
from modules.backend.repositories.base import BaseRepository


class LlmLedgerRepository(BaseRepository[LlmCall]):
    """Read-only cost queries over llm_calls and llm_call_daily_aggregates."""

    model = LlmCall

    async def sum_cost(
        self,
        mission_id: str,
        *,
        since: datetime | None,
        until: datetime | None,
        mission_run_id: str | None = None,
    ) -> float:
        """Mission spend in [since, until), optionally for one run.

        Run-scoped sums read raw rows only: retention never rolls up rows of a
        non-terminal run (3.1.11). Mission-wide sums add the daily aggregates,
        whose ``day`` window is ``since.date() <= day < until.date()``.
        """
        raw = select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(
            LlmCall.mission_id == mission_id
        )
        if mission_run_id is not None:
            raw = raw.where(LlmCall.mission_run_id == mission_run_id)
        if since is not None:
            raw = raw.where(LlmCall.created_at >= since)
        if until is not None:
            raw = raw.where(LlmCall.created_at < until)
        total = float((await self.session.execute(raw)).scalar_one())
        if mission_run_id is not None:
            return total

        rolled = select(func.coalesce(func.sum(LlmCallDailyAggregate.cost_usd), 0.0)).where(
            LlmCallDailyAggregate.mission_id == mission_id
        )
        if since is not None:
            rolled = rolled.where(LlmCallDailyAggregate.day >= since.date())
        if until is not None:
            rolled = rolled.where(LlmCallDailyAggregate.day < until.date())
        return total + float((await self.session.execute(rolled)).scalar_one())
