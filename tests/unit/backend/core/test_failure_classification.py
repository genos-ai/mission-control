"""Deterministic failure classifier (Plan 88, 88.2.3b; contracts 3.8.3 and 3.8.4).

Frame-path rules are exercised with real tracebacks: small modules are
written under a temporary ``modules/`` directory, which the classifier
under test treats as the platform modules directory.
"""

import asyncio
import importlib.util
import json
import os
import textwrap
import uuid
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from sqlalchemy.exc import OperationalError

from modules.backend.core.config import find_project_root
from modules.backend.core.config_schema import FailuresSchema
from modules.backend.core.exceptions import (
    BudgetExceededError,
    ContractViolationError,
    DatabaseError,
    ExecutionEnvironmentError,
    ExternalServiceError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientProviderError,
)
from modules.backend.core.failure_classification import (
    AGENT_TOOL_DIRS,
    FailureClassifier,
    WorkflowStepFailedError,
    get_failure_classifier,
)
from modules.backend.schemas.execution_outcome import (
    FailedCheck,
    Tier2Outcome,
    VerificationOutcome,
)
from modules.backend.schemas.task_failure import FailureClass, FailureOrigin


def _config(
    *,
    unknown_retryable: bool = True,
    max_message_chars: int = 2000,
    max_summary_chars: int = 300,
    max_traceback_frames: int = 8,
) -> FailuresSchema:
    return FailuresSchema(
        evidence={
            "max_message_chars": max_message_chars,
            "max_summary_chars": max_summary_chars,
            "max_traceback_frames": max_traceback_frames,
        },
        supervisor={"max_failure_digests": 10},
        unknown_retryable=unknown_retryable,
    )


@pytest.fixture
def platform(tmp_path: Path) -> Path:
    """A temporary platform modules directory."""
    root = tmp_path / "platform" / "modules"
    root.mkdir(parents=True)
    return root


def _classifier(platform_dir: Path, **kwargs) -> FailureClassifier:
    return FailureClassifier(_config(**kwargs), platform_dir)


def _load(base: Path, rel: str, source: str):
    """Write ``source`` to ``base/rel`` and import it as a fresh module."""
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))
    spec = importlib.util.spec_from_file_location(f"_fc_{uuid.uuid4().hex}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _caught(fn, *args) -> BaseException:
    try:
        fn(*args)
    except BaseException as exc:  # noqa: BLE001 - the test inspects whatever was raised
        return exc
    raise AssertionError("expected an exception")


def _raised(exc: BaseException) -> BaseException:
    """Raise ``exc`` from this test module, so it carries a non-platform traceback."""

    def _raise():
        raise exc

    return _caught(_raise)


# =============================================================================
# Provider and contract
# =============================================================================


def test_quota_is_provider_not_retryable(platform):
    failure = _classifier(platform).from_exception(_raised(QuotaExhaustedError("quota gone")))
    assert failure.origin is FailureOrigin.PROVIDER
    assert failure.failure_class is FailureClass.QUOTA_EXHAUSTED
    assert failure.retryable is False


def test_rate_limited_is_transient_retryable(platform):
    failure = _classifier(platform).from_exception(_raised(RateLimitedError("slow down")))
    assert failure.origin is FailureOrigin.PROVIDER
    assert failure.failure_class is FailureClass.TRANSIENT_PROVIDER
    assert failure.retryable is True


def test_raw_sdk_rate_limit_is_transient_provider(platform):
    raw = ModelHTTPError(status_code=429, model_name="m", body="slow down")
    failure = _classifier(platform).from_exception(_raised(raw))
    assert failure.origin is FailureOrigin.PROVIDER
    assert failure.failure_class is FailureClass.TRANSIENT_PROVIDER
    assert failure.retryable is True
    assert failure.evidence.exception_type == "ModelHTTPError"


class _NoRetryTransient(TransientProviderError):
    retry_policy = "none"


@pytest.mark.parametrize(
    "exc_type", [QuotaExhaustedError, RateLimitedError, TransientProviderError, _NoRetryTransient]
)
def test_provider_retryable_follows_retry_policy(platform, exc_type):
    failure = _classifier(platform).from_exception(_raised(exc_type("provider said no")))
    assert failure.origin is FailureOrigin.PROVIDER
    assert failure.retryable is (exc_type.retry_policy != "none")


def test_contract_violation_is_agent_contract(platform):
    failure = _classifier(platform).from_exception(_raised(ContractViolationError("bad shape")))
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.AGENT,
        FailureClass.AGENT_CONTRACT,
    )
    assert failure.retryable is False


class _Shape(BaseModel):
    count: int


def test_pydantic_validation_error_is_agent_contract(platform):
    exc = _caught(_Shape.model_validate, {"count": "not-a-number"})
    assert isinstance(exc, PydanticValidationError)
    failure = _classifier(platform).from_exception(exc)
    assert failure.failure_class is FailureClass.AGENT_CONTRACT
    assert failure.retryable is False


def test_unexpected_model_behavior_is_agent_contract(platform):
    failure = _classifier(platform).from_exception(_raised(UnexpectedModelBehavior("no tool")))
    assert failure.failure_class is FailureClass.AGENT_CONTRACT


def test_usage_limit_exceeded_is_agent_contract(platform):
    failure = _classifier(platform).from_exception(_raised(UsageLimitExceeded("tokens")))
    assert failure.failure_class is FailureClass.AGENT_CONTRACT
    assert failure.retryable is False


# =============================================================================
# Control, environment and platform infrastructure
# =============================================================================


def test_budget_exceeded_is_control(platform):
    failure = _classifier(platform).from_exception(_raised(BudgetExceededError()))
    assert failure.origin is FailureOrigin.CONTROL
    assert failure.failure_class is FailureClass.BUDGET_EXCEEDED
    assert failure.summary == "budget_exceeded"
    assert failure.retryable is False


def test_env_error_is_environment(platform):
    failure = _classifier(platform).from_exception(
        _raised(ExecutionEnvironmentError("no workspace"))
    )
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.ENVIRONMENT,
        FailureClass.ENV_UNAVAILABLE,
    )
    assert failure.retryable is False


@pytest.mark.parametrize("exc", [TimeoutError(), asyncio.TimeoutError()])
def test_timeout_is_agent_timeout(platform, exc):
    failure = _classifier(platform).from_exception(_raised(exc))
    assert (failure.origin, failure.failure_class) == (FailureOrigin.AGENT, FailureClass.TIMEOUT)
    assert failure.retryable is True


def test_db_connection_error_is_platform_transient(platform):
    def _fail():
        try:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        except OperationalError:
            raise DatabaseError("Database operation failed") from None

    failure = _classifier(platform).from_exception(_caught(_fail))
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.PLATFORM,
        FailureClass.PLATFORM_TRANSIENT,
    )
    assert failure.retryable is True


def test_db_constraint_violation_is_platform_defect(platform):
    module = _load(
        platform,
        "backend/services/thing.py",
        """
        from sqlalchemy.exc import IntegrityError
        from modules.backend.core.exceptions import DatabaseError

        def save():
            try:
                raise IntegrityError("INSERT", {}, Exception("duplicate key"))
            except IntegrityError:
                raise DatabaseError("Database constraint violation: save")
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.save))
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.PLATFORM,
        FailureClass.PLATFORM_DEFECT,
    )
    assert failure.retryable is False


def test_external_service_error_is_platform_transient(platform):
    failure = _classifier(platform).from_exception(_raised(ExternalServiceError("503")))
    assert failure.failure_class is FailureClass.PLATFORM_TRANSIENT
    assert failure.retryable is True


# =============================================================================
# Agent tool errors
# =============================================================================


def test_scope_violation_is_agent_tool_error(platform):
    tool = _load(
        platform,
        "backend/tools/read_file.py",
        """
        def read(path):
            raise PermissionError(f"path outside scope: {path}")
        """,
    )
    service = _load(
        platform,
        "backend/services/other.py",
        """
        def check(value):
            raise PermissionError(f"not allowed: {value}")
        """,
    )
    classifier = _classifier(platform)

    tool_failure = classifier.from_exception(_caught(tool.read, "/etc/passwd"))
    assert (tool_failure.origin, tool_failure.failure_class) == (
        FailureOrigin.AGENT,
        FailureClass.AGENT_TOOL_ERROR,
    )
    assert tool_failure.retryable is True

    service_failure = classifier.from_exception(_caught(service.check, "x"))
    assert service_failure.failure_class is FailureClass.PLATFORM_DEFECT


def test_agent_tool_dirs_exist():
    classifier = get_failure_classifier()
    assert len(classifier.tool_dirs) == len(AGENT_TOOL_DIRS)
    for directory in classifier.tool_dirs:
        assert os.path.isdir(directory)
        assert os.path.isfile(os.path.join(directory, "__init__.py"))


# =============================================================================
# Frame-path test
# =============================================================================


def test_platform_frame_is_platform_defect(platform):
    module = _load(
        platform,
        "backend/services/broken.py",
        """
        def lookup(data):
            return data["missing"]
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.lookup, {}))
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.PLATFORM,
        FailureClass.PLATFORM_DEFECT,
    )
    assert failure.retryable is False
    assert failure.evidence.traceback_tail[-1] == "backend/services/broken.py:lookup"


def test_missing_third_party_import_is_dependency_missing(platform):
    module = _load(
        platform,
        "backend/services/needs_pkg.py",
        """
        def use():
            import definitely_not_installed_pkg_88  # noqa: F401
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.use))
    assert (failure.origin, failure.failure_class) == (
        FailureOrigin.PLATFORM,
        FailureClass.PLATFORM_DEPENDENCY_MISSING,
    )
    assert failure.evidence.module_name == "definitely_not_installed_pkg_88"


def test_missing_internal_module_is_platform_defect(platform):
    module = _load(
        platform,
        "backend/services/needs_internal.py",
        """
        def use():
            import modules.backend.definitely_missing_88  # noqa: F401
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.use))
    assert failure.origin is FailureOrigin.PLATFORM
    assert failure.failure_class is FailureClass.PLATFORM_DEFECT


def test_import_module_failure_is_platform(platform):
    module = _load(
        platform,
        "backend/services/dynamic.py",
        """
        import importlib

        def load():
            return importlib.import_module("definitely_not_installed_pkg_88")
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.load))
    assert failure.origin is FailureOrigin.PLATFORM
    assert failure.failure_class is FailureClass.PLATFORM_DEPENDENCY_MISSING


def test_json_error_from_platform_caller_is_platform(platform):
    module = _load(
        platform,
        "backend/services/parse.py",
        """
        import json

        def parse(text):
            return json.loads(text)
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.parse, "{"))
    assert failure.origin is FailureOrigin.PLATFORM
    assert failure.failure_class is FailureClass.PLATFORM_DEFECT


def test_site_packages_error_not_platform(platform):
    module = _load(
        platform,
        "backend/services/load_yaml.py",
        """
        import yaml

        def parse(text):
            return yaml.safe_load(text)
        """,
    )
    failure = _classifier(platform).from_exception(_caught(module.parse, "a: [unclosed"))
    assert failure.origin is FailureOrigin.UNKNOWN
    assert failure.failure_class is FailureClass.UNKNOWN


def test_site_packages_nested_in_stdlib_not_skipped(platform):
    classifier = _classifier(platform)
    assert classifier.is_skipped_frame(yaml.__file__) is False
    assert classifier.is_skipped_frame(json.__file__) is True
    assert classifier.is_skipped_frame("<frozen importlib._bootstrap>") is True


def test_target_package_named_modules_not_platform(tmp_path, platform):
    target = _load(
        tmp_path / "target" / "modules",
        "backend/services/app.py",
        """
        def run():
            raise KeyError("target bug")
        """,
    )
    failure = _classifier(platform).from_exception(_caught(target.run))
    assert failure.origin is FailureOrigin.UNKNOWN
    assert failure.failure_class is FailureClass.UNKNOWN


# =============================================================================
# Workflow pass-through and explicit constructors
# =============================================================================


def test_workflow_step_failure_passes_through(platform):
    classifier = _classifier(platform)
    carried = classifier.agent_outcome("workflow:scan", "workflow halted: no deliverable")
    failure = classifier.from_exception(_raised(WorkflowStepFailedError(carried, "step failed")))
    assert failure == carried


def _verification() -> VerificationOutcome:
    return VerificationOutcome(
        tier_2=Tier2Outcome(
            status="fail", failed_checks=[FailedCheck(check="has_citations", reason="none")]
        )
    )


@pytest.mark.parametrize(
    ("build", "origin", "failure_class", "summary"),
    [
        (
            lambda c: c.control(FailureClass.CANCELLED, "cancelled"),
            FailureOrigin.CONTROL,
            FailureClass.CANCELLED,
            "cancelled",
        ),
        (
            lambda c: c.control(FailureClass.RUN_ABORTED, "aborted at post_task gate"),
            FailureOrigin.CONTROL,
            FailureClass.RUN_ABORTED,
            "aborted at post_task gate",
        ),
        (
            lambda c: c.upstream_blocked("v1-task-001.result", "v1-task-001"),
            FailureOrigin.UPSTREAM,
            FailureClass.UPSTREAM_BLOCKED,
            "upstream_blocked: v1-task-001.result",
        ),
        (
            lambda c: c.roster_miss("ghost.agent"),
            FailureOrigin.PLATFORM,
            FailureClass.PLATFORM_DEFECT,
            "platform_defect: ghost.agent",
        ),
        (
            lambda c: c.plan_invalid("research", "missing loop_config"),
            FailureOrigin.AGENT,
            FailureClass.AGENT_CONTRACT,
            "missing loop_config",
        ),
        (
            lambda c: c.agent_outcome("qa.agent", "success: False"),
            FailureOrigin.AGENT,
            FailureClass.AGENT_REPORTED_FAILURE,
            "success: False",
        ),
        (
            lambda c: c.verification_failed("qa.agent", _verification()),
            FailureOrigin.AGENT,
            FailureClass.VERIFICATION_FAILED,
            "verification_failed: qa.agent",
        ),
        (
            lambda c: c.orphaned("workflow closed"),
            FailureOrigin.PLATFORM,
            FailureClass.ORPHANED,
            "workflow closed",
        ),
    ],
)
def test_explicit_constructors(platform, build, origin, failure_class, summary):
    failure = build(_classifier(platform))
    assert failure.origin is origin
    assert failure.failure_class is failure_class
    assert failure.summary == summary
    assert failure.retryable is False
    assert len(failure.fingerprint) == 64


def test_control_rejects_non_control_class(platform):
    with pytest.raises(ValueError, match="does not take"):
        _classifier(platform).control(FailureClass.TIMEOUT, "x")


# =============================================================================
# Fingerprint
# =============================================================================


def test_upstream_cascade_one_fingerprint(platform):
    classifier = _classifier(platform)
    first = classifier.upstream_blocked("v1-task-001.result", "v1-task-001")
    second = classifier.upstream_blocked("v1-task-001.summary", "v1-task-001")
    assert first.fingerprint == second.fingerprint


def test_distinct_upstream_ids_distinct_fingerprints(platform):
    classifier = _classifier(platform)
    first = classifier.upstream_blocked("v1-task-001.result", "v1-task-001")
    second = classifier.upstream_blocked("v1-task-002.result", "v1-task-002")
    assert first.fingerprint != second.fingerprint


def test_distinct_platform_sites_have_distinct_fingerprints(platform):
    module = _load(
        platform,
        "backend/services/sites.py",
        """
        def first(data):
            return data["a"]

        def second(data):
            return data["b"]
        """,
    )
    classifier = _classifier(platform)
    a = classifier.from_exception(_caught(module.first, {}))
    b = classifier.from_exception(_caught(module.second, {}))
    again = classifier.from_exception(_caught(module.first, {}))
    assert a.fingerprint != b.fingerprint
    assert a.fingerprint == again.fingerprint


def test_fingerprint_has_no_line_numbers(platform):
    source = """
        def boom(data):
            return data["x"]
        """
    classifier = _classifier(platform)
    before = classifier.from_exception(
        _caught(_load(platform, "backend/services/shift.py", source).boom, {})
    )
    shifted = classifier.from_exception(
        _caught(_load(platform, "backend/services/shift.py", "\n\n\n\n" + source).boom, {})
    )
    assert before.fingerprint == shifted.fingerprint
    assert all(frame.count(":") == 1 for frame in before.evidence.traceback_tail)


# =============================================================================
# Policy and bounds
# =============================================================================


@pytest.mark.parametrize("unknown_retryable", [True, False])
def test_unknown_uses_config_retryable(platform, unknown_retryable):
    classifier = _classifier(platform, unknown_retryable=unknown_retryable)
    failure = classifier.from_exception(_raised(RuntimeError("odd")))
    assert failure.failure_class is FailureClass.UNKNOWN
    assert failure.retryable is unknown_retryable


def test_summary_format_and_bound(platform):
    classifier = _classifier(platform, max_summary_chars=40)
    failure = classifier.from_exception(_raised(RuntimeError("first line\nsecond line")))
    assert failure.summary == "unknown: first line"

    long = classifier.from_exception(_raised(RuntimeError("x" * 500)))
    assert long.summary.startswith("unknown: xxx")
    assert len(long.summary) == 40


def test_evidence_redacted_and_bounded(platform):
    module = _load(
        platform,
        "backend/services/deep.py",
        """
        def recurse(n, secret):
            if n == 0:
                raise RuntimeError(f"token={secret} " + "y" * 500)
            return recurse(n - 1, secret)
        """,
    )
    classifier = _classifier(platform, max_message_chars=60, max_traceback_frames=3)
    failure = classifier.from_exception(_caught(module.recurse, 6, "sk-abcdefghijklmnopqrstuvwxyz"))
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in failure.evidence.message
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in failure.summary
    assert len(failure.evidence.message) == 60
    assert len(failure.evidence.traceback_tail) == 3


def test_singleton_uses_project_modules_dir():
    classifier = get_failure_classifier()
    assert classifier is get_failure_classifier()
    expected = os.path.realpath(find_project_root() / "modules")
    assert all(d.startswith(expected + os.sep) for d in classifier.tool_dirs)
