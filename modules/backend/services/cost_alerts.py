"""Cost alerting service — budget enforcement and anomaly detection (Plan 60 Phase 3).

Checks are run before agent execution to enforce spend limits.
Alert thresholds come from config/settings/cost.yaml.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now
from modules.backend.models.llm_call import LlmCall
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


class CostAlert:
    """A triggered cost alert."""

    def __init__(self, rule: str, message: str, severity: str = "warning") -> None:
        self.rule = rule
        self.message = message
        self.severity = severity

    def __repr__(self) -> str:
        return f"<CostAlert rule={self.rule!r} severity={self.severity}>"


class CostAlertService(BaseService):
    """Evaluates cost alert rules against llm_calls data."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._config = get_app_config().cost

    async def check_alerts(self) -> list[CostAlert]:
        """Run all alert rules and return any that triggered."""
        alerts: list[CostAlert] = []

        hourly_alert = await self._check_hourly_spend()
        if hourly_alert:
            alerts.append(hourly_alert)

        agent_alerts = await self._check_per_agent_spend()
        alerts.extend(agent_alerts)

        cache_alert = await self._check_cache_hit_rate()
        if cache_alert:
            alerts.append(cache_alert)

        return alerts

    async def check_agent_budget(self, agent_name: str) -> CostAlert | None:
        """Check if a specific agent has exceeded its hourly budget.

        Called before agent execution to prevent runaway spend.
        Returns an alert if the agent should be throttled, None otherwise.
        """
        limit = self._config.alerts.per_agent_hourly_limit_usd
        since = utc_now() - timedelta(hours=1)

        stmt = select(func.sum(LlmCall.cost_usd)).where(
            LlmCall.agent_name == agent_name,
            LlmCall.created_at >= since,
        )
        result = await self._session.execute(stmt)
        spent = float(result.scalar() or 0)

        if spent >= limit:
            return CostAlert(
                rule="per_agent_hourly_limit",
                message=(
                    f"Agent '{agent_name}' has spent ${spent:.2f} in the last hour "
                    f"(limit: ${limit:.2f}). Possible runaway loop."
                ),
                severity="critical",
            )
        return None

    async def get_emergency_model(self) -> str | None:
        """Return the emergency downgrade model if hourly spend is exceeded.

        Returns the model name to downgrade to, or None if no downgrade needed.
        """
        limit = self._config.alerts.hourly_spend_limit_usd
        since = utc_now() - timedelta(hours=1)

        stmt = select(func.sum(LlmCall.cost_usd)).where(
            LlmCall.created_at >= since,
        )
        result = await self._session.execute(stmt)
        spent = float(result.scalar() or 0)

        if spent >= limit:
            logger.warning(
                "Hourly spend limit exceeded — emergency downgrade active",
                extra={"spent": spent, "limit": limit},
            )
            return self._config.emergency_downgrade_model
        return None

    async def _check_hourly_spend(self) -> CostAlert | None:
        limit = self._config.alerts.hourly_spend_limit_usd
        since = utc_now() - timedelta(hours=1)

        stmt = select(func.sum(LlmCall.cost_usd)).where(
            LlmCall.created_at >= since,
        )
        result = await self._session.execute(stmt)
        spent = float(result.scalar() or 0)

        if spent >= limit:
            return CostAlert(
                rule="hourly_spend_limit",
                message=f"Hourly spend ${spent:.2f} exceeds limit ${limit:.2f}",
                severity="critical",
            )
        return None

    async def _check_per_agent_spend(self) -> list[CostAlert]:
        limit = self._config.alerts.per_agent_hourly_limit_usd
        since = utc_now() - timedelta(hours=1)

        stmt = (
            select(
                LlmCall.agent_name,
                func.sum(LlmCall.cost_usd).label("spent"),
            )
            .where(LlmCall.created_at >= since)
            .group_by(LlmCall.agent_name)
            .having(func.sum(LlmCall.cost_usd) >= limit)
        )
        result = await self._session.execute(stmt)

        return [
            CostAlert(
                rule="per_agent_hourly_limit",
                message=(
                    f"Agent '{row.agent_name}' spent ${float(row.spent):.2f}/hour "
                    f"(limit: ${limit:.2f})"
                ),
                severity="warning",
            )
            for row in result.all()
        ]

    async def _check_cache_hit_rate(self) -> CostAlert | None:
        min_rate = self._config.alerts.min_cache_hit_rate
        since = utc_now() - timedelta(hours=1)

        stmt = select(
            func.sum(LlmCall.cache_read_tokens).label("reads"),
            func.sum(LlmCall.input_tokens).label("inputs"),
        ).where(LlmCall.created_at >= since)
        result = await self._session.execute(stmt)
        row = result.one()

        reads = float(row.reads or 0)
        inputs = float(row.inputs or 0)
        total = reads + inputs

        if total < 1000:
            return None  # Not enough data to evaluate

        rate = reads / total
        if rate < min_rate:
            return CostAlert(
                rule="low_cache_hit_rate",
                message=(
                    f"Cache hit rate {rate:.1%} is below minimum {min_rate:.0%}. "
                    f"Check for prefix instability."
                ),
                severity="warning",
            )
        return None
