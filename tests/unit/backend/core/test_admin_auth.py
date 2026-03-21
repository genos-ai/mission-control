"""Tests for admin auth dependency (require_admin, _resolve_role, require_role)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from modules.backend.core.config_schema import RoleSchema
from modules.backend.core.dependencies import _resolve_role, require_admin, require_role

SETTINGS_PATH = "modules.backend.core.config.get_settings"
APP_CONFIG_PATH = "modules.backend.core.config.get_app_config"


class TestResolveRole:
    """Tests for _resolve_role."""

    @patch(SETTINGS_PATH)
    def test_admin_key_match(self, mock_settings):
        mock_settings.return_value = MagicMock(admin_api_key="secret-admin-key")
        assert _resolve_role("secret-admin-key") == "admin"

    @patch(SETTINGS_PATH)
    def test_wrong_key_returns_viewer(self, mock_settings):
        mock_settings.return_value = MagicMock(admin_api_key="secret-admin-key")
        assert _resolve_role("wrong-key") == "viewer"

    @patch(SETTINGS_PATH)
    def test_no_key_returns_viewer(self, mock_settings):
        mock_settings.return_value = MagicMock(admin_api_key="secret-admin-key")
        assert _resolve_role(None) == "viewer"

    @patch(SETTINGS_PATH)
    def test_no_admin_key_configured(self, mock_settings):
        mock_settings.return_value = MagicMock(admin_api_key="")
        assert _resolve_role("any-key") == "viewer"

    @patch(SETTINGS_PATH)
    def test_missing_admin_key_attr(self, mock_settings):
        settings = MagicMock(spec=[])
        mock_settings.return_value = settings
        assert _resolve_role("any-key") == "viewer"


def _mock_roles():
    return {
        "viewer": RoleSchema(level=1, description="Read-only"),
        "trader": RoleSchema(level=2, description="Trade"),
        "admin": RoleSchema(level=3, description="Full"),
    }


class TestRequireRole:
    """Tests for require_role factory."""

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_admin_passes_admin_check(self, mock_resolve, mock_config):
        mock_resolve.return_value = "admin"
        mock_config.return_value.security.roles = _mock_roles()

        check = require_role("admin")
        result = await check(api_key="test-key")
        assert result == "admin"

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_viewer_fails_admin_check(self, mock_resolve, mock_config):
        mock_resolve.return_value = "viewer"
        mock_config.return_value.security.roles = _mock_roles()

        check = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await check(api_key="test-key")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_trader_passes_trader_check(self, mock_resolve, mock_config):
        mock_resolve.return_value = "trader"
        mock_config.return_value.security.roles = _mock_roles()

        check = require_role("trader")
        result = await check(api_key="test-key")
        assert result == "trader"

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_admin_passes_lower_level_check(self, mock_resolve, mock_config):
        mock_resolve.return_value = "admin"
        mock_config.return_value.security.roles = _mock_roles()

        check = require_role("viewer")
        result = await check(api_key="test-key")
        assert result == "admin"

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_unknown_required_role_raises_500(self, mock_resolve, mock_config):
        mock_resolve.return_value = "admin"
        mock_config.return_value.security.roles = _mock_roles()

        check = require_role("superadmin")
        with pytest.raises(HTTPException) as exc_info:
            await check(api_key="test-key")
        assert exc_info.value.status_code == 500


class TestRequireAdmin:
    """Tests for the concrete require_admin dependency."""

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_admin_passes(self, mock_resolve, mock_config):
        mock_resolve.return_value = "admin"
        mock_config.return_value.security.roles = _mock_roles()

        result = await require_admin(api_key="test-key")
        assert result == "admin"

    @pytest.mark.asyncio
    @patch(APP_CONFIG_PATH)
    @patch("modules.backend.core.dependencies._resolve_role")
    async def test_viewer_denied(self, mock_resolve, mock_config):
        mock_resolve.return_value = "viewer"
        mock_config.return_value.security.roles = _mock_roles()

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(api_key="test-key")
        assert exc_info.value.status_code == 403
