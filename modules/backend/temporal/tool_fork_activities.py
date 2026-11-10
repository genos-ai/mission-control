"""
Tool fork activities (Plan 56 Phase B).

Activities for workflows that handle Director tool calls forked to Temporal:
- execute_design_workflow: Runs the Workflow Architect agent
- execute_run_workflow: Runs a named workflow
- update_execution_record_status: Updates the ExecutionRecord lifecycle

Each activity opens its own DB session and commits independently.
"""

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.tool_fork_models import (
    DesignWorkflowInput,
    RunWorkflowInput,
    ToolForkResult,
)

logger = get_logger(__name__)


async def _emit_activity_error(mission_id: str, source: str, error: str) -> None:
    """Emit a SystemEvent from a Temporal activity so errors surface in the console."""
    from modules.backend.temporal.activity_helpers import emit_activity_error

    await emit_activity_error(mission_id, source, error)


@activity.defn
async def update_execution_record_status(
    execution_record_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """Update an ExecutionRecord's status. Used at start and end of forked work."""
    from modules.backend.core.database import get_async_session
    from modules.backend.core.utils import utc_now
    from modules.backend.repositories.execution_record import ExecutionRecordRepository

    # SQLAlchemy Enum(native_enum=False) stores by enum NAME (uppercase).
    normalised = status.upper()

    async with get_async_session() as db:
        repo = ExecutionRecordRepository(db)
        update_kwargs: dict = {"status": normalised}
        if normalised == "RUNNING":
            update_kwargs["started_at"] = utc_now()
        if normalised in ("COMPLETED", "FAILED", "CANCELLED"):
            update_kwargs["completed_at"] = utc_now()
        await repo.update(execution_record_id, **update_kwargs)
        await db.commit()

    activity.logger.info(
        "ExecutionRecord status updated",
        extra={"execution_record_id": execution_record_id, "status": status},
    )


@activity.defn
async def execute_design_workflow(input: DesignWorkflowInput) -> ToolForkResult:
    """Run the Workflow Architect agent to design a workflow.

    This is the actual heavy work — runs the architect agent with tool calls
    (browse_catalog, validate_workflow, save_workflow). Can take 30+ seconds.
    """
    activity.logger.info(
        "Designing workflow",
        extra={
            "mission_id": input.mission_id,
            "workflow_name": input.workflow_name,
        },
    )

    try:
        from modules.backend.agents.mission.workflow.architect.deps import ArchitectAgentDeps
        from modules.backend.agents.mission_control.helpers import _build_model
        from modules.backend.agents.mission_control.helpers.agent_setup import (
            build_deps_from_config,
        )
        from modules.backend.core.agent_registry import get_registry
        from modules.backend.core.database import get_async_session

        _ARCHITECT = "mission.workflow.architect"

        async with get_async_session() as db:
            registry = get_registry()
            agent_config = registry.get(_ARCHITECT)
            model = _build_model(agent_config.model)
            architect = registry.get_instance(_ARCHITECT, model)

            common = build_deps_from_config(agent_config)
            deps = ArchitectAgentDeps(
                **common,
                session_id=input.session_id,
                mission_id=input.mission_id,
                db_session=db,
            )

            prompt = (
                f"Design and save a workflow with these specifications:\n\n"
                f"Name: {input.workflow_name}\n"
                f"Description: {input.description}\n\n"
                f"Instructions:\n{input.instructions}\n\n"
                f"Use browse_catalog to check available agents, then "
                f"design the steps, validate with validate_workflow, "
                f"and save with save_workflow. Do NOT ask for confirmation — "
                f"the user already confirmed by requesting this."
            )

            result = await architect.run(prompt, deps=deps)
            await db.commit()

        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="completed",
            summary=str(result.output)[:500],
            cost_usd=result.usage().total_tokens * 0.00001 if result.usage() else 0.0,
        )
    except Exception as e:
        # Catch-all justified: Temporal activity boundary wrapping an
        # agent.run() call whose exception surface is unbounded — must
        # convert to a failed ToolForkResult rather than raise.
        activity.logger.error(
            "execute_design_workflow failed",
            extra={"mission_id": input.mission_id, "error": str(e)},
            exc_info=True,
        )
        await _emit_activity_error(
            input.mission_id, "workflow_architect", f"Design workflow failed: {e}"
        )
        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="failed",
            error=str(e)[:500],
        )


@activity.defn
async def execute_run_workflow(input: RunWorkflowInput) -> ToolForkResult:
    """Run a named workflow via WorkflowRunService."""
    activity.logger.info(
        "Running workflow",
        extra={
            "mission_id": input.mission_id,
            "workflow_name": input.workflow_name,
        },
    )

    try:
        from redis.asyncio import Redis as AsyncRedis

        from modules.backend.core.config import get_redis_url
        from modules.backend.events.bus import SessionEventBus
        from modules.backend.services.workflow_run import WorkflowRunService

        redis = AsyncRedis.from_url(get_redis_url())
        event_bus = SessionEventBus(redis, mission_id=input.mission_id)
        try:
            async with WorkflowRunService.factory(event_bus=event_bus) as svc:
                await svc.run_workflow(
                    workflow_name=input.workflow_name,
                    triggered_by=input.triggered_by,
                    mission_id=input.mission_id,
                    context_overrides=input.context_overrides,
                    temporal_workflow_id=activity.info().workflow_id,
                )
        finally:
            await redis.aclose()

        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="completed",
            summary=f"Workflow {input.workflow_name} completed",
        )
    except Exception as e:
        # Catch-all justified: Temporal activity boundary wrapping
        # WorkflowRunService.run_workflow() whose exception surface is
        # unbounded — must convert to a failed ToolForkResult rather than
        # raise.
        activity.logger.error(
            "execute_run_workflow failed",
            extra={"mission_id": input.mission_id, "error": str(e)},
            exc_info=True,
        )
        await _emit_activity_error(
            input.mission_id, "workflow_runner", f"Run workflow '{input.workflow_name}' failed: {e}"
        )
        return ToolForkResult(
            execution_record_id=input.execution_record_id,
            status="failed",
            error=str(e)[:500],
        )


@activity.defn
async def notify_director_on_completion(
    mission_id: str,
    session_id: str,
    followup_event_types: list[str] | None,
    fallback_prompt: str,
) -> str:
    """Fire any matching followups and start a Director turn — atomically.

    1. If followup_event_types is set, fires matching session followups.
       A matching followup's rendered prompt replaces the fallback.
    2. Starts a ChatTurnWorkflow with the chosen prompt.

    Returns the Director ChatTurnWorkflow ID.

    By combining followup consumption and Director notification in one
    activity, we avoid the race where a followup is consumed but the
    Director turn fails to start in a separate step.
    """
    import uuid

    from modules.backend.core.config import get_app_config
    from modules.backend.temporal.chat_models import ChatTurnInput
    from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.config_snapshots import build_workflow_timeouts_snapshot

    prompt = fallback_prompt

    # Fire matching followups and use their rendered prompt if available
    if followup_event_types:
        from modules.backend.core.database import get_async_session
        from modules.backend.services.session_followup import SessionFollowupService

        rendered: list[str] = []

        async def _capture(_s: str, _m: str, p: str) -> None:
            rendered.append(p)

        async with get_async_session() as db:
            followup_svc = SessionFollowupService(db)
            for evt_type in followup_event_types:
                await followup_svc.fire_matching(
                    {"event_type": evt_type, "mission_id": mission_id},
                    agent_turn_runner=_capture,
                )
            await db.commit()

        if rendered:
            prompt = rendered[0]
            activity.logger.info(
                "Using followup prompt for Director",
                extra={
                    "mission_id": mission_id,
                    "event_types": followup_event_types,
                },
            )

    # Start Director turn
    client = await get_temporal_client()
    config = get_app_config().temporal

    workflow_id = f"director-followup-{mission_id[:12]}-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        ChatTurnWorkflow.run,
        ChatTurnInput(
            session_id=session_id,
            mission_id=mission_id,
            message=prompt,
            sender_id="mission.supervisor.agent",
            agent_id="mission.director.agent",
            channel="followup",
            timeouts=build_workflow_timeouts_snapshot(),
        ),
        id=workflow_id,
        task_queue=config.task_queue,
    )

    activity.logger.info(
        "Director notified on completion",
        extra={"mission_id": mission_id, "workflow_id": workflow_id},
    )
    return workflow_id
