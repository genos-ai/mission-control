"""Director tools: workflow discovery, background-forked workflow runs, design.

Split out of agent.py (Plan 84 Phase 5.3). Pure move, no behavior change.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent, RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import _emit_tool_failure
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ── Plan 56 Phase B: Tool Fork Helpers ──────────────────────────────────


async def _create_background_record(
    *,
    mission_id: str,
    session_id: str,
    task_type: str,
    objective: str,
    params: dict,
) -> Any:
    """Create an ExecutionRecord for a background task via the service layer."""
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.create_background_record(
            mission_id=mission_id,
            session_id=session_id,
            task_type=task_type,
            objective=objective,
            params=params,
        )
        record_id = record.id

    # Return a lightweight ref — the ORM instance is detached after commit
    class _Ref:
        def __init__(self, id: str):
            self.id = id

    return _Ref(record_id)


async def _start_tool_fork_workflow(
    *,
    workflow_name: str,
    input_data: Any,
    record_id: str,
) -> str:
    """Start a Temporal workflow for a forked tool call. Returns workflow ID."""
    import uuid

    from modules.backend.temporal.client import get_temporal_client, get_temporal_config
    from modules.backend.temporal.tool_fork_workflow import (
        DesignWorkflowWorkflow,
        RunWorkflowWorkflow,
    )

    workflow_map = {
        "DesignWorkflowWorkflow": DesignWorkflowWorkflow.run,
        "RunWorkflowWorkflow": RunWorkflowWorkflow.run,
    }

    run_method = workflow_map[workflow_name]
    client = await get_temporal_client()
    config = get_temporal_config()

    workflow_id = f"tool-fork-{workflow_name.lower()}-{record_id[:12]}-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        run_method,
        input_data,
        id=workflow_id,
        task_queue=config.task_queue,
    )

    # Update the record with the temporal workflow ID
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.get_execution(record_id)
        if record is not None:
            record.temporal_workflow_id = workflow_id

    return workflow_id


async def _schedule_director_followup(
    *,
    db_session,
    session_id: str | None,
    mission_id: str | None,
    trigger_event_types: list[str],
    prompt_template: str,
) -> None:
    """Schedule a session followup so the Director wakes on a future event.

    Best-effort — failures are logged but never block the calling tool.
    Used by approve_plan_tasks to ensure the Director
    proactively reports outcomes to the user (Plan 51 Phase E).
    """
    if db_session is None or session_id is None:
        return
    try:
        from modules.backend.agents.adapters.followup import schedule_followup

        await schedule_followup(
            db_session,
            session_id=session_id,
            mission_id=mission_id,
            trigger_event_types=trigger_event_types,
            prompt_template=prompt_template,
            created_by_agent="mission.director.agent",
        )
    except Exception:
        logger.warning(
            "Director followup scheduling failed (non-fatal)",
            extra={"session_id": session_id, "mission_id": mission_id},
            exc_info=True,
        )


def register_workflow_tools(agent: Agent) -> None:
    """Register workflow discovery/run/design tools on the Director agent."""

    @agent.tool
    async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List available workflows (mission-scoped + system templates)."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.workflow_definition import WorkflowDefinitionService

            svc = WorkflowDefinitionService(ctx.deps.db_session)

            # Mission-scoped workflows
            mission_wfs = await svc.list_workflows(ctx.deps.mission_id, enabled_only=True)
            # System templates
            system_wfs = await svc.list_workflows(None, enabled_only=True)

            results = []
            seen_names: set[str] = set()

            for wf in mission_wfs:
                seen_names.add(wf.name)
                results.append(
                    {
                        "name": wf.name,
                        "description": wf.description,
                        "version": wf.version,
                        "trigger_type": wf.trigger_type,
                        "step_count": wf.step_count,
                        "scope": "mission",
                    }
                )

            for wf in system_wfs:
                if wf.name in seen_names:
                    continue  # Mission-scoped takes precedence
                results.append(
                    {
                        "name": wf.name,
                        "description": wf.description,
                        "version": wf.version,
                        "trigger_type": wf.trigger_type,
                        "step_count": wf.step_count,
                        "scope": "system",
                    }
                )

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(
                "list_workflows failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "list_workflows", e)
            return json.dumps({"error": str(e)})

    # ── Action Tools ──────────────────────────────────────

    @agent.tool
    async def run_workflow(
        ctx: RunContext[MissionDirectorDeps],
        workflow_name: str,
        context_overrides: dict[str, str] | None = None,
    ) -> str:
        """Start a named workflow against the current mission.

        Creates an execution record and starts a durable Temporal workflow
        in the background. Returns immediately — use check_background_tasks
        to check progress.

        Resolves workflow_name against mission-scoped workflows first,
        then system templates. Strips '.workflow' suffix if present.

        Args:
            workflow_name: The workflow identifier (e.g., "security.webapp-assessment"
                          or "system.platform-audit.workflow").
            context_overrides: Optional key-value pairs merged into the workflow
                              context before execution (e.g., {"target_path": "/path/to/code"}).
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            mission_id = ctx.deps.mission_id

            # Strip .workflow suffix — DB stores names without it
            clean_name = workflow_name
            if clean_name.endswith(".workflow"):
                clean_name = clean_name[: -len(".workflow")]

            record = await _create_background_record(
                mission_id=mission_id,
                session_id=ctx.deps.session_id,
                task_type="run_workflow",
                objective=f"Run workflow: {clean_name}",
                params={"workflow_name": clean_name, "context_overrides": context_overrides},
            )

            from modules.backend.temporal.tool_fork_models import RunWorkflowInput

            workflow_id = await _start_tool_fork_workflow(
                workflow_name="RunWorkflowWorkflow",
                input_data=RunWorkflowInput(
                    mission_id=mission_id,
                    session_id=ctx.deps.session_id,
                    execution_record_id=record.id,
                    workflow_name=clean_name,
                    context_overrides=context_overrides,
                ),
                record_id=record.id,
            )

            return json.dumps(
                {
                    "execution_record_id": record.id,
                    "temporal_workflow_id": workflow_id,
                    "workflow_name": clean_name,
                    "mission_id": mission_id,
                    "status": "started_in_background",
                    "message": (
                        "Workflow started in background. "
                        "Check progress via check_background_tasks."
                    ),
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            logger.error(
                "run_workflow failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "run_workflow", e)
            return json.dumps({"error": str(e)})

    # start_research removed (Plan 72): research goes through refine_plan
    # → Planning Agent decomposes into individual tasks with dependencies.
    # The research_loop executor in dispatch/research_loop.py is preserved
    # for future conversion to a workflow template.

    @agent.tool
    async def design_workflow(
        ctx: RunContext[MissionDirectorDeps],
        name: str,
        description: str,
        instructions: str,
    ) -> str:
        """Delegate workflow design to the Workflow Architect agent.

        Starts the Architect in a durable Temporal workflow and returns
        immediately. The user sees progress in the stream tab. Use
        check_background_tasks to check completion.

        Args:
            name: Workflow name (e.g. 'ops.health-check').
            description: What the workflow does.
            instructions: Detailed instructions for the architect — what
                agents to use, what steps to include, what to check.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            record = await _create_background_record(
                mission_id=ctx.deps.mission_id,
                session_id=ctx.deps.session_id,
                task_type="design_workflow",
                objective=f"Design workflow: {name}",
                params={"name": name, "description": description, "instructions": instructions},
            )

            from modules.backend.temporal.tool_fork_models import DesignWorkflowInput

            workflow_id = await _start_tool_fork_workflow(
                workflow_name="DesignWorkflowWorkflow",
                input_data=DesignWorkflowInput(
                    mission_id=ctx.deps.mission_id,
                    session_id=ctx.deps.session_id,
                    execution_record_id=record.id,
                    workflow_name=name,
                    description=description,
                    instructions=instructions,
                ),
                record_id=record.id,
            )

            return json.dumps(
                {
                    "execution_record_id": record.id,
                    "temporal_workflow_id": workflow_id,
                    "status": "started_in_background",
                    "workflow_name": name,
                    "message": f"The Workflow Architect is designing '{name}'. "
                    "You'll see progress in the stream tab. "
                    "Use check_background_tasks to check completion.",
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            logger.error(
                "design_workflow failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "design_workflow", e)
            return json.dumps({"error": str(e)})
