"""Plan 88 steps 88.0.10 and 88.1.10: system schedule registration (fake gateway)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from temporalio.client import Schedule, ScheduleOverlapPolicy

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import TemporalSchema
from modules.backend.temporal.config_snapshots import config_hash
from modules.backend.temporal.mission_run_models import ReconcilerInput
from modules.backend.temporal.system_schedules import register_system_schedules

_KEYS = (
    "reconciler",
    "retention",
    "hourly_health_check",
    "weekly_report",
    "metrics_aggregation",
    "cleanup_environments",
    "knowledge_extraction",
    "knowledge_officer",
    "embedding_backfill",
)


class FakeGateway:
    """Records upserts and deletes; list_ids returns the seeded ids."""

    def __init__(self, existing: list[str] | None = None) -> None:
        self.existing = list(existing or [])
        self.upserts: dict[str, Schedule] = {}
        self.deleted: list[str] = []

    async def upsert(self, schedule_id: str, schedule: Schedule) -> None:
        self.upserts[schedule_id] = schedule

    async def list_ids(self, prefix: str | None) -> list[str]:
        ids = self.existing + list(self.upserts)
        return [i for i in ids if prefix is None or i.startswith(prefix)]

    async def delete(self, schedule_id: str) -> None:
        self.deleted.append(schedule_id)


@pytest.mark.asyncio
async def test_upserts_all_nine():
    gateway = FakeGateway()

    await register_system_schedules(gateway)

    assert set(gateway.upserts) == {f"system-{k}" for k in _KEYS}
    cfg = get_app_config().temporal
    for key in _KEYS:
        schedule = gateway.upserts[f"system-{key}"]
        assert schedule.spec.cron_expressions == [cfg.system_schedules[key].cron]
        assert schedule.spec.time_zone_name == "UTC"
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.action.id == f"system-{key}"
        assert schedule.action.task_queue == cfg.task_queue
        if key == "reconciler":
            (arg,) = schedule.action.args
            assert isinstance(arg, ReconcilerInput)
            assert arg.orphan_grace_seconds == 600
            assert arg.config_hash == config_hash(arg)
        else:
            assert schedule.action.args == []
    assert gateway.upserts["system-retention"].action.workflow == "DailyCleanupWorkflow"
    assert gateway.deleted == []


@pytest.mark.asyncio
async def test_deletes_only_legacy_ids():
    gateway = FakeGateway(
        [
            "mission-plan-dispatch-schedule",
            "maintenance-workflow-schedules",
            "mission-schedule-x",
            "third-party-schedule",
        ]
    )

    await register_system_schedules(gateway)

    assert gateway.deleted == ["mission-plan-dispatch-schedule", "maintenance-workflow-schedules"]


@pytest.mark.asyncio
async def test_registry_mismatch_raises():
    temporal = get_app_config().temporal
    schedules = {k: v for k, v in temporal.system_schedules.items() if k != "weekly_report"}
    fake = SimpleNamespace(temporal=temporal.model_copy(update={"system_schedules": schedules}))
    gateway = FakeGateway()

    with (
        patch("modules.backend.temporal.system_schedules.get_app_config", return_value=fake),
        pytest.raises(RuntimeError, match="system schedule registry mismatch"),
    ):
        await register_system_schedules(gateway)
    assert gateway.upserts == {}


def test_system_schedules_keys_must_match():
    data = get_app_config().temporal.model_dump()

    missing = {**data, "system_schedules": dict(data["system_schedules"])}
    del missing["system_schedules"]["knowledge_officer"]
    with pytest.raises(ValidationError, match=r"missing \['knowledge_officer'\]"):
        TemporalSchema(**missing)

    extra = {**data, "system_schedules": dict(data["system_schedules"])}
    extra["system_schedules"]["nightly_surprise"] = {"cron": "0 1 * * *"}
    with pytest.raises(ValidationError, match=r"unknown \['nightly_surprise'\]"):
        TemporalSchema(**extra)
