"""Tests for RunMemoryService's context packet and planning brief (Plan 88, 88.3.5).

Runs against the real test database (P12) with transaction rollback.
"""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger
from modules.backend.models.mission_run_digest import DigestGenerator, MissionRunDigest
from modules.backend.services.mission_context import MissionContextManager
from modules.backend.services.run_memory import RunMemoryService
from tests.conftest import TEST_USER_ID

_MOD = "modules.backend.services.run_memory"


async def _mission(db_session: AsyncSession) -> tuple[str, str]:
    mission_id, plan_id = str(uuid4()), str(uuid4())
    db_session.add(
        Mission(id=mission_id, name=f"mem-{mission_id}", description="t", owner_id=TEST_USER_ID)
    )
    db_session.add(
        MissionPlan(
            id=plan_id,
            mission_id=mission_id,
            gate_mode=GateMode.AUTONOMOUS,
            budget_per_run_usd=5.0,
            budget_per_month_usd=100.0,
        )
    )
    await db_session.flush()
    return mission_id, plan_id


async def _run(
    db_session: AsyncSession,
    mission_id: str,
    plan_id: str,
    sequence: int,
    *,
    start: int | None,
    previous: str | None = None,
    status: MissionRunStatus = MissionRunStatus.SUCCEEDED,
) -> str:
    run = MissionRun(
        mission_id=mission_id,
        plan_id=plan_id,
        sequence=sequence,
        trigger=MissionRunTrigger.MANUAL,
        status=status,
        context_version_start=start,
        previous_run_id=previous,
    )
    db_session.add(run)
    await db_session.flush()
    return run.id


async def _write_to(manager: MissionContextManager, mission_id: str, version: int) -> None:
    """Apply one single-change update per version until the MCD reaches ``version``."""
    _, current = await manager.get_context_with_version(mission_id)
    for v in range(current + 1, version + 1):
        await manager.apply_updates(
            mission_id,
            [
                {
                    "op": "add",
                    "path": f"architecture.components.c{v}",
                    "value": {"n": v},
                    "reason": f"r{v}",
                }
            ],
            agent_id="test",
            task_id=None,
            mission_run_id=None,
            reason="test",
        )


async def _two_runs(db_session: AsyncSession, *, first_start: int, second_start: int):
    """An MCD written to second_start; run 1 started at first_start, run 2 at second_start."""
    mission_id, plan_id = await _mission(db_session)
    manager = MissionContextManager(db_session)
    await manager.create_context(mission_id, "mem", "desc")
    await _write_to(manager, mission_id, first_start)
    run1 = await _run(db_session, mission_id, plan_id, 1, start=first_start)
    await _write_to(manager, mission_id, second_start)
    run2 = await _run(
        db_session,
        mission_id,
        plan_id,
        2,
        start=second_start,
        previous=run1,
        status=MissionRunStatus.RUNNING,
    )
    return mission_id, run1, run2, manager


def _digest(mission_id: str, run_id: str, summary: str = "Did the thing.") -> MissionRunDigest:
    return MissionRunDigest(
        mission_run_id=run_id,
        mission_id=mission_id,
        schema_version=1,
        generator=DigestGenerator.DETERMINISTIC,
        summary=summary,
        outcomes=[],
        open_items=[{"text": "Fix the flaky test", "source_task_id": None}],
        metrics={"tasks_completed": 2},
    )


@pytest.mark.asyncio
async def test_first_run_has_no_digest_or_delta(test_user, db_session):
    mission_id, plan_id = await _mission(db_session)
    run_id = await _run(
        db_session, mission_id, plan_id, 1, start=1, status=MissionRunStatus.RUNNING
    )

    packet = await RunMemoryService(db_session).build_context_packet(run_id)

    assert packet.is_first_run is True
    assert packet.previous_run_digest is None
    assert packet.context_delta is None


@pytest.mark.asyncio
async def test_delta_is_changes_between_previous_and_current_watermark(test_user, db_session):
    _, _, run2, _ = await _two_runs(db_session, first_start=3, second_start=7)

    packet = await RunMemoryService(db_session).build_context_packet(run2)

    delta = packet.context_delta
    assert packet.is_first_run is False
    assert (delta.from_version, delta.to_version) == (3, 7)
    assert [e.version for e in delta.entries] == [4, 5, 6, 7]
    assert delta.entries[0].path == "architecture.components.c4"
    assert delta.entries[0].value_excerpt == '{"n": 4}'
    assert delta.entries[0].reason == "r4"
    assert delta.omitted_count == 0


@pytest.mark.asyncio
async def test_delta_excludes_changes_after_current_start(test_user, db_session):
    mission_id, _, run2, manager = await _two_runs(db_session, first_start=3, second_start=5)
    await _write_to(manager, mission_id, 8)

    packet = await RunMemoryService(db_session).build_context_packet(run2)

    assert [e.version for e in packet.context_delta.entries] == [4, 5]


@pytest.mark.asyncio
async def test_delta_truncation_reports_omitted_count(test_user, db_session):
    _, _, run2, _ = await _two_runs(db_session, first_start=1, second_start=11)
    cfg = SimpleNamespace(
        missions=SimpleNamespace(
            context_packet=SimpleNamespace(
                previous_digest_max_chars=4000,
                context_delta_max_changes=6,
                context_delta_max_tokens=10_000,
                context_delta_value_max_chars=200,
            )
        )
    )

    with patch(f"{_MOD}.get_app_config", return_value=cfg):
        packet = await RunMemoryService(db_session).build_context_packet(run2)

    delta = packet.context_delta
    assert [e.version for e in delta.entries] == [6, 7, 8, 9, 10, 11]
    assert delta.omitted_count == 4


@pytest.mark.asyncio
async def test_delta_token_cap_drops_oldest(test_user, db_session):
    _, _, run2, _ = await _two_runs(db_session, first_start=1, second_start=11)
    cfg = SimpleNamespace(
        missions=SimpleNamespace(
            context_packet=SimpleNamespace(
                previous_digest_max_chars=4000,
                context_delta_max_changes=100,
                context_delta_max_tokens=100,
                context_delta_value_max_chars=200,
            )
        )
    )

    with patch(f"{_MOD}.get_app_config", return_value=cfg):
        packet = await RunMemoryService(db_session).build_context_packet(run2)

    delta = packet.context_delta
    assert 0 < len(delta.entries) < 10
    assert delta.entries[-1].version == 11
    assert delta.omitted_count == 10 - len(delta.entries)


@pytest.mark.asyncio
async def test_planning_brief_empty_for_first_run(test_user, db_session):
    mission_id, plan_id = await _mission(db_session)
    run_id = await _run(
        db_session, mission_id, plan_id, 1, start=1, status=MissionRunStatus.RUNNING
    )
    service = RunMemoryService(db_session)

    assert service.render_planning_brief(await service.build_context_packet(run_id)) == ""


@pytest.mark.asyncio
async def test_planning_brief_contains_previous_summary_and_open_items(test_user, db_session):
    mission_id, run1, run2, _ = await _two_runs(db_session, first_start=2, second_start=4)
    db_session.add(_digest(mission_id, run1))
    await db_session.flush()
    service = RunMemoryService(db_session)

    packet = await service.build_context_packet(run2)
    brief = service.render_planning_brief(packet)

    assert packet.previous_run_digest.summary == "Did the thing."
    assert "## Previous run (#1, succeeded, digest: deterministic)" in brief
    assert "Did the thing." in brief
    assert "### Open items\n- Fix the flaky test" in brief
    assert "## Mission context changes since previous run (v2→v4)" in brief
    assert "- v3 add architecture.components.c3" in brief
    assert "- v4 add architecture.components.c4" in brief
    assert "omitted" not in brief


@pytest.mark.asyncio
async def test_previous_digest_summary_truncated(test_user, db_session):
    mission_id, run1, run2, _ = await _two_runs(db_session, first_start=1, second_start=1)
    db_session.add(_digest(mission_id, run1, summary="x" * 5000))
    await db_session.flush()

    packet = await RunMemoryService(db_session).build_context_packet(run2)

    assert len(packet.previous_run_digest.summary) == 4000
    assert packet.context_delta.entries == []
