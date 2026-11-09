"""
Unit tests for Telegram bot middlewares.

Tests authentication, rate limiting, and logging middlewares.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Update


class TestAuthMiddleware:
    """Tests for AuthMiddleware."""

    def _create_mock_update(self, user_id: int, username: str) -> MagicMock:
        """Create a mock Update object that passes isinstance checks."""
        user = MagicMock()
        user.id = user_id
        user.username = username

        message = MagicMock()
        message.from_user = user
        message.chat.type = "private"

        # Create a proper mock that will pass isinstance(event, Update)
        event = MagicMock(spec=Update)
        event.message = message
        event.callback_query = None
        event.inline_query = None

        return event

    @pytest.mark.asyncio
    async def test_allows_authorized_user(self):
        """Test that authorized users are allowed through."""
        from modules.clients.telegram.middlewares.auth import AuthMiddleware

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="result")

        event = self._create_mock_update(123456789, "testuser")

        mock_app_config = MagicMock()
        mock_app_config.application.telegram.authorized_users = [123456789, 987654321]

        with patch(
            "modules.clients.telegram.middlewares.auth.get_app_config",
            return_value=mock_app_config,
        ):
            result = await middleware(handler, event, {})

        assert result == "result"
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocks_unauthorized_user(self):
        """Test that unauthorized users are blocked."""
        from modules.clients.telegram.middlewares.auth import AuthMiddleware

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="result")

        event = self._create_mock_update(999999999, "unauthorized")

        mock_app_config = MagicMock()
        mock_app_config.application.telegram.authorized_users = [123456789]

        with patch(
            "modules.clients.telegram.middlewares.auth.get_app_config",
            return_value=mock_app_config,
        ):
            result = await middleware(handler, event, {})

        assert result is None
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_allowlist_denies(self):
        """An empty allowlist denies every user (fail closed, P8)."""
        from modules.clients.telegram.middlewares.auth import AuthMiddleware

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="result")

        event = self._create_mock_update(123456789, "anyuser")

        mock_app_config = MagicMock()
        mock_app_config.application.telegram.authorized_users = []

        with patch(
            "modules.clients.telegram.middlewares.auth.get_app_config",
            return_value=mock_app_config,
        ):
            result = await middleware(handler, event, {})

        assert result is None
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_role_mapping_from_config(self):
        """Test that user gets role from security.yaml user_roles mapping."""
        from modules.clients.telegram.middlewares.auth import AuthMiddleware

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="result")
        data = {}

        event = self._create_mock_update(123456789, "admin_user")

        mock_app_config = MagicMock()
        mock_app_config.application.telegram.authorized_users = [123456789, 987654321]
        mock_app_config.security.roles = {
            "viewer": MagicMock(level=1),
            "user": MagicMock(level=2),
            "admin": MagicMock(level=3),
        }
        mock_app_config.security.user_roles = {"123456789": "admin"}

        with (
            patch(
                "modules.clients.telegram.middlewares.auth.get_app_config",
                return_value=mock_app_config,
            ),
            patch(
                "modules.backend.core.security.get_app_config",
                return_value=mock_app_config,
            ),
        ):
            await middleware(handler, event, data)

        assert data["user_role"] == "admin"

    @pytest.mark.asyncio
    async def test_unmapped_user_defaults_to_viewer(self):
        """Test that authorized users without explicit mapping get viewer role."""
        from modules.clients.telegram.middlewares.auth import AuthMiddleware

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="result")
        data = {}

        event = self._create_mock_update(987654321, "other_user")

        mock_app_config = MagicMock()
        mock_app_config.application.telegram.authorized_users = [123456789, 987654321]
        mock_app_config.security.roles = {
            "viewer": MagicMock(level=1),
            "user": MagicMock(level=2),
            "admin": MagicMock(level=3),
        }
        mock_app_config.security.user_roles = {"123456789": "admin"}

        with (
            patch(
                "modules.clients.telegram.middlewares.auth.get_app_config",
                return_value=mock_app_config,
            ),
            patch(
                "modules.backend.core.security.get_app_config",
                return_value=mock_app_config,
            ),
        ):
            await middleware(handler, event, data)

        assert data["user_role"] == "viewer"


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def _create_mock_message(self, user_id: int) -> MagicMock:
        """Create a mock Message object."""
        from aiogram.types import Message

        message = MagicMock(spec=Message)
        message.from_user = MagicMock(id=user_id)
        message.answer = AsyncMock()
        return message

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self):
        """Test that requests under the rate limit are allowed."""
        from modules.clients.telegram.middlewares.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(rate_limit=10, rate_window=60)
        handler = AsyncMock(return_value="result")

        message = self._create_mock_message(123)

        result = await middleware(handler, message, {})

        assert result == "result"
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self):
        """Test that requests over the rate limit are blocked."""
        from modules.clients.telegram.middlewares.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(rate_limit=2, rate_window=60)
        handler = AsyncMock(return_value="result")

        message = self._create_mock_message(123)

        # Make requests up to the limit
        await middleware(handler, message, {})
        await middleware(handler, message, {})

        # This should be blocked
        result = await middleware(handler, message, {})

        assert result is None
        assert handler.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self):
        """Test that rate limit resets after the time window."""
        from modules.clients.telegram.middlewares.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(rate_limit=1, rate_window=60)
        handler = AsyncMock(return_value="result")

        message = self._create_mock_message(123)

        fake_now = 1000.0

        with patch("modules.clients.telegram.middlewares.rate_limit.time") as mock_time:
            mock_time.time.return_value = fake_now

            # First request allowed
            await middleware(handler, message, {})

            # Second request blocked (same window)
            result = await middleware(handler, message, {})
            assert result is None

            # Advance past the window
            mock_time.time.return_value = fake_now + 61.0

            # Third request should be allowed
            result = await middleware(handler, message, {})
            assert result == "result"

    @pytest.mark.asyncio
    async def test_separate_limits_per_user(self):
        """Test that rate limits are tracked per user."""
        from modules.clients.telegram.middlewares.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(rate_limit=1, rate_window=60)
        handler = AsyncMock(return_value="result")

        message1 = self._create_mock_message(123)
        message2 = self._create_mock_message(456)

        # User 1 makes a request
        await middleware(handler, message1, {})

        # User 2 should still be allowed
        result = await middleware(handler, message2, {})
        assert result == "result"


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    def _create_mock_update(self, user_id: int, username: str, text: str = "/start") -> MagicMock:
        """Create a mock Update object."""
        from aiogram.types import Update

        user = MagicMock()
        user.id = user_id
        user.username = username

        message = MagicMock()
        message.from_user = user
        message.chat.id = 456
        message.chat.type = "private"
        message.text = text

        event = MagicMock(spec=Update)
        event.update_id = 789
        event.event_type = "message"
        event.message = message
        event.callback_query = None
        event.inline_query = None

        return event

    @pytest.mark.asyncio
    async def test_logs_update_context(self):
        """Test that logging middleware extracts and logs context."""
        from modules.clients.telegram.middlewares.logging import LoggingMiddleware

        middleware = LoggingMiddleware()
        handler = AsyncMock(return_value="result")

        event = self._create_mock_update(123, "testuser")

        result = await middleware(handler, event, {})

        assert result == "result"
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_errors(self):
        """Test that errors are logged."""
        from modules.clients.telegram.middlewares.logging import LoggingMiddleware

        middleware = LoggingMiddleware()
        handler = AsyncMock(side_effect=ValueError("test error"))

        event = self._create_mock_update(123, "testuser")

        with pytest.raises(ValueError, match="test error"):
            await middleware(handler, event, {})


class TestUserRoles:
    """Tests for config-driven role definitions."""

    def test_role_hierarchy_from_config(self):
        """Test that role hierarchy is read from security.yaml."""
        from modules.backend.core.config import get_app_config

        roles = get_app_config().security.roles
        assert roles["viewer"].level < roles["user"].level
        assert roles["user"].level < roles["admin"].level

    def test_all_roles_defined_in_config(self):
        """Test that all expected roles exist in security.yaml."""
        from modules.backend.core.config import get_app_config

        roles = get_app_config().security.roles
        assert "viewer" in roles
        assert "user" in roles
        assert "admin" in roles

    def test_check_role_level(self):
        """Test check_role_level compares roles using config levels."""
        from modules.backend.core.security import check_role_level

        mock_app_config = MagicMock()
        mock_app_config.security.roles = {
            "viewer": MagicMock(level=1),
            "user": MagicMock(level=2),
            "admin": MagicMock(level=3),
        }

        with patch(
            "modules.backend.core.security.get_app_config",
            return_value=mock_app_config,
        ):
            assert check_role_level("admin", "viewer") is True
            assert check_role_level("user", "user") is True
            assert check_role_level("viewer", "admin") is False
