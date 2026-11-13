"""Backend integration fixtures: committed missions for multi-session tests."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import uuid7

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.backend.core import security
from modules.backend.models.execution_record import (
    ExecutionDecision,
    ExecutionRecord,
    TaskExecution,
)
from modules.backend.models.llm_call import LlmCall
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import GateMode, MissionPlan
from modules.backend.models.mission_run import MissionRun
from modules.backend.models.mission_schedule import MissionSchedule
from modules.backend.models.session import Session
from modules.backend.models.user import User
from modules.backend.models.workflow_definition import WorkflowDefinition
from modules.backend.models.workflow_run import WorkflowRun


@pytest.fixture
async def committed_owner(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[Callable[[], Awaitable[tuple[User, Mission, MissionPlan]]], None]:
    """Factory for a committed user, mission and MANUAL plan; all deleted on teardown.

    Multi-session tests need rows other sessions can see, so the rolled-back
    db_session fixture does not serve.
    """
    users: list[str] = []
    missions: list[str] = []

    async def make() -> tuple[User, Mission, MissionPlan]:
        suffix = str(uuid7())
        async with db_session_factory() as session:
            user = User(
                email=f"repo-{suffix}@test.dev",
                display_name="Repo Test",
                hashed_password=security.hash_password("repo-test-password"),
                system_role="user",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            mission = Mission(
                name=f"repo-{suffix}",
                description="repository test",
                owner_id=user.id,
                status="active",
                default_roster="default",
            )
            session.add(mission)
            await session.flush()
            plan = MissionPlan(
                mission_id=mission.id,
                gate_mode=GateMode.MANUAL,
                budget_per_run_usd=5.0,
                budget_per_month_usd=100.0,
            )
            session.add(plan)
            await session.commit()
            users.append(user.id)
            missions.append(mission.id)
            return user, mission, plan

    yield make

    async with db_session_factory() as session:
        if missions:
            # Rows without a CASCADE FK to missions would outlive them; remove them first.
            # Runs and schedules hold RESTRICT FKs to workflow definitions.
            records = select(ExecutionRecord.id).where(ExecutionRecord.mission_id.in_(missions))
            for child in (TaskExecution, ExecutionDecision):
                await session.execute(delete(child).where(child.execution_record_id.in_(records)))
            for model in (
                ExecutionRecord,
                LlmCall,
                WorkflowRun,
                Session,
                MissionRun,
                MissionSchedule,
                WorkflowDefinition,
            ):
                await session.execute(delete(model).where(model.mission_id.in_(missions)))
            await session.execute(delete(Mission).where(Mission.id.in_(missions)))
        if users:
            await session.execute(delete(User).where(User.id.in_(users)))
        await session.commit()
