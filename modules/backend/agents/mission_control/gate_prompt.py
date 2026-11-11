"""Gate LLM prompt construction — system prompt, context formatter, action parser."""

from __future__ import annotations

import json

from modules.backend.agents.mission_control.gate_models import GateAction, GateContext
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


_GATE_SYSTEM_PROMPT = """\
You are a gate reviewer for a multi-agent mission dispatch system.

Your role is to review execution state at key decision points and decide
whether to continue, skip, retry or abort the current step.

You will receive structured context about the current gate point including:
- Gate type (pre_dispatch, pre_layer, post_task, verification_failed, post_layer)
- Mission ID and budget information
- Task details, outputs, and verification results
- Cost tracking and layer progress

Decision guidelines:
- CONTINUE: Proceed normally. Use when everything looks healthy.
- SKIP: Skip this task or layer. Use when a task is unnecessary or redundant.
- RETRY: Re-run with feedback. Use when output is close but needs adjustment.
- ABORT: Halt the entire mission. Use for budget overruns, cascading failures,
  or when the mission objective cannot be met.

Cost awareness:
- Flag when cumulative cost exceeds 80% of budget.
- Consider cost-per-value: abort if remaining tasks won't justify spend.

Quality awareness:
- At post_task: check that output matches the task description and verification passed.
- At verification_failed: the only actions are retry, skip or abort. Failed
  output is never accepted as-is; retry when feedback can fix it, otherwise abort.

Respond with your decision as structured JSON.
"""


def _build_gate_prompt(context: GateContext) -> str:
    """Build a user-facing prompt from gate context for the LLM reviewer."""
    parts = [f"## Gate Point: {context.gate_type}\n"]

    parts.append(f"**Mission:** {context.mission_id}")
    parts.append(
        f"**Budget:** ${context.total_cost_usd:.4f} spent " f"/ ${context.budget_usd:.2f} total"
    )

    if context.budget_usd > 0:
        pct = (context.total_cost_usd / context.budget_usd) * 100
        parts.append(f"**Budget utilization:** {pct:.1f}%")

    if context.gate_type == "pre_dispatch":
        parts.append(f"\n**Tasks in plan:** {len(context.pending_tasks)}")
        if context.pending_tasks:
            task_summary = json.dumps(
                [
                    {
                        "task_id": t.get("task_id"),
                        "agent": t.get("agent"),
                        "description": (t.get("description") or "")[:100],
                    }
                    for t in context.pending_tasks
                ],
                indent=2,
            )
            parts.append(f"\n```json\n{task_summary}\n```")

    elif context.gate_type == "pre_layer":
        parts.append(f"\n**Layer:** {context.layer_index + 1}/{context.total_layers}")
        parts.append(f"**Tasks in layer:** {len(context.pending_tasks)}")
        if context.pending_tasks:
            task_summary = json.dumps(
                [
                    {
                        "task_id": t.get("task_id"),
                        "agent": t.get("agent"),
                        "instructions": (t.get("instructions") or "")[:80],
                    }
                    for t in context.pending_tasks
                ],
                indent=2,
            )
            parts.append(f"\n```json\n{task_summary}\n```")

    elif context.gate_type == "post_task":
        parts.append(f"\n**Task:** {context.task_id}")
        if context.task_output:
            meta = context.task_output.get("_meta", {})
            parts.append(
                f"**Task cost:** ${meta.get('cost_usd', 0):.4f}  |  "
                f"Tokens: {meta.get('input_tokens', 0):,} in / "
                f"{meta.get('output_tokens', 0):,} out"
            )
            output_preview = {k: v for k, v in context.task_output.items() if k != "_meta"}
            preview_str = json.dumps(output_preview, indent=2, default=str)
            if len(preview_str) > 1000:
                preview_str = preview_str[:1000] + "\n... (truncated)"
            parts.append(f"\n**Output:**\n```json\n{preview_str}\n```")
        if context.verification:
            parts.append(
                f"\n**Verification:**\n```json\n"
                f"{json.dumps(context.verification, indent=2, default=str)}\n```"
            )

    elif context.gate_type == "verification_failed":
        parts.append(f"\n**Task:** {context.task_id}")
        parts.append("**Status:** VERIFICATION FAILED")
        if context.verification:
            parts.append(
                f"\n**Verification details:**\n```json\n"
                f"{json.dumps(context.verification, indent=2, default=str)}\n```"
            )
        parts.append("\nDecide: retry (with feedback), skip, or abort.")

    elif context.gate_type == "post_layer":
        parts.append(f"\n**Layer:** {context.layer_index + 1}/{context.total_layers} complete")
        if context.completed_tasks:
            statuses: dict[str, int] = {}
            for t in context.completed_tasks:
                s = t.get("status", "?")
                statuses[s] = statuses.get(s, 0) + 1
            parts.append(f"**Results:** {statuses}")

    parts.append("\nWhat is your decision?")
    return "\n".join(parts)


def _parse_action(action_str: str) -> GateAction:
    """Parse action string to GateAction; an unknown action is ABORT (fail closed)."""
    try:
        return GateAction(action_str.lower().strip())
    except ValueError:
        # non-critical log: pure parsing function with no mission context or
        # event bus; the ABORT decision itself is recorded by the caller.
        logger.warning("Unknown gate action %r: aborting (fail closed)", action_str)
        return GateAction.ABORT
