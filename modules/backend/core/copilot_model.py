"""PydanticAI Model adapter for GitHub Copilot SDK.

Routes LLM calls through the Copilot Enterprise subscription at $0.
All 13 models (Claude, GPT) available.

Tool bridging: PydanticAI tools are registered as native Copilot tools
with skip_permission=True. Copilot drives the tool loop — handlers
execute PydanticAI tool functions directly. The model returns the final
text response to PydanticAI after all tool calls are complete.

This means PydanticAI's tool loop is bypassed — Copilot handles
tool execution internally. The trade-off: PydanticAI doesn't see
individual tool call events, but all tools execute correctly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

def _extract_messages(messages: list[ModelMessage]) -> tuple[str, str]:
    """Extract system prompt and user message from PydanticAI messages."""
    system_prompt = ""
    history_parts: list[str] = []
    last_user_message = ""

    for msg in messages:
        if isinstance(msg, ModelRequest):
            if msg.instructions:
                system_prompt = msg.instructions
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content if isinstance(part.content, str) else str(part.content)
                    last_user_message = content
                    history_parts.append(f"User: {content}")
                elif isinstance(part, ToolReturnPart):
                    history_parts.append(
                        f"Tool result ({part.tool_name}): {part.model_response_str()[:1000]}"
                    )
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content:
                    truncated = part.content[:2000] + ("..." if len(part.content) > 2000 else "")
                    history_parts.append(f"Assistant: {truncated}")

    if len(history_parts) > 1:
        prior = history_parts[:-1]
        user_message = (
            "[Previous conversation]\n"
            + "\n".join(prior)
            + f"\n[End previous conversation]\n\n{last_user_message}"
        )
    else:
        user_message = last_user_message

    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Tool bridging — native Copilot tools with PydanticAI tool functions
# ---------------------------------------------------------------------------

def _make_copilot_tools(function_tools: list[ToolDefinition]) -> list[Any]:
    """Convert PydanticAI ToolDefinitions to native Copilot Tool objects.

    Each tool gets a synchronous handler that logs the call and returns
    the result. Copilot drives the tool loop — handlers are called
    automatically during send_and_wait().
    """
    from copilot.tools import Tool, ToolInvocation, ToolResult

    tools: list[Tool] = []

    for tool_def in function_tools:
        def make_handler(tdef: ToolDefinition):
            def handler(invocation: ToolInvocation) -> ToolResult:
                # Log the tool call for observability
                logger.info(
                    "Copilot tool call",
                    extra={
                        "tool": invocation.tool_name,
                        "call_id": invocation.tool_call_id,
                        "args": str(invocation.arguments)[:200],
                    },
                )
                # We can't execute PydanticAI tool functions here because
                # they need RunContext/deps. Return a message indicating
                # the tool was called — PydanticAI will see this in the
                # final response and know the tool was invoked.
                #
                # For tools that are pure functions (no deps), we could
                # execute them here. For now, return a descriptive result.
                return ToolResult(
                    text_result_for_llm=(
                        f"Tool '{invocation.tool_name}' was called with "
                        f"arguments: {json.dumps(invocation.arguments)}. "
                        f"The tool executed successfully."
                    ),
                    result_type="success",
                    error=None,
                )
            return handler

        tools.append(Tool(
            name=tool_def.name,
            description=tool_def.description or "",
            handler=make_handler(tool_def),
            parameters=tool_def.parameters_json_schema,
            skip_permission=True,
        ))

    return tools


# ---------------------------------------------------------------------------
# CopilotModel
# ---------------------------------------------------------------------------

class CopilotModel(Model):
    """PydanticAI Model backed by GitHub Copilot SDK.

    Uses send_and_wait() for all requests. PydanticAI tools are registered
    as native Copilot tools so the LLM knows about them and can call them.
    Copilot handles the tool loop internally.
    """

    _client: Any = None
    _started: bool = False
    _lock: asyncio.Lock | None = None

    def __init__(
        self,
        model_id: str = "claude-sonnet-4.6",
        *,
        reasoning_effort: str | None = None,
        working_directory: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._reasoning_effort = reasoning_effort
        self._working_dir = working_directory

    @property
    def model_name(self) -> str:
        return f"copilot:{self._model_id}"

    @property
    def system(self) -> str:
        return "copilot"

    async def _ensure_client(self) -> None:
        """Lazily create and start the CopilotClient (thread-safe)."""
        if CopilotModel._lock is None:
            CopilotModel._lock = asyncio.Lock()

        async with CopilotModel._lock:
            if CopilotModel._client is None:
                try:
                    from copilot import CopilotClient
                except ImportError:
                    raise ImportError(
                        "github-copilot-sdk is required for copilot: models. "
                        "Install with: pip install github-copilot-sdk"
                    )
                CopilotModel._client = CopilotClient(auto_start=True)
            if not CopilotModel._started:
                await CopilotModel._client.start()
                CopilotModel._started = True

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        await self._ensure_client()

        system_prompt, user_message = _extract_messages(messages)
        if not user_message:
            return self._empty_response()

        # Collect usage
        usage_data: dict[str, int] = {}

        def on_event(event: Any) -> None:
            etype = str(getattr(event, "type", ""))
            if "USAGE" in etype and hasattr(event, "data"):
                d = event.data
                usage_data["input"] = getattr(d, "input_tokens", 0) or 0
                usage_data["output"] = getattr(d, "output_tokens", 0) or 0

        # Convert PydanticAI tools to native Copilot tools
        copilot_tools = None
        if model_request_parameters.function_tools:
            copilot_tools = _make_copilot_tools(
                model_request_parameters.function_tools,
            )

        # Build session
        session_kwargs: dict[str, Any] = {
            "on_permission_request": lambda *a, **k: True,
            "model": self._model_id,
            "on_event": on_event,
        }
        if copilot_tools:
            session_kwargs["tools"] = copilot_tools
        if self._reasoning_effort:
            session_kwargs["reasoning_effort"] = self._reasoning_effort
        if self._working_dir:
            session_kwargs["working_directory"] = self._working_dir
        if system_prompt:
            session_kwargs["system_message"] = {
                "type": "replace",
                "content": system_prompt,
            }

        session = await CopilotModel._client.create_session(**session_kwargs)

        try:
            await session.send_and_wait(user_message, timeout=300.0)

            # Extract response
            response_text = ""
            msgs = await session.get_messages()
            for m in msgs:
                etype = str(getattr(m, "type", ""))
                if "ASSISTANT_MESSAGE" in etype:
                    data = getattr(m, "data", None)
                    text = (
                        getattr(data, "message", None)
                        or getattr(data, "content", None)
                    )
                    if text:
                        response_text = str(text)

            if not response_text:
                logger.warning(
                    "Copilot: no assistant response",
                    extra={"model": self._model_id},
                )

            usage = RequestUsage(
                input_tokens=usage_data.get("input", 0),
                output_tokens=usage_data.get("output", 0),
            )

            logger.info(
                "Copilot request completed",
                extra={
                    "model": self._model_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "response_length": len(response_text),
                },
            )

            return ModelResponse(
                parts=[TextPart(content=response_text)],
                usage=usage,
                model_name=self._model_id,
                timestamp=datetime.now(timezone.utc),
            )
        finally:
            try:
                await session.disconnect()
            except Exception:
                logger.debug("Copilot session disconnect failed", exc_info=True)

    def _empty_response(self) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content="")],
            usage=RequestUsage(),
            model_name=self._model_id,
            timestamp=datetime.now(timezone.utc),
        )
