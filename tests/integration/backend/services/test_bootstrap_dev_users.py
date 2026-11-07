"""Dev users have well-known passwords, so they are only ever created in a development setup.

Real database, no mocks. The runtime environment comes from the application config.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.models.user import User
from modules.backend.services.bootstrap import BootstrapService


def _dev_emails() -> set[str]:
    return {acct["email"] for acct in BootstrapService.DEV_USERS}


async def _existing_dev_emails(db: AsyncSession) -> set[str]:
    result = await db.execute(select(User.email).where(User.email.in_(_dev_emails())))
    return set(result.scalars().all())


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    def set_environment(name: str) -> None:
        monkeypatch.setattr(get_app_config().application, "environment", name)

    return set_environment


@pytest.mark.parametrize("name", ["development", "test"])
async def test_dev_users_are_created_in_a_development_setup(
    db_session: AsyncSession, environment, name
):
    environment(name)

    created = await BootstrapService(db_session).ensure_dev_users()

    assert {user.email for user in created} == _dev_emails()
    assert await _existing_dev_emails(db_session) == _dev_emails()


@pytest.mark.parametrize("name", ["production", "staging", "prod", "", "Production"])
async def test_dev_users_are_refused_anywhere_else(db_session: AsyncSession, environment, name):
    """Anything that is not exactly development or test is refused, so a typo fails closed."""
    environment(name)

    with pytest.raises(AuthorizationError, match="dev users"):
        await BootstrapService(db_session).ensure_dev_users()

    assert await _existing_dev_emails(db_session) == set()


async def test_refusal_names_the_environment(db_session: AsyncSession, environment):
    environment("production")

    with pytest.raises(AuthorizationError, match="'production'"):
        await BootstrapService(db_session).ensure_dev_users()
