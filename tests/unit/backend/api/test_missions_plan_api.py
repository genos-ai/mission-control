"""Tests for the mission plan API operator rule (Plan 88, step 88.0.9).

Real db_session with rollback; the router runs with the real exception handlers.
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.missions_plan import router
from modules.backend.core import security
from modules.backend.core.exception_handlers import register_exception_handlers
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.user import User
from modules.backend.services.mission_plan import MissionPlanService


@pytest.mark.asyncio
async def test_patch_plan_gate_mode_viewer_forbidden(db_session, test_user):
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user

    viewer = User(
        id=str(uuid4()),
        email=f"p88-plan-viewer-{uuid4().hex[:8]}@test.dev",
        display_name="Viewer",
        hashed_password=security.hash_password("viewer-password-123"),
        system_role="user",
        is_active=True,
    )
    mission = Mission(
        id=str(uuid4()),
        name=f"p88-plan-viewer-{uuid4().hex[:8]}",
        description="Plan 88 viewer test",
        owner_id=test_user.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add_all([viewer, mission])
    await db_session.flush()
    db_session.add(
        MissionMember(mission_id=mission.id, user_id=viewer.id, role=MissionMemberRole.VIEWER)
    )
    await db_session.flush()
    plan = await MissionPlanService(db_session).get_or_create_plan(mission.id)
    plan.gate_mode = "manual"
    await db_session.flush()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1/missions")

    async def override_db():
        yield db_session

    async def override_user():
        return viewer

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.patch(
            f"/api/v1/missions/{mission.id}/plan", json={"gate_mode": "autonomous"}
        )

    assert response.status_code == 403
    await db_session.refresh(plan)
    assert plan.gate_mode == "manual"
