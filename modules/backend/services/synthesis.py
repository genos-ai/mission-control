"""Synthesis Service — turns structured execution data into human narrative.

Post-processing service, NOT a dispatched agent. Called after dispatch
completes to generate a readable summary of what happened and why.

Tools & access: NONE. Pure LLM call over structured input data.
Model: Haiku (cheap, fast — input is already structured, no complex reasoning).

Usage:
    from modules.backend.services.synthesis import summarize_outcome

    outcome = await dispatch(...)
    outcome.summary = await summarize_outcome(outcome)
"""

from __future__ import annotations

import json

from pydantic_ai import Agent

from modules.backend.core.model_builder import _build_model
from modules.backend.core.logging import get_logger
from modules.backend.schemas.execution_outcome import ExecutionOutcome

logger = get_logger(__name__)

_MODEL = "copilot:claude-haiku-4.5"

_INSTRUCTIONS = """\
You are a concise technical writer. Given structured execution outcome data,
produce a brief narrative summary (2-5 sentences) for a human operator.

Rules:
- State what was done, what succeeded, what failed, and why.
- Include key metrics: total cost, duration, task count.
- For failures, state the root cause clearly.
- Be factual. Do not evaluate agent performance or suggest fixes.
- Do not use markdown headers. Plain text only.
"""


def _create_agent() -> Agent[None, str]:
    """Create a fresh synthesis agent (no caching — avoids stale model singletons)."""
    model = _build_model(_MODEL)
    return Agent(model, output_type=str, instructions=_INSTRUCTIONS)


def _build_prompt(outcome: ExecutionOutcome) -> str:
    """Build a compact prompt from the outcome — only what matters."""
    tasks = []
    for t in outcome.task_results:
        entry: dict = {
            "task_id": t.task_id,
            "agent": t.agent_name,
            "status": t.status.value,
            "cost_usd": round(t.cost_usd, 4),
            "duration_s": round(t.duration_seconds, 1),
        }
        # Include summary from output if present
        if t.output_reference.get("summary"):
            entry["summary"] = t.output_reference["summary"]
        # Include failure reason
        if t.status == "failed" and t.retry_history:
            entry["failure_reason"] = t.retry_history[-1].failure_reason
            entry["retries"] = t.retry_count
        if t.skip_reason:
            entry["skip_reason"] = t.skip_reason
        tasks.append(entry)

    data = {
        "overall_status": outcome.status.value,
        "total_cost_usd": round(outcome.total_cost_usd, 4),
        "total_duration_s": round(outcome.total_duration_seconds, 1),
        "task_count": len(outcome.task_results),
        "tasks": tasks,
    }
    if outcome.abort_reason:
        data["abort_reason"] = outcome.abort_reason

    return (
        "Summarize this execution outcome:\n\n"
        f"```json\n{json.dumps(data, indent=2)}\n```"
    )


async def summarize_outcome(outcome: ExecutionOutcome) -> str:
    """Generate a human-readable summary of an execution outcome.

    Returns empty string on failure — synthesis is best-effort,
    never blocks or fails the execution.
    """
    try:
        agent = _create_agent()
        prompt = _build_prompt(outcome)
        result = await agent.run(prompt)
        summary = result.output.strip()
        logger.info(
            "Synthesis complete",
            extra={"chars": len(summary), "status": outcome.status.value},
        )
        return summary
    except Exception:
        logger.warning("Synthesis failed — returning empty summary", exc_info=True)
        return ""
