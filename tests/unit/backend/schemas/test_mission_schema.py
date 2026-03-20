"""Tests for Mission schemas."""

import pytest
from pydantic import ValidationError

from modules.backend.schemas.mission import (
    MissionCreate,
    MissionResponse,
    MissionUpdate,
)


class TestMissionCreate:
    def test_valid_minimal(self):
        schema = MissionCreate(
            name="my-mission",
            description="A test mission",
            owner_id="user:test",
        )
        assert schema.name == "my-mission"
        assert schema.default_roster == "default"

    def test_valid_full(self):
        schema = MissionCreate(
            name="full-mission",
            description="Full mission",
            owner_id="user:test",
            team_id="team-alpha",
            default_roster="research",
            budget_ceiling_usd=50.0,
            repo_url="https://github.com/test/repo",
            repo_root="/home/test/repo",
        )
        assert schema.budget_ceiling_usd == 50.0

    def test_invalid_name_uppercase(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="MyMission",
                description="Bad name",
                owner_id="user:test",
            )

    def test_invalid_name_starts_with_number(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="1mission",
                description="Bad name",
                owner_id="user:test",
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="",
                description="No name",
                owner_id="user:test",
            )

    def test_budget_must_be_positive(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="cheap-mission",
                description="Negative budget",
                owner_id="user:test",
                budget_ceiling_usd=0.0,
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(
                name="strict-mission",
                description="No extras",
                owner_id="user:test",
                unknown_field="bad",
            )


class TestMissionUpdate:
    def test_all_none(self):
        schema = MissionUpdate()
        assert schema.description is None
        assert schema.status is None

    def test_valid_status(self):
        schema = MissionUpdate(status="paused")
        assert schema.status == "paused"

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            MissionUpdate(status="deleted")


class TestMissionResponse:
    def test_from_dict(self):
        resp = MissionResponse(
            id="abc-123",
            name="resp-mission",
            description="Response test",
            status="active",
            owner_id="user:test",
            team_id=None,
            default_roster="default",
            budget_ceiling_usd=None,
            repo_url=None,
            repo_root=None,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        assert resp.id == "abc-123"
        assert resp.name == "resp-mission"
