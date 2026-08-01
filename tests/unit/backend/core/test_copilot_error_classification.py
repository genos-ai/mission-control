"""
Unit tests for CopilotModel._classify_session_error (Plan 84 Phase 4.3).

Verifies the refactor that delegates generic quota-message detection to
the shared classify_provider_error, keeping only the Copilot-specific
request-ID extraction local.
"""

from modules.backend.core.copilot_model import CopilotModel, CopilotQuotaExhaustedError


def _model() -> CopilotModel:
    return CopilotModel(model_id="test-model")


def test_quota_message_classified_with_request_id():
    model = _model()
    exc = Exception("Error: 402 monthly quota exceeded (Request ID: req-abc-123)")
    result = model._classify_session_error(exc)
    assert isinstance(result, CopilotQuotaExhaustedError)
    assert result.request_id == "req-abc-123"
    assert result.provider == "copilot"
    assert result.model == "test-model"


def test_quota_message_classified_without_request_id():
    model = _model()
    exc = Exception("quota exceeded for this billing period")
    result = model._classify_session_error(exc)
    assert isinstance(result, CopilotQuotaExhaustedError)
    assert result.request_id is None


def test_unrelated_error_unchanged():
    model = _model()
    exc = Exception("session closed unexpectedly")
    result = model._classify_session_error(exc)
    assert result is exc
