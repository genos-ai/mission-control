"""Shared rows for the Plan 88 budget tests (real db_session)."""

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.models.llm_call import LlmCall
from modules.backend.models.llm_call_daily_aggregate import LlmCallDailyAggregate
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun, MissionRunStatus, MissionRunTrigger


async def mission_with_plan(
    db: AsyncSession,
    owner_id: str,
    *,
    per_run: float = 5.0,
    per_month: float = 100.0,
    lifetime: float | None = None,
) -> tuple[str, str]:
    """Insert a mission and its plan with the given caps; return (mission_id, plan_id)."""
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"budget-{uuid.uuid4().hex[:8]}",
        description="Budget test mission",
        owner_id=owner_id,
    )
    db.add(mission)
    await db.flush()
    plan = MissionPlan(
        mission_id=mission.id,
        gate_mode=GateMode.MANUAL,
        budget_per_run_usd=per_run,
        budget_per_month_usd=per_month,
        budget_lifetime_usd=lifetime,
    )
    db.add(plan)
    await db.flush()
    return mission.id, plan.id


async def run(
    db: AsyncSession,
    mission_id: str,
    plan_id: str,
    *,
    sequence: int = 1,
    status: MissionRunStatus = MissionRunStatus.RUNNING,
    cap: float | None = None,
) -> str:
    """Insert a manual run; return its id."""
    row = MissionRun(
        mission_id=mission_id,
        plan_id=plan_id,
        sequence=sequence,
        trigger=MissionRunTrigger.MANUAL,
        status=status,
        budget_cap_usd=cap,
    )
    db.add(row)
    await db.flush()
    return row.id


async def call(
    db: AsyncSession,
    mission_id: str,
    cost: float,
    at: datetime,
    *,
    run_id: str | None = None,
) -> None:
    """Insert one llm_calls ledger row."""
    db.add(
        LlmCall(
            agent_name="test.agent",
            agent_role="worker",
            model="test-model",
            provider="test",
            input_tokens=1,
            output_tokens=1,
            cost_usd=cost,
            mission_id=mission_id,
            mission_run_id=run_id,
            created_at=at,
            updated_at=at,
        )
    )
    await db.flush()


async def aggregate(db: AsyncSession, mission_id: str | None, day: date, cost: float) -> None:
    """Insert one llm_call_daily_aggregates row."""
    db.add(
        LlmCallDailyAggregate(
            day=day,
            mission_id=mission_id,
            agent_name="test.agent",
            model="test-model",
            provider="test",
            call_count=1,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            thinking_tokens=0,
            cost_usd=cost,
        )
    )
    await db.flush()
