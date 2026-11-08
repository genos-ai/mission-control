"""Visibility through the seeder and create_entry, against the real test database.

The seeder runs on a temporary project root, so the repository's own agents are
untouched.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.schemas.agent_config import AgentConfigSchema
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.catalog_seeder import seed_catalog

DEFAULT = AgentConfigSchema.model_fields["visibility"].default

AGENT_YAML = """\
agent_name: {name}
agent_type: {agent_type}
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
def agents(tmp_path: Path, monkeypatch) -> Path:
    """Three agents: one declares system, one declares nothing, one is typed `system`."""
    for name, agent_type, extra in [
        ("test.vis.restricted", "vertical", "visibility: system"),
        ("test.vis.plain", "vertical", ""),
        ("test.vis.typed", "system", ""),
    ]:
        path = tmp_path / "config" / "agents" / "test" / name.split(".")[2] / "agent.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            AGENT_YAML.format(name=name, agent_type=agent_type, extra=extra), encoding="utf-8"
        )
    monkeypatch.setattr(
        "modules.backend.services.catalog_seeder.find_project_root", lambda: tmp_path
    )
    return tmp_path


class TestSeeder:
    async def test_an_agent_that_declares_system_is_seeded_as_system(
        self, db_session: AsyncSession, agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        assert (await service.get_by_name("test.vis.restricted")).visibility == "system"

    async def test_an_agent_that_declares_nothing_is_seeded_with_the_default(
        self, db_session: AsyncSession, agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        assert (await service.get_by_name("test.vis.plain")).visibility == DEFAULT

    async def test_an_agent_typed_system_is_not_made_system_by_its_type(
        self, db_session: AsyncSession, agents: Path
    ):
        service = AgentCatalogService(db_session)
        await seed_catalog(service, force=True)

        assert (await service.get_by_name("test.vis.typed")).visibility == DEFAULT


class TestCreateEntry:
    async def test_an_agent_created_without_visibility_gets_the_default(
        self, db_session: AsyncSession
    ):
        row = await AgentCatalogService(db_session).create_entry(
            agent_name="test.created.agent", agent_type="vertical", description="A test agent"
        )

        assert row.visibility == DEFAULT

    async def test_visibility_passed_in_is_kept(self, db_session: AsyncSession):
        row = await AgentCatalogService(db_session).create_entry(
            agent_name="test.created.agent",
            agent_type="vertical",
            description="A test agent",
            visibility="system",
        )

        assert row.visibility == "system"
