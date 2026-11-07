"""Integration tests for CatalogYamlSyncService: real database, real files.

Edit cases run against a temporary project root. The seed round trip runs
against the repository's own agent YAML, to prove the sync fields are the exact
inverse of what the seeder writes.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.config import get_app_config
from modules.backend.core.exceptions import ValidationError
from modules.backend.schemas.agent_config import AgentModelSchema
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.catalog_seeder import seed_catalog
from modules.backend.services.catalog_yaml_sync import CatalogYamlSyncService

AGENT = "test.sync.agent"

# Defaults come from the schemas and config the sync reads, so no value is repeated here.
DEFAULT_TIMEOUT = get_app_config().application.timeouts.agent_task
SLOW_TIMEOUT = DEFAULT_TIMEOUT * 5
DEFAULT_TEMPERATURE = AgentModelSchema.model_fields["temperature"].default
DEFAULT_MAX_TOKENS = AgentModelSchema.model_fields["max_tokens"].default


def _model(name: str) -> dict:
    return {"name": name, "temperature": DEFAULT_TEMPERATURE, "max_tokens": DEFAULT_MAX_TOKENS}


SAMPLE = """\
# Header comment
agent_name: test.sync.agent
agent_type: vertical
description: "A test agent"
enabled: true
model: "foundry:gpt-5-mini"
max_input_length: 1000
max_budget_usd: 0.10

execution:
  mode: local

keywords:
  - alpha  # first
  - beta
tools:
  - system.get_app_info
scope:
  read:
    - docs/
  write: []
"""


@pytest.fixture
def agent_file(tmp_path: Path, monkeypatch) -> Path:
    """A temporary project root holding SAMPLE as the YAML of ``test.sync.agent``."""
    path = tmp_path / "config" / "agents" / "test" / "sync" / "agent.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(
        "modules.backend.services.catalog_yaml_sync.find_project_root", lambda: tmp_path
    )
    return path


async def _add_agent(db: AsyncSession, **overrides) -> None:
    fields = dict(
        agent_name=AGENT,
        agent_type="vertical",
        description="A test agent",
        model_config_json=_model("foundry:gpt-5-mini"),
        keywords=["alpha", "beta"],
        tools=["system.get_app_info"],
        scope={"read": ["docs/"], "write": []},
        constraints={"timeout_seconds": DEFAULT_TIMEOUT},
        max_input_length=1000,
        max_budget_usd=0.1,
        execution_mode="local",
    )
    fields.update(overrides)
    await AgentCatalogService(db).create_entry(**fields)


class TestPlan:
    async def test_a_catalog_row_that_matches_its_file_is_in_sync(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(db_session)

        plan = await CatalogYamlSyncService(db_session).plan(agent_name=AGENT)

        assert plan.report.clean
        assert plan.report.in_sync == 1
        assert plan.writes == {}

    async def test_a_changed_model_is_reported_with_both_values(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(
            db_session,
            model_config_json=_model("foundry:claude-opus-5-5"),
        )

        plan = await CatalogYamlSyncService(db_session).plan(agent_name=AGENT)

        (drift,) = plan.report.drifted
        assert drift.agent_name == AGENT
        assert drift.path == "config/agents/test/sync/agent.yaml"
        (change,) = drift.changes
        assert (change.field, change.yaml_value, change.database_value) == (
            "model.name",
            "foundry:gpt-5-mini",
            "foundry:claude-opus-5-5",
        )

    async def test_planning_writes_nothing(self, db_session: AsyncSession, agent_file: Path):
        await _add_agent(db_session, enabled=False)

        await CatalogYamlSyncService(db_session).plan(agent_name=AGENT)

        assert agent_file.read_text(encoding="utf-8") == SAMPLE

    async def test_an_agent_with_no_yaml_file_is_listed_not_failed(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(db_session, agent_name="test.api_created.agent")

        plan = await CatalogYamlSyncService(db_session).plan(agent_name="test.api_created.agent")

        assert plan.report.database_only == ["test.api_created.agent"]
        assert plan.report.clean

    async def test_an_agent_that_is_not_in_the_catalog_is_refused(
        self, db_session: AsyncSession, agent_file: Path
    ):
        with pytest.raises(ValidationError, match="not in the catalog"):
            await CatalogYamlSyncService(db_session).plan(agent_name="no.such.agent")

    async def test_a_change_that_would_invalidate_the_file_is_refused(
        self, db_session: AsyncSession, agent_file: Path
    ):
        # The schema rejects a CLI engine that declares output fields.
        await _add_agent(
            db_session,
            engine="claude_code",
            interface={"input": {"q": "str"}, "output": {"a": "str"}},
        )

        plan = await CatalogYamlSyncService(db_session).plan(agent_name=AGENT)

        (failure,) = plan.report.failures
        assert failure.agent_name == AGENT
        assert "would not validate" in failure.reason
        assert plan.writes == {}
        assert not plan.report.clean

    async def test_a_file_that_does_not_round_trip_is_refused(
        self, db_session: AsyncSession, agent_file: Path
    ):
        agent_file.write_text(SAMPLE.replace("enabled: true", "enabled:   true"), encoding="utf-8")
        await _add_agent(db_session, description="Renamed")

        plan = await CatalogYamlSyncService(db_session).plan(agent_name=AGENT)

        (failure,) = plan.report.failures
        assert "formatting would not be preserved" in failure.reason
        assert plan.writes == {}


class TestApply:
    async def test_the_file_gets_the_catalog_value_and_keeps_its_comments(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(
            db_session,
            description="Renamed",
            tools=["system.get_app_info", "system.check_services"],
        )
        service = CatalogYamlSyncService(db_session)

        CatalogYamlSyncService.apply(await service.plan(agent_name=AGENT))

        expected = SAMPLE.replace('"A test agent"', '"Renamed"').replace(
            "  - system.get_app_info\n",
            "  - system.get_app_info\n  - system.check_services\n",
        )
        assert agent_file.read_text(encoding="utf-8") == expected

    async def test_a_second_sync_finds_nothing_to_do(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(
            db_session, chat_enabled=True, constraints={"timeout_seconds": SLOW_TIMEOUT}
        )
        service = CatalogYamlSyncService(db_session)

        CatalogYamlSyncService.apply(await service.plan(agent_name=AGENT))
        again = await service.plan(agent_name=AGENT)

        assert again.report.clean
        assert again.writes == {}

    async def test_no_temporary_file_is_left_behind(
        self, db_session: AsyncSession, agent_file: Path
    ):
        await _add_agent(db_session, description="Renamed")
        service = CatalogYamlSyncService(db_session)

        CatalogYamlSyncService.apply(await service.plan(agent_name=AGENT))

        assert sorted(p.name for p in agent_file.parent.iterdir()) == ["agent.yaml"]


class TestSeedRoundTrip:
    async def test_seeding_the_repository_yaml_leaves_no_drift(self, db_session: AsyncSession):
        counts = await seed_catalog(AgentCatalogService(db_session), force=True)
        assert counts["seeded"] > 0
        assert counts["errors"] == 0

        report = (await CatalogYamlSyncService(db_session).plan()).report

        assert report.drifted == []
        assert report.failures == []
        assert report.yaml_only == []
        assert report.in_sync == counts["seeded"]
