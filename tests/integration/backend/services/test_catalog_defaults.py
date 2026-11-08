"""An agent created with nothing but its identity gets every default from agent_defaults.

Also guards that the ORM columns carry no literal defaults of their own.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core import agent_defaults
from modules.backend.core.agent_registry import _db_row_to_config
from modules.backend.models.agent_catalog import AgentCatalog
from modules.backend.services.agent_catalog import AgentCatalogService


async def _create(db: AsyncSession, **fields):
    return await AgentCatalogService(db).create_entry(
        agent_name="test.defaults.agent",
        agent_type="vertical",
        description="A test agent",
        **fields,
    )


class TestCreateEntryDefaults:
    async def test_every_scalar_default_comes_from_agent_defaults(self, db_session: AsyncSession):
        row = await _create(db_session)

        assert row.version == agent_defaults.version()
        assert row.visibility == agent_defaults.visibility()
        assert row.engine == agent_defaults.engine()
        assert row.invocation_tier == agent_defaults.invocation_tier()
        assert row.execution_mode == agent_defaults.execution_mode()
        assert row.max_input_length == agent_defaults.max_input_length()
        assert row.max_budget_usd == agent_defaults.max_budget_usd()
        assert row.constraints == {
            "timeout_seconds": agent_defaults.task_timeout_seconds(),
            "cost_ceiling_usd": agent_defaults.max_budget_usd(),
            "retry_budget": agent_defaults.retry_budget(),
        }

    async def test_a_zero_budget_is_kept_not_replaced_by_the_default(
        self, db_session: AsyncSession
    ):
        row = await _create(db_session, max_budget_usd=0, max_input_length=1)

        assert row.max_budget_usd == 0
        assert row.max_input_length == 1

    async def test_values_passed_in_are_kept(self, db_session: AsyncSession):
        row = await _create(db_session, version="9.9.9", engine="codex", execution_mode="local")

        assert (row.version, row.engine, row.execution_mode) == ("9.9.9", "codex", "local")


class TestColumnsCarryNoLiteralDefaults:
    @pytest.mark.parametrize(
        "column",
        [
            "version",
            "visibility",
            "engine",
            "invocation_tier",
            "execution_mode",
            "max_input_length",
            "max_budget_usd",
        ],
    )
    def test_the_column_has_no_default_of_its_own(self, column):
        assert AgentCatalog.__table__.c[column].default is None


class TestRowMapping:
    def _row(self, **overrides):
        base = dict(
            agent_name="test.mapping.agent",
            agent_type="vertical",
            description="d",
            enabled=True,
            model_config_json={"name": "foundry:gpt-fixture", "temperature": 0.5},
            keywords=[],
            tools=[],
            max_input_length=1000,
            max_budget_usd=0.5,
            execution_mode="local",
            invocation_tier="user",
            scope={},
            interface=None,
            version="1.0.0",
            chat_enabled=False,
            engine="pydantic_ai",
            system_prompt="",
            visibility="public",
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_a_model_with_a_temperature_but_no_token_limit_gets_the_default_limit(self):
        config = _db_row_to_config(self._row())

        assert config.model.temperature == 0.5
        assert config.model.max_tokens == agent_defaults.max_tokens()

    def test_the_budget_and_input_limit_are_the_rows_own(self):
        config = _db_row_to_config(self._row())

        assert config.max_budget_usd == 0.5
        assert config.max_input_length == 1000
