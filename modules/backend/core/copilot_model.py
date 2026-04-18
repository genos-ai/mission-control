"""PydanticAI Model adapter for GitHub Copilot SDK.

Routes LLM calls through the Copilot Enterprise subscription
instead of direct API keys. All 13 models (Claude, GPT) available
at $0 cost on the enterprise subscription.

Phase 1: Pure text LLM — no PydanticAI tool support.
Phase 2: Tool bridging + streaming.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
from pydantic_ai.usage import RequestUsage

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _extract_messages(messages: list[ModelMessage]) -> tuple[str, str]:
    """Extract system prompt and user message from PydanticAI messages.

    PydanticAI passes the full conversation history. We extract:
    - System prompt from the first ModelRequest with instructions
    - Full conversation context serialized into the user message

    Copilot sessions are ephemeral (new session per request), so
    prior turns are included as context in the prompt.
    """
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
                    history_parts.append(f"Tool ({part.tool_name}): {part.model_response_str()[:500]}")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content:
                    truncated = part.content[:2000] + ("..." if len(part.content) > 2000 else "")
                    history_parts.append(f"Assistant: {truncated}")

    # If there's prior history, prepend it to the last user message
    if len(history_parts) > 1:
        # Remove the last entry (it's the current user message, already in last_user_message)
        prior = history_parts[:-1]
        user_message = (
            f"[Previous conversation]\n"
            + "\n".join(prior)
            + f"\n[End previous conversation]\n\n{last_user_message}"
        )
    else:
        user_message = last_user_message

    return system_prompt, user_message


class CopilotModel(Model):
    """PydanticAI Model backed by GitHub Copilot SDK.

    Creates a CopilotClient on first use (lazily), reuses across requests.
    Each request creates a fresh session, sends the message, collects
    the response, and disconnects the session.
    """

    _client: Any = None
    _started: bool = False
    _lock: Any = None  # asyncio.Lock, created lazily

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
        import asyncio

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
        """Send a message via Copilot SDK, return the response."""
        await self._ensure_client()

        system_prompt, user_message = _extract_messages(messages)
        if not user_message:
            return ModelResponse(
                parts=[TextPart(content="")],
                usage=RequestUsage(),
                model_name=self._model_id,
                timestamp=datetime.now(timezone.utc),
            )

        # Collect usage data from events
        usage_data: dict[str, int] = {}

        def on_event(event: Any) -> None:
            etype = str(getattr(event, "type", ""))
            if "USAGE" in etype and hasattr(event, "data"):
                d = event.data
                usage_data["input"] = getattr(d, "input_tokens", 0) or 0
                usage_data["output"] = getattr(d, "output_tokens", 0) or 0

        # Build session kwargs
        session_kwargs: dict[str, Any] = {
            "on_permission_request": lambda *a, **k: True,
            "model": self._model_id,
            "on_event": on_event,
        }
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

            # Extract assistant response from session messages
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
                    "Copilot: no assistant response found in session messages",
                    extra={"model": self._model_id, "message_count": len(msgs)},
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
