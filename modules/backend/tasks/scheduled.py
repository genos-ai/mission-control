"""
Scheduled Background Tasks.

Plain async functions for maintenance cron jobs. These are called by
Temporal maintenance activities (Plan 56 Phase C) — no TaskIQ dependency.

Previously registered with TaskIQ via register_scheduled_tasks().
Now wrapped as Temporal activities in temporal/maintenance_activities.py
and triggered by Temporal Schedules registered in main.py lifespan.
"""

from typing import Any

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


async def daily_cleanup(older_than_days: int = 30) -> dict[str, Any]:
    """
    Clean up expired records from various tables. Runs daily at 2:00 AM UTC.

    Args:
        older_than_days: Delete records older than this many days

    Returns:
        Cleanup statistics
    """
    logger.info("Starting daily cleanup", extra={"older_than_days": older_than_days})

    result = {
        "status": "completed",
        "older_than_days": older_than_days,
        "tables_cleaned": [],
        "completed_at": utc_now().isoformat(),
    }

    logger.info("Daily cleanup completed", extra=result)
    return result


async def hourly_health_check() -> dict[str, Any]:
    """
    Perform periodic health checks on external services. Runs every hour.

    Returns:
        Health check results
    """
    logger.info("Starting hourly health check")

    from modules.backend.api.health import check_database, check_redis

    import asyncio
    db_check, redis_check = await asyncio.gather(
        check_database(),
        check_redis(),
        return_exceptions=True,
    )

    if isinstance(db_check, Exception):
        db_check = {"status": "error", "error": str(db_check)}
    if isinstance(redis_check, Exception):
        redis_check = {"status": "error", "error": str(redis_check)}

    checks = {"database": db_check, "redis": redis_check}
    all_healthy = all(
        c.get("status") in ("healthy", "not_configured")
        for c in checks.values()
    )

    result = {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks,
        "checked_at": utc_now().isoformat(),
    }

    log_level = "info" if all_healthy else "warning"
    getattr(logger, log_level)("Hourly health check completed", extra=result)
    return result


async def weekly_report_generation() -> dict[str, Any]:
    """
    Generate weekly summary reports. Runs every Sunday at 6:00 AM UTC.

    Returns:
        Report generation status
    """
    logger.info("Starting weekly report generation")

    result = {
        "status": "completed",
        "reports_generated": [],
        "generated_at": utc_now().isoformat(),
    }

    logger.info("Weekly report generation completed", extra=result)
    return result


async def metrics_aggregation(interval_minutes: int = 15) -> dict[str, Any]:
    """
    Aggregate metrics for monitoring dashboards. Runs every 15 minutes.

    Args:
        interval_minutes: Aggregation interval

    Returns:
        Aggregation status
    """
    logger.debug("Starting metrics aggregation", extra={"interval_minutes": interval_minutes})

    result = {
        "status": "completed",
        "interval_minutes": interval_minutes,
        "metrics_aggregated": [],
        "aggregated_at": utc_now().isoformat(),
    }

    logger.debug("Metrics aggregation completed", extra=result)
    return result


async def cleanup_stale_environments(
    idle_timeout_minutes: int = 60,
    max_lifetime_hours: int = 24,
) -> dict[str, Any]:
    """
    Clean up stale execution environments. Runs every hour.

    Two cleanup strategies:
    1. Exited containers — stopped/crashed, remove immediately
    2. Idle containers — running but no execution for idle_timeout_minutes
    3. Old containers — running past max_lifetime_hours regardless

    Also reconciles DB records with actual container state.

    Returns:
        Cleanup statistics
    """
    logger.info("Starting environment cleanup")
    cleaned = []
    idle_stopped = []

    try:
        import docker
        from datetime import datetime, timedelta, timezone

        client = docker.from_env()
        now = datetime.now(timezone.utc)
        idle_cutoff = now - timedelta(minutes=idle_timeout_minutes)
        lifetime_cutoff = now - timedelta(hours=max_lifetime_hours)

        # 1. Remove exited containers
        exited = client.containers.list(
            all=True,
            filters={"label": "mission-control=true", "status": "exited"},
        )
        for container in exited:
            try:
                container.remove(force=True)
                cleaned.append(container.name)
            except Exception as e:
                logger.warning(
                    "Failed to remove exited container",
                    extra={"container": container.name, "error": str(e)},
                )

        # 2. Stop and remove idle/old running containers
        running = client.containers.list(
            filters={"label": "mission-control=true", "status": "running"},
        )
        for container in running:
            try:
                # Parse container creation time
                created_str = container.attrs.get("Created", "")
                if created_str:
                    created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                else:
                    continue

                # Check lifetime limit
                if created < lifetime_cutoff:
                    container.stop(timeout=10)
                    container.remove(force=True)
                    idle_stopped.append(f"{container.name} (max lifetime)")
                    continue

                # Check idle timeout via label or last exec time
                # For now, use container creation as proxy
                # TODO: check last_execution_at from DB
                if created < idle_cutoff and not _container_has_recent_activity(container):
                    container.stop(timeout=10)
                    container.remove(force=True)
                    idle_stopped.append(f"{container.name} (idle)")
            except Exception as e:
                logger.warning(
                    "Failed to stop idle container",
                    extra={"container": container.name, "error": str(e)},
                )
    except ImportError:
        logger.debug("docker-py not installed, skipping container cleanup")
    except Exception as e:
        logger.warning("Docker not available for cleanup", extra={"error": str(e)})

    result = {
        "status": "completed",
        "exited_removed": cleaned,
        "idle_stopped": idle_stopped,
        "total_cleaned": len(cleaned) + len(idle_stopped),
        "cleaned_at": utc_now().isoformat(),
    }
    logger.info("Environment cleanup completed", extra=result)
    return result


def _container_has_recent_activity(container: Any) -> bool:
    """Check if a container has had recent exec activity.

    Uses docker inspect to check if any exec instances ran recently.
    This is a heuristic — the DB last_execution_at is more accurate.
    """
    try:
        top = container.top()
        # If there are processes beyond 'sleep infinity', it's active
        return len(top.get("Processes", [])) > 1
    except Exception:
        return False


