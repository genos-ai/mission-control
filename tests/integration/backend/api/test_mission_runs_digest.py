"""GET /missions/{id}/runs/{run_id_or_seq} returns the run's digest (Plan 88 step 88.3.8).

The digest comes from RunMemoryService.get_digest inside ApiResponse, with the
generator and every outcome status as lowercase values and each outcome's
artifact_ids. A run with no digest (it never reached RUNNING) has digest null;
another mission's run is 404.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.utils import utc_now
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode
from modules.backend.models.mission_run import (
    MissionRun,
    MissionRunStatus,
    MissionRunStatusReason,
    MissionRunTrigger,
)
from modules.backend.models.mission_run_digest import DigestGenerator, MissionRunDigest
from tests.conftest import TEST_USER_ID
from tests.integration.backend.api.helpers import create_mission, set_plan

pytestmark = pytest.mark.usefixtures("signed_in")

TASK_ID = "00000000-0000-0000-0000-0000000000c1"
ARTIFACT_ID = "00000000-0000-0000-0000-0000000000d1"


async def _run(
    db: AsyncSession, mission: Mission, sequence: int, status: MissionRunStatus
) -> MissionRun:
    plan = await set_plan(db, mission, GateMode.AUTONOMOUS)
    run = MissionRun(
        mission_id=mission.id,
        plan_id=plan.id,
        sequence=sequence,
        trigger=MissionRunTrigger.MANUAL,
        triggered_by_user_id=TEST_USER_ID,
        objective="Summarise open issues",
        status=status,
        status_reason=(
            MissionRunStatusReason.NO_FURTHER_WORK if status == MissionRunStatus.SUCCEEDED else None
        ),
        context_version_start=0,
        context_version_end=2,
        started_at=utc_now(),
        ended_at=utc_now(),
    )
    db.add(run)
    await db.flush()
    return run


async def _digest(db: AsyncSession, run: MissionRun) -> MissionRunDigest:
    digest = MissionRunDigest(
        mission_run_id=run.id,
        mission_id=run.mission_id,
        schema_version=1,
        generator=DigestGenerator.AGENT,
        summary="Run #1 ended succeeded (no_further_work). 1/1 tasks completed, 0 failed.",
        outcomes=[
            {
                "task_id": TASK_ID,
                "agent": "research.analyst.agent",
                "status": "completed",
                "headline": "Listed the open issues",
                "artifact_ids": [ARTIFACT_ID],
            }
        ],
        decisions=[],
        open_items=[{"text": "Triage issue 12", "source_task_id": TASK_ID}],
        context_changes=[{"version": 2, "change_type": "update", "path": "current_state.focus"}],
        metrics={
            "cost_usd": 0.01,
            "duration_seconds": 42.0,
            "task_count": 1,
            "completed_task_count": 1,
            "failed_task_count": 0,
            "iteration_count": 1,
        },
        generation_cost_usd=0.002,
    )
    db.add(digest)
    await db.flush()
    return digest


@pytest.fixture
async def mission(db_session: AsyncSession, test_user) -> Mission:
    return await create_mission(db_session, "digest-read", TEST_USER_ID)


@pytest.mark.asyncio
async def test_run_detail_includes_digest(client, db_session, mission):
    run = await _run(db_session, mission, 1, MissionRunStatus.SUCCEEDED)
    digest = await _digest(db_session, run)

    resp = await client.get(f"/api/v1/missions/{mission.id}/runs/1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    got = body["data"]["digest"]
    assert got["id"] == digest.id
    assert got["mission_run_id"] == run.id
    assert got["generator"] == "agent"
    assert got["summary"] == digest.summary
    assert got["outcomes"] == [
        {
            "task_id": TASK_ID,
            "agent": "research.analyst.agent",
            "status": "completed",
            "headline": "Listed the open issues",
            "artifact_ids": [ARTIFACT_ID],
        }
    ]
    assert got["open_items"] == [{"text": "Triage issue 12", "source_task_id": TASK_ID}]
    assert got["context_changes"] == [
        {"version": 2, "change_type": "update", "path": "current_state.focus"}
    ]
    assert got["decisions"] == []
    assert got["metrics"]["iteration_count"] == 1
    assert got["generation_cost_usd"] == pytest.approx(0.002)
    assert got["created_at"]


@pytest.mark.asyncio
async def test_run_detail_digest_null_for_skipped_run(client, db_session, mission):
    run = await _run(db_session, mission, 1, MissionRunStatus.SKIPPED)

    resp = await client.get(f"/api/v1/missions/{mission.id}/runs/{run.id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["digest"] is None


@pytest.mark.asyncio
async def test_run_detail_other_mission_404(client, db_session, mission):
    other = await create_mission(db_session, "digest-other", TEST_USER_ID)
    run = await _run(db_session, other, 1, MissionRunStatus.SUCCEEDED)
    await _digest(db_session, run)

    resp = await client.get(f"/api/v1/missions/{mission.id}/runs/{run.id}")

    assert resp.status_code == 404, resp.text
