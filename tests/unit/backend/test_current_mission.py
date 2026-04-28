"""Tests for current mission selection feature.

Covers UserService.set_current_mission(), UserResponse.from_user(),
SetCurrentMissionRequest validation, and the auth API endpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modules.backend.api.v1.endpoints.auth import router
from modules.backend.core.database import get_db_session
from modules.backend.core.dependencies import get_current_user
from modules.backend.core.exceptions import NotFoundError, ValidationError
from modules.backend.schemas.user import (
    SetCurrentMissionRequest,
    UserResponse,
)
from tests.conftest import TEST_USER_ID


# ── Schema tests ──────────────────────────────────────────────────────


class TestSetCurrentMissionRequest:
    def test_valid_mission_id(self):
        req = SetCurrentMissionRequest(mission_id="abc-123")
        assert req.mission_id == "abc-123"

    def test_null_clears(self):
        req = SetCurrentMissionRequest(mission_id=None)
        assert req.mission_id is None

    def test_default_is_none(self):
        req = SetCurrentMissionRequest()
        assert req.mission_id is None

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            SetCurrentMissionRequest(mission_id="abc", extra_field="bad")


class TestUserResponseFromUser:
    def test_with_current_mission(self):
        mission = MagicMock()
        mission.name = "Alpha"

        user = MagicMock()
        user.id = TEST_USER_ID
        user.email = "a@b.com"
        user.display_name = "Test"
        user.system_role = "user"
        user.is_active = True
        user.is_service_account = False
        user.last_login_at = None
        user.current_mission_id = "mission-1"
        user.current_mission = mission
        user.created_at = "2026-01-01T00:00:00"
        user.updated_at = "2026-01-01T00:00:00"

        response = UserResponse.from_user(user)
        assert response.current_mission_id == "mission-1"
        assert response.current_mission_name == "Alpha"

    def test_without_current_mission(self):
        user = MagicMock()
        user.id = TEST_USER_ID
        user.email = "a@b.com"
        user.display_name = "Test"
        user.system_role = "user"
        user.is_active = True
        user.is_service_account = False
        user.last_login_at = None
        user.current_mission_id = None
        user.current_mission = None
        user.created_at = "2026-01-01T00:00:00"
        user.updated_at = "2026-01-01T00:00:00"

        response = UserResponse.from_user(user)
        assert response.current_mission_id is None
        assert response.current_mission_name is None


# ── Service tests ─────────────────────────────────────────────────────


class TestUserServiceSetCurrentMission:
    @pytest.mark.asyncio
    async def test_set_mission_happy_path(self):
        from modules.backend.services.user import UserService

        mock_session = AsyncMock()
        service = UserService(mock_session)

        requesting_user = MagicMock()
        requesting_user.id = TEST_USER_ID
        requesting_user.has_role = MagicMock(return_value=False)

        mock_mission = MagicMock()
        mock_mission.status = "active"

        with patch.object(service, "user_repo") as mock_user_repo, \
             patch("modules.backend.repositories.mission.MissionRepository") as MockMissionRepo:
            mock_mission_repo = MockMissionRepo.return_value
            mock_mission_repo.get_by_id_or_none = AsyncMock(return_value=mock_mission)

            updated_user = MagicMock()
            mock_user_repo.update = AsyncMock(return_value=updated_user)

            result = await service.set_current_mission(
                user_id=TEST_USER_ID,
                mission_id="mission-1",
                requesting_user=requesting_user,
            )

            mock_mission_repo.get_by_id_or_none.assert_awaited_once_with("mission-1")
            mock_user_repo.update.assert_awaited_once_with(
                TEST_USER_ID, current_mission_id="mission-1",
            )
            assert result is updated_user

    @pytest.mark.asyncio
    async def test_clear_mission(self):
        from modules.backend.services.user import UserService

        mock_session = AsyncMock()
        service = UserService(mock_session)

        requesting_user = MagicMock()
        requesting_user.id = TEST_USER_ID
        requesting_user.has_role = MagicMock(return_value=False)

        with patch.object(service, "user_repo") as mock_user_repo:
            updated_user = MagicMock()
            mock_user_repo.update = AsyncMock(return_value=updated_user)

            result = await service.set_current_mission(
                user_id=TEST_USER_ID,
                mission_id=None,
                requesting_user=requesting_user,
            )

            mock_user_repo.update.assert_awaited_once_with(
                TEST_USER_ID, current_mission_id=None,
            )

    @pytest.mark.asyncio
    async def test_mission_not_found(self):
        from modules.backend.services.user import UserService

        mock_session = AsyncMock()
        service = UserService(mock_session)

        requesting_user = MagicMock()
        requesting_user.id = TEST_USER_ID
        requesting_user.has_role = MagicMock(return_value=False)

        with patch("modules.backend.repositories.mission.MissionRepository") as MockMissionRepo:
            mock_mission_repo = MockMissionRepo.return_value
            mock_mission_repo.get_by_id_or_none = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError):
                await service.set_current_mission(
                    user_id=TEST_USER_ID,
                    mission_id="nonexistent",
                    requesting_user=requesting_user,
                )

    @pytest.mark.asyncio
    async def test_inactive_mission_rejected(self):
        from modules.backend.services.user import UserService

        mock_session = AsyncMock()
        service = UserService(mock_session)

        requesting_user = MagicMock()
        requesting_user.id = TEST_USER_ID
        requesting_user.has_role = MagicMock(return_value=False)

        mock_mission = MagicMock()
        mock_mission.status = "archived"

        with patch("modules.backend.repositories.mission.MissionRepository") as MockMissionRepo:
            mock_mission_repo = MockMissionRepo.return_value
            mock_mission_repo.get_by_id_or_none = AsyncMock(return_value=mock_mission)

            with pytest.raises(ValidationError):
                await service.set_current_mission(
                    user_id=TEST_USER_ID,
                    mission_id="archived-mission",
                    requesting_user=requesting_user,
                )

    @pytest.mark.asyncio
    async def test_non_self_user_rejected(self):
        from modules.backend.core.exceptions import AuthorizationError
        from modules.backend.services.user import UserService

        mock_session = AsyncMock()
        service = UserService(mock_session)

        requesting_user = MagicMock()
        requesting_user.id = "other-user"
        requesting_user.has_role = MagicMock(return_value=False)

        with pytest.raises(AuthorizationError):
            await service.set_current_mission(
                user_id=TEST_USER_ID,
                mission_id="mission-1",
                requesting_user=requesting_user,
            )


# ── API tests ─────────────────────────────────────────────────────────


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/auth")

    from fastapi.responses import JSONResponse
    from modules.backend.core.exceptions import NotFoundError, ValidationError

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


class TestSetCurrentMissionEndpoint:
    @pytest.mark.asyncio
    async def test_set_returns_200(self, app):
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user.email = "a@b.com"
        mock_user.display_name = "Test"
        mock_user.system_role = "user"
        mock_user.is_active = True
        mock_user.is_service_account = False
        mock_user.last_login_at = None
        mock_user.current_mission_id = "mission-1"
        mock_user.current_mission = MagicMock()
        mock_user.current_mission.name = "Alpha"
        mock_user.created_at = "2026-01-01T00:00:00"
        mock_user.updated_at = "2026-01-01T00:00:00"

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()

        with patch(
            "modules.backend.services.user.UserService",
        ) as MockService:
            instance = MockService.return_value
            instance.set_current_mission = AsyncMock(return_value=mock_user)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.put(
                    "/auth/me/current-mission",
                    json={"mission_id": "mission-1"},
                )

        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
