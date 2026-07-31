"""
Human Input Activities (Plan 45 Phase 4).

Two activities called by HumanInputWorkflow:
1. notify_human_input_needed — create DB row, update run status, emit SSE, notify human
2. mark_human_input_resolved — update DB row, restore run status, emit SSE
"""

from datetime import timedelta

from temporalio import activity

from modules.backend.temporal.human_input_models import HumanInputWorkflowInput


@activity.defn
async def notify_human_input_needed(input: HumanInputWorkflowInput) -> None:
    """Record pending request in DB, notify human, emit SSE event."""
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.core.utils import utc_now
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.events.types import WorkflowHumanInputRequestedEvent
    from modules.backend.models.human_input_request import (
        HumanInputRequest,
        HumanInputRequestStatus,
    )
    from modules.backend.models.workflow_run import WorkflowRunState

    activity.logger.info(
        "notify_human_input_needed",
        extra={"request_id": input.request_id, "step_id": input.step_id},
    )

    now = utc_now()
    timeout_at = now + timedelta(seconds=input.timeout_seconds) if input.timeout_seconds else None

    async with get_async_session() as db:
        # Upsert the human input request row
        request = HumanInputRequest(
            id=input.request_id,
            workflow_run_id=input.workflow_run_id,
            step_id=input.step_id,
            mission_id=input.mission_id,
            session_id=input.session_id,
            temporal_workflow_id=f"human-input-{input.workflow_run_id}-{input.step_id}",
            prompt_message=input.prompt_message,
            channel=input.channel,
            choices_json=input.choices if input.choices else None,
            status=HumanInputRequestStatus.PENDING,
            timeout_at=timeout_at,
            created_at=now,
            updated_at=now,
        )
        db.add(request)

        # Update workflow run status to AWAITING_INPUT
        from sqlalchemy import update

        from modules.backend.models.workflow_run import WorkflowRun

        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == input.workflow_run_id)
            .values(status=WorkflowRunState.AWAITING_INPUT)
        )
        await db.commit()

    # Emit SSE event
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis, mission_id=input.mission_id)
        event = WorkflowHumanInputRequestedEvent(
            session_id=input.session_id,
            source="workflow.human_input",
            workflow_run_id=input.workflow_run_id,
            step_id=input.step_id,
            request_id=input.request_id,
            prompt_message=input.prompt_message,
            channel=input.channel,
            choices=input.choices or [],
            timeout_at=timeout_at.isoformat() if timeout_at else None,
        )
        await event_bus.publish_to_mission(input.mission_id, event)
    finally:
        await redis.aclose()

    # Dispatch notification to channel (Telegram/SSE)
    try:
        from modules.backend.services.run_notifier import _dispatch_to_channels

        title = f"Human input needed: {input.step_id}"
        choices_str = f"\n\nChoices: {', '.join(input.choices)}" if input.choices else ""
        body = f"{input.prompt_message}{choices_str}"
        await _dispatch_to_channels(
            [input.channel],
            title,
            body,
            "warning",
            {"mission_id": input.mission_id, "request_id": input.request_id},
        )
    except Exception:
        # best-effort — the mission event (WorkflowHumanInputRequestedEvent)
        # was already published above; this only covers the secondary
        # Telegram/SSE notification channel.
        activity.logger.warning(
            "Failed to dispatch notification for human input",
            extra={"request_id": input.request_id, "mission_id": input.mission_id},
            exc_info=True,
        )


@activity.defn
async def mark_human_input_resolved(
    request_id: str,
    response: str,
    timed_out: bool,
) -> None:
    """Update DB row with response, restore workflow run status, emit SSE."""
    from redis.asyncio import Redis as AsyncRedis
    from sqlalchemy import select, update

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.core.utils import utc_now
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.events.types import WorkflowHumanInputRespondedEvent
    from modules.backend.models.human_input_request import (
        HumanInputRequest,
        HumanInputRequestStatus,
    )
    from modules.backend.models.workflow_run import WorkflowRun, WorkflowRunState

    activity.logger.info(
        "mark_human_input_resolved",
        extra={"request_id": request_id, "timed_out": timed_out},
    )

    now = utc_now()
    new_status = (
        HumanInputRequestStatus.TIMED_OUT if timed_out else HumanInputRequestStatus.COMPLETED
    )

    async with get_async_session() as db:
        # Fetch the request to get related IDs
        result = await db.execute(
            select(HumanInputRequest).where(HumanInputRequest.id == request_id)
        )
        req = result.scalar_one()

        # Update request row
        await db.execute(
            update(HumanInputRequest)
            .where(HumanInputRequest.id == request_id)
            .values(
                status=new_status,
                response=response,
                resolved_at=now,
                updated_at=now,
            )
        )

        # Restore workflow run status to RUNNING
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == req.workflow_run_id)
            .values(status=WorkflowRunState.RUNNING)
        )
        await db.commit()

        mission_id = req.mission_id
        session_id = req.session_id
        workflow_run_id = req.workflow_run_id
        step_id = req.step_id

    # Emit SSE event
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        event_bus = SessionEventBus(redis, mission_id=mission_id)
        event = WorkflowHumanInputRespondedEvent(
            session_id=session_id,
            source="workflow.human_input",
            workflow_run_id=workflow_run_id,
            step_id=step_id,
            request_id=request_id,
            response=response,
            timed_out=timed_out,
        )
        await event_bus.publish_to_mission(mission_id, event)
    finally:
        await redis.aclose()
