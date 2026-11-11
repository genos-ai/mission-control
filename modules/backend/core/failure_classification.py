"""Deterministic task failure classifier (Plan 88, contracts 3.8.3 and 3.8.4).

Every failed task gets one ``TaskFailure`` built here, from an explicit
constructor or from ``from_exception``. Classification is mechanical:
exception types, traceback frame paths and explicit constructors. No LLM
and no config rule assigns an origin; ``failures.yaml`` holds bounds and
the retry policy for ``UNKNOWN`` only.

The module does no I/O beyond resolving frame paths and imports nothing
from ``modules.backend.agents`` or ``modules.backend.tools``.
"""

from __future__ import annotations

import hashlib
import os
import site
import sys
import sysconfig
import traceback
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.exceptions import IncompleteToolCall, UnexpectedModelBehavior, UsageLimitExceeded
from sqlalchemy.exc import InterfaceError, OperationalError

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.config_schema import FailuresSchema
from modules.backend.core.exceptions import (
    BudgetExceededError,
    ContractViolationError,
    DatabaseError,
    ExecutionEnvironmentError,
    ExternalServiceError,
    ProviderError,
    QuotaExhaustedError,
    RateLimitedError,
    TransientProviderError,
    classify_provider_error,
)
from modules.backend.core.redaction import redact_secrets
from modules.backend.schemas.execution_outcome import VerificationOutcome
from modules.backend.schemas.task_failure import (
    FailureClass,
    FailureEvidence,
    FailureOrigin,
    TaskFailure,
)

# The agent's output did not satisfy its contract. The only home of this tuple.
CONTRACT_ERRORS: tuple[type[BaseException], ...] = (
    ContractViolationError,
    PydanticValidationError,
    UnexpectedModelBehavior,
    IncompleteToolCall,
    UsageLimitExceeded,
)

# Directories, under the platform modules directory, whose bad-argument errors
# are the agent's tool misuse rather than a platform defect (3.8.3 step 7).
AGENT_TOOL_DIRS: tuple[str, ...] = ("backend/tools", "backend/agents/deps")

_TOOL_ERROR_TYPES: tuple[type[BaseException], ...] = (PermissionError, ValueError, TypeError)
_RETRYABLE_CLASSES = frozenset(
    {FailureClass.PLATFORM_TRANSIENT, FailureClass.AGENT_TOOL_ERROR, FailureClass.TIMEOUT}
)
_PROVIDER_CLASSES: tuple[tuple[type[ProviderError], FailureClass], ...] = (
    (QuotaExhaustedError, FailureClass.QUOTA_EXHAUSTED),
    (RateLimitedError, FailureClass.TRANSIENT_PROVIDER),
    (TransientProviderError, FailureClass.TRANSIENT_PROVIDER),
)
_CONTROL_CLASSES = frozenset(
    {FailureClass.CANCELLED, FailureClass.BUDGET_EXCEEDED, FailureClass.RUN_ABORTED}
)


class WorkflowStepFailedError(RuntimeError):
    """A workflow step failed; carries the step's classified failure (contracts 3.5.5)."""

    def __init__(self, failure: TaskFailure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in roots)


class FailureClassifier:
    """Builds every ``TaskFailure`` in the platform. One instance per process."""

    def __init__(self, config: FailuresSchema, platform_modules_dir: Path) -> None:
        self._config = config
        self._platform_dir = os.path.realpath(platform_modules_dir)
        self._tool_dirs = tuple(
            os.path.realpath(os.path.join(self._platform_dir, d)) for d in AGENT_TOOL_DIRS
        )
        paths = sysconfig.get_paths()
        self._stdlib_roots = tuple(
            {os.path.realpath(paths["stdlib"]), os.path.realpath(paths["platstdlib"])}
        )
        self._package_roots = tuple(
            {
                os.path.realpath(p)
                for p in (paths["purelib"], paths["platlib"], *site.getsitepackages())
            }
        )
        # Longest first, so a frame is made relative to its most specific entry.
        self._sys_path_roots = tuple(
            sorted({os.path.realpath(p) for p in sys.path}, key=len, reverse=True)
        )

    @property
    def tool_dirs(self) -> tuple[str, ...]:
        """The resolved ``AGENT_TOOL_DIRS``."""
        return self._tool_dirs

    # ── Explicit constructors (3.8.3) ─────────────────────────────────────

    def control(self, failure_class: FailureClass, summary: str) -> TaskFailure:
        """Stopped by the platform: cancellation, gate abort, budget stop or run end."""
        if failure_class not in _CONTROL_CLASSES:
            raise ValueError(f"control() does not take {failure_class.value}")
        return self._record(FailureOrigin.CONTROL, failure_class, summary, key=failure_class.value)

    def upstream_blocked(self, missing_ref: str, upstream_task_id: str) -> TaskFailure:
        """A from_upstream reference has no output to read."""
        cls = FailureClass.UPSTREAM_BLOCKED
        return self._record(
            FailureOrigin.UPSTREAM, cls, f"{cls.value}: {missing_ref}", key=upstream_task_id
        )

    def roster_miss(self, agent_name: str) -> TaskFailure:
        """The task's agent is not on the roster."""
        cls = FailureClass.PLATFORM_DEFECT
        return self._record(
            FailureOrigin.PLATFORM,
            cls,
            f"{cls.value}: {agent_name}",
            key=f"{cls.value}|{agent_name}",
        )

    def plan_invalid(self, agent_name: str, detail: str) -> TaskFailure:
        """The planner produced an unusable task, such as a missing loop_config."""
        cls = FailureClass.AGENT_CONTRACT
        return self._record(FailureOrigin.AGENT, cls, detail, key=f"{cls.value}|{agent_name}")

    def agent_outcome(self, agent_name: str, detail: str) -> TaskFailure:
        """An agent or sub-run finished without raising but reported failure."""
        cls = FailureClass.AGENT_REPORTED_FAILURE
        return self._record(FailureOrigin.AGENT, cls, detail, key=f"{cls.value}|{agent_name}")

    def verification_failed(
        self, agent_name: str, verification_outcome: VerificationOutcome
    ) -> TaskFailure:
        """The verification retries are exhausted."""
        cls = FailureClass.VERIFICATION_FAILED
        tier, check = _first_failing_check(verification_outcome)
        return self._record(
            FailureOrigin.AGENT,
            cls,
            f"{cls.value}: {agent_name}",
            key=f"{agent_name}|{tier}|{check}",
        )

    def orphaned(self, detail: str) -> TaskFailure:
        """The run's workflow closed or vanished without finalising the task."""
        cls = FailureClass.ORPHANED
        return self._record(FailureOrigin.PLATFORM, cls, detail, key=cls.value)

    # ── Exceptions (3.8.3) ───────────────────────────────────────────────

    def from_exception(self, exc: BaseException) -> TaskFailure:
        """Classify a raw exception. The first matching rule wins."""
        if isinstance(exc, WorkflowStepFailedError):
            return exc.failure
        if isinstance(exc, BudgetExceededError):
            return self.control(FailureClass.BUDGET_EXCEEDED, FailureClass.BUDGET_EXCEEDED.value)

        typed = classify_provider_error(exc, provider="", model="")
        for provider_type, cls in _PROVIDER_CLASSES:
            if isinstance(typed, provider_type):
                retryable = typed.retry_policy != "none"
                return self._from_raised(exc, FailureOrigin.PROVIDER, cls, retryable=retryable)

        if isinstance(exc, CONTRACT_ERRORS):
            return self._from_raised(exc, FailureOrigin.AGENT, FailureClass.AGENT_CONTRACT)
        if isinstance(exc, ExecutionEnvironmentError):
            return self._from_raised(exc, FailureOrigin.ENVIRONMENT, FailureClass.ENV_UNAVAILABLE)
        if isinstance(exc, TimeoutError):
            return self._from_raised(exc, FailureOrigin.AGENT, FailureClass.TIMEOUT)
        if isinstance(exc, ExternalServiceError) or (
            isinstance(exc, DatabaseError)
            and isinstance(exc.__context__, (OperationalError, InterfaceError))
        ):
            return self._from_raised(exc, FailureOrigin.PLATFORM, FailureClass.PLATFORM_TRANSIENT)

        innermost = self._innermost_frame(exc)
        if (
            isinstance(exc, _TOOL_ERROR_TYPES)
            and innermost is not None
            and _under(innermost, self._tool_dirs)
        ):
            return self._from_raised(exc, FailureOrigin.AGENT, FailureClass.AGENT_TOOL_ERROR)
        if innermost is not None and _under(innermost, (self._platform_dir,)):
            cls = FailureClass.PLATFORM_DEFECT
            if isinstance(exc, ImportError) and _missing_top_level(exc) not in (None, "modules"):
                cls = FailureClass.PLATFORM_DEPENDENCY_MISSING
            return self._from_raised(exc, FailureOrigin.PLATFORM, cls)
        return self._from_raised(exc, FailureOrigin.UNKNOWN, FailureClass.UNKNOWN)

    # ── Frames ───────────────────────────────────────────────────────────

    def is_skipped_frame(self, filename: str) -> bool:
        """A frozen or standard-library frame. Site-packages frames are never skipped."""
        if filename.startswith("<frozen"):
            return True
        path = os.path.realpath(filename)
        return _under(path, self._stdlib_roots) and not _under(path, self._package_roots)

    def _frames(self, exc: BaseException) -> list[tuple[str, str]]:
        """Non-skipped frames of the traceback, outermost first, as (resolved path, function)."""
        return [
            (os.path.realpath(fs.filename), fs.name)
            for fs in traceback.extract_tb(exc.__traceback__)
            if not self.is_skipped_frame(fs.filename)
        ]

    def _innermost_frame(self, exc: BaseException) -> str | None:
        frames = self._frames(exc)
        return frames[-1][0] if frames else None

    def _format_frame(self, path: str, function: str) -> str:
        """``path.py:function`` relative to the platform dir or the frame's sys.path entry."""
        if _under(path, (self._platform_dir,)):
            return f"{os.path.relpath(path, self._platform_dir)}:{function}"
        for root in self._sys_path_roots:
            if root and _under(path, (root,)):
                return f"{os.path.relpath(path, root)}:{function}"
        return f"{os.path.basename(path)}:{function}"

    def _fingerprint_frame(self, frames: list[tuple[str, str]]) -> str:
        for path, function in reversed(frames):
            if _under(path, (self._platform_dir,)):
                return self._format_frame(path, function)
        if frames:
            return self._format_frame(*frames[-1])
        return ""

    # ── Record building ──────────────────────────────────────────────────

    def _from_raised(
        self,
        exc: BaseException,
        origin: FailureOrigin,
        failure_class: FailureClass,
        *,
        retryable: bool | None = None,
    ) -> TaskFailure:
        bounds = self._config.evidence
        frames = self._frames(exc)
        message = redact_secrets(str(exc))[: bounds.max_message_chars]
        module_name = getattr(exc, "name", None) if isinstance(exc, ImportError) else None
        evidence = FailureEvidence(
            exception_type=type(exc).__name__,
            message=message,
            traceback_tail=[
                self._format_frame(p, f) for p, f in frames[-bounds.max_traceback_frames :]
            ],
            module_name=module_name,
        )
        first_line = message.splitlines()[0] if message.strip() else type(exc).__name__
        if failure_class is FailureClass.PLATFORM_DEPENDENCY_MISSING:
            key = module_name or ""
        else:
            key = f"{type(exc).__name__}|{self._fingerprint_frame(frames)}"
        return TaskFailure(
            origin=origin,
            failure_class=failure_class,
            fingerprint=_fingerprint(origin, failure_class, key),
            summary=redact_secrets(f"{failure_class.value}: {first_line}")[
                : bounds.max_summary_chars
            ],
            retryable=self._retryable(failure_class) if retryable is None else retryable,
            evidence=evidence,
        )

    def _record(
        self,
        origin: FailureOrigin,
        failure_class: FailureClass,
        summary: str,
        *,
        key: str,
    ) -> TaskFailure:
        bounds = self._config.evidence
        redacted = redact_secrets(summary)
        return TaskFailure(
            origin=origin,
            failure_class=failure_class,
            fingerprint=_fingerprint(origin, failure_class, key),
            summary=redacted[: bounds.max_summary_chars],
            retryable=self._retryable(failure_class),
            evidence=FailureEvidence(
                exception_type=None,
                message=redacted[: bounds.max_message_chars],
                traceback_tail=[],
                module_name=None,
            ),
        )

    def _retryable(self, failure_class: FailureClass) -> bool:
        if failure_class is FailureClass.UNKNOWN:
            return self._config.unknown_retryable
        return failure_class in _RETRYABLE_CLASSES


def _fingerprint(origin: FailureOrigin, failure_class: FailureClass, key: str) -> str:
    return hashlib.sha256(f"{origin.value}|{failure_class.value}|{key}".encode()).hexdigest()


def _missing_top_level(exc: ImportError) -> str | None:
    name = getattr(exc, "name", None)
    return name.split(".", 1)[0] if name else None


def _first_failing_check(outcome: VerificationOutcome) -> tuple[str, str]:
    """The first failing tier and its first failed check name ("" when the tier has none)."""
    if outcome.tier_1.status == "fail":
        return "tier_1", ""
    if outcome.tier_2.status == "fail":
        checks = outcome.tier_2.failed_checks
        return "tier_2", checks[0].check if checks else ""
    if outcome.tier_3.status == "fail":
        return "tier_3", ""
    return "", ""


@lru_cache(maxsize=1)
def get_failure_classifier() -> FailureClassifier:
    """The process-wide classifier over ``failures.yaml`` and the platform modules directory."""
    return FailureClassifier(
        get_app_config().failures,
        Path(os.path.realpath(find_project_root() / "modules")),
    )
