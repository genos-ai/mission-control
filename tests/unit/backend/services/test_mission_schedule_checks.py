"""build_tick_schedule (Plan 88 contract 3.3.2): the tick action's execution timeout."""

from datetime import timedelta

import pytest

from modules.backend.core.config import get_app_config
from modules.backend.services.mission_schedule_checks import build_spec, build_tick_schedule
from modules.backend.temporal.config_snapshots import build_tick_config_snapshot


@pytest.mark.parametrize("catch_up_window_seconds", [600, 21600])
def test_tick_execution_timeout_covers_catch_up_window(catch_up_window_seconds: int) -> None:
    """A tick started during a worker outage must outlive the catch-up window."""
    run_timeout = get_app_config().temporal.mission_run.tick_execution_timeout_seconds
    schedule = build_tick_schedule(
        "schedule-1",
        build_tick_config_snapshot(),
        build_spec("*/5 * * * *", "UTC", None, None),
        catch_up_window_seconds,
        False,
        "active",
    )

    assert schedule.action.execution_timeout == timedelta(
        seconds=catch_up_window_seconds + run_timeout
    )
    assert schedule.policy.catchup_window == timedelta(seconds=catch_up_window_seconds)
