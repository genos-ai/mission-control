"""Dispatch runtime — everything a task needs to execute, built once per dispatch (Plan 88, 88.2.3).

``build_dispatch_runtime`` derives the roster from the mission team, builds
the mission context services, provisions the execution environment and
creates the agent executor. The per-task Temporal activity builds one per
task, passing its ``task_id`` so every ledger row it writes is attributed
to the task.

The build has two phases, so a caller that plans first need not provision
an environment for a plan that fails: ``build_context_services`` (roster
and context services, which the planner needs) and
``provision_dispatch_runtime`` (environment and executor).
``handle_mission`` runs the first before planning and the second once the
plan is valid; ``build_dispatch_runtime`` runs both.

Provisioning fails closed (Plan 88 88.2.3a, contracts 3.8.5): a non-local
mode that cannot get an isolated workspace raises ``ExecutionEnvironmentError``
instead of running on the host.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from modules.backend.agents.mission_control.helpers import _make_agent_executor
from modules.backend.agents.mission_control.models import (
    ContextAssemblerProtocol,
    ContextCuratorProtocol,
    EventBusProtocol,
    ExecuteAgentFn,
)
from modules.backend.agents.mission_control.roster import Roster, derive_roster_from_team
from modules.backend.core.config import find_project_root
from modules.backend.core.exceptions import ExecutionEnvironmentError
from modules.backend.core.logging import get_logger
from modules.backend.services.code_map.loader import CodeMapLoader
from modules.backend.services.context_assembler import ContextAssembler
from modules.backend.services.context_curator import ContextCurator
from modules.backend.services.mission_context import MissionContextManager

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.services.execution_environment import EnvironmentHandle

logger = get_logger(__name__)


@dataclass
class DispatchRuntime:
    """The roster, executor and context services one dispatch runs tasks with.

    The context services share one AsyncSession, which rejects concurrent
    operations. ``context_lock`` serialises context assembly across the
    tasks of a layer, which ``run_single_task`` runs concurrently.
    ``mission_run_id`` scopes the run context layers; None outside a run.
    """

    roster: Roster
    execute_agent_fn: ExecuteAgentFn
    context_curator: ContextCuratorProtocol | None
    context_assembler: ContextAssemblerProtocol | None
    environment_handle: object | None
    mission_run_id: str | None
    context_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class ContextServices:
    """The roster and mission context services, built before planning."""

    roster: Roster
    context_curator: ContextCuratorProtocol
    context_assembler: ContextAssemblerProtocol


async def build_context_services(*, db_session: AsyncSession, mission_id: str) -> ContextServices:
    """Derive the roster from the mission team and build the context services."""
    roster = await derive_roster_from_team(mission_id, db_session)
    pcd_manager = MissionContextManager(db_session)
    return ContextServices(
        roster=roster,
        context_curator=ContextCurator(pcd_manager),
        context_assembler=ContextAssembler.for_session(
            db_session,
            context_manager=pcd_manager,
            code_map_loader=CodeMapLoader(find_project_root()),
        ),
    )


async def provision_dispatch_runtime(
    services: ContextServices,
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
    budget_headroom_usd: float | None,
) -> DispatchRuntime:
    """Provision the execution environment and executor on top of ``services``.

    ``mission_run_id`` and ``task_id`` tag every LLM ledger row the executor
    writes; ``task_id`` is None when the runtime serves a whole plan.
    ``budget_headroom_usd`` caps what the executor may spend (88.4.6); None
    when no run budget applies.
    """
    env_handle = await _provision_environment(
        db_session=db_session,
        mission_id=mission_id,
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
        budget_headroom_usd=budget_headroom_usd,
    )

    return DispatchRuntime(
        roster=services.roster,
        execute_agent_fn=execute_agent_fn,
        context_curator=services.context_curator,
        context_assembler=services.context_assembler,
        environment_handle=env_handle,
        mission_run_id=mission_run_id,
    )


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
    budget_headroom_usd: float | None,
) -> DispatchRuntime:
    """Build the runtime for one dispatch of a mission's tasks: both phases in one call."""
    services = await build_context_services(db_session=db_session, mission_id=mission_id)
    return await provision_dispatch_runtime(
        services,
        db_session=db_session,
        event_bus=event_bus,
        mission_id=mission_id,
        session_id=session_id,
        execution_mode=execution_mode,
        mission_repo_root=mission_repo_root,
        container_image=container_image,
        extra_volumes=extra_volumes,
        mission_run_id=mission_run_id,
        task_id=task_id,
        budget_headroom_usd=budget_headroom_usd,
    )


async def _provision_environment(
    *,
    db_session: AsyncSession,
    mission_id: str,
    execution_mode: str,
    mission_repo_root: str | None,
    container_image: str | None,
    extra_volumes: list[dict[str, str]] | None,
) -> EnvironmentHandle | None:
    """Provision the execution environment for a non-local mode; None means local.

    Fails closed (contracts 3.8.5): a non-local mode without a repo root, any
    provisioning error, or a git-aware handle without a host worktree raises
    ``ExecutionEnvironmentError``. There is no fallback to local execution.
    """
    if execution_mode == "local":
        return None
    if not mission_repo_root:
        raise ExecutionEnvironmentError(f"execution mode '{execution_mode}' requires repo_root")
    try:
        from modules.backend.services.container_backend import ContainerBackend
        from modules.backend.services.execution_environment import ExecutionEnvironmentService

        env_service = ExecutionEnvironmentService(db_session=db_session)
        env_service.register_backend("container", ContainerBackend())

        container_config: dict[str, Any] = {
            "image": container_image or "code-workspace:latest",
            "git_aware": True,
            "repo_root": mission_repo_root,
            "branch_name": f"agent/{mission_id[:8]}/dispatch",
        }
        if extra_volumes:
            container_config["extra_volumes"] = extra_volumes
        env_handle = await env_service.get_or_create_for_mission(
            mission_id=mission_id, mode=execution_mode, config=container_config
        )
    except ExecutionEnvironmentError:
        raise
    except Exception as exc:
        # Catch-all justified: provisioning spans Docker, git and the DB, whose
        # exception surface is unbounded. Every failure is re-raised typed, with
        # the original as __cause__; nothing continues without an environment.
        raise ExecutionEnvironmentError(
            f"execution environment provisioning failed for mode '{execution_mode}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if env_handle.host_working_dir is None:
        raise ExecutionEnvironmentError(
            f"execution environment '{env_handle.environment_id}' has no host worktree"
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
