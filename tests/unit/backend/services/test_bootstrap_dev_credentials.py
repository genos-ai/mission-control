"""The startup banner shows the credentials the dev user seed creates, read from one place."""

import pytest

from modules.backend.services.bootstrap import BootstrapService
from modules.clients.service_manager.preflight import dev_login_line


@pytest.mark.parametrize("acct", BootstrapService.DEV_USERS, ids=lambda a: a["system_role"])
def test_dev_credentials_are_the_seeded_ones(acct):
    assert BootstrapService.dev_credentials(acct["system_role"]) == (
        acct["email"],
        acct["password"],
    )


def test_unknown_role_is_refused():
    with pytest.raises(ValueError, match="No dev user is seeded"):
        BootstrapService.dev_credentials("nobody")


def test_banner_line_shows_the_seeded_admin_login():
    admin = next(a for a in BootstrapService.DEV_USERS if a["system_role"] == "admin")

    assert dev_login_line().strip() == f"Login:          {admin['email']} / {admin['password']}"
