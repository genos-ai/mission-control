"""Token economics service — queries for cost dashboards (Plan 60).

All queries read from the llm_calls table. Supports two scoping modes:
  - Platform-wide: filtered by timeframe (admin dashboard)
  - Per-mission: filtered by mission_id (mission costs tab)
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.llm_call import LlmCall
from modules.backend.services.base import BaseService

logger = get_logger(__name__)

_TIMEFRAME_DELTA = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _since(timeframe: str) -> datetime:
    delta = _TIMEFRAME_DELTA.get(timeframe, timedelta(days=7))
    return utc_now() - delta


def _scope_filters(*, timeframe: str | None = None, mission_id: str | None = None) -> list:
    """Return WHERE clauses for scoping. Supports both together."""
    conditions = []
    if mission_id:
        conditions.append(LlmCall.mission_id == mission_id)
    if timeframe:
        conditions.append(LlmCall.created_at >= _since(timeframe))
    if not conditions:
        conditions.append(LlmCall.created_at >= _since("7d"))
    return conditions


class TokenEconomicsService(BaseService):
    """Dashboard queries for token economics.

    All query methods accept either `timeframe` (platform-wide) or
    `mission_id` (per-mission). Pass one or the other, not both.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_token_breakdown(
        self,
        *,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Per-agent token breakdown with cost attribution."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        stmt = (
            select(
                LlmCall.agent_name,
                func.count().label("call_count"),
                func.sum(LlmCall.input_tokens).label("input_tokens"),
                func.sum(LlmCall.output_tokens).label("output_tokens"),
                func.sum(LlmCall.cache_read_tokens).label("cache_read_tokens"),
                func.sum(LlmCall.cache_write_5m_tokens + LlmCall.cache_write_1h_tokens).label(
                    "cache_write_tokens"
                ),
                func.sum(LlmCall.thinking_tokens).label("thinking_tokens"),
                func.sum(LlmCall.cost_usd).label("total_cost_usd"),
            )
            .where(*scope)
            .group_by(LlmCall.agent_name)
            .order_by(func.sum(LlmCall.cost_usd).desc())
        )
        result = await self._session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    async def get_cache_performance(
        self,
        *,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Per-agent cache hit rate and savings."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        total_input = LlmCall.cache_read_tokens + LlmCall.input_tokens
        stmt = (
            select(
                LlmCall.agent_name,
                func.sum(LlmCall.input_tokens).label("total_input_tokens"),
                func.sum(LlmCall.cache_read_tokens).label("cache_read_tokens"),
                func.sum(LlmCall.cache_write_5m_tokens).label("cache_write_5m_tokens"),
                func.sum(LlmCall.cache_write_1h_tokens).label("cache_write_1h_tokens"),
                case(
                    (
                        func.sum(total_input) > 0,
                        cast(func.sum(LlmCall.cache_read_tokens), Float)
                        / cast(func.sum(total_input), Float),
                    ),
                    else_=0.0,
                ).label("cache_hit_rate"),
                case(
                    (
                        func.sum(LlmCall.cache_read_tokens) > 0,
                        cast(
                            func.sum(LlmCall.cache_write_5m_tokens + LlmCall.cache_write_1h_tokens),
                            Float,
                        )
                        / cast(func.sum(LlmCall.cache_read_tokens), Float),
                    ),
                    else_=0.0,
                ).label("write_to_read_ratio"),
            )
            .where(*scope)
            .group_by(LlmCall.agent_name)
            .order_by(func.sum(LlmCall.cache_read_tokens).desc())
        )
        result = await self._session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    async def get_cost_timeline(
        self,
        *,
        timeframe: str = "7d",
        group_by: str = "agent",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hourly cost for time-series chart."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        group_col = LlmCall.agent_name if group_by == "agent" else LlmCall.model
        hour_trunc = func.date_trunc("hour", LlmCall.created_at)
        stmt = (
            select(
                hour_trunc.label("timestamp"),
                group_col.label("group"),
                func.sum(LlmCall.cost_usd).label("cost_usd"),
            )
            .where(*scope)
            .group_by(hour_trunc, group_col)
            .order_by(hour_trunc)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "group": row.group,
                "cost_usd": float(row.cost_usd or 0),
            }
            for row in result.all()
        ]

    async def get_expensive_calls(
        self,
        *,
        limit: int = 20,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Top N most expensive individual LLM calls."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        stmt = (
            select(
                LlmCall.id,
                LlmCall.created_at,
                LlmCall.agent_name,
                LlmCall.model,
                LlmCall.input_tokens,
                LlmCall.output_tokens,
                LlmCall.cache_read_tokens,
                LlmCall.thinking_tokens,
                LlmCall.cost_usd,
                LlmCall.latency_ms,
            )
            .where(*scope)
            .order_by(LlmCall.cost_usd.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            {
                **dict(row._mapping),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.all()
        ]

    async def get_model_distribution(
        self,
        *,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call count and cost percentage per model."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        stmt = (
            select(
                LlmCall.model,
                func.count().label("call_count"),
                func.sum(LlmCall.cost_usd).label("cost_usd"),
            )
            .where(*scope)
            .group_by(LlmCall.model)
            .order_by(func.sum(LlmCall.cost_usd).desc())
        )
        result = await self._session.execute(stmt)
        rows = [dict(row._mapping) for row in result.all()]

        total_calls = sum(r["call_count"] for r in rows) or 1
        total_cost = sum(float(r["cost_usd"] or 0) for r in rows) or 1.0

        for row in rows:
            row["call_pct"] = round(row["call_count"] / total_calls * 100, 1)
            row["cost_pct"] = round(float(row["cost_usd"] or 0) / total_cost * 100, 1)

        return rows

    async def get_output_efficiency(
        self,
        *,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Per-agent output/input ratio — high = expensive."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        from modules.backend.core.config import get_app_config

        thresholds = get_app_config().cost.output_efficiency

        stmt = (
            select(
                LlmCall.agent_name,
                func.avg(LlmCall.input_tokens).label("avg_input_tokens"),
                func.avg(LlmCall.output_tokens).label("avg_output_tokens"),
            )
            .where(*scope)
            .group_by(LlmCall.agent_name)
            .having(func.avg(LlmCall.input_tokens) > 0)
            .order_by((func.avg(LlmCall.output_tokens) / func.avg(LlmCall.input_tokens)).desc())
        )
        result = await self._session.execute(stmt)
        rows = []
        for row in result.all():
            avg_in = float(row.avg_input_tokens or 1)
            avg_out = float(row.avg_output_tokens or 0)
            ratio = round(avg_out / avg_in, 2) if avg_in > 0 else 0.0
            flag = "ok"
            if ratio >= thresholds.critical_threshold:
                flag = "critical"
            elif ratio >= thresholds.high_threshold:
                flag = "high"
            rows.append(
                {
                    "agent_name": row.agent_name,
                    "avg_input_tokens": round(avg_in),
                    "avg_output_tokens": round(avg_out),
                    "output_input_ratio": ratio,
                    "flag": flag,
                }
            )
        return rows

    async def get_summary(
        self,
        *,
        timeframe: str = "7d",
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Summary stats for the top-level cards."""
        scope = _scope_filters(timeframe=timeframe, mission_id=mission_id)
        stmt = select(
            func.sum(LlmCall.cost_usd).label("total_cost"),
            func.count().label("total_calls"),
            func.avg(LlmCall.cost_usd).label("avg_cost_per_call"),
            case(
                (
                    func.sum(LlmCall.cache_read_tokens + LlmCall.input_tokens) > 0,
                    cast(func.sum(LlmCall.cache_read_tokens), Float)
                    / cast(func.sum(LlmCall.cache_read_tokens + LlmCall.input_tokens), Float),
                ),
                else_=0.0,
            ).label("cache_hit_rate"),
            case(
                (
                    func.sum(LlmCall.input_tokens) > 0,
                    cast(func.sum(LlmCall.output_tokens), Float)
                    / cast(func.sum(LlmCall.input_tokens), Float),
                ),
                else_=0.0,
            ).label("output_ratio"),
        ).where(*scope)
        row = (await self._session.execute(stmt)).one()
        return {
            "total_cost_usd": round(float(row.total_cost or 0), 4),
            "total_calls": row.total_calls or 0,
            "avg_cost_per_call": round(float(row.avg_cost_per_call or 0), 6),
            "cache_hit_rate": round(float(row.cache_hit_rate or 0), 4),
            "output_ratio": round(float(row.output_ratio or 0), 2),
        }
