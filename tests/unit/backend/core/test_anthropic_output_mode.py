"""Structured-output mode on models called over the Anthropic Messages API.

Foundry claude-sonnet-5-5 answers HTTP 400 "tool_choice: type "tool" and "any"
are not supported for this model". PydanticAI's tool output mode sends
tool_choice {"type": "any"}, so models like it are built with prompted output.
These tests run a real AnthropicModel against a mocked SDK client and inspect the
request it would send; nothing goes over the network.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic import AsyncAnthropic
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicJsonSchemaTransformer, AnthropicProvider

from modules.backend.core.model_backends import _anthropic_profile


@pytest.fixture
def allow_mocked_requests():
    """tests/conftest.py blocks model requests; the SDK client here is a mock."""
    with override_allow_model_requests(True):
        yield


class Report(BaseModel):
    ok: bool


def _message(content) -> BetaMessage:
    return BetaMessage(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-fixture",
        content=content,
        stop_reason="end_turn",
        usage=BetaUsage(input_tokens=1, output_tokens=1),
    )


def _model(output_mode: str, reply: BetaMessage) -> tuple[AnthropicModel, AsyncMock]:
    client = MagicMock(spec=AsyncAnthropic)
    create = AsyncMock(return_value=reply)
    client.beta.messages.create = create
    model = AnthropicModel(
        "claude-fixture",
        provider=AnthropicProvider(anthropic_client=client),
        profile=_anthropic_profile("claude-fixture", output_mode),
    )
    return model, create


def _agent(model: AnthropicModel) -> Agent:
    agent = Agent(model, output_type=Report)

    @agent.tool_plain
    def lookup(key: str) -> str:
        """An ordinary function tool, so the request carries tools."""
        return key

    return agent


class TestAnthropicProfile:
    def test_tool_mode_leaves_the_provider_profile_in_place(self):
        assert _anthropic_profile("claude-fixture", "tool") is None

    def test_prompted_mode_pins_the_default_structured_output_mode(self):
        profile = _anthropic_profile("claude-fixture", "prompted")

        assert profile.default_structured_output_mode == "prompted"

    def test_prompted_profile_keeps_the_anthropic_schema_transformer(self):
        profile = _anthropic_profile("claude-fixture", "prompted")

        assert profile.json_schema_transformer is AnthropicJsonSchemaTransformer


@pytest.mark.usefixtures("allow_mocked_requests")
class TestToolChoiceOnTheWire:
    @pytest.mark.asyncio
    async def test_prompted_output_sends_no_forced_tool_choice(self):
        model, create = _model(
            "prompted", _message([BetaTextBlock(type="text", text='{"ok": true}')])
        )

        result = await _agent(model).run("go")

        sent = create.call_args.kwargs
        assert result.output == Report(ok=True)
        assert [tool["name"] for tool in sent["tools"]] == ["lookup"]
        assert sent["tool_choice"] == {"type": "auto"}
        assert "ok" in str(sent["system"])  # the output schema is in the instructions

    @pytest.mark.asyncio
    async def test_tool_output_forces_a_tool_choice(self):
        # The behaviour claude-sonnet-5-5 rejects, kept as the control case.
        model, create = _model(
            "tool",
            _message(
                [
                    BetaToolUseBlock(
                        type="tool_use", id="t1", name="final_result", input={"ok": True}
                    )
                ]
            ),
        )

        result = await _agent(model).run("go")

        assert result.output == Report(ok=True)
        assert create.call_args.kwargs["tool_choice"] == {"type": "any"}
