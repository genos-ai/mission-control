"""Plan 88 Phase 0 (88.0.2): config snapshots and config_hash."""

import dataclasses
from dataclasses import dataclass

from modules.backend.core.config import get_app_config
from modules.backend.temporal.config_snapshots import (
    build_run_config_snapshot,
    build_tick_config_snapshot,
    config_hash,
    policy_snapshot,
)


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
