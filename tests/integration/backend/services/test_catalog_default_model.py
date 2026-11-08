"""An agent created without a model gets the `quick` alias, with the schema's defaults."""

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.model_builder import _resolve_model_alias
from modules.backend.schemas.agent_config import AgentModelSchema
from modules.backend.services.agent_catalog import AgentCatalogService

DEFAULTS = AgentModelSchema(name="x:y")


async def test_an_agent_created_without_a_model_gets_the_quick_alias(db_session: AsyncSession):
    row = await AgentCatalogService(db_session).create_entry(
        agent_name="test.default_model.agent", agent_type="vertical", description="A test agent"
    )

    assert row.model_config_json == {
        "name": _resolve_model_alias("quick"),
        "temperature": DEFAULTS.temperature,
        "max_tokens": DEFAULTS.max_tokens,
    }


async def test_a_model_passed_in_is_kept_as_given(db_session: AsyncSession):
    given = {"name": "p:m", "temperature": 0.5, "max_tokens": 10}

    row = await AgentCatalogService(db_session).create_entry(
        agent_name="test.default_model.agent",
        agent_type="vertical",
        description="A test agent",
        model_config_json=given,
    )

    assert row.model_config_json == given
