"""Tests for GateMode and eager plan creation (Plan 88 step 88.1.0)."""

import uuid

import pydantic
import pytest
import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import find_project_root
from modules.backend.core.config_schema import GateSchema
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.models.mission import Mission
from modules.backend.models.mission_plan import AUTO_APPROVE_GATE_MODES, GateMode, MissionPlan
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_plan import MissionPlanService


def test_values_are_lowercase_names():
    assert [m.value for m in GateMode] == ["interactive", "manual", "ai_assisted", "autonomous"]


def test_auto_approve_only_autonomous():
    assert AUTO_APPROVE_GATE_MODES == frozenset({GateMode.AUTONOMOUS})


@pytest.mark.asyncio
async def test_enum_stores_name(db_session: AsyncSession, test_user):
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="GateMode storage test",
        owner_id=test_user.id,
    )
    db_session.add(mission)
    await db_session.flush()
    plan = MissionPlan(mission_id=mission.id, gate_mode=GateMode.AI_ASSISTED)
    db_session.add(plan)
    await db_session.flush()

    stored = await db_session.scalar(
        text("SELECT gate_mode FROM mission_plans WHERE id = :id"), {"id": plan.id}
    )

    assert stored == "AI_ASSISTED"


@pytest.mark.asyncio
async def test_create_mission_creates_plan_with_mode(db_session: AsyncSession, test_user):
    mission = await MissionService(db_session).create_mission(
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Eager plan test",
        owner_id=test_user.id,
        gate_mode="manual",
    )

    plans = (
        (await db_session.execute(select(MissionPlan).where(MissionPlan.mission_id == mission.id)))
        .scalars()
        .all()
    )

    assert len(plans) == 1
    assert plans[0].gate_mode == GateMode.MANUAL


@pytest.mark.asyncio
async def test_create_mission_rejects_unknown_mode(db_session: AsyncSession, test_user):
    with pytest.raises(ValidationError):
        await MissionService(db_session).create_mission(
            name=f"test-{uuid.uuid4().hex[:8]}",
            description="Bad gate mode",
            owner_id=test_user.id,
            gate_mode="bogus",
        )


@pytest.mark.asyncio
async def test_get_or_create_plan_raises_when_absent(db_session: AsyncSession, test_user):
    mission = Mission(
        id=str(uuid.uuid4()),
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="Mission without a plan",
        owner_id=test_user.id,
    )
    db_session.add(mission)
    await db_session.flush()

    with pytest.raises(NotFoundError, match="has no plan"):
        await MissionPlanService(db_session).get_or_create_plan(mission.id)


def test_gate_schema_mode_required():
    path = find_project_root() / "config" / "settings" / "gate.yaml"
    mapping = yaml.safe_load(path.read_text())
    del mapping["mode"]

    with pytest.raises(pydantic.ValidationError, match="mode"):
        GateSchema.model_validate(mapping)
