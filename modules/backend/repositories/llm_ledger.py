"""
LLM Ledger Repository (Plan 88, contract 3.5.2).

Cost sums over the LLM call ledger. 88.1.7 reads raw llm_calls only;
88.4.1 adds the daily aggregate table to sum_cost.
"""

from datetime import datetime

from sqlalchemy import func, select

from modules.backend.models.llm_call import LlmCall
from modules.backend.repositories.base import BaseRepository


class LlmLedgerRepository(BaseRepository[LlmCall]):
    """Read-only cost queries over llm_calls."""

    model = LlmCall

    async def sum_cost(
        self,
        mission_id: str,
        *,
        since: datetime | None,
        until: datetime | None,
        mission_run_id: str | None = None,
    ) -> float:
        """Sum of llm_calls.cost_usd for the mission, in [since, until), optionally for one run."""
        stmt = select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(
            LlmCall.mission_id == mission_id
        )
        if mission_run_id is not None:
            stmt = stmt.where(LlmCall.mission_run_id == mission_run_id)
        if since is not None:
            stmt = stmt.where(LlmCall.created_at >= since)
        if until is not None:
            stmt = stmt.where(LlmCall.created_at < until)
        return float((await self.session.execute(stmt)).scalar_one())
