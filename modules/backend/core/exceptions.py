"""
Custom Exceptions.

Application-specific exception classes for consistent error handling.
Every concrete subclass should be registered in
`core/exception_handlers.EXCEPTION_STATUS_MAP` if it can reach an API
boundary, so the FastAPI handler returns the correct HTTP status.
"""

import re
from typing import Any, ClassVar, Literal

from modules.backend.core.logging import get_logger

RetryPolicy = Literal["none", "backoff", "immediate"]

_QUOTA_MESSAGE_PATTERN = re.compile(r"quota", re.IGNORECASE)
_logger = get_logger(__name__)


class ApplicationError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, code: str = "SYS_INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


class NotFoundError(ApplicationError):
    """Raised when a resource cannot be found."""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, code="RES_NOT_FOUND")


class ValidationError(ApplicationError):
    """Raised when validation fails."""

    def __init__(self, message: str = "Validation failed", details: dict | None = None) -> None:
        self.details = details or {}
        super().__init__(message, code="VAL_VALIDATION_ERROR")


class AuthenticationError(ApplicationError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message, code="AUTH_UNAUTHORIZED")


class AuthorizationError(ApplicationError):
    """Raised when authorization fails."""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message, code="AUTHZ_FORBIDDEN")


class ConflictError(ApplicationError):
    """Raised when there is a state conflict."""

    def __init__(self, message: str = "Resource conflict") -> None:
        super().__init__(message, code="RES_CONFLICT")


class ExternalServiceError(ApplicationError):
    """Raised when an external service call fails."""

    def __init__(self, message: str = "External service error") -> None:
        super().__init__(message, code="SYS_EXTERNAL_SERVICE_ERROR")


class BudgetExceededError(ApplicationError):
    """Raised when a session's cost budget is exceeded."""

    def __init__(
        self,
        message: str = "Cost budget exceeded",
        current_cost: float = 0.0,
        budget: float = 0.0,
    ) -> None:
        self.current_cost = current_cost
        self.budget = budget
        super().__init__(message, code="COST_BUDGET_EXCEEDED")


class DatabaseError(ApplicationError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database error") -> None:
        super().__init__(message, code="SYS_DATABASE_ERROR")


# ---------------------------------------------------------------------------
# LLM Provider error taxonomy
# ---------------------------------------------------------------------------
#
# Provider adapters (Copilot, Anthropic, OpenAI, Foundry) catch native
# SDK exceptions and re-raise one of the subclasses below. The retry
# handler branches policy off the abstract base (`ProviderError`) and
# the per-subclass `retry_policy` constant — adding a new provider is
# subclassing one of these, not editing the handler.
#
# Each subclass is registered in EXCEPTION_STATUS_MAP so the FastAPI
# handler returns the right HTTP status when the error reaches an API
# boundary. Single inheritance keeps the MRO obvious; HTTP mapping is
# explicit via the map (the handler uses exact-type lookup).


class ProviderError(ApplicationError):
    """Base for typed errors from any LLM provider adapter.

    Carries the operational context an operator needs to triage:
    provider name, model id, provider-side request id, raw SDK
    message, plus class-level constants (`log_event`, `remediation`,
    `retry_policy`) that describe how the failure should be handled.

    Concrete subclasses set those constants and the `code` default;
    the base accepts everything as kwargs so subclasses don't need
    custom __init__ overrides for the common case.
    """

    log_event: ClassVar[str] = "Provider error"
    remediation: ClassVar[str | None] = None
    retry_policy: ClassVar[RetryPolicy] = "none"

    def __init__(
        self,
        message: str,
        *,
        code: str = "SYS_EXTERNAL_SERVICE_ERROR",
        provider: str | None = None,
        model: str | None = None,
        request_id: str | None = None,
        raw: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.provider = provider
        self.model = model
        self.request_id = request_id
        self.raw = raw if raw is not None else message

    def log_extra(self) -> dict[str, Any]:
        """Standard structured fields for the ERROR log entry.

        Catch sites extend this via the `**context` kwargs of
        `log_provider_error`.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "provider_request_id": self.request_id,
            "raw": str(self.raw)[:500] if self.raw else None,
            "remediation": self.remediation,
        }


class QuotaExhaustedError(ProviderError):
    """Provider billing quota / hard limit is exhausted.

    Permanent for the current window — retries inside this process
    cannot help. HTTP 429 (caller hit a limit).
    """

    log_event = "Provider quota exhausted"
    remediation = (
        "Quota exhausted for the current window. Wait for reset, "
        "upgrade the plan, or switch affected agents to a provider "
        "with remaining capacity."
    )
    retry_policy = "none"

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "RATE_LIMITED")
        super().__init__(message, **kwargs)


class RateLimitedError(ProviderError):
    """Provider is rate-limiting the current request burst.

    Distinct from quota exhaustion: self-clears after a short
    backoff. HTTP 429.
    """

    log_event = "Provider rate-limited"
    remediation = "Backing off and retrying — typically self-resolves."
    retry_policy = "backoff"

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("code", "RATE_LIMITED")
        super().__init__(message, **kwargs)


class TransientProviderError(ProviderError):
    """Transient infrastructure failure between us and the model.

    SDK session loss, connectivity hiccup, empty response from a
    momentarily flaky session. HTTP 502. Retry immediately.
    """

    log_event = "Provider transient failure"
    remediation = "Retrying — usually a session or SDK hiccup."
    retry_policy = "immediate"


class ContractViolationError(ProviderError):
    """Model produced output that violates the agent's contract.

    Wrong schema, missing required fields, didn't call the required
    output tool. Re-prompting almost always reproduces the same
    failure. HTTP 502 (upstream misbehavior, not caller's fault).
    """

    log_event = "Provider contract violation"
    remediation = (
        "Model output did not match the expected schema. Inspect "
        "the agent's prompt and output_type — adjust the prompt, "
        "switch models, or correct the schema."
    )
    retry_policy = "none"


# ---------------------------------------------------------------------------
# Workflow contract errors
# ---------------------------------------------------------------------------


class WorkflowOutputMappingError(ValidationError):
    """A workflow step's output_mapping references a field that the
    source agent doesn't actually emit.

    Raised at workflow runtime by `extract_outputs` when a declared
    `source_field` isn't present on the agent's actual output. Seed-
    time validation in `workflow_validator.validate_output_mappings`
    catches most cases earlier; this is defense-in-depth for workflows
    that bypass the seeder (e.g. designed at runtime by the Workflow
    Architect) or agent schemas that change after seed.

    Promoted from a silent warning to a step failure because the
    workflow's downstream contract is broken — letting the step
    transition to `completed` with missing data causes downstream
    agents to fabricate output, masquerading a degraded run as a
    success.
    """

    def __init__(
        self,
        message: str,
        *,
        step_id: str | None = None,
        source_task: str | None = None,
        source_field: str | None = None,
        available_fields: list[str] | None = None,
    ) -> None:
        details = {
            "step_id": step_id,
            "source_task": source_task,
            "source_field": source_field,
            "available_fields": available_fields or [],
        }
        super().__init__(message, details=details)


def log_provider_error(
    log: Any,
    exc: ProviderError,
    *,
    event: str | None = None,
    **context: Any,
) -> None:
    """Log a provider error at ERROR level with the canonical shape.

    `log` is a structlog/stdlib logger. The event name defaults to
    `exc.log_event` (the exception's own perspective on the failure);
    pass `event=` to override at the call site when the surrounding
    layer wants its own framing (e.g. retry handler logging
    "Task failed (no retry)" instead of "Provider quota exhausted").

    `context` kwargs are merged into the structured `extra` dict.
    `None`-valued entries are dropped to keep the log readable.
    """
    extra = exc.log_extra()
    extra.update({k: v for k, v in context.items() if v is not None})
    log.error(event or exc.log_event, extra=extra)


def classify_provider_error(exc: BaseException, *, provider: str, model: str) -> BaseException:
    """Classify a raw provider/SDK exception into a typed `ProviderError`.

    Single home for cross-adapter classification (PydanticAI's
    `ModelHTTPError` for Anthropic/OpenAI/Foundry models, plus the
    Anthropic and OpenAI SDK exception types directly, since Foundry
    runs through the OpenAI SDK path). SDK exception types are imported
    lazily so this module doesn't hard-depend on every provider package
    being installed.

    Returns `exc` unchanged when no known pattern matches, so callers can
    re-raise (or further handle) the original exception as-is — same
    contract as `CopilotModel._classify_session_error`.
    """
    from pydantic_ai.exceptions import ModelHTTPError

    msg = str(exc)

    if isinstance(exc, ModelHTTPError):
        status = exc.status_code
        body_msg = str(exc.body) if exc.body is not None else ""
        if status == 402 or _QUOTA_MESSAGE_PATTERN.search(f"{msg} {body_msg}"):
            return QuotaExhaustedError(msg, provider=provider, model=model, raw=msg)
        if status == 429:
            return RateLimitedError(msg, provider=provider, model=model, raw=msg)
        if status >= 500 or status == 408:
            return TransientProviderError(msg, provider=provider, model=model, raw=msg)
        return exc

    try:
        import anthropic

        if isinstance(exc, anthropic.RateLimitError):
            return RateLimitedError(msg, provider=provider, model=model, raw=msg)
        if isinstance(
            exc,
            (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.InternalServerError,
            ),
        ):
            return TransientProviderError(msg, provider=provider, model=model, raw=msg)
    except ImportError:
        _logger.debug(
            "anthropic package not installed — skipping anthropic-specific classification"
        )

    try:
        import openai

        if isinstance(exc, openai.RateLimitError):
            return RateLimitedError(msg, provider=provider, model=model, raw=msg)
        if isinstance(
            exc,
            (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError),
        ):
            return TransientProviderError(msg, provider=provider, model=model, raw=msg)
    except ImportError:
        _logger.debug("openai package not installed — skipping openai-specific classification")

    # Generic fallback: some adapters (e.g. Copilot) raise a plain
    # Exception whose message embeds the failure reason rather than a
    # typed SDK exception. A quota-pattern message is still a quota
    # failure regardless of exception type.
    if _QUOTA_MESSAGE_PATTERN.search(msg):
        return QuotaExhaustedError(msg, provider=provider, model=model, raw=msg)

    return exc
