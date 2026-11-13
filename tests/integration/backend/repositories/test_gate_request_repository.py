"""GateRequestRepository (Plan 88, 88.4.3): undecided check and archive-time cancel."""

from uuid import uuid7

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission import Mission
from modules.backend.repositories.gate_request import GateRequestRepository
from tests.integration.backend.api.helpers import create_mission


async def _gate(db: AsyncSession, mission: Mission, status: GateRequestStatus) -> str:
    gate = GateRequest(
        mission_id=mission.id,
        gate_type="post_run",
        context_json={},
        status=status,
        created_at=utc_now(),
    )
    db.add(gate)
    await db.flush()
    return gate.id


async def _statuses(db: AsyncSession, mission_id: str) -> dict[str, GateRequestStatus]:
    rows = await db.execute(
        select(GateRequest.id, GateRequest.status)
        .where(GateRequest.mission_id == mission_id)
        .execution_options(populate_existing=True)
    )
    return {gate_id: status for gate_id, status in rows.all()}


async def test_has_undecided_counts_escalated_and_timed_out(
    db_session: AsyncSession, test_user
) -> None:
    repo = GateRequestRepository(db_session)
    for status in (GateRequestStatus.ESCALATED, GateRequestStatus.TIMED_OUT):
        mission = await create_mission(db_session, f"undecided-{uuid7()}", test_user.id)
        await _gate(db_session, mission, GateRequestStatus.DECIDED)
        assert await repo.has_undecided(mission.id) is False
        await _gate(db_session, mission, status)
        assert await repo.has_undecided(mission.id) is True


async def test_cancel_undecided_leaves_decided_rows(db_session: AsyncSession, test_user) -> None:
    mission = await create_mission(db_session, f"cancel-{uuid7()}", test_user.id)
    other = await create_mission(db_session, f"cancel-other-{uuid7()}", test_user.id)
    undecided = [
        await _gate(db_session, mission, status)
        for status in (
            GateRequestStatus.PENDING,
            GateRequestStatus.ESCALATED,
            GateRequestStatus.TIMED_OUT,
        )
    ]
    decided = await _gate(db_session, mission, GateRequestStatus.DECIDED)
    other_pending = await _gate(db_session, other, GateRequestStatus.PENDING)
    repo = GateRequestRepository(db_session)

    assert await repo.cancel_undecided(mission.id) == 3

    statuses = await _statuses(db_session, mission.id)
    assert all(statuses[gate_id] == GateRequestStatus.CANCELLED for gate_id in undecided)
    assert statuses[decided] == GateRequestStatus.DECIDED
    assert (await _statuses(db_session, other.id))[other_pending] == GateRequestStatus.PENDING
    assert await repo.has_undecided(mission.id) is False
