"""
Run Notifier Service.

Dispatches notifications for workflow run lifecycle events: completion,
failure, and budget warnings. Reads notification config to determine
which channels to notify and which events to send.

Delegates to the Telegram NotificationService for delivery.
"""

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class RunNotifierService:
    """Dispatches run lifecycle notifications to configured channels."""

    @staticmethod
    async def notify_run_completed(
        run_id: str,
        workflow_name: str,
        total_cost_usd: float,
        step_count: int,
        mission_id: str | None = None,
    ) -> None:
        """Send completion notification for a successful workflow run."""
        config = get_app_config().notifications
        if not config.enabled or not config.notify_on_completion:
            return

        title = "Workflow Completed"
        body = (
            f"Workflow **{workflow_name}** completed successfully.\n"
            f"Steps: {step_count} | Cost: ${total_cost_usd:.4f}"
        )
        data = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "cost_usd": total_cost_usd,
            "mission_id": mission_id,
        }

        await _dispatch_to_channels(config.notify_channels, title, body, "success", data)

    @staticmethod
    async def notify_run_failed(
        run_id: str,
        workflow_name: str,
        error: str,
        total_cost_usd: float = 0.0,
        mission_id: str | None = None,
    ) -> None:
        """Send failure notification for a failed workflow run."""
        config = get_app_config().notifications
        if not config.enabled or not config.notify_on_failure:
            return

        title = "Workflow Failed"
        body = (
            f"Workflow **{workflow_name}** failed.\n"
            f"Error: {error[:500]}\n"
            f"Cost incurred: ${total_cost_usd:.4f}"
        )
        data = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "error": error[:1000],
            "cost_usd": total_cost_usd,
            "mission_id": mission_id,
        }

        await _dispatch_to_channels(config.notify_channels, title, body, "error", data)

    @staticmethod
    async def notify_budget_warning(
        run_id: str,
        workflow_name: str,
        cost_usd: float,
        budget_usd: float,
        pct_used: float,
    ) -> None:
        """Send warning when run cost exceeds threshold percentage of budget."""
        config = get_app_config().notifications
        if not config.enabled:
            return

        if pct_used < config.budget_warning_threshold_pct:
            return

        title = "Budget Warning"
        body = (
            f"Workflow **{workflow_name}** has used {pct_used:.0f}% of its budget.\n"
            f"Cost: ${cost_usd:.4f} / ${budget_usd:.2f}"
        )
        data = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "cost_usd": cost_usd,
            "budget_usd": budget_usd,
            "pct_used": pct_used,
        }

        await _dispatch_to_channels(config.notify_channels, title, body, "warning", data)

    @staticmethod
    async def notify_schedule_error(
        schedule_id: str,
        error: str,
    ) -> None:
        """Send notification for a schedule processing failure."""
        config = get_app_config().notifications
        if not config.enabled or not config.notify_on_failure:
            return

        title = "Schedule Error"
        body = (
            f"Failed to execute scheduled workflow.\n"
            f"Schedule: {schedule_id}\n"
            f"Error: {error[:500]}"
        )
        data = {"schedule_id": schedule_id, "error": error[:1000]}

        await _dispatch_to_channels(config.notify_channels, title, body, "error", data)


async def _dispatch_to_channels(
    channels: list[str],
    title: str,
    body: str,
    alert_type: str,
    data: dict | None = None,
) -> None:
    """Dispatch notification to configured channels.

    Currently supports 'telegram' and 'sse'. Other channels (slack, webhook, etc.)
    can be added here without changing the callers.
    """
    # Always publish to SSE notification channel for web frontend
    await _publish_sse_notification(title, body, alert_type, data)

    for channel in channels:
        try:
            if channel == "telegram":
                await _send_telegram(title, body, alert_type, data)
            else:
                logger.debug(
                    "Unsupported notification channel",
                    extra={"channel": channel},
                )
        except Exception:
            logger.warning(
                "Failed to send notification",
                extra={"channel": channel, "title": title},
                exc_info=True,
            )


async def _publish_sse_notification(
    title: str,
    body: str,
    alert_type: str,
    data: dict | None = None,
) -> None:
    """Publish notification to Redis pub/sub for SSE delivery to web frontend.

    Publishes to notify:{user_id} channels for all mission members
    associated with the notification's mission_id. Falls back to
    broadcasting to all known channels if no mission context.
    """
    import json

    try:
        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url

        mission_id = (data or {}).get("mission_id")
        if not mission_id:
            return  # No mission context, skip SSE (Telegram still sends)

        payload = json.dumps(
            {
                "type": alert_type,
                "title": title,
                "body": body,
                "data": data,
            }
        )

        # Publish to a mission-scoped notification channel.
        # The frontend subscribes to notify:{user_id}, but we also
        # publish to notify:mission:{mission_id} so a per-mission
        # fan-out can be done at the edge or by a lightweight subscriber.
        redis = AsyncRedis.from_url(get_redis_url())
        try:
            await redis.publish(f"notify:mission:{mission_id}", payload)
        finally:
            await redis.close()

    except Exception:
        logger.debug("Failed to publish SSE notification", exc_info=True)


async def _send_telegram(
    title: str,
    body: str,
    alert_type: str,
    data: dict | None = None,
) -> None:
    """Send notification via the Telegram NotificationService."""
    try:
        from modules.clients.telegram.services.notifications import (
            AlertType,
            get_notification_service,
        )
    except ImportError:
        logger.debug("Telegram notification service not available")
        return

    type_map = {
        "success": AlertType.SUCCESS,
        "error": AlertType.ERROR,
        "warning": AlertType.WARNING,
        "info": AlertType.INFO,
    }

    svc = get_notification_service()
    if svc is None:
        logger.debug("Telegram notification service returned None")
        return

    app_config = get_app_config()
    authorized_users = app_config.application.telegram.authorized_users

    for user_id in authorized_users:
        try:
            await svc.send_alert(
                user_id=user_id,
                title=title,
                body=body,
                alert_type=type_map.get(alert_type, AlertType.INFO),
                data=data,
            )
        except Exception:
            logger.debug(
                "Failed to send telegram notification to user",
                extra={"user_id": user_id},
                exc_info=True,
            )
