"""Plan 88 (88.0.2, 88.2.2): config snapshots and config_hash."""

import dataclasses
import subprocess
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from temporalio.converter import DataConverter

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.temporal import config_snapshots
from modules.backend.temporal.config_snapshots import (
    build_run_config_snapshot,
    build_tick_config_snapshot,
    config_hash,
    policy_snapshot,
)
from modules.backend.temporal.mission_run_models import RunConfigSnapshot


@dataclass(frozen=True)
class _Snapshot:
    config_hash: str
    orphan_grace_seconds: int


def test_policy_snapshot_maps_every_field() -> None:
    schema = get_app_config().temporal.reconciler.activity
    snap = policy_snapshot(schema)
    assert snap.start_to_close_seconds == schema.start_to_close_seconds
    assert snap.heartbeat_timeout_seconds == schema.heartbeat_timeout_seconds
    assert snap.retry.initial_interval_seconds == schema.retry.initial_interval_seconds
    assert snap.retry.backoff_coefficient == schema.retry.backoff_coefficient
    assert snap.retry.maximum_interval_seconds == schema.retry.maximum_interval_seconds
    assert snap.retry.maximum_attempts == schema.retry.maximum_attempts


def test_config_hash_ignores_own_field() -> None:
    a = _Snapshot(config_hash="", orphan_grace_seconds=600)
    b = dataclasses.replace(a, config_hash="something-else")
    assert config_hash(a) == config_hash(b)


def test_config_hash_changes_with_field() -> None:
    a = _Snapshot(config_hash="", orphan_grace_seconds=600)
    b = dataclasses.replace(a, orphan_grace_seconds=900)
    assert config_hash(a) != config_hash(b)


def test_build_run_config_snapshot_hash_matches() -> None:
    snap = build_run_config_snapshot()
    assert snap.config_hash == config_hash(snap)


def test_build_tick_config_snapshot_hash_matches() -> None:
    snap = build_tick_config_snapshot()
    assert snap.config_hash == config_hash(snap)


def test_run_snapshot_hash_stable() -> None:
    assert build_run_config_snapshot().config_hash == build_run_config_snapshot().config_hash


def test_run_snapshot_hash_changes_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    real = get_app_config()
    temporal = real.temporal.model_copy(deep=True)
    temporal.mission_run.activities.execute_task.start_to_close_seconds += 60
    before = build_run_config_snapshot()
    monkeypatch.setattr(
        config_snapshots,
        "get_app_config",
        lambda: SimpleNamespace(temporal=temporal, gate=real.gate, failures=real.failures),
    )
    after = build_run_config_snapshot()
    assert (
        after.execute_task.start_to_close_seconds == before.execute_task.start_to_close_seconds + 60
    )
    assert after.config_hash != before.config_hash


def test_run_snapshot_carries_duration_and_heartbeat() -> None:
    snap = build_run_config_snapshot()
    assert snap.max_run_duration_seconds == 43200
    assert snap.task_heartbeat_interval_seconds == 20
    assert snap.max_failure_digests == 10


async def test_snapshot_round_trips_temporal_converter() -> None:
    snap = build_run_config_snapshot()
    converter = DataConverter.default
    payloads = await converter.encode([snap])
    decoded = await converter.decode(payloads, [RunConfigSnapshot])
    assert decoded == [snap]


def test_single_snapshot_builder() -> None:
    root = find_project_root()
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--include=*.py",
            r"def build_.*config_snapshot\|def policy_snapshot\|def snapshot_from_schema",
            "modules/backend",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    files = {line.split(":", 1)[0] for line in result.stdout.splitlines()}
    assert files == {"modules/backend/temporal/config_snapshots.py"}
