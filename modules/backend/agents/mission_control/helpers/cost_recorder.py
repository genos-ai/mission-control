"""Records LLM calls to the llm_calls table for cost attribution (Plan 60).

Called from both agent_executor.py (dispatch path) and
mission_control.py (chat path) to ensure all costs are captured.

Raises on failure — callers decide whether to catch.
"""

from __future__ import annotations

from typing import TypedDict

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Estimate ~200 tokens per tool definition (name + description + schema).
TOKENS_PER_TOOL_ESTIMATE = 200


class UsageFields(TypedDict):
    """Extracted token fields from a PydanticAI usage object."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    thinking_tokens: int


def extract_usage(usage: object) -> UsageFields:
    """Extract token fields from a PydanticAI Usage/RunUsage object.

    Centralises the getattr+details logic so callers don't repeat it.
    """
    details = usage.details if hasattr(usage, "details") and usage.details else {}
    return UsageFields(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_write_tokens", 0) or 0,
        thinking_tokens=(details.get("reasoning_tokens", 0) or details.get("thinking_tokens", 0)),
    )


async def record_llm_call(
    *,
    session_id: str | None,
    mission_id: str | None,
    agent_name: str,
    agent_role: str,
    model: str,
    usage: object,
    cost_usd: float,
    latency_ms: int = 0,
    tool_count: int = 0,
    execution_record_id: str | None = None,
    mission_run_id: str | None = None,
    task_id: str | None = None,
) -> None:
    """Persist an LlmCall row. Manages its own DB session.

    mission_run_id and task_id attribute the call to a run and a plan task;
    None when the call is outside either (chat, planning).

    Raises on failure — silent data loss in cost tracking
    defeats the purpose of this system.
    """
    from modules.backend.services.token_economics import TokenEconomicsService

    provider = model.split(":")[0] if ":" in model else "unknown"
    fields = extract_usage(usage)

    # PydanticAI reports cache_write_tokens as a single value.
    # Attribute to 1h bucket by default (our default TTL).
    # If usage.details has per-TTL breakdown, use it.
    details = usage.details if hasattr(usage, "details") and usage.details else {}
    cache_write_5m = details.get("cache_creation_5m_tokens", 0)
    cache_write_1h = details.get("cache_creation_1h_tokens", 0)
    if not cache_write_5m and not cache_write_1h:
        cache_write_1h = fields["cache_write_tokens"]

    async with TokenEconomicsService.factory() as svc:
        await svc.record_call(
            session_id=session_id,
            mission_id=mission_id,
            execution_record_id=execution_record_id,
            mission_run_id=mission_run_id,
            task_id=task_id,
            agent_name=agent_name,
            agent_role=agent_role,
            model=model,
            provider=provider,
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cache_read_tokens=fields["cache_read_tokens"],
            cache_write_5m_tokens=cache_write_5m,
            cache_write_1h_tokens=cache_write_1h,
            thinking_tokens=fields["thinking_tokens"],
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            tool_count=tool_count,
            tool_schema_tokens=tool_count * TOKENS_PER_TOOL_ESTIMATE,
        )
