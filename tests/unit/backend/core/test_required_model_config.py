"""Model names in config are required, never assumed.

A missing key must fail at load with its name, not fall back to a model that may not
be reachable.
"""

import pytest
from pydantic import ValidationError

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import CostSchema, ModelsSchema


class TestCostSchema:
    def test_the_downgrade_model_is_required(self):
        with pytest.raises(ValidationError, match="emergency_downgrade_model"):
            CostSchema()

    def test_a_configured_downgrade_model_is_kept(self):
        assert CostSchema(emergency_downgrade_model="p:m").emergency_downgrade_model == "p:m"


class TestModelsSchema:
    def test_the_aliases_are_required(self):
        with pytest.raises(ValidationError, match="aliases"):
            ModelsSchema()

    def test_an_empty_alias_table_is_accepted(self):
        assert ModelsSchema(aliases={}).aliases == {}


class TestShippedConfig:
    def test_every_configured_model_name_is_in_the_registry(self):
        from modules.backend.core.model_builder import (
            _resolve_model_alias,
            resolve_model,
        )

        config = get_app_config()
        configured = [
            *config.models.aliases.values(),
            config.gate.ai.model,
            config.cost.emergency_downgrade_model,
        ]

        for name in configured:
            assert resolve_model(_resolve_model_alias(name))
