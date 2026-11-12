"""Tests for the pure MCD pruning helpers (Plan 88, 88.3.2 and 88.3.3)."""

from modules.backend.services.mcd_pruning import (
    mcd_size_bytes,
    split_decisions_by_age,
    split_milestones,
)


def test_split_decisions_by_age_pure():
    decisions = [
        {"id": "old", "date": "2020-01-01"},
        {"id": "edge", "date": "2026-01-01"},
        {"id": "new", "date": "2026-06-01"},
        {"id": "undated"},
    ]
    snapshot = [dict(d) for d in decisions]

    keep, archive = split_decisions_by_age(decisions, "2026-01-01")

    assert [d["id"] for d in keep] == ["edge", "new"]
    assert [d["id"] for d in archive] == ["old", "undated"]
    assert decisions == snapshot


def test_split_milestones_pure():
    milestones = [f"m{i}" for i in range(7)]

    keep, archive = split_milestones(milestones, 5)

    assert keep == ["m0", "m1", "m2", "m3", "m4"]
    assert archive == ["m5", "m6"]
    assert milestones == [f"m{i}" for i in range(7)]
    assert split_milestones(["a"], 5) == (["a"], [])


def test_mcd_size_bytes_counts_utf8():
    assert mcd_size_bytes("€") == mcd_size_bytes("") + 3
    assert mcd_size_bytes({"a": "b"}) == len('{"a": "b"}')
