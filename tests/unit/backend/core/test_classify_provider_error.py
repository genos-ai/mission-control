"""
Unit tests for classify_provider_error (Plan 84 Phase 4.3).

Covers the PydanticAI ModelHTTPError status-code mapping and the
generic message-pattern fallback used for adapters (like Copilot) that
raise plain exceptions instead of typed SDK errors.
"""

from pydantic_ai.exceptions import ModelHTTPError

from modules.backend.core.exceptions import (
    QuotaExhaustedError,
    RateLimitedError,
    TransientProviderError,
    classify_provider_error,
)


def test_model_http_error_429_is_rate_limited():
    exc = ModelHTTPError(status_code=429, model_name="claude-sonnet-5", body="rate limited")
    result = classify_provider_error(exc, provider="anthropic", model="claude-sonnet-5")
    assert isinstance(result, RateLimitedError)
    assert result.provider == "anthropic"
    assert result.model == "claude-sonnet-5"


def test_model_http_error_402_is_quota_exhausted():
    exc = ModelHTTPError(status_code=402, model_name="gpt-5", body="payment required")
    result = classify_provider_error(exc, provider="openai", model="gpt-5")
    assert isinstance(result, QuotaExhaustedError)


def test_model_http_error_quota_message_is_quota_exhausted():
    exc = ModelHTTPError(
        status_code=400,
        model_name="gpt-5",
        body={"error": {"message": "monthly quota exceeded"}},
    )
    result = classify_provider_error(exc, provider="openai", model="gpt-5")
    assert isinstance(result, QuotaExhaustedError)


def test_model_http_error_5xx_is_transient():
    exc = ModelHTTPError(status_code=503, model_name="gpt-5", body="service unavailable")
    result = classify_provider_error(exc, provider="openai", model="gpt-5")
    assert isinstance(result, TransientProviderError)


def test_model_http_error_408_is_transient():
    exc = ModelHTTPError(status_code=408, model_name="gpt-5", body="timeout")
    result = classify_provider_error(exc, provider="openai", model="gpt-5")
    assert isinstance(result, TransientProviderError)


def test_model_http_error_unrecognized_status_unchanged():
    exc = ModelHTTPError(status_code=400, model_name="gpt-5", body="bad request")
    result = classify_provider_error(exc, provider="openai", model="gpt-5")
    assert result is exc


def test_generic_exception_with_quota_message_is_classified():
    exc = Exception("Request failed: 402 monthly quota exceeded (Request ID: abc123)")
    result = classify_provider_error(exc, provider="copilot", model="gpt-5")
    assert isinstance(result, QuotaExhaustedError)


def test_generic_exception_unrelated_message_unchanged():
    exc = Exception("connection reset by peer")
    result = classify_provider_error(exc, provider="copilot", model="gpt-5")
    assert result is exc


def test_plain_value_error_unchanged():
    exc = ValueError("not a provider error at all")
    result = classify_provider_error(exc, provider="anthropic", model="claude-sonnet-5")
    assert result is exc
