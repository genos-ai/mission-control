"""PydanticAI Model adapter for GitHub Copilot SDK.

Routes LLM calls through the Copilot Enterprise subscription at $0.
All 13 models (Claude, GPT) available.

Tool bridging architecture:
  PydanticAI tools are registered as native Copilot tools with async
  handlers. When the LLM calls a tool, the handler signals PydanticAI
  via an asyncio.Queue, then awaits a Future for the result. PydanticAI
  executes the tool (with full deps/context), then resolves the Future.
  The handler unblocks, returns the result to Copilot, and the LLM
  continues.

  This works because Copilot v3 protocol launches handlers via
  asyncio.ensure_future — the event loop stays free during await.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from pydantic_ai.profiles import ModelProfile

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStreamEvent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

# ---------------------------------------------------------------------------
# JSON repair for prompted structured output
# ---------------------------------------------------------------------------


def _repair_json_in_text(text: str) -> str:
    """Attempt to repair malformed JSON in LLM responses.

    CopilotModel uses prompted structured output (schema injected into the
    system prompt). The LLM occasionally produces JSON with missing commas,
    trailing commas, or unescaped characters. This function finds JSON blocks
    in the text and repairs them using json_repair.

    Only runs when the text contains JSON-like content. Falls back to the
    original text if repair fails or json_repair is unavailable.
    """
    try:
        from json_repair import repair_json
    except ImportError:
        return text

    import re

    # Find JSON block (possibly wrapped in ```json ... ```)
    json_match = re.search(r"```json\s*([\s\S]*?)```", text)
    if json_match:
        raw_json = json_match.group(1).strip()
        repaired = repair_json(raw_json)
        if repaired != raw_json:
            return text[: json_match.start(1)] + repaired + text[json_match.end(1) :]
        return text

    # Try to find a top-level JSON object or array
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        raw_json = text[first_brace : last_brace + 1]
        try:
            json.loads(raw_json)
            return text  # Already valid
        except json.JSONDecodeError:
            repaired = repair_json(raw_json)
            if repaired and repaired != raw_json:
                return text[:first_brace] + repaired + text[last_brace + 1 :]

    return text


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
                elif isinstance(part, ToolCallPart):
                    args_str = (
                        json.dumps(part.args) if isinstance(part.args, dict) else str(part.args)
                    )
                    history_parts.append(f"Tool call: {part.tool_name}({args_str})")

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


def _has_tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    """Extract ToolReturnParts from the message list."""
    parts: list[ToolReturnPart] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    parts.append(part)
    return parts


# ---------------------------------------------------------------------------
# Typed errors raised by CopilotModel — let callers classify transient
# infrastructure failures distinctly from logical contract failures.
# ---------------------------------------------------------------------------


from modules.backend.core.exceptions import (  # noqa: E402
    QuotaExhaustedError,
    TransientProviderError,
    log_provider_error,
)


class EmptyCopilotSessionError(TransientProviderError):
    """The Copilot session ended without the model engaging.

    Symptoms: 0 input tokens, 0 output tokens, no assistant message,
    no tool calls. Observed when GitHub Copilot rate-limits a rapid
    retry burst or when the SDK's session lifecycle hiccups. Inherits
    `retry_policy = "immediate"` from `TransientProviderError`.
    """


class CopilotQuotaExhaustedError(QuotaExhaustedError):
    """GitHub Copilot returned 402 — account's monthly quota exhausted.

    Inherits `retry_policy = "none"` from `QuotaExhaustedError` —
    operators must wait for the window to reset, upgrade the plan, or
    switch agents to a provider with remaining capacity.
    """


_QUOTA_PATTERN = re.compile(
    r"402.*(?:quota|monthly quota|exceeded)",
    re.IGNORECASE | re.DOTALL,
)
_REQUEST_ID_PATTERN = re.compile(r"Request ID:\s*([A-Za-z0-9:.\-]+)")


# ---------------------------------------------------------------------------
# Tool bridge — async handlers that await PydanticAI tool results
# ---------------------------------------------------------------------------


@dataclass
class _ToolBridge:
    """Bridges tool calls between Copilot and PydanticAI.

    Flow:
      1. LLM calls tool → Copilot fires handler via ensure_future
      2. Handler puts ToolInvocation on pending_calls queue
      3. Handler awaits a Future in results dict
      4. CopilotModel.request() reads pending_calls → returns ToolCallPart
      5. PydanticAI executes tool → calls request() with ToolReturnPart
      6. request() resolves the Future with the tool result
      7. Handler unblocks → returns ToolResult to Copilot
      8. LLM gets the result and continues
    """

    pending_calls: asyncio.Queue = field(default_factory=asyncio.Queue)
    results: dict[str, asyncio.Future] = field(default_factory=dict)


def _make_copilot_tools(
    function_tools: list[ToolDefinition],
    output_tool_names: set[str],
    bridge: _ToolBridge,
) -> list[Any]:
    """Convert PydanticAI ToolDefinitions to native Copilot Tools.

    Function tools round-trip: handler waits for PydanticAI to execute
    and resolve the Future. Output tools (PydanticAI's structured-output
    sentinels like final_result) do NOT round-trip — PydanticAI captures
    the call args as the typed output and ends the agent run, so the
    Future is never resolved. For output tools the handler returns
    success immediately after queueing the invocation.
    """
    from copilot.tools import Tool, ToolInvocation, ToolResult

    tools: list[Tool] = []

    for tool_def in function_tools:
        is_output_tool = tool_def.name in output_tool_names

        async def handler(
            invocation: ToolInvocation,
            _bridge: _ToolBridge = bridge,
            _is_output: bool = is_output_tool,
        ) -> ToolResult:
            logger.info(
                "Copilot tool call → PydanticAI",
                extra={
                    "tool": invocation.tool_name,
                    "call_id": invocation.tool_call_id,
                    "output_tool": _is_output,
                },
            )

            if _is_output:
                # Output sentinel — push to queue so CopilotModel.request
                # returns the ToolCallPart to PydanticAI (which captures
                # args as typed output and terminates). No tool return
                # will come back; do not create or await a Future.
                await _bridge.pending_calls.put(invocation)
                return ToolResult(
                    text_result_for_llm="OK",
                    result_type="success",
                    error=None,
                )

            # Function tool — round-trip via PydanticAI execution.
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            _bridge.results[invocation.tool_call_id] = future
            await _bridge.pending_calls.put(invocation)

            try:
                from modules.backend.core.config import get_app_config

                tool_timeout = get_app_config().application.timeouts.tool_bridge
                result_text = await asyncio.wait_for(future, timeout=tool_timeout)
            except asyncio.TimeoutError:
                logger.error(
                    "Tool bridge timeout",
                    extra={"tool": invocation.tool_name, "call_id": invocation.tool_call_id},
                )
                return ToolResult(
                    text_result_for_llm="Tool execution timed out",
                    result_type="timeout",
                    error="Timed out waiting for tool result",
                )

            return ToolResult(
                text_result_for_llm=str(result_text),
                result_type="success",
                error=None,
            )

        tools.append(
            Tool(
                name=tool_def.name,
                description=tool_def.description or "",
                handler=handler,
                parameters=tool_def.parameters_json_schema,
                skip_permission=True,
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Streamed response wrapper (converts request() result to a stream)
# ---------------------------------------------------------------------------


@dataclass
class CopilotStreamedResponse(StreamedResponse):
    """Wraps a completed ModelResponse as a single-chunk stream.

    Copilot doesn't support real-time streaming to PydanticAI (the
    response comes back complete from send_and_wait). This wrapper
    yields the full response as a single PartStartEvent so PydanticAI's
    streaming infrastructure (event_stream_handler) works correctly.
    """

    _model_response: ModelResponse = field(default=None)
    _model_id: str = ""
    _timestamp: datetime = field(default_factory=utc_now)

    @property
    def model_name(self) -> str:
        return f"copilot:{self._model_id}"

    @property
    def provider_name(self) -> str:
        return "copilot"

    @property
    def provider_url(self) -> str:
        return "https://github.com/copilot"

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """Yield each part of the response via the parts manager."""
        for part in self._model_response.parts:
            event = self._parts_manager.handle_part(
                vendor_part_id=None,
                part=part,
            )
            yield event
        self._usage = self._model_response.usage


# ---------------------------------------------------------------------------
# CopilotModel
# ---------------------------------------------------------------------------


class CopilotModel(Model):
    """PydanticAI Model backed by GitHub Copilot SDK.

    Full PydanticAI tool support via async handler bridging.
    Copilot drives the tool loop, but handlers await PydanticAI's
    tool execution before returning results.

    Structured output: Copilot SDK does not support native JSON schema
    output. We set default_structured_output_mode='prompted' so PydanticAI
    injects the JSON schema into the system prompt automatically. The LLM
    is instructed to respond with JSON matching the schema — no native API
    enforcement, but reliable enough for structured output types.
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
        profile: "ModelProfile | None" = None,
    ) -> None:
        from pydantic_ai.profiles import ModelProfile

        # Copilot SDK doesn't support native JSON schema output (response_format),
        # but DOES validate tool-call argument schemas end-to-end (P17). Using
        # 'tool' mode makes PydanticAI create a hidden `final_result` tool whose
        # parameters ARE the output schema — validated by Pydantic on each call.
        # This only affects CopilotModel; Anthropic/OpenAI models have
        # supports_json_schema_output=True so this fallback is never consulted.
        self._profile = profile or ModelProfile(
            supports_json_schema_output=False,
            default_structured_output_mode="tool",
        )
        self._model_id = model_id
        self._reasoning_effort = reasoning_effort
        self._working_dir = working_directory
        # Per-turn state (persists across tool round-trips)
        self._active_session: Any = None
        self._tool_bridge: _ToolBridge | None = None
        self._response_text: str = ""
        self._response_ready: asyncio.Event | None = None
        self._usage_data: dict[str, int] = {}
        # Captured when a SESSION_ERROR event fires — lets the tool path
        # detect quota/auth/etc. failures that arrive as events rather
        # than as exceptions from send().
        self._session_error_text: str | None = None

    @property
    def model_name(self) -> str:
        return f"copilot:{self._model_id}"

    @property
    def system(self) -> str:
        return "copilot"

    async def _ensure_client(self) -> None:
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

    # ---- Error classification helpers --------------------------------
    #
    # The Copilot SDK raises a plain `Exception` whose message embeds
    # the HTTP status code and the GitHub Copilot Request ID. We
    # string-match here because the SDK doesn't expose typed quota /
    # rate-limit exceptions. As provider classifications get added
    # (auth failure, transient connection, etc.) they go here.

    def _classify_session_error(self, exc: BaseException) -> BaseException:
        """Return a typed `ProviderError` subclass if the raw SDK
        exception matches a known pattern; otherwise return `exc`
        unchanged so the caller can re-raise as-is.
        """
        msg = str(exc)
        if _QUOTA_PATTERN.search(msg):
            rid_match = _REQUEST_ID_PATTERN.search(msg)
            return CopilotQuotaExhaustedError(
                msg,
                provider="copilot",
                model=self._model_id,
                request_id=rid_match.group(1) if rid_match else None,
                raw=msg,
            )
        return exc

    def _raise_empty_session(
        self,
        message: str,
        *,
        raw: str | None = None,
    ) -> NoReturn:
        """Raise an `EmptyCopilotSessionError` populated with this
        adapter's provider/model context, and emit the canonical
        ERROR log entry. Used everywhere we detect that the Copilot
        session ended without the model engaging.
        """
        empty = EmptyCopilotSessionError(
            message,
            provider="copilot",
            model=self._model_id,
            raw=raw,
        )
        log_provider_error(logger, empty)
        raise empty

    # ---- Main entry ----

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        # Resolve output_mode (auto → prompted), merge settings, inject
        # schema into instructions. Must happen before _handle_new_turn
        # reads the messages — the prompted output schema is appended to
        # the instructions field by PydanticAI's base prepare_request.
        model_settings, model_request_parameters = self.prepare_request(
            model_settings,
            model_request_parameters,
        )

        await self._ensure_client()

        # Tool return continuation?
        tool_returns = _has_tool_returns(messages)
        if tool_returns and self._active_session and self._tool_bridge:
            return await self._handle_tool_return(tool_returns)

        # New turn
        return await self._handle_new_turn(messages, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Stream wrapper — calls request() and yields result as a single chunk.

        PydanticAI's agent.run() with event_stream_handler requires
        request_stream(). We call request() (blocking), then yield
        the complete response as a stream. Not real-time streaming,
        but satisfies the interface.
        """
        response = await self.request(messages, model_settings, model_request_parameters)
        streamed = CopilotStreamedResponse(
            model_request_parameters=model_request_parameters,
            _model_response=response,
            _model_id=self._model_id,
        )
        streamed._usage = response.usage
        yield streamed

    # ---- New turn ----

    async def _handle_new_turn(
        self,
        messages: list[ModelMessage],
        params: ModelRequestParameters,
    ) -> ModelResponse:
        _, user_message = _extract_messages(messages)
        if not user_message:
            return self._empty_response()

        # Use PydanticAI's _get_instructions which appends the prompted
        # output schema (JSON schema instructions) to the base instructions.
        # Without this, agents with output_type get no schema guidance and
        # the LLM returns free-form text instead of JSON.
        system_prompt = self._get_instructions(messages, params) or ""

        # Reset turn state
        self._response_text = ""
        self._response_ready = asyncio.Event()
        self._usage_data = {}
        self._session_error_text = None
        # Merge function tools + output tools (e.g. final_result for
        # structured output in 'tool' mode). Without output_tools, the
        # model never sees final_result and falls back to prompted text.
        # Output tools terminate the run — the bridge handler must not
        # await a result for them (see _make_copilot_tools).
        all_tools = list(params.function_tools or [])
        output_tool_names: set[str] = set()
        if params.output_tools:
            all_tools.extend(params.output_tools)
            output_tool_names = {t.name for t in params.output_tools}
        has_tools = bool(all_tools)

        # Output-contract hardening: when output_tools are present, the
        # only valid termination is a call to the output sentinel
        # (final_result). Empirically the model occasionally writes a
        # text reply instead, which then fails Pydantic validation
        # downstream. Append an explicit contract to the system prompt.
        if output_tool_names:
            tool_list = ", ".join(f"`{n}`" for n in sorted(output_tool_names))
            system_prompt = (
                system_prompt.rstrip()
                + "\n\n## OUTPUT CONTRACT (non-negotiable)\n\n"
                + f"You MUST conclude your response by calling the {tool_list} "
                + "tool with arguments that satisfy its schema in full. "
                + "Do NOT write a text reply, summary, or acknowledgement as "
                + "your final response — the tool call is the only valid "
                + "termination. If you cannot complete the task, still call "
                + "the tool with the closest valid empty/error shape permitted "
                + "by the schema, never with free-form text.\n"
            )

        if has_tools:
            self._tool_bridge = _ToolBridge()
            copilot_tools = _make_copilot_tools(
                all_tools,
                output_tool_names,
                self._tool_bridge,
            )
        else:
            self._tool_bridge = None
            copilot_tools = None

        # Build session
        session_kwargs: dict[str, Any] = {
            "on_permission_request": lambda *a, **k: True,
            "model": self._model_id,
            "on_event": self._on_event,
        }
        if copilot_tools:
            session_kwargs["tools"] = copilot_tools
        if self._reasoning_effort:
            session_kwargs["reasoning_effort"] = self._reasoning_effort
        if self._working_dir:
            session_kwargs["working_directory"] = self._working_dir
        if system_prompt:
            # Use the sections API (public preview, April 2026) to fully
            # replace the Copilot CLI's default identity. The old top-level
            # "type": "replace" format is ignored by newer SDK versions,
            # leaving the default "I'm GitHub Copilot CLI" identity.
            session_kwargs["system_message"] = {
                "mode": "customize",
                "sections": {
                    "identity": {"action": "replace", "content": system_prompt},
                },
            }

        self._active_session = await CopilotModel._client.create_session(
            **session_kwargs,
        )

        if not has_tools:
            # No tools — simple path with send_and_wait
            return await self._simple_request(user_message)

        # Has tools — use send + wait for tool calls or completion
        try:
            await self._active_session.send(user_message)
        except Exception as exc:
            classified = self._classify_session_error(exc)
            if isinstance(classified, CopilotQuotaExhaustedError):
                await self._cleanup_session()
                log_provider_error(logger, classified)
                raise classified from exc
            raise
        return await self._wait_for_response()

    # ---- Simple request (no tools) ----

    async def _simple_request(self, user_message: str) -> ModelResponse:
        try:
            try:
                await self._active_session.send_and_wait(user_message, timeout=300.0)
            except Exception as exc:
                classified = self._classify_session_error(exc)
                if isinstance(classified, CopilotQuotaExhaustedError):
                    log_provider_error(logger, classified)
                    raise classified from exc
                raise
            return self._extract_final_response()
        finally:
            await self._cleanup_session()

    # ---- Tool return continuation ----

    async def _handle_tool_return(self, tool_returns: list[ToolReturnPart]) -> ModelResponse:
        """PydanticAI executed tools — resolve the Futures so handlers unblock."""
        for part in tool_returns:
            future = self._tool_bridge.results.pop(part.tool_call_id, None)
            if future and not future.done():
                future.set_result(part.model_response_str())
                logger.info(
                    "Tool result → Copilot",
                    extra={"tool": part.tool_name, "call_id": part.tool_call_id},
                )

        # Wait for next tool call or final response
        self._response_ready.clear()
        return await self._wait_for_response()

    # ---- Event handler ----

    def _on_event(self, event: Any) -> None:
        etype = str(getattr(event, "type", ""))

        if "USAGE" in etype and hasattr(event, "data"):
            d = event.data
            self._usage_data["input"] = getattr(d, "input_tokens", 0) or 0
            self._usage_data["output"] = getattr(d, "output_tokens", 0) or 0

        elif "ASSISTANT_MESSAGE" in etype and "DELTA" not in etype:
            data = getattr(event, "data", None)
            text = getattr(data, "message", None) or getattr(data, "content", None)
            if text:
                self._response_text = str(text)

        elif "SESSION_ERROR" in etype:
            # Capture the error message so _wait_for_response can
            # classify it (quota / auth / transient) instead of just
            # seeing "no response".
            data = getattr(event, "data", None)
            err_text = (
                getattr(data, "message", None)
                or getattr(data, "error", None)
                or getattr(data, "content", None)
                or str(data)
                if data is not None
                else None
            )
            if err_text:
                self._session_error_text = str(err_text)
            if self._response_ready:
                self._response_ready.set()

        elif "SESSION_IDLE" in etype:
            if self._response_ready:
                self._response_ready.set()

    # ---- Wait for tool call or final response ----

    async def _wait_for_response(self) -> ModelResponse:
        """Race between a tool call from the bridge and session completion."""
        tool_task = asyncio.ensure_future(self._tool_bridge.pending_calls.get())
        idle_task = asyncio.ensure_future(self._response_ready.wait())

        try:
            done, pending = await asyncio.wait(
                {tool_task, idle_task},
                timeout=300.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            tool_task.cancel()
            idle_task.cancel()
            raise

        for t in pending:
            t.cancel()

        if not done:
            # 300s elapsed with NO events at all — session never produced
            # a tool call, an assistant message, or an idle/error signal.
            # That's an infrastructure timeout, not a logical failure.
            await self._cleanup_session()
            self._raise_empty_session("Copilot session timed out at 300s without events")

        if tool_task in done:
            # Tool call — return to PydanticAI for execution
            invocation = tool_task.result()
            args = invocation.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {"raw": args}

            logger.info(
                "Tool call → PydanticAI",
                extra={"tool": invocation.tool_name, "call_id": invocation.tool_call_id},
            )

            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=invocation.tool_name,
                        args=args,
                        tool_call_id=invocation.tool_call_id,
                    )
                ],
                usage=RequestUsage(),
                model_name=self._model_id,
                timestamp=utc_now(),
            )

        # Session idle — classify what kind of "no response" this is.
        # 1. SESSION_ERROR with a 402-quota signature → quota
        # 2. SESSION_ERROR without a known signature → transient
        # 3. Idle + 0 tokens + no text/tools → transient (empty session)
        # 4. Idle with text or tokens → return whatever was captured
        if self._session_error_text:
            classified = self._classify_session_error(
                Exception(self._session_error_text),
            )
            await self._cleanup_session()
            if isinstance(classified, CopilotQuotaExhaustedError):
                log_provider_error(logger, classified)
                raise classified
            # Unknown SESSION_ERROR — surface as a transient provider
            # failure so the retry handler retries while the operator
            # still sees the underlying message in the structured log.
            self._raise_empty_session(
                f"Copilot session error: {self._session_error_text[:200]}",
                raw=self._session_error_text,
            )

        input_tokens = self._usage_data.get("input", 0)
        output_tokens = self._usage_data.get("output", 0)
        if not self._response_text and input_tokens == 0 and output_tokens == 0:
            await self._cleanup_session()
            self._raise_empty_session(
                "Copilot session ended without model engagement "
                "(input_tokens=0, output_tokens=0)"
            )

        response = self._extract_final_response()
        await self._cleanup_session()
        return response

    # ---- Helpers ----

    def _extract_final_response(self) -> ModelResponse:
        if not self._response_text:
            # Try from session messages
            if self._active_session:
                try:
                    import asyncio

                    msgs = asyncio.get_event_loop().run_until_complete(
                        self._active_session.get_messages()
                    )
                except Exception:
                    msgs = []
                for m in msgs:
                    etype = str(getattr(m, "type", ""))
                    if "ASSISTANT_MESSAGE" in etype:
                        data = getattr(m, "data", None)
                        text = getattr(data, "message", None) or getattr(data, "content", None)
                        if text:
                            self._response_text = str(text)

        if not self._response_text:
            logger.warning("Copilot: no assistant response", extra={"model": self._model_id})

        usage = RequestUsage(
            input_tokens=self._usage_data.get("input", 0),
            output_tokens=self._usage_data.get("output", 0),
        )

        logger.info(
            "Copilot request completed",
            extra={
                "model": self._model_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "response_length": len(self._response_text),
            },
        )

        # Repair malformed JSON in prompted structured output responses.
        # CopilotModel uses prompted mode (schema in system prompt), and the
        # LLM occasionally produces JSON with missing commas or trailing commas.
        # json_repair fixes these before PydanticAI's Pydantic validation runs.
        text = self._response_text
        if text and "{" in text:
            text = _repair_json_in_text(text)

        return ModelResponse(
            parts=[TextPart(content=text)],
            usage=usage,
            model_name=self._model_id,
            timestamp=utc_now(),
        )

    async def _cleanup_session(self) -> None:
        session = self._active_session
        self._active_session = None
        self._tool_bridge = None
        if session:
            try:
                await session.disconnect()
            except Exception:
                logger.debug("Copilot session disconnect failed", exc_info=True)

    def _empty_response(self) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content="")],
            usage=RequestUsage(),
            model_name=self._model_id,
            timestamp=utc_now(),
        )
