"""Dispatch runtime — everything a task needs to execute, built once per dispatch (Plan 88, 88.2.3).

``build_dispatch_runtime`` derives the roster from the mission team, builds
the mission context services, provisions the execution environment and
creates the agent executor. ``handle_mission`` builds one per in-process
dispatch; the per-task Temporal activity builds one per task, passing its
``task_id`` so every ledger row it writes is attributed to the task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from modules.backend.agents.mission_control.helpers import _emit, _make_agent_executor
from modules.backend.agents.mission_control.models import (
    ContextAssemblerProtocol,
    ContextCuratorProtocol,
    EventBusProtocol,
    ExecuteAgentFn,
)
from modules.backend.agents.mission_control.roster import Roster, derive_roster_from_team
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.events.types import SystemEvent
from modules.backend.services.code_map.loader import CodeMapLoader
from modules.backend.services.context_assembler import ContextAssembler
from modules.backend.services.context_curator import ContextCurator
from modules.backend.services.history_query import HistoryQueryService
from modules.backend.services.mission_context import MissionContextManager

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass
class DispatchRuntime:
    """The roster, executor and context services one dispatch runs tasks with."""

    roster: Roster
    execute_agent_fn: ExecuteAgentFn
    context_curator: ContextCuratorProtocol | None
    context_assembler: ContextAssemblerProtocol | None
    environment_handle: object | None


async def build_dispatch_runtime(
    *,
    db_session: AsyncSession,
    event_bus: EventBusProtocol,
    mission_id: str,
    session_id: str,
    execution_mode: str,
    mission_repo_root: str | None,
    container_image: str | None,
    extra_volumes: list[dict[str, str]] | None,
    mission_run_id: str | None,
    task_id: str | None,
) -> DispatchRuntime:
    """Build the runtime for one dispatch of a mission's tasks.

    ``mission_run_id`` and ``task_id`` tag every LLM ledger row the executor
    writes; ``task_id`` is None when the runtime serves a whole plan.
    """
    roster = await derive_roster_from_team(mission_id, db_session)

    pcd_manager = MissionContextManager(db_session)
    context_curator = ContextCurator(pcd_manager)
    context_assembler = ContextAssembler(
        context_manager=pcd_manager,
        history_service=HistoryQueryService(db_session),
        code_map_loader=CodeMapLoader(find_project_root()),
    )

    env_handle = await _provision_environment(
        db_session=db_session,
        event_bus=event_bus,
        mission_id=mission_id,
        session_id=session_id,
        execution_mode=execution_mode,
        mission_repo_root=mission_repo_root,
        container_image=container_image,
        extra_volumes=extra_volumes,
    )

    execute_agent_fn = _make_agent_executor(
        event_bus,
        session_id=session_id,
        mission_id=mission_id,
        environment_handle=env_handle,
        current_user_id=None,  # Plan 55: resolved in Phase B
        mission_run_id=mission_run_id,
        task_id=task_id,
    )

    return DispatchRuntime(
        roster=roster,
        execute_agent_fn=execute_agent_fn,
        context_curator=context_curator,
        context_assembler=context_assembler,
        environment_handle=env_handle,
    )


async def _provision_environment(
    *,
    db_session: AsyncSession,
    event_bus: EventBusProtocol,
    mission_id: str,
    session_id: str,
    execution_mode: str,
    mission_repo_root: str | None,
    container_image: str | None,
    extra_volumes: list[dict[str, str]] | None,
) -> object | None:
    """Provision the execution environment for a non-local mode; None means local."""
    if execution_mode == "local":
        return None
    try:
        from modules.backend.services.container_backend import ContainerBackend
        from modules.backend.services.execution_environment import ExecutionEnvironmentService

        env_service = ExecutionEnvironmentService(db_session=db_session)
        env_service.register_backend("container", ContainerBackend())

        repo_root = mission_repo_root or str(find_project_root())
        container_config: dict[str, Any] = {
            "image": container_image or "code-workspace:latest",
            "git_aware": True,
            "repo_root": repo_root,
            "branch_name": f"agent/{mission_id[:8]}/dispatch",
        }
        if extra_volumes:
            container_config["extra_volumes"] = extra_volumes
        env_handle = await env_service.get_or_create_for_mission(
            mission_id=mission_id, mode=execution_mode, config=container_config
        )
        logger.info(
            "Execution environment ready",
            extra={
                "mode": execution_mode,
                "environment_id": env_handle.environment_id,
                "reused": env_handle.metadata.get("execution_count", 0) > 1,
            },
        )
        return env_handle
    except Exception as exc:
        logger.warning(
            "Failed to provision execution environment, falling back to local",
            extra={"mission_id": mission_id},
            exc_info=True,
        )
        await _emit(
            event_bus,
            SystemEvent,
            session_id=session_id,
            source="mission_dispatch",
            level="warning",
            message=f"Environment provisioning failed, falling back to local: {exc}",
            mission_id=mission_id,
        )
        return None
