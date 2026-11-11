"""digest_failures, the only grouping rule for failure digests (Plan 88 step 88.2.6)."""

from modules.backend.temporal.mission_run_models import ExecuteTaskResult, digest_failures


def _failed(task_id: str, fingerprint: str | None, reason: str = "boom") -> ExecuteTaskResult:
    return ExecuteTaskResult(
        task_id=task_id,
        status="failed",
        verification_failed=False,
        cost_usd=0.0,
        idempotent_replay=False,
        failure_reason=reason,
        failure_origin="agent" if fingerprint else None,
        failure_class="agent_reported_failure" if fingerprint else None,
        failure_fingerprint=fingerprint,
    )


def test_failures_deduped_by_fingerprint():
    digests, truncated = digest_failures(
        [_failed("a", "f1", "first"), _failed("b", "f2"), _failed("c", "f1", "third")], 10
    )

    assert truncated == 0
    assert [(d.task_id, d.fingerprint, d.occurrences) for d in digests] == [
        ("a", "f1", 2),
        ("b", "f2", 1),
    ]
    assert digests[0].summary == "first"
    assert (digests[0].origin, digests[0].failure_class) == ("agent", "agent_reported_failure")


def test_failures_cap_counts_truncated():
    digests, truncated = digest_failures([_failed("a", "f1"), _failed("b", "f2")], 1)

    assert [d.fingerprint for d in digests] == ["f1"]
    assert truncated == 1


def test_unclassified_failures_group_as_unknown():
    digests, truncated = digest_failures([_failed("a", None), _failed("b", None)], 10)

    assert truncated == 0
    assert [(d.origin, d.failure_class, d.fingerprint, d.occurrences) for d in digests] == [
        ("unknown", "unknown", "", 2)
    ]


def test_no_failures_no_digests():
    assert digest_failures([], 10) == ([], 0)
