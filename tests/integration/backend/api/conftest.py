"""Fixtures shared by the mission API integration tests."""

import pytest
from httpx import AsyncClient

from modules.backend.core.dependencies import get_current_user


@pytest.fixture
def signed_in(client: AsyncClient, test_user):
    """Act as test_user (a regular user) for the test."""
    client.app.dependency_overrides[get_current_user] = lambda: test_user
    yield test_user
    client.app.dependency_overrides.pop(get_current_user, None)
