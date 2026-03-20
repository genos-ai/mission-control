"""Async service wrappers for the TUI.

Bridges Textual's @work coroutines to backend service factories.
Each method opens its own DB session, keeping the TUI stateless
with respect to database connections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.backend.agents.mission_control.gate import GateReviewer
from modules.backend.agents.mission_control.mission_control import handle_mission
from modules.backend.agents.mission_control.models import EventBusProtocol, NoOpEventBus
from modules.backend.agents.mission_control.outcome import ExecutionOutcome
from modules.backend.agents.mission_control.roster import load_roster, Roster
from modules.backend.core.database import get_async_session
from modules.backend.core.logging import get_logger
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission import MissionService
from modules.backend.services.session import SessionService

if TYPE_CHECKING:
    from modules.backend.models.mission import Mission

logger = get_logger(__name__)


class ServiceBridge:
    """Facade that wraps backend service factories for TUI consumption.

    Every public method manages its own DB session via async context manager.
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
        async with get_async_session() as db:
            svc = MissionService(db)
            missions = await svc.list_missions()
            return [
                {
                    "id": str(m.id),
                    "name": m.name,
                    "description": m.description,
                    "status": m.status,
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
        async with get_async_session() as db:
            svc = MissionService(db)
            mission = await svc.create_mission(name=name, description=description)
            await db.commit()
            return {"id": str(mission.id), "name": mission.name}

    async def get_mission(self, mission_id: str) -> Mission | None:
        """Fetch a single mission by ID."""
        async with get_async_session() as db:
            svc = MissionService(db)
            return await svc.get_mission(mission_id)

    # ── Roster ───────────────────────────────────────────────────────

    def load_roster(self, roster_name: str = "default") -> Roster:
        """Load agent roster from YAML config."""
        return load_roster(roster_name)

    # ── Execution dispatch ──────────────────────────────────────────

    async def run_execution(
        self,
        *,
        brief: str,
        project_id: str,
        session_id: str,
        roster_name: str = "default",
        budget_usd: float = 10.0,
        gate: GateReviewer | None = None,
    ) -> ExecutionOutcome:
        """Execute a dispatch in-process with full event streaming.

        This is the TUI's primary execution path. It calls handle_mission()
        directly, wiring the TuiGateReviewer and TuiEventBus.
        """
        async with get_async_session() as db:
            session_service = SessionService(db)
            mission_id = f"tui-{session_id}"

            outcome = await handle_mission(
                mission_id=mission_id,
                mission_brief=brief,
                session_service=session_service,
                event_bus=self._event_bus,
                roster_name=roster_name,
                mission_budget_usd=budget_usd,
                session_id=session_id,
                project_id=project_id,
                db_session=db,
                gate=gate,
            )

            await db.commit()
            return outcome

    # ── Execution history ─────────────────────────────────────────────

    async def list_executions(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return execution records as dicts for the history screen."""
        async with get_async_session() as db:
            svc = ExecutionPersistenceService(db)
            records = await svc.list_executions(
                status=status, limit=limit, offset=offset,
            )
            return [
                {
                    "id": str(r.id),
                    "execution_id": r.execution_id if hasattr(r, "execution_id") else str(r.id),
                    "objective": getattr(r, "objective", "") or "",
                    "status": getattr(r, "status", "unknown"),
                    "total_cost_usd": getattr(r, "total_cost_usd", 0.0) or 0.0,
                    "roster_name": getattr(r, "roster_name", "") or "",
                    "created_at": str(getattr(r, "created_at", "")),
                }
                for r in records
            ]

    async def get_execution_detail(self, execution_id: str) -> dict[str, Any] | None:
        """Return a single execution record with task details."""
        async with get_async_session() as db:
            svc = ExecutionPersistenceService(db)
            record = await svc.get_execution(execution_id)
            if not record:
                return None
            task_executions = await svc.get_task_executions(execution_id)
            return {
                "id": str(record.id),
                "objective": getattr(record, "objective", ""),
                "status": getattr(record, "status", "unknown"),
                "total_cost_usd": getattr(record, "total_cost_usd", 0.0) or 0.0,
                "roster_name": getattr(record, "roster_name", ""),
                "created_at": str(getattr(record, "created_at", "")),
                "task_plan_json": getattr(record, "task_plan_json", None),
                "mission_outcome_json": getattr(record, "mission_outcome_json", None),
                "task_executions": [
                    {
                        "task_id": getattr(t, "task_id", ""),
                        "agent_name": getattr(t, "agent_name", ""),
                        "status": getattr(t, "status", ""),
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
        async with get_async_session() as db:
            svc = ExecutionPersistenceService(db)
            return await svc.get_cost_breakdown(execution_id)
