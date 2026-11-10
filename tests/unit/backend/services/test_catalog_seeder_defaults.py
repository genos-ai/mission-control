"""The seeder takes its model defaults from the schema, not from literals of its own."""

from modules.backend.schemas.agent_config import AgentModelSchema
from modules.backend.services.catalog_seeder import _extract_model_config

DEFAULTS = AgentModelSchema(name="x:y")


def test_a_flat_model_string_gets_the_schema_defaults():
    assert _extract_model_config("provider:model") == {
        "name": "provider:model",
        "temperature": DEFAULTS.temperature,
        "max_tokens": DEFAULTS.max_tokens,
        "betas": DEFAULTS.betas,
    }


def test_a_model_block_keeps_its_own_values():
    block = AgentModelSchema(name="provider:model", temperature=0.7, max_tokens=123)

    assert _extract_model_config(block) == {
        "name": "provider:model",
        "temperature": 0.7,
        "max_tokens": 123,
        "betas": DEFAULTS.betas,
    }


def test_every_schema_field_that_is_set_is_stored():
    block = AgentModelSchema(name="provider:model", output_mode="prompted", betas=["b"])

    stored = _extract_model_config(block)

    assert set(stored) == set(AgentModelSchema.model_fields)
    assert stored["output_mode"] == "prompted"
    assert stored["betas"] == ["b"]
