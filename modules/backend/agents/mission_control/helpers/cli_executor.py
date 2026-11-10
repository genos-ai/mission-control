"""CLI agent executor — dispatches tasks to CLI coding agents.

Counterpart to agent_executor.py which handles PydanticAI in-process agents.
The engine function runs the agent, passes the system prompt and task
instructions, and returns the agent's output as a dict matching the _meta
structure expected by retry_handler.py.

Only ``claude_code`` exists, read-only. ``codex`` and ``copilot`` were deleted
because they write regardless of ``scope.write`` (Plan 88 contracts 3.8.5);
the repair-loop plan restores CLI engines inside the container (3.8.7).
"""

from __future__ import annotations

import json
import os
from typing import Any

from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.core.exceptions import ExecutionEnvironmentError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Read-only tool set for claude_code until CLI engines run inside the
# container (Plan 88 contracts 3.8.5 and 3.8.7).
CLAUDE_CODE_READ_TOOLS: list[str] = ["Read", "Grep", "Glob"]


def _make_emitter(
    event_bus: EventBusProtocol | None,
    session_id: str | None,
    agent_name: str,
):
    """Return an async callable that publishes events when bus and session_id are set."""
    if not event_bus or not session_id:

        async def _noop(**_kwargs: Any) -> None:
            pass

        return _noop

    from modules.backend.events.types import (
        AgentResponseChunkEvent,
        AgentToolCallEvent,
        AgentToolResultEvent,
    )

    async def _emit(kind: str, **kwargs: Any) -> None:
        try:
            if kind == "chunk":
                event = AgentResponseChunkEvent(
                    session_id=session_id,
                    source="cli_executor",
                    agent_id=agent_name,
                    content=kwargs["content"],
                )
            elif kind == "tool_call":
                event = AgentToolCallEvent(
                    session_id=session_id,
                    source="cli_executor",
                    agent_id=agent_name,
                    tool_name=kwargs["tool_name"],
                    tool_args=kwargs.get("tool_args", {}),
                    tool_call_id=kwargs["tool_call_id"],
                )
            elif kind == "tool_result":
                event = AgentToolResultEvent(
                    session_id=session_id,
                    source="cli_executor",
                    agent_id=agent_name,
                    tool_name=kwargs["tool_name"],
                    tool_call_id=kwargs["tool_call_id"],
                    result=kwargs.get("result"),
                    status="error" if kwargs.get("is_error") else "success",
                )
            else:
                return
            await event_bus.publish(event)
        except Exception:
            logger.debug("CLI event emission failed", extra={"kind": kind, "agent": agent_name})

    return _emit


def _cli_result_from_sdk(output: str, result_msg: Any | None) -> dict:
    """Build _cli_result dict, pulling real usage from ResultMessage if available."""
    if result_msg is None:
        return _cli_result(output)

    cost_usd = result_msg.total_cost_usd or 0.0
    usage = result_msg.usage or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)

    return {
        "output": output,
        "_meta": {
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": 0,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
    }


def _cli_result(output: str) -> dict:
    """Normalize CLI executor output to match PydanticAI agent return structure."""
    return {
        "output": output,
        "_meta": {
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
        },
    }


def _compose_user_message(instructions: str, inputs: dict) -> str:
    """Build the user message from task instructions and inputs."""
    message = instructions
    if inputs:
        message += f"\n\nInputs:\n```json\n{json.dumps(inputs, indent=2)}\n```"
    return message


async def execute_claude_code(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    environment_handle: Any | None,
    effort: str | None = None,
    max_turns: int = 50,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
    scope_read: list[str] | None = None,
    scope_write: list[str] | None = None,
) -> dict:
    """Execute a task via Claude Code Agent SDK, read-only, in the handle's worktree.

    The session runs on the worker host, so a worktree sets its working
    directory but does not contain it. Until CLI engines run inside the
    container (contracts 3.8.7) it fails closed (contracts 3.8.5): a non-empty
    ``scope_write``, a ``None`` handle or a handle without ``host_working_dir``
    raises ``ExecutionEnvironmentError``. It gets only read tools and loads no
    settings or hooks from the target repository (``setting_sources=[]``).
    """
    if scope_write:
        raise ExecutionEnvironmentError(
            f"agent '{agent_name}': claude_code cannot write until CLI engines run "
            "inside the container (contracts 3.8.7)"
        )
    if environment_handle is None or environment_handle.host_working_dir is None:
        raise ExecutionEnvironmentError(
            f"agent '{agent_name}': claude_code needs an environment handle with a host worktree"
        )
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
        from claude_agent_sdk.types import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
        )
    except ImportError:
        raise ImportError(
            "claude-agent-sdk is required for engine='claude_code'. "
            "Install with: pip install claude-agent-sdk"
        )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=str(environment_handle.host_working_dir),
        max_turns=max_turns,
        tools=list(CLAUDE_CODE_READ_TOOLS),
        allowed_tools=list(CLAUDE_CODE_READ_TOOLS),
        setting_sources=[],
    )

    if effort:
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = effort

    user_message = _compose_user_message(instructions, inputs)
    response_parts: list[str] = []
    # Maps tool_use_id → tool_name so ToolResultBlock events carry a readable name.
    pending_tool_calls: dict[str, str] = {}
    result_msg: ResultMessage | None = None

    _emit = _make_emitter(event_bus, session_id, agent_name)

    try:
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
                        await _emit("chunk", content=block.text)
                    elif isinstance(block, ToolUseBlock):
                        pending_tool_calls[block.id] = block.name
                        await _emit(
                            "tool_call",
                            tool_name=block.name,
                            tool_args=block.input,
                            tool_call_id=block.id,
                        )
                    elif isinstance(block, ToolResultBlock):
                        tool_name = pending_tool_calls.pop(block.tool_use_id, block.tool_use_id)
                        result_content = (
                            block.content if isinstance(block.content, str) else str(block.content)
                        )
                        await _emit(
                            "tool_result",
                            tool_name=tool_name,
                            tool_call_id=block.tool_use_id,
                            result=result_content,
                            is_error=bool(block.is_error),
                        )
            elif isinstance(message, ResultMessage):
                result_msg = message
    finally:
        os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)

    output = "\n".join(response_parts)
    return _cli_result_from_sdk(output, result_msg)
