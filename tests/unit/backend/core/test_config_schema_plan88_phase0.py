"""Plan 88 Phase 0 (88.0.2): temporal mission_run, reconciler and system_schedules schemas."""

import pytest
from pydantic import ValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import MissionRunSchema, TemporalSchema


def _temporal_data() -> dict:
    return get_app_config().temporal.model_dump()


def _mission_run_data() -> dict:
    return get_app_config().temporal.mission_run.model_dump()


def test_repo_temporal_yaml_validates() -> None:
    temporal = get_app_config().temporal
    assert temporal.reconciler.orphan_grace_seconds == 600
    assert temporal.system_schedules["reconciler"].cron == "*/5 * * * *"


def test_heartbeat_validator_rejects_interval_over_half_timeout() -> None:
    data = _mission_run_data()
    data["task_heartbeat_interval_seconds"] = 31
    data["activities"]["execute_task"]["heartbeat_timeout_seconds"] = 60
    with pytest.raises(ValidationError, match="at most half"):
        MissionRunSchema(**data)


def test_heartbeat_validator_rejects_null_execute_task_heartbeat() -> None:
    data = _mission_run_data()
    data["activities"]["execute_task"]["heartbeat_timeout_seconds"] = None
    with pytest.raises(ValidationError, match="heartbeat_timeout_seconds is required"):
        MissionRunSchema(**data)


def test_system_schedules_rejects_unknown_key() -> None:
    data = _temporal_data()
    data["system_schedules"]["nightly_surprise"] = {"cron": "0 1 * * *"}
    with pytest.raises(ValidationError, match="must match the registry exactly"):
        TemporalSchema(**data)


def test_system_schedules_requires_reconciler() -> None:
    data = _temporal_data()
    data["system_schedules"] = {"retention": {"cron": "30 2 * * *"}}
    with pytest.raises(ValidationError, match=r"missing \[.*'reconciler'"):
        TemporalSchema(**data)


def test_mission_run_schema_has_no_defaults() -> None:
    for name, field in MissionRunSchema.model_fields.items():
        assert field.is_required() is True, name
