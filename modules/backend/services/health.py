"""
Health Check Service.

Runs dependency health checks and returns structured results.
Used by both the API health endpoints and client status commands.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


@dataclass
class ComponentStatus:
    """Health status for a single component."""

    name: str
    status: str  # "healthy", "unhealthy", "not_configured"
    latency_ms: int | None = None
    error: str | None = None
    detail: str | None = (
        None  # what a healthy or unconfigured component reports (pollers, token expiry)
    )


@dataclass
class HealthReport:
    """Aggregated health report across all components."""

    overall_status: str
    components: list[ComponentStatus] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return self.overall_status == "healthy"


def _elapsed_ms(start) -> int:
    return int((utc_now() - start).total_seconds() * 1000)


def _failure(e: Exception, timeout: int) -> str:
    """The reason a probe failed, in words an operator can act on."""
    if isinstance(e, asyncio.TimeoutError):
        return f"no answer within {timeout} s"
    return f"{type(e).__name__}: {e}"


async def check_temporal() -> dict[str, Any]:
    """Whether the Temporal server answers: workflows, schedules and the reconciler need it.

    Read-only: one health RPC on the cached client. No workflow is started.
    """
    from modules.backend.temporal.client import get_temporal_client

    config = get_app_config()
    if not config.temporal.enabled:
        return {"status": "not_configured", "detail": "temporal.enabled is false"}

    timeout = config.application.timeouts.health_probe
    start = utc_now()
    try:
        client = await asyncio.wait_for(get_temporal_client(), timeout)
        await asyncio.wait_for(client.service_client.check_health(), timeout)
    except Exception as e:
        logger.warning("Temporal health check failed", extra={"error": str(e)})
        return {"status": "unhealthy", "error": _failure(e, timeout)}
    return {
        "status": "healthy",
        "latency_ms": _elapsed_ms(start),
        "detail": f"{config.temporal.server_url}, namespace {config.temporal.namespace}",
    }


async def count_task_queue_pollers(client: Any, namespace: str, task_queue: str) -> int:
    """How many workers are polling this task queue for workflow tasks (a read-only RPC)."""
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=namespace,
            task_queue=TaskQueue(name=task_queue),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    return len(response.pollers)


async def check_temporal_worker() -> dict[str, Any]:
    """Whether a worker is polling the mission task queue.

    The server can be up with no worker: workflows are then accepted and never run, and
    nothing else reports it.
    """
    from modules.backend.temporal.client import get_temporal_client

    config = get_app_config()
    if not config.temporal.enabled:
        return {"status": "not_configured", "detail": "temporal.enabled is false"}

    timeout = config.application.timeouts.health_probe
    queue = config.temporal.task_queue
    start = utc_now()
    try:
        client = await asyncio.wait_for(get_temporal_client(), timeout)
        pollers = await asyncio.wait_for(
            count_task_queue_pollers(client, config.temporal.namespace, queue), timeout
        )
    except Exception as e:
        logger.warning("Temporal worker health check failed", extra={"error": str(e)})
        return {"status": "unhealthy", "error": _failure(e, timeout)}
    if pollers == 0:
        return {
            "status": "unhealthy",
            "latency_ms": _elapsed_ms(start),
            "error": f"No worker is polling {queue!r}: runs are accepted but never start",
        }
    return {
        "status": "healthy",
        "latency_ms": _elapsed_ms(start),
        "detail": f"{pollers} {'worker' if pollers == 1 else 'workers'} polling {queue}",
    }


async def check_foundry() -> dict[str, Any]:
    """Whether the Azure login the Foundry models use can obtain a token.

    Every agent call goes through Foundry, and a lapsed `az login` fails only at request time.
    This asks for a token (no model call, no cost, and the token is neither returned nor logged),
    so it proves the login and the token endpoint, not the model deployments.
    """
    from modules.backend.core.model_providers import credential_status, get_foundry_credential

    foundry = get_app_config().providers.foundry
    if foundry.auth_mode != "entra":
        status = credential_status("foundry")
        if status == "present":
            return {"status": "healthy", "detail": f"{foundry.auth_mode} credential present"}
        return {"status": "unhealthy", "error": f"{foundry.auth_mode} credential is {status}"}

    timeout = get_app_config().application.timeouts.health_probe
    start = utc_now()
    try:
        token = await asyncio.wait_for(get_foundry_credential().get_token(foundry.scope), timeout)
    except Exception as e:
        logger.warning("Foundry credential health check failed", extra={"error": str(e)})
        return {"status": "unhealthy", "error": _failure(e, timeout)}
    minutes_left = int((token.expires_on - utc_now().timestamp()) // 60)
    return {
        "status": "healthy",
        "latency_ms": _elapsed_ms(start),
        "detail": f"Entra token valid for {minutes_left} min",
    }


class HealthCheckService:
    """Runs health checks against backend dependencies."""

    async def check_readiness(self) -> HealthReport:
        """Run all readiness checks and return a structured report.

        Mirrors the logic of the /health/ready endpoint but returns
        domain objects instead of HTTP responses.
        """
        from modules.backend.api.health import check_database, check_redis

        raw = await asyncio.gather(
            check_database(),
            check_redis(),
            check_temporal(),
            check_temporal_worker(),
            check_foundry(),
            return_exceptions=True,
        )
        names = ("database", "redis", "temporal", "temporal_worker", "foundry")

        components = [
            self._parse_component(
                name,
                (
                    {"status": "unhealthy", "error": str(result)}
                    if isinstance(result, Exception)
                    else result
                ),
            )
            for name, result in zip(names, raw)
        ]

        degraded = any(c.status not in ("healthy", "not_configured") for c in components)
        overall = "degraded" if degraded else "healthy"

        return HealthReport(overall_status=overall, components=components)

    @staticmethod
    def _parse_component(name: str, raw: dict[str, Any]) -> ComponentStatus:
        return ComponentStatus(
            name=name,
            status=raw.get("status", "unknown"),
            latency_ms=raw.get("latency_ms"),
            error=raw.get("error"),
            detail=raw.get("detail"),
        )
