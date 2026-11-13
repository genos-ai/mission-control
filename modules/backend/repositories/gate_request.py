"""
Gate Request Repository (Plan 88, contract 3.5.2).

Data access for gate_requests. 88.4.3 creates it with the undecided-gate
check and the archive-time cancel; 88.4.8 adds the decision methods.
"""

from sqlalchemy import exists, select, update

from modules.backend.models.gate_request import (
    UNDECIDED_GATE_STATUSES,
    GateRequest,
    GateRequestStatus,
)
from modules.backend.repositories.base import BaseRepository


class GateRequestRepository(BaseRepository[GateRequest]):
    """Repository for GateRequest rows."""

    model = GateRequest

    async def has_undecided(self, mission_id: str) -> bool:
        """True when any gate of the mission is PENDING, ESCALATED or TIMED_OUT."""
        stmt = select(
            exists().where(
                GateRequest.mission_id == mission_id,
                GateRequest.status.in_(UNDECIDED_GATE_STATUSES),
            )
        )
        return bool((await self.session.execute(stmt)).scalar())

    async def cancel_undecided(self, mission_id: str) -> int:
        """Set every undecided gate of the mission to CANCELLED; return the row count."""
        stmt = (
            update(GateRequest)
            .where(
                GateRequest.mission_id == mission_id,
                GateRequest.status.in_(UNDECIDED_GATE_STATUSES),
            )
            .values(status=GateRequestStatus.CANCELLED)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
