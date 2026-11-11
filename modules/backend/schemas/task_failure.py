"""Typed task failure record (Plan 88, contracts 3.8.2).

Every failed or timed-out task carries one ``TaskFailure``. Its origin and
class come from mechanical rules in ``core/failure_classification.py``;
nothing here classifies. ``message`` and ``summary`` are redacted and
bounded before a record is built.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict


class FailureOrigin(str, enum.Enum):
    # The running platform: its code, its installed dependencies, its infrastructure.
    PLATFORM = "platform"
    # LLM provider error, already typed by classify_provider_error.
    PROVIDER = "provider"
    # No isolated workspace could be provided (3.8.5).
    ENVIRONMENT = "environment"
    # The agent run itself: output contract, tool misuse, verification, timeout, reported failure.
    AGENT = "agent"
    # A dependency of this task failed or produced no output.
    UPSTREAM = "upstream"
    # Stopped by the platform: cancellation, budget, run end, gate abort.
    CONTROL = "control"
    UNKNOWN = "unknown"


class FailureClass(str, enum.Enum):
    TRANSIENT_PROVIDER = "transient_provider"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AGENT_CONTRACT = "agent_contract"
    AGENT_TOOL_ERROR = "agent_tool_error"
    AGENT_REPORTED_FAILURE = "agent_reported_failure"
    VERIFICATION_FAILED = "verification_failed"
    TIMEOUT = "timeout"
    UPSTREAM_BLOCKED = "upstream_blocked"
    PLATFORM_DEFECT = "platform_defect"
    PLATFORM_DEPENDENCY_MISSING = "platform_dependency_missing"
    PLATFORM_TRANSIENT = "platform_transient"
    ORPHANED = "orphaned"
    ENV_UNAVAILABLE = "env_unavailable"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    RUN_ABORTED = "run_aborted"
    UNKNOWN = "unknown"


class FailureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_type: str | None
    message: str  # redacted, cut to failures.evidence.max_message_chars
    # Innermost failures.evidence.max_traceback_frames frames, each written as in 3.8.4.
    traceback_tail: list[str]
    module_name: str | None  # ModuleNotFoundError.name, when present


class TaskFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: FailureOrigin
    failure_class: FailureClass
    fingerprint: str  # 64 hex chars (3.8.4)
    summary: str  # becomes tasks.failure_reason and ExecuteTaskResult.failure_reason
    retryable: bool  # whether the same agent may retry inside the task (3.8.3)
    evidence: FailureEvidence
