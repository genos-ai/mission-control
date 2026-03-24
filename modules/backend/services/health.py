"""
Health Check Service.

Runs dependency health checks and returns structured results.
Used by both the API health endpoints and client status commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ComponentStatus:
    """Health status for a single component."""

    name: str
    status: str  # "healthy", "unhealthy", "not_configured"
    latency_ms: int | None = None
    error: str | None = None


@dataclass
class HealthReport:
    """Aggregated health report across all components."""

    overall_status: str
    components: list[ComponentStatus] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return self.overall_status == "healthy"


class HealthCheckService:
    """Runs health checks against backend dependencies."""

    async def check_readiness(self) -> HealthReport:
        """Run all readiness checks and return a structured report.

        Mirrors the logic of the /health/ready endpoint but returns
        domain objects instead of HTTP responses.
        """
        from modules.backend.api.health import check_database, check_redis

        import asyncio

        db_raw, redis_raw = await asyncio.gather(
            check_database(),
            check_redis(),
            return_exceptions=True,
        )

        if isinstance(db_raw, Exception):
            db_raw = {"status": "unhealthy", "error": str(db_raw)}
        if isinstance(redis_raw, Exception):
            redis_raw = {"status": "unhealthy", "error": str(redis_raw)}

        components = [
            self._parse_component("database", db_raw),
            self._parse_component("redis", redis_raw),
        ]

        degraded = any(
            c.status not in ("healthy", "not_configured")
            for c in components
        )
        overall = "degraded" if degraded else "healthy"

        return HealthReport(overall_status=overall, components=components)

    @staticmethod
    def _parse_component(name: str, raw: dict[str, Any]) -> ComponentStatus:
        return ComponentStatus(
            name=name,
            status=raw.get("status", "unknown"),
            latency_ms=raw.get("latency_ms"),
            error=raw.get("error"),
        )
