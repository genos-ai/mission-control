"""Async service wrappers for the TUI.

Bridges Textual's @work coroutines to backend service factories.
Each method uses the service's factory() pattern, keeping the TUI
stateless with respect to database connections and transactions.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from modules.backend.agents.mission_control.gate import GateReviewer
from modules.backend.agents.mission_control.mission_control import handle_mission
from modules.backend.agents.mission_control.models import EventBusProtocol, NoOpEventBus
from modules.backend.agents.mission_control.outcome import ExecutionOutcome
from modules.backend.agents.mission_control.roster import derive_roster_from_team, Roster
from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

from modules.backend.models.base import SYSTEM_CLI_ID as CLI_USER_ID


@asynccontextmanager
async def _cli_user_session() -> AsyncGenerator[tuple[Any, Any], None]:
    """Shared context manager for operations requiring the CLI service user.

    Yields (db_session, requesting_user) — callers create
    their own service instance using the session.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.user import UserService

    async with get_async_session() as db:
        svc = UserService(db)
        # get_by_id raises NotFoundError via the repo if user doesn't exist
        requesting_user = await svc.user_repo.get_by_id(CLI_USER_ID)
        yield db, requesting_user


def _enum_str(val: Any) -> str:
    """Convert an enum or string value to its string representation."""
    return val.value if hasattr(val, "value") else str(val)


class ServiceBridge:
    """Facade that wraps backend service factories for TUI consumption.

    Every public method delegates to service factory() calls.
    The TUI never sees raw SQLAlchemy sessions.
    """

    def __init__(
        self,
        *,
        event_bus: EventBusProtocol = NoOpEventBus(),
    ) -> None:
        self._event_bus = event_bus

    # ── Mission operations ────────────────────────────────────────────

    async def list_missions(self) -> list[dict[str, Any]]:
        """Return all active missions as dicts."""
        from modules.backend.services.mission import MissionService

        async with MissionService.factory() as svc:
            missions = await svc.list_missions()
            return [
                {
                    "id": str(m.id),
                    "name": m.name,
                    "description": m.description,
                    "status": _enum_str(m.status),
                }
                for m in missions
            ]

    async def create_mission(
        self,
        *,
        name: str,
        description: str,
    ) -> dict[str, str]:
        """Create a mission and return its id and name."""
        from modules.backend.services.mission import MissionService

        async with MissionService.factory() as svc:
            mission = await svc.create_mission(name=name, description=description)
            return {"id": str(mission.id), "name": mission.name}

    async def get_mission(self, mission_id: str) -> Any:
        """Fetch a single mission by ID."""
        from modules.backend.services.mission import MissionService

        async with MissionService.factory() as svc:
            return await svc.get_mission(mission_id)

    # ── User operations ────────────────────────────────────────────────

    async def get_current_user(self) -> dict[str, Any]:
        """Return the CLI service account's profile including current mission."""
        async with _cli_user_session() as (db, user):
            return {
                "id": user.id,
                "current_mission_id": user.current_mission_id,
                "current_mission_name": (
                    user.current_mission.name if user.current_mission else None
                ),
            }

    async def set_current_mission(self, mission_id: str | None) -> None:
        """Set the current user's active mission."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            await svc.set_current_mission(
                user_id=CLI_USER_ID,
                mission_id=mission_id,
                requesting_user=requesting_user,
            )
            await db.commit()

    # ── Roster ───────────────────────────────────────────────────────

    async def load_roster(self, mission_id: str, db_session: "Any") -> Roster:
        """Load agent roster from mission team in the database."""
        return await derive_roster_from_team(mission_id, db_session)

    # ── Execution dispatch ──────────────────────────────────────────

    async def run_execution(
        self,
        *,
        brief: str,
        mission_id: str,
        session_id: str,
        roster_name: str = "default",
        budget_usd: float | None = None,
        gate: GateReviewer | None = None,
    ) -> ExecutionOutcome:
        """Execute a dispatch in-process with full event streaming.

        This is the TUI's primary execution path. It calls handle_mission()
        directly, wiring the TuiGateReviewer and TuiEventBus.
        """
        budget_usd = budget_usd or get_default_budget_usd()

        from modules.backend.services.session import SessionService

        async with SessionService.factory() as session_service:
            mission_run_id = f"tui-{session_id}"

            outcome = await handle_mission(
                mission_run_id=mission_run_id,
                mission_brief=brief,
                session_service=session_service,
                event_bus=self._event_bus,
                roster_name=roster_name,
                mission_budget_usd=budget_usd,
                session_id=session_id,
                mission_id=mission_id,
                db_session=session_service.session,
                gate=gate,
            )

            return outcome

    # ── Execution history ─────────────────────────────────────────────

    async def list_executions(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return execution records as dicts for the history screen.

        Note: Backend returns tuple[list, total_count]. For backwards
        compatibility, this method returns only the list. Use
        list_executions_paginated() for the tuple version.
        """
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            records, _total = await svc.list_executions(
                status=status, limit=limit, offset=offset,
            )
            return [
                self._execution_to_dict(r)
                for r in records
            ]

    async def list_executions_paginated(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return execution records with total count for pagination."""
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            records, total = await svc.list_executions(
                status=status, limit=limit, offset=offset,
            )
            return [self._execution_to_dict(r) for r in records], total

    @staticmethod
    def _execution_to_dict(r: object) -> dict[str, Any]:
        """Convert an ExecutionRecord to a display dict."""
        rid = str(getattr(r, "id", ""))
        return {
            "id": rid,
            "execution_id": r.execution_id if hasattr(r, "execution_id") else rid,
            "objective": getattr(r, "objective_statement", "") or getattr(r, "objective", "") or "",
            "status": _enum_str(getattr(r, "status", "unknown")),
            "total_cost_usd": getattr(r, "total_cost_usd", 0.0) or 0.0,
            "roster_name": getattr(r, "roster_name", "") or "",
            "created_at": str(getattr(r, "created_at", "")),
        }

    async def get_execution_decisions(
        self, execution_id: str,
    ) -> list[dict[str, Any]]:
        """Wraps ExecutionPersistenceService.get_decisions()."""
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            decisions = await svc.get_decisions(execution_id)
            return [
                {
                    "id": str(d.id),
                    "decision_type": d.decision_type.value if hasattr(d.decision_type, "value") else str(d.decision_type),
                    "task_id": d.task_id,
                    "reasoning": d.reasoning,
                    "created_at": str(getattr(d, "created_at", "")),
                }
                for d in decisions
            ]

    async def get_execution_detail(self, execution_id: str) -> dict[str, Any] | None:
        """Return a single execution record with task details."""
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            record = await svc.get_execution(execution_id)
            if not record:
                return None
            task_executions = await svc.get_task_executions(execution_id)
            return {
                "id": str(record.id),
                "objective": getattr(record, "objective", ""),
                "status": _enum_str(getattr(record, "status", "unknown")),
                "total_cost_usd": getattr(record, "total_cost_usd", 0.0) or 0.0,
                "roster_name": getattr(record, "roster_name", ""),
                "created_at": str(getattr(record, "created_at", "")),
                "execution_outcome_json": getattr(record, "execution_outcome_json", None),
                "task_executions": [
                    {
                        "task_id": getattr(t, "task_id", ""),
                        "agent_name": getattr(t, "agent_name", ""),
                        "status": _enum_str(getattr(t, "status", "")),
                        "cost_usd": getattr(t, "cost_usd", 0.0) or 0.0,
                        "input_tokens": getattr(t, "input_tokens", 0) or 0,
                        "output_tokens": getattr(t, "output_tokens", 0) or 0,
                    }
                    for t in task_executions
                ],
            }

    async def get_execution_cost_breakdown(
        self, execution_id: str,
    ) -> dict[str, Any] | None:
        """Return cost breakdown for an execution."""
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        async with ExecutionPersistenceService.factory() as svc:
            return await svc.get_cost_breakdown(execution_id)

    # ── Team operations (Plan 32 Phase T2) ─────────────────────────────

    async def get_team(self, mission_id: str) -> list[dict[str, Any]]:
        """Wraps MissionTeamService.list_team(mission_id)."""
        from modules.backend.services.mission_team import MissionTeamService

        async with MissionTeamService.factory() as svc:
            members = await svc.list_team(mission_id)
            return [
                {
                    "id": str(m.id),
                    "agent_catalog_id": str(m.agent_catalog_id),
                    "agent_name": m.agent_catalog.agent_name if m.agent_catalog else "",
                    "agent_type": m.agent_catalog.agent_type if m.agent_catalog else "",
                    "description": m.agent_catalog.description if m.agent_catalog else "",
                    "version": m.agent_catalog.version if m.agent_catalog else "",
                    "user_prompt": m.user_prompt or "",
                    "system_prompt": m.agent_catalog.system_prompt if m.agent_catalog else "",
                    "enabled": m.enabled,
                    "display_order": m.display_order,
                }
                for m in members
            ]

    async def add_team_member(
        self, mission_id: str, *, agent_name: str,
    ) -> dict[str, Any]:
        """Add an agent to the team by name.

        Backend gap: MissionTeamService.add_agent() requires
        agent_catalog_id, not agent_name. Bridge resolves name->ID
        via AgentCatalogService. This MUST move to backend.
        """
        from modules.backend.services.agent_catalog import AgentCatalogService
        from modules.backend.services.mission_team import MissionTeamService

        async with AgentCatalogService.factory() as cat_svc:
            agent = await cat_svc.get_by_name(agent_name)
            if agent is None:
                raise ValueError(f"Agent '{agent_name}' not found in catalog")
            agent_catalog_id = str(agent.id)

        async with MissionTeamService.factory() as svc:
            member = await svc.add_agent(mission_id, agent_catalog_id)
            return {
                "id": str(member.id),
                "agent_catalog_id": agent_catalog_id,
                "agent_name": agent_name,
            }

    async def remove_team_member(
        self, mission_id: str, *, member_id: str,
    ) -> None:
        """Wraps MissionTeamService.remove_agent(member_id)."""
        from modules.backend.services.mission_team import MissionTeamService

        async with MissionTeamService.factory() as svc:
            await svc.remove_agent(member_id)

    async def update_team_member_prompt(
        self, mission_id: str, *, member_id: str, user_prompt: str,
    ) -> dict[str, Any]:
        """Wraps MissionTeamService.update_user_prompt()."""
        from modules.backend.services.mission_team import MissionTeamService

        async with MissionTeamService.factory() as svc:
            member = await svc.update_user_prompt(
                member_id, user_prompt, changed_by=CLI_USER_ID,
            )
            return {"id": str(member.id), "user_prompt": member.user_prompt}

    # ── Catalog operations (Plan 32 Phase T2) ──────────────────────────

    async def list_catalog_agents(
        self,
        *,
        enabled_only: bool = True,
        visibility: str | None = None,
        agent_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Wraps AgentCatalogService.list_catalog()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            agents = await svc.list_catalog(
                enabled_only=enabled_only,
                visibility=visibility,
                agent_type=agent_type,
            )
            return [
                {
                    "id": str(a.id),
                    "agent_name": a.agent_name,
                    "agent_type": a.agent_type,
                    "description": a.description or "",
                    "version": a.version or "",
                    "keywords": a.keywords or [],
                    "enabled": a.enabled,
                    "visibility": a.visibility or "public",
                    "tools": a.tools or [],
                    "constraints": a.constraints or {},
                }
                for a in agents
            ]

    async def search_catalog(self, *, query: str) -> list[dict[str, Any]]:
        """Wraps AgentCatalogService.search_by_keyword()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            agents = await svc.search_by_keyword(query)
            return [
                {
                    "id": str(a.id),
                    "agent_name": a.agent_name,
                    "agent_type": a.agent_type,
                    "description": a.description or "",
                    "version": a.version or "",
                }
                for a in agents
            ]

    # ── Chat/Session operations (Plan 32 Phase T5) ──────────────────────

    async def create_session(
        self, *, mission_id: str, agent_name: str,
    ) -> dict[str, Any]:
        """Create a new chat session."""
        from modules.backend.services.session import SessionService

        async with SessionService.factory() as svc:
            session = await svc.create_session(
                mission_id=mission_id, agent_name=agent_name,
            )
            return {
                "session_id": str(session.id),
                "agent_name": agent_name,
            }

    async def send_message(
        self, *, session_id: str, content: str,
    ) -> None:
        """Wraps SessionService.send_message(). Backend handles dispatch."""
        from modules.backend.services.session import SessionService

        async with SessionService.factory() as svc:
            await svc.send_message(session_id, content)

    async def list_sessions(
        self, *, mission_id: str,
    ) -> list[dict[str, Any]]:
        """List chat sessions for a mission."""
        from modules.backend.services.session import SessionService

        async with SessionService.factory() as svc:
            sessions = await svc.list_sessions(mission_id=mission_id)
            return [
                {
                    "session_id": str(s.id),
                    "agent_name": getattr(s, "agent_name", ""),
                    "created_at": str(getattr(s, "created_at", "")),
                    "last_message": getattr(s, "last_message", ""),
                }
                for s in sessions
            ]

    async def get_session_messages(
        self, *, session_id: str,
    ) -> list[dict[str, Any]]:
        """Get message history for a session."""
        from modules.backend.services.session import SessionService

        async with SessionService.factory() as svc:
            messages = await svc.get_messages(session_id)
            return [
                {
                    "id": str(getattr(m, "id", "")),
                    "role": getattr(m, "role", ""),
                    "content": getattr(m, "content", ""),
                    "created_at": str(getattr(m, "created_at", "")),
                    "cost_usd": getattr(m, "cost_usd", 0.0),
                }
                for m in messages
            ]

    # ── Workflow operations (Plan 32 Phase T3) ───────────────────────────

    async def list_workflows(self, mission_id: str) -> list[dict[str, Any]]:
        """Wraps WorkflowService.list_workflows().

        Internally synchronous (YAML) but async for uniform interface.
        """
        from modules.backend.services.workflow import WorkflowService

        svc = WorkflowService()
        workflows = svc.list_workflows()
        return [svc.to_list_item(w) for w in workflows]

    async def get_workflow_detail(
        self, workflow_name: str,
    ) -> dict[str, Any] | None:
        """Wraps WorkflowService.get_workflow() + to_detail().

        Internally synchronous but async for uniform interface.
        """
        from modules.backend.services.workflow import WorkflowService

        svc = WorkflowService()
        workflow = svc.get_workflow(workflow_name)
        if not workflow:
            return None
        return svc.to_detail(workflow)

    async def architect_chat(
        self, mission_id: str, *, message: str,
        session_id: str | None = None,
        message_history: list | None = None,
    ) -> dict[str, Any]:
        """Wraps WorkflowArchitectService.chat()."""
        from modules.backend.services.workflow_architect import WorkflowArchitectService

        async with WorkflowArchitectService.factory() as svc:
            return await svc.chat(
                mission_id, message,
                session_id=session_id,
                message_history=message_history,
            )

    # ── Workshop operations (Plan 32 Phase T6) ──────────────────────────

    async def get_cached_inputs(
        self, *, agent_name: str, mission_id: str,
    ) -> list[dict[str, Any]]:
        """Wraps WorkshopService.get_cached_inputs()."""
        from modules.backend.services.workshop import WorkshopService

        async with WorkshopService.factory() as svc:
            return await svc.get_cached_inputs(
                agent_name, mission_id=mission_id,
            )

    async def run_workshop_test(
        self,
        *,
        agent_name: str,
        prompt_override: str | None = None,
        inputs: dict[str, Any] | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        """Wraps WorkshopService.run_agent()."""
        from modules.backend.services.workshop import WorkshopService

        async with WorkshopService.factory() as svc:
            return await svc.run_agent(
                agent_name,
                prompt_override=prompt_override,
                inputs=inputs,
                budget_usd=budget_usd,
            )

    async def list_workshop_runs(
        self,
        *,
        agent_name: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Wraps WorkshopService.list_runs_as_dicts()."""
        from modules.backend.services.workshop import WorkshopService

        async with WorkshopService.factory() as svc:
            return await svc.list_runs_as_dicts(agent_name, limit)

    # ── Context operations (Plan 32 Phase T6) ──────────────────────────

    async def get_mission_context(
        self, mission_id: str,
    ) -> dict[str, Any]:
        """Wraps MissionContextManager.get_context()."""
        from modules.backend.services.mission_context import MissionContextManager

        async with MissionContextManager.factory() as svc:
            return await svc.get_context(mission_id)

    async def get_context_history(
        self, mission_id: str, *, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Wraps MissionContextManager.get_history()."""
        from modules.backend.services.mission_context import MissionContextManager

        async with MissionContextManager.factory() as svc:
            changes = await svc.get_history(mission_id, limit)
            return [
                {
                    "version": getattr(c, "version", 0),
                    "agent_id": getattr(c, "agent_id", ""),
                    "task_id": getattr(c, "task_id", ""),
                    "summary": getattr(c, "change_summary", ""),
                    "created_at": str(getattr(c, "created_at", "")),
                }
                for c in changes
            ]

    async def get_context_size(
        self, mission_id: str,
    ) -> dict[str, Any]:
        """Wraps MissionContextManager.get_context_size()."""
        from modules.backend.services.mission_context import MissionContextManager

        async with MissionContextManager.factory() as svc:
            return await svc.get_context_size(mission_id)

    # ── Health (Plan 32 Phase T1/T2) ───────────────────────────────────

    async def get_health(self) -> dict[str, Any]:
        """Wraps HealthCheckService.check_readiness()."""
        from modules.backend.services.health import HealthCheckService

        svc = HealthCheckService()
        report = await svc.check_readiness()
        return {
            "overall_status": _enum_str(report.overall_status),
            "components": [
                {
                    "name": c.name,
                    "status": _enum_str(c.status),
                    "latency_ms": c.latency_ms,
                    "error": c.error,
                }
                for c in report.components
            ],
        }

    # ── Admin operations (Plan 32 Phase T7) ────────────────────────────

    async def admin_create_agent(
        self, *, data: dict[str, Any],
    ) -> dict[str, Any]:
        """Wraps AgentCatalogService.create_entry()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            agent = await svc.create_entry(**data)
            return {
                "id": str(agent.id),
                "agent_name": agent.agent_name,
            }

    async def admin_update_agent(
        self, agent_name: str, *, data: dict[str, Any],
    ) -> dict[str, Any]:
        """Wraps AgentCatalogService.update_entry()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            agent = await svc.update_entry(agent_name, **data)
            return {
                "id": str(agent.id),
                "agent_name": agent.agent_name,
            }

    async def admin_delete_agent(self, agent_name: str) -> None:
        """Wraps AgentCatalogService.delete_entry()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            await svc.delete_entry(agent_name)

    async def admin_update_system_prompt(
        self,
        agent_name: str,
        *,
        prompt: str,
        change_reason: str | None = None,
    ) -> dict[str, Any]:
        """Wraps AgentCatalogService.update_system_prompt()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            agent = await svc.update_system_prompt(
                agent_name,
                content=prompt,
                changed_by=CLI_USER_ID,
                change_reason=change_reason,
            )
            return {
                "id": str(agent.id),
                "agent_name": agent.agent_name,
            }

    async def admin_get_prompt_history(
        self, agent_name: str, *, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Wraps AgentCatalogService.get_prompt_history()."""
        from modules.backend.services.agent_catalog import AgentCatalogService

        async with AgentCatalogService.factory() as svc:
            history = await svc.get_prompt_history(agent_name, limit)
            return [
                {
                    "id": str(getattr(h, "id", "")),
                    "version": getattr(h, "version", 0),
                    "content": getattr(h, "content", ""),
                    "changed_by": getattr(h, "changed_by", ""),
                    "change_reason": getattr(h, "change_reason", ""),
                    "created_at": str(getattr(h, "created_at", "")),
                }
                for h in history
            ]

    async def admin_get_metrics_overview(self) -> dict[str, Any]:
        """Wraps PlatformMetricsService.get_overview()."""
        from modules.backend.services.platform_metrics import PlatformMetricsService

        async with PlatformMetricsService.factory() as svc:
            return await svc.get_overview()

    async def admin_get_cost_breakdown(self) -> dict[str, Any]:
        """Wraps PlatformMetricsService.get_cost_summary()."""
        from modules.backend.services.platform_metrics import PlatformMetricsService

        async with PlatformMetricsService.factory() as svc:
            return await svc.get_cost_summary()

    async def admin_get_agent_utilisation(self) -> list[dict[str, Any]]:
        """Wraps PlatformMetricsService.get_agent_utilisation()."""
        from modules.backend.services.platform_metrics import PlatformMetricsService

        async with PlatformMetricsService.factory() as svc:
            return await svc.get_agent_utilisation()

    async def admin_get_activity(
        self, *, limit: int = 10,
    ) -> dict[str, Any]:
        """Wraps PlatformMetricsService.get_recent_activity()."""
        from modules.backend.services.platform_metrics import PlatformMetricsService

        async with PlatformMetricsService.factory() as svc:
            return await svc.get_recent_activity(limit)

    async def admin_get_config(self) -> dict[str, Any]:
        """Return platform configuration as dict."""
        from modules.backend.core.config import get_settings

        settings = get_settings()
        return {
            "application": {
                "name": "mission-control",
                "debug": settings.DEBUG if hasattr(settings, "DEBUG") else False,
            },
            "database": {
                "url": "***",
            },
        }

    async def admin_list_users(
        self, *, limit: int = 50, offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Wraps UserService.list_users()."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            users = await svc.list_users(
                requesting_user, limit=limit, offset=offset,
            )
            return [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "display_name": u.display_name or "",
                    "system_role": u.system_role,
                    "is_active": u.is_active,
                    "is_service_account": u.is_service_account,
                }
                for u in users
            ]

    async def admin_create_user(
        self, *, data: dict[str, Any],
    ) -> dict[str, Any]:
        """Wraps UserService.create_user()."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            user = await svc.create_user(
                email=data["email"],
                display_name=data["display_name"],
                password=data.get("password"),
                system_role=data.get("system_role", "user"),
                is_service_account=data.get("is_service_account", False),
                requesting_user=requesting_user,
            )
            await db.commit()
            return {"id": str(user.id), "email": user.email}

    async def admin_deactivate_user(self, user_id: str) -> None:
        """Wraps UserService.deactivate_user()."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            await svc.deactivate_user(user_id, requesting_user)
            await db.commit()

    async def admin_reset_password(
        self, user_id: str, *, new_password: str,
    ) -> None:
        """Wraps UserService.admin_reset_password()."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            await svc.admin_reset_password(
                user_id, new_password, requesting_user,
            )
            await db.commit()

    # ── Profile operations (Plan 32 Phase T7) ──────────────────────────

    async def get_profile(self) -> dict[str, Any]:
        """Get current user's profile."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            user = await svc.get_user(CLI_USER_ID, requesting_user)
            return {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name or "",
                "system_role": user.system_role,
                "is_service_account": user.is_service_account,
                "is_active": user.is_active,
            }

    async def update_display_name(
        self, *, display_name: str,
    ) -> None:
        """Update current user's display name."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            await svc.update_user(
                CLI_USER_ID, requesting_user,
                display_name=display_name,
            )
            await db.commit()

    async def change_password(
        self, *, current_password: str, new_password: str,
    ) -> None:
        """Change current user's password."""
        from modules.backend.services.user import UserService

        async with _cli_user_session() as (db, requesting_user):
            svc = UserService(db)
            await svc.change_password(
                CLI_USER_ID, current_password,
                new_password, requesting_user,
            )
            await db.commit()

    async def list_api_keys(self) -> list[dict[str, Any]]:
        """List current user's API keys."""
        from modules.backend.services.auth import AuthService

        async with _cli_user_session() as (db, requesting_user):
            svc = AuthService(db)
            keys = await svc.list_api_keys(CLI_USER_ID, requesting_user)
            return [
                {
                    "id": str(k.id),
                    "name": k.name,
                    "prefix": k.key_prefix if hasattr(k, "key_prefix") else "",
                    "expires_at": str(getattr(k, "expires_at", "never") or "never"),
                    "is_active": getattr(k, "is_active", True),
                }
                for k in keys
            ]

    async def create_api_key(
        self, *, name: str, expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        """Create an API key for the current user."""
        from modules.backend.services.auth import AuthService

        async with _cli_user_session() as (db, requesting_user):
            svc = AuthService(db)
            full_key, api_key = await svc.create_api_key(
                CLI_USER_ID, name, expires_in_days, requesting_user,
            )
            await db.commit()
            return {
                "full_key": full_key,
                "id": str(api_key.id),
                "name": api_key.name,
            }

    async def revoke_api_key(self, *, key_id: str) -> None:
        """Revoke an API key."""
        from modules.backend.services.auth import AuthService

        async with _cli_user_session() as (db, requesting_user):
            svc = AuthService(db)
            await svc.revoke_api_key(key_id, requesting_user)
            await db.commit()
