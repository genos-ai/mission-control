"""
Unit tests for CLI agent executor (Plan 55 Phase A).

Tests the cli_executor helper functions and engine routing logic
in agent_executor.py.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai import UsageLimits

from modules.backend.agents.mission_control.helpers.cli_executor import (
    _cli_result,
    _compose_user_message,
)

# =============================================================================
# _cli_result
# =============================================================================


class TestCliResult:
    """Tests for the _cli_result() normalizer."""

    def test_returns_output_key(self):
        result = _cli_result("Hello world")
        assert result["output"] == "Hello world"

    def test_returns_meta_key(self):
        result = _cli_result("test")
        assert "_meta" in result

    def test_meta_cost_usd_zero(self):
        result = _cli_result("test")
        assert result["_meta"]["cost_usd"] == 0.0

    def test_meta_has_all_token_fields(self):
        result = _cli_result("test")
        meta = result["_meta"]
        assert meta["input_tokens"] == 0
        assert meta["output_tokens"] == 0
        assert meta["thinking_tokens"] == 0

    def test_empty_output(self):
        result = _cli_result("")
        assert result["output"] == ""
        assert result["_meta"]["cost_usd"] == 0.0

    def test_multiline_output(self):
        text = "line1\nline2\nline3"
        result = _cli_result(text)
        assert result["output"] == text


# =============================================================================
# _compose_user_message
# =============================================================================


class TestComposeUserMessage:
    """Tests for _compose_user_message()."""

    def test_instructions_only(self):
        msg = _compose_user_message("Do the thing", {})
        assert msg == "Do the thing"

    def test_with_empty_inputs(self):
        msg = _compose_user_message("Do the thing", {})
        assert "Inputs" not in msg

    def test_with_inputs(self):
        inputs = {"file": "main.py", "action": "review"}
        msg = _compose_user_message("Review code", inputs)
        assert "Review code" in msg
        assert "Inputs:" in msg
        assert "```json" in msg
        assert '"file": "main.py"' in msg
        assert '"action": "review"' in msg

    def test_inputs_are_valid_json(self):
        inputs = {"key": "value", "count": 42}
        msg = _compose_user_message("task", inputs)
        # Extract JSON from the message
        json_start = msg.index("```json\n") + len("```json\n")
        json_end = msg.index("\n```", json_start)
        parsed = json.loads(msg[json_start:json_end])
        assert parsed == inputs

    def test_no_inputs_returns_raw_instructions(self):
        msg = _compose_user_message("Just instructions", {})
        assert msg == "Just instructions"


# =============================================================================
# Engine routing in agent_executor
# =============================================================================


def _make_fake_agent_config(engine: str = "pydantic_ai", effort: str | None = None):
    """Build a minimal AgentConfigSchema-like object for mocking."""
    config = MagicMock()
    config.engine = engine
    config.effort = effort
    config.model = "anthropic:claude-haiku-4-5"
    config.invocation.tier = "user"
    config.scope.read = ["src/"]
    config.scope.write = []
    config.agent_name = "test.dummy.agent"
    config.tools = []
    config.cache_ttl = None
    config.thinking_budget = None
    config.max_tokens = 4096
    config.produces_artifact = False
    config.artifact_type = None
    config.agent_type = "user"
    return config


def _make_fake_handle():
    """A fake environment handle with a host worktree (Plan 88 contracts 3.8.5)."""
    handle = MagicMock()
    handle.host_working_dir = Path("/tmp/worktrees/test/workspace")
    handle.working_dir = Path("/workspace")
    return handle


class TestEngineRoutingClaudeCode:
    """Verify that engine='claude_code' routes to the CLI executor."""

    async def test_claude_code_engine_calls_execute_claude_code(self):
        """When agent config has engine='claude_code', execute_claude_code is called."""
        fake_config = _make_fake_agent_config(engine="claude_code", effort="high")
        fake_result = {
            "output": "CLI agent output",
            "_meta": {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
        }

        event_bus = AsyncMock()
        event_bus.publish = AsyncMock()

        with (
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor.get_registry"
            ) as mock_registry,
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor._import_agent_module"
            ),
            patch("modules.backend.agents.mission_control.helpers.agent_executor._build_model"),
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor._build_agent_deps"
            ),
            patch(
                "modules.backend.agents.mission_control.helpers.cli_executor.execute_claude_code",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_execute,
            patch(
                "modules.backend.agents.mission_control.helpers.prompt_builder"
                ".load_agent_system_prompt",
                return_value="You are a test agent.",
            ),
        ):
            mock_registry.return_value.get.return_value = fake_config

            from modules.backend.agents.mission_control.helpers.agent_executor import (
                _make_agent_executor,
            )

            execute_agent = _make_agent_executor(
                event_bus,
                session_id="test-session",
                mission_id="test-mission",
                environment_handle=_make_fake_handle(),
            )

            result = await execute_agent(
                agent_name="test.dummy.agent",
                instructions="Do something",
                inputs={"key": "value"},
                usage_limits=UsageLimits(request_limit=10),
            )

            mock_execute.assert_called_once()
            call_kwargs = mock_execute.call_args
            assert call_kwargs.kwargs["agent_name"] == "test.dummy.agent"
            assert result["output"] == "CLI agent output"
            assert result["_meta"]["cost_usd"] == 0.0


class TestEngineRoutingPydanticAI:
    """Verify that engine='pydantic_ai' (default) uses the PydanticAI path."""

    async def test_pydantic_ai_engine_imports_agent_module(self):
        """When engine='pydantic_ai', the code imports the agent module and streams."""
        fake_config = _make_fake_agent_config(engine="pydantic_ai")

        event_bus = AsyncMock()
        event_bus.publish = AsyncMock()

        with (
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor.get_registry"
            ) as mock_registry,
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor._import_agent_module"
            ) as mock_import,
            patch("modules.backend.agents.mission_control.helpers.agent_executor._build_model"),
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor._build_agent_deps"
            ) as mock_build_deps,
            patch(
                "modules.backend.agents.mission_control.helpers.cli_executor.execute_claude_code",
                new_callable=AsyncMock,
            ) as mock_cli,
            patch(
                "modules.backend.agents.mission_control.helpers.agent_executor.record_llm_call",
                new_callable=AsyncMock,
            ),
        ):
            mock_registry.return_value.get.return_value = fake_config

            # Set up the PydanticAI agent mock
            mock_agent = MagicMock()
            mock_stream = AsyncMock()
            mock_stream.stream_text = MagicMock(return_value=AsyncIterHelper([]))
            mock_stream.get_output = AsyncMock(return_value={"result": "done"})
            mock_stream.usage = MagicMock(
                return_value=MagicMock(
                    input_tokens=10,
                    output_tokens=5,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    details={},
                )
            )
            # The executor reads message history off the stream synchronously:
            # _emit_tool_events() calls new_messages(), trace_and_emit() calls
            # all_messages(). AsyncMock would return coroutines here.
            mock_stream.new_messages = MagicMock(return_value=[])
            mock_stream.all_messages = MagicMock(return_value=[])

            # Mock run_stream context manager
            mock_agent.run_stream = MagicMock(return_value=AsyncContextHelper(mock_stream))
            mock_import.return_value.create_agent.return_value = mock_agent
            mock_build_deps.return_value = MagicMock(spec=[])

            from modules.backend.agents.mission_control.helpers.agent_executor import (
                _make_agent_executor,
            )

            execute_agent = _make_agent_executor(
                event_bus,
                session_id="test-session",
                mission_id="test-mission",
                environment_handle=_make_fake_handle(),
            )

            result = await execute_agent(
                agent_name="test.dummy.agent",
                instructions="Do PydanticAI work",
                inputs={},
                usage_limits=UsageLimits(request_limit=10),
            )

            # CLI executor should NOT have been called
            mock_cli.assert_not_called()
            # PydanticAI path should have imported the module
            mock_import.assert_called_once_with("test.dummy.agent")
            assert "_meta" in result


# =============================================================================
# Async helper stubs
# =============================================================================


class AsyncIterHelper:
    """Async iterator helper for mocking stream_text()."""

    def __init__(self, items):
        self._items = items
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        val = self._items[self._idx]
        self._idx += 1
        return val


class AsyncContextHelper:
    """Async context manager helper for mocking run_stream()."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass
