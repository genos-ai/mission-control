"""Tests for User and ApiKey models.

Tests User.has_role() config-driven authorization and ApiKey.is_active property.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from modules.backend.core.config_schema import RoleSchema
from modules.backend.core.utils import utc_now


def _mock_app_config(roles=None):
    """Create a mock app config with role definitions."""
    if roles is None:
        roles = {
            "viewer": RoleSchema(level=1, description="Read-only"),
            "user": RoleSchema(level=2, description="Standard"),
            "admin": RoleSchema(level=3, description="Full"),
        }
    config = MagicMock()
    config.security.roles = roles
    return config


class TestUserHasRole:
    """Tests for User.has_role() method."""

    def _make_user(self, role: str):
        """Create a MagicMock User that delegates has_role to real logic."""
        from modules.backend.models.user import User

        user = MagicMock(spec=User)
        user.system_role = role
        # Bind the real has_role method to our mock
        user.has_role = lambda minimum: User.has_role(user, minimum)
        return user

    def test_admin_has_all_roles(self):
        user = self._make_user("admin")
        with patch("modules.backend.core.config.get_app_config", return_value=_mock_app_config()):
            assert user.has_role("viewer") is True
            assert user.has_role("user") is True
            assert user.has_role("admin") is True

    def test_user_has_viewer_and_user(self):
        user = self._make_user("user")
        with patch("modules.backend.core.config.get_app_config", return_value=_mock_app_config()):
            assert user.has_role("viewer") is True
            assert user.has_role("user") is True
            assert user.has_role("admin") is False

    def test_viewer_only_has_viewer(self):
        user = self._make_user("viewer")
        with patch("modules.backend.core.config.get_app_config", return_value=_mock_app_config()):
            assert user.has_role("viewer") is True
            assert user.has_role("user") is False
            assert user.has_role("admin") is False

    def test_unknown_minimum_raises(self):
        user = self._make_user("admin")
        with patch("modules.backend.core.config.get_app_config", return_value=_mock_app_config()):
            with pytest.raises(ValueError, match="Unknown role: superadmin"):
                user.has_role("superadmin")

    def test_unknown_user_role_treated_as_level_zero(self):
        user = self._make_user("ghost")
        with patch("modules.backend.core.config.get_app_config", return_value=_mock_app_config()):
            assert user.has_role("viewer") is False


class TestApiKeyIsActive:
    """Tests for ApiKey.is_active property."""

    def _make_key(self, revoked_at=None, expires_at=None):
        """Create a MagicMock ApiKey that delegates is_active to real property."""
        from modules.backend.models.api_key import ApiKey

        key = MagicMock(spec=ApiKey)
        key.revoked_at = revoked_at
        key.expires_at = expires_at
        # Bind the real is_active property to our mock
        type(key).is_active = property(lambda self: ApiKey.is_active.fget(self))
        return key

    def test_active_key(self):
        key = self._make_key()
        assert key.is_active is True

    def test_revoked_key(self):
        key = self._make_key(revoked_at=utc_now())
        assert key.is_active is False

    def test_expired_key(self):
        key = self._make_key(expires_at=utc_now() - timedelta(hours=1))
        assert key.is_active is False

    def test_future_expiry_is_active(self):
        key = self._make_key(expires_at=utc_now() + timedelta(days=30))
        assert key.is_active is True

    def test_revoked_and_expired(self):
        key = self._make_key(
            revoked_at=utc_now(),
            expires_at=utc_now() - timedelta(hours=1),
        )
        assert key.is_active is False
