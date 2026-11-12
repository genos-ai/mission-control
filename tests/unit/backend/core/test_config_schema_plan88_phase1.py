"""Plan 88 Phase 1 (88.1.1): recurrence config and deleted unread keys."""

import pytest
from pydantic import ValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import TemporalSchema
from modules.backend.core.config_schema_missions import RecurrenceSchema


def _recurrence_data() -> dict:
    return {
        "enabled": True,
        "default_catch_up_window_seconds": 21600,
        "max_catch_up_window_seconds": 604800,
        "min_interval_seconds": 300,
        "max_schedules_per_mission": 5,
        "objective_template_max_chars": 4000,
    }


def test_recurrence_requires_every_field() -> None:
    data = _recurrence_data()
    del data["min_interval_seconds"]
    with pytest.raises(ValidationError):
        RecurrenceSchema(**data)

    data = _recurrence_data()
    del data["enabled"]
    with pytest.raises(ValidationError):
        RecurrenceSchema(**data)


def test_recurrence_default_window_le_max() -> None:
    data = _recurrence_data()
    data["default_catch_up_window_seconds"] = 700000
    data["max_catch_up_window_seconds"] = 604800
    with pytest.raises(ValidationError, match="must not exceed"):
        RecurrenceSchema(**data)


def test_deleted_temporal_keys_rejected() -> None:
    data = get_app_config().temporal.model_dump()
    data["activity_retry_max_attempts"] = 3
    with pytest.raises(ValidationError):
        TemporalSchema(**data)


def test_repo_yaml_loads() -> None:
    assert get_app_config().missions.recurrence.default_catch_up_window_seconds == 21600


def test_cli_yaml_loads() -> None:
    assert get_app_config().cli.mc.runs_list_limit == 20
