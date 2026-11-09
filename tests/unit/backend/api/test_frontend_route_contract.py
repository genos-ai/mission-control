"""Plan 88 step 88.0.13: the web gate UI calls the real gate routes.

The first two tests are static contracts between the frontend source and the
FastAPI route table. The last two use a real db_session with rollback, the
real MissionPlanService and the real exception handlers, so the gate route's
response shape and its operator rule are exercised end to end.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.missions_gates import router
from modules.backend.core import security
from modules.backend.core.config import find_project_root
from modules.backend.core.exception_handlers import register_exception_handlers
from modules.backend.core.utils import utc_now
from modules.backend.models.gate_request import GateRequest, GateRequestStatus
from modules.backend.models.mission import Mission, MissionMember, MissionMemberRole, MissionStatus
from modules.backend.models.user import User

_FRONTEND_SRC = find_project_root() / "modules" / "frontend" / "src"
_USE_GATES = _FRONTEND_SRC / "hooks" / "use-gates.ts"
_TEMPLATE_PARAM = re.compile(r"\$\{[^}]*\}")
_PATH_PARAM = re.compile(r"\{[^}]*\}")


def test_no_frontend_reference_to_submit_approval():
    offenders = [
        str(path.relative_to(_FRONTEND_SRC))
        for path in _FRONTEND_SRC.rglob("*")
        if path.is_file()
        and (
            "submit-approval" in path.read_text(encoding="utf-8", errors="ignore")
            or "agent.approval.requested" in path.read_text(encoding="utf-8", errors="ignore")
        )
    ]
    assert offenders == []


def test_gate_hook_targets_existing_route():
    from modules.backend.main import create_app

    source = _USE_GATES.read_text(encoding="utf-8")
    match = re.search(r"`(/missions/\$\{[^}]+\}/gates/\$\{[^}]+\}/decide)`", source)
    assert match is not None, "decide path template not found in use-gates.ts"
    hook_path = "/api/v1" + _TEMPLATE_PARAM.sub("{}", match.group(1))
    assert hook_path == "/api/v1/missions/{}/gates/{}/decide"

    routes = {
        (method, _PATH_PARAM.sub("{}", route.path))
        for route in create_app().routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("POST", hook_path) in routes


# ---- Real DB ----


def _user(label: str) -> User:
    return User(
        id=str(uuid4()),
        email=f"p88-gate-{label}-{uuid4().hex[:8]}@test.dev",
        display_name=label,
        hashed_password=security.hash_password("gate-password-123"),
        system_role="user",
        is_active=True,
    )


async def _mission_with_gate(
    db_session, owner: User, gate_type: str
) -> tuple[Mission, GateRequest]:
    mission = Mission(
        id=str(uuid4()),
        name=f"p88-gate-{uuid4().hex[:8]}",
        description="Plan 88 gate route test",
        owner_id=owner.id,
        status=MissionStatus.ACTIVE,
    )
    db_session.add(mission)
    await db_session.flush()
    gate = GateRequest(
        id=str(uuid4()),
        mission_id=mission.id,
        gate_type=gate_type,
        context_json={"gate_type": gate_type},
        status=GateRequestStatus.PENDING,
        created_at=utc_now(),
    )
    db_session.add(gate)
    await db_session.flush()
    return mission, gate


def _real_client(db_session, user: User) -> AsyncClient:
    from modules.backend.core.database import get_db_session
    from modules.backend.core.dependencies import get_current_user, get_event_bus

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1/missions")

    async def override_db():
        yield db_session

    async def override_user():
        return user

    async def override_bus():
        return AsyncMock()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_event_bus] = override_bus
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_get_gate_returns_allowed_actions(db_session):
    owner = _user("owner")
    db_session.add(owner)
    await db_session.flush()
    mission, gate = await _mission_with_gate(db_session, owner, "post_run")

    async with _real_client(db_session, owner) as ac:
        response = await ac.get(f"/api/v1/missions/{mission.id}/gates/{gate.id}")

    assert response.status_code == 200
    assert response.json()["data"]["allowed_actions"] == [
        "advance_approved",
        "advance_refine",
        "escalate",
        "propose_complete",
        "wait",
    ]


@pytest.mark.asyncio
async def test_decide_requires_operator(db_session):
    owner, viewer = _user("owner"), _user("viewer")
    db_session.add_all([owner, viewer])
    await db_session.flush()
    mission, gate = await _mission_with_gate(db_session, owner, "pre_layer")
    db_session.add(
        MissionMember(mission_id=mission.id, user_id=viewer.id, role=MissionMemberRole.VIEWER)
    )
    await db_session.flush()

    async with _real_client(db_session, viewer) as ac:
        response = await ac.post(
            f"/api/v1/missions/{mission.id}/gates/{gate.id}/decide",
            json={"action": "continue"},
        )

    assert response.status_code == 403
    await db_session.refresh(gate)
    assert gate.status == GateRequestStatus.PENDING
