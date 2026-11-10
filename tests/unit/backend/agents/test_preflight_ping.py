"""The model ping asks for structured output, so a model that rejects its output mode fails it.

A plain-text ping passed on Foundry claude-sonnet-5-5 while every agent with an
output type failed with HTTP 400 on the forced tool choice. No network: the
model is replaced with PydanticAI's TestModel or FunctionModel.
"""

import pytest
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from modules.backend.agents import preflight

REJECTION = (
    "status_code: 400, body: {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'tool_choice: type \"tool\" and \"any\" are not supported for this model.'}}"
)


@pytest.fixture
def built(monkeypatch):
    """Make _build_model return whatever model the test puts in the list."""
    models: list = []
    monkeypatch.setattr(preflight, "_build_model", lambda name: models[0])
    return models


class TestPingModel:
    @pytest.mark.asyncio
    async def test_the_ping_requests_structured_output(self, built):
        model = TestModel()
        built.append(model)

        check = await preflight._ping_model("foundry:fixture")

        assert check.ok
        params = model.last_model_request_parameters
        assert [tool.name for tool in params.output_tools] == ["final_result"]
        assert params.allow_text_output is False  # tool mode: the choice is forced

    @pytest.mark.asyncio
    async def test_a_forced_tool_choice_rejection_is_named_with_the_fix(self, built):
        def reject(messages, info: AgentInfo):
            raise RuntimeError(REJECTION)

        built.append(FunctionModel(reject))

        check = await preflight._ping_model("foundry:fixture")

        assert not check.ok
        assert check.error_type == "forced_tool_choice_unsupported"
        assert "output_mode: prompted" in check.error


class TestClassifyPingError:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Your credit balance is too low", "insufficient_credits"),
            (REJECTION, "forced_tool_choice_unsupported"),
            ("connection reset", "error"),
        ],
    )
    def test_classification(self, message, expected):
        assert preflight.classify_ping_error(message) == expected
