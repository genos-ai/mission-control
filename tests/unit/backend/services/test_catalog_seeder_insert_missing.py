"""Non-force seed inserts agents missing from the DB and leaves existing rows untouched.

The seeder runs on a temporary project root, so the repository's own agents are
untouched.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.catalog_seeder import seed_catalog

AGENT_YAML = """\
agent_name: {name}
agent_type: vertical
description: "{description}"
enabled: true
model: "foundry:gpt-fixture"
max_input_length: 1000
max_budget_usd: 0.10
execution:
  mode: local
"""


def _write_agent(root: Path, name: str, description: str) -> None:
    path = root / "config" / "agents" / "test" / name.split(".")[1] / "agent.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(AGENT_YAML.format(name=name, description=description), encoding="utf-8")


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch) -> Path:
    _write_agent(tmp_path, "test.existing.agent", "from yaml")
    _write_agent(tmp_path, "test.missing.agent", "new agent")
    monkeypatch.setattr(
        "modules.backend.services.catalog_seeder.find_project_root", lambda: tmp_path
    )
    return tmp_path


async def _create_existing(service: AgentCatalogService) -> None:
    await service.create_entry(
        agent_name="test.existing.agent",
        agent_type="vertical",
        description="edited via admin api",
        model_config_json={"name": "foundry:gpt-edited"},
    )


class TestSeedWithoutForce:
    async def test_inserts_missing_agent_into_non_empty_catalog(
        self, db_session: AsyncSession, project_root: Path
    ):
        service = AgentCatalogService(db_session)
        await _create_existing(service)

        counts = await seed_catalog(service)

        assert counts == {"seeded": 1, "skipped": 1, "errors": 0}
        assert (await service.get_by_name("test.missing.agent")).description == "new agent"

    async def test_leaves_existing_row_untouched(
        self, db_session: AsyncSession, project_root: Path
    ):
        service = AgentCatalogService(db_session)
        await _create_existing(service)

        await seed_catalog(service)

        existing = await service.get_by_name("test.existing.agent")
        assert existing.description == "edited via admin api"
        assert existing.model_config_json["name"] == "foundry:gpt-edited"

    async def test_empty_catalog_gets_every_agent(
        self, db_session: AsyncSession, project_root: Path
    ):
        service = AgentCatalogService(db_session)

        counts = await seed_catalog(service)

        assert counts == {"seeded": 2, "skipped": 0, "errors": 0}

    async def test_second_run_is_a_no_op(self, db_session: AsyncSession, project_root: Path):
        service = AgentCatalogService(db_session)
        await seed_catalog(service)

        counts = await seed_catalog(service)

        assert counts == {"seeded": 0, "skipped": 2, "errors": 0}


class TestSeedWithForce:
    async def test_force_updates_existing_row_from_yaml(
        self, db_session: AsyncSession, project_root: Path
    ):
        service = AgentCatalogService(db_session)
        await _create_existing(service)

        counts = await seed_catalog(service, force=True)

        assert counts == {"seeded": 2, "skipped": 0, "errors": 0}
        assert (await service.get_by_name("test.existing.agent")).description == "from yaml"
