"""Retry budget through the seeder and create_entry, against the real test database.

The seeder runs on a temporary project root holding two agent files, so the real
repository agents are untouched.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config, get_mission_control_config
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.catalog_seeder import seed_catalog

DEFAULT_RETRIES = get_mission_control_config().dispatch.default_retry_budget
DEFAULT_TIMEOUT = get_app_config().application.timeouts.agent_task

AGENT_YAML = """\
agent_name: {name}
agent_type: vertical
description: "A test agent"
enabled: true
model: "foundry:gpt-fixture"
max_input_length: 1000
max_budget_usd: 0.10
{extra}
execution:
  mode: local
"""


@pytest.fixture
def two_agents(tmp_path: Path, monkeypatch) -> Path:
    """A temporary project root with one agent that sets retry_budget and one that does not."""
    for name, extra in [
        ("test.retry.explicit", f"retry_budget: {DEFAULT_RETRIES + 4}"),
        ("test.retry.implicit", ""),
    ]:
        path = tmp_path / "config" / "agents" / "test" / name.split(".")[2] / "agent.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(AGENT_YAML.format(name=name, extra=extra), encoding="utf-8")
    monkeypatch.setattr(
        "modules.backend.services.catalog_seeder.find_project_root", lambda: tmp_path
    )
    return tmp_path


class TestSeeder:
    async def test_an_agent_that_sets_a_retry_budget_keeps_it(
        self, db_session: AsyncSession, two_agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        row = await service.get_by_name("test.retry.explicit")

        assert row.constraints["retry_budget"] == DEFAULT_RETRIES + 4

    async def test_an_agent_that_sets_none_gets_the_config_default(
        self, db_session: AsyncSession, two_agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        row = await service.get_by_name("test.retry.implicit")

        assert row.constraints["retry_budget"] == DEFAULT_RETRIES

    async def test_a_seeded_agent_with_no_timeout_gets_the_configured_task_timeout(
        self, db_session: AsyncSession, two_agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        row = await service.get_by_name("test.retry.implicit")

        assert row.constraints["timeout_seconds"] == DEFAULT_TIMEOUT


class TestCreateEntry:
    async def test_an_agent_created_without_constraints_gets_the_configured_defaults(
        self, db_session: AsyncSession
    ):
        service = AgentCatalogService(db_session)

        row = await service.create_entry(
            agent_name="test.created.agent", agent_type="vertical", description="A test agent"
        )

        assert row.constraints["retry_budget"] == DEFAULT_RETRIES
        assert row.constraints["timeout_seconds"] == DEFAULT_TIMEOUT

    async def test_constraints_passed_in_are_kept_as_given(self, db_session: AsyncSession):
        service = AgentCatalogService(db_session)

        row = await service.create_entry(
            agent_name="test.created.agent",
            agent_type="vertical",
            description="A test agent",
            constraints={"retry_budget": DEFAULT_RETRIES + 2},
        )

        assert row.constraints == {"retry_budget": DEFAULT_RETRIES + 2}
