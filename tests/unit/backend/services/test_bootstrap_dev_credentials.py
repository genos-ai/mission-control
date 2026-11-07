"""The seeded dev credentials come from config/.env, and the banner shows what the seed creates."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.backend.core.exceptions import ValidationError
from modules.backend.services.bootstrap import BootstrapService
from modules.clients.service_manager.preflight import dev_login_line

SETTINGS = SimpleNamespace(
    dev_sysadmin_password="sysadmin-from-env",
    dev_admin_password="admin-from-env",
    dev_user_password="user-from-env",
)


@pytest.fixture
def settings():
    with patch("modules.backend.services.bootstrap.get_settings", return_value=SETTINGS):
        yield SETTINGS


@pytest.mark.parametrize("acct", BootstrapService.DEV_USERS, ids=lambda a: a["system_role"])
def test_dev_credentials_come_from_the_settings(settings, acct):
    assert BootstrapService.dev_credentials(acct["system_role"]) == (
        acct["email"],
        getattr(settings, acct["password_setting"]),
    )


def test_no_password_is_held_in_code():
    assert all("password" not in acct for acct in BootstrapService.DEV_USERS)


def test_unknown_role_is_refused(settings):
    with pytest.raises(ValueError, match="No dev user is seeded"):
        BootstrapService.dev_credentials("nobody")


def test_a_missing_password_is_refused_and_names_the_variable():
    unset = SimpleNamespace(**{**vars(SETTINGS), "dev_admin_password": ""})

    with patch("modules.backend.services.bootstrap.get_settings", return_value=unset):
        with pytest.raises(ValidationError, match="DEV_ADMIN_PASSWORD is not set"):
            BootstrapService.dev_credentials("admin")


def test_banner_line_shows_the_configured_admin_login(settings):
    assert dev_login_line().strip() == ("Login:          admin@missioncontrol.dev / admin-from-env")


def test_banner_line_says_so_when_the_password_is_not_configured():
    unset = SimpleNamespace(**{**vars(SETTINGS), "dev_admin_password": ""})

    with patch("modules.backend.services.bootstrap.get_settings", return_value=unset):
        line = dev_login_line()

    assert "not available" in line and "DEV_ADMIN_PASSWORD" in line
