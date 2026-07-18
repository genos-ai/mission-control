"""
Integration Tests for Request Context Middleware.

Tests that request context is properly propagated through the API.
"""

import pytest
from httpx import AsyncClient

from modules.backend.core.dependencies import get_current_user


@pytest.fixture(autouse=True)
def _authenticated(client: AsyncClient, test_user):
    """Endpoints require auth (endpoint-authz hardening); act as test_user."""
    client.app.dependency_overrides[get_current_user] = lambda: test_user
    yield
    client.app.dependency_overrides.pop(get_current_user, None)


class TestRequestIdHeader:
    """Tests for X-Request-ID header handling."""

    @pytest.mark.asyncio
    async def test_generates_request_id(self, client: AsyncClient):
        """Should generate X-Request-ID when not provided."""
        response = await client.get("/health")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # UUID format: 8-4-4-4-12 = 36 characters
        assert len(response.headers["X-Request-ID"]) == 36

    @pytest.mark.asyncio
    async def test_propagates_provided_request_id(self, client: AsyncClient):
        """Should use provided X-Request-ID header."""
        custom_id = "my-custom-request-id-12345"

        response = await client.get(
            "/health",
            headers={"X-Request-ID": custom_id},
        )

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == custom_id

    @pytest.mark.asyncio
    async def test_request_id_consistent_across_endpoints(self, client: AsyncClient):
        """Should use same request ID format across all endpoints."""
        endpoints = ["/health", "/health/ready", "/api/v1/sessions"]

        for endpoint in endpoints:
            response = await client.get(endpoint)
            assert "X-Request-ID" in response.headers
            # All should be valid UUIDs (36 chars)
            assert len(response.headers["X-Request-ID"]) == 36


class TestResponseTimeHeader:
    """Tests for X-Response-Time header."""

    @pytest.mark.asyncio
    async def test_includes_response_time(self, client: AsyncClient):
        """Should include X-Response-Time header."""
        response = await client.get("/health")

        assert response.status_code == 200
        assert "X-Response-Time" in response.headers
        assert response.headers["X-Response-Time"].endswith("ms")

    @pytest.mark.asyncio
    async def test_response_time_is_numeric(self, client: AsyncClient):
        """Should have numeric response time value."""
        response = await client.get("/health")

        time_header = response.headers["X-Response-Time"]
        # Remove 'ms' suffix and verify it's a number
        time_value = time_header.rstrip("ms")
        assert time_value.isdigit()

    @pytest.mark.asyncio
    async def test_response_time_on_error(self, client: AsyncClient):
        """Should include response time even on error responses."""
        response = await client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000")

        # 403 for non-admins (anti-enumeration) — timing header must still be present
        assert response.status_code == 403
        assert "X-Response-Time" in response.headers


class TestRequestContextInErrors:
    """Tests for request context in error responses."""

    @pytest.mark.asyncio
    async def test_error_response_includes_request_id(self, client: AsyncClient):
        """Should include request_id in error response metadata."""
        custom_id = "error-test-request-id"

        response = await client.get(
            "/api/v1/sessions/00000000-0000-0000-0000-000000000000",
            headers={"X-Request-ID": custom_id},
        )

        # 403 for non-admins (anti-enumeration)
        assert response.status_code == 403
        data = response.json()

        # Error response should include request_id in metadata
        assert data["metadata"]["request_id"] == custom_id

    @pytest.mark.asyncio
    async def test_validation_error_includes_request_id(self, client: AsyncClient):
        """Should include request_id in validation error response metadata."""
        custom_id = "validation-error-request-id"

        response = await client.post(
            "/api/v1/sessions",
            json={"cost_budget_usd": "not-a-number"},  # Invalid type triggers validation error
            headers={"X-Request-ID": custom_id},
        )

        assert response.status_code == 422
        data = response.json()

        # Validation error should also include request_id in metadata
        assert data["metadata"]["request_id"] == custom_id
