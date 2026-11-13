"""Tests for Mission schemas."""

import pytest
from pydantic import ValidationError

from modules.backend.models.mission import MissionPauseReason
from modules.backend.schemas.mission import (
    MissionCreate,
    MissionResponse,
    MissionUpdate,
)
from tests.conftest import TEST_USER_ID


class TestMissionCreate:
    def test_valid_minimal(self):
        schema = MissionCreate(
            name="my-mission",
            description="A test mission",
            owner_id=TEST_USER_ID,
            gate_mode="manual",
        )
        assert schema.name == "my-mission"
        assert schema.default_roster == "default"

    def test_valid_full(self):
        schema = MissionCreate(
            name="full-mission",
            description="Full mission",
            owner_id=TEST_USER_ID,
            gate_mode="manual",
            team_id="team-alpha",
            default_roster="research",
            budget_per_run_usd=5.0,
            budget_per_month_usd=50.0,
            budget_lifetime_usd=500.0,
            repo_url="https://github.com/test/repo",
            repo_root="/home/test/repo",
        )
        assert (
            schema.budget_per_run_usd,
            schema.budget_per_month_usd,
            schema.budget_lifetime_usd,
        ) == (5.0, 50.0, 500.0)

    def test_invalid_name_uppercase(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="MyMission",
                description="Bad name",
                owner_id=TEST_USER_ID,
                gate_mode="manual",
            )

    def test_invalid_name_starts_with_number(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="1mission",
                description="Bad name",
                owner_id=TEST_USER_ID,
                gate_mode="manual",
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="",
                description="No name",
                owner_id=TEST_USER_ID,
                gate_mode="manual",
            )

    def test_budget_must_be_positive(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="cheap-mission",
                description="Negative budget",
                owner_id=TEST_USER_ID,
                gate_mode="manual",
                budget_per_run_usd=0.0,
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="strict-mission",
                description="No extras",
                owner_id=TEST_USER_ID,
                gate_mode="manual",
                unknown_field="bad",
            )


class TestMissionUpdate:
    def test_all_none(self):
        schema = MissionUpdate()
        assert schema.description is None

    def test_mission_update_rejects_status(self):
        """Status changes only through the lifecycle endpoints (88.4.2)."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            MissionUpdate(status="paused")


class TestMissionResponse:
    def test_from_dict(self):
        resp = MissionResponse(
            id="abc-123",
            name="resp-mission",
            description="Response test",
            brief=None,
            status="active",
            tier="user",
            owner_id=TEST_USER_ID,
            team_id=None,
            default_roster="default",
            repo_url=None,
            repo_root=None,
            execution_environment=None,
            paused_reason=None,
            paused_at=None,
            spent_usd=0.0,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        assert resp.id == "abc-123"
        assert resp.name == "resp-mission"

    def test_paused_reason_serialised_as_lowercase_value(self):
        resp = MissionResponse(
            id="abc-123",
            name="resp-mission",
            description="Response test",
            brief=None,
            status="paused",
            tier="user",
            owner_id=TEST_USER_ID,
            team_id=None,
            default_roster="default",
            repo_url=None,
            repo_root=None,
            execution_environment=None,
            paused_reason=MissionPauseReason.BUDGET_MONTHLY_CAP,
            paused_at="2025-01-01T00:00:00Z",
            spent_usd=0.0,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        assert resp.model_dump(mode="json")["paused_reason"] == "budget_monthly_cap"
