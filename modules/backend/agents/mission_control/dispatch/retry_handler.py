"""Retry-with-feedback handler for single-task execution.

Executes a task, runs 3-tier verification, and retries with feedback
when verification fails. Integrates gate review at verification failure
and post-task checkpoints.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from pydantic_ai.exceptions import IncompleteToolCall, UnexpectedModelBehavior, UsageLimitExceeded

from modules.backend.core.exceptions import (
    QuotaExhaustedError,
    RateLimitedError,
    TransientProviderError,
    log_provider_error,
)

# PydanticAI-native validation failures — the model responded but with
# wrong-shape output. PydanticAI has already retried internally before
# surfacing these. We keep catching them as the original exception
# types (not wrapped) because PydanticAI raises them; wrapping would
# require boundary code in every provider adapter.
_CONTRACT_FAILURE_EXCEPTIONS = (
    PydanticValidationError,
    UnexpectedModelBehavior,
    IncompleteToolCall,
)

from modules.backend.agents.mission_control.dispatch.result_builders import (
    append_feedback,
    failed_result,
    skipped_result,
)
from modules.backend.agents.mission_control.dispatch.step_executor import execute_task, verify_task
from modules.backend.agents.mission_control.gate import (
    GateAction,
    GateContext,
    GateReviewer,
    NoOpGate,
)
from modules.backend.agents.mission_control.outcome import (
    RetryHistoryEntry,
    TaskResult,
    TaskStatus,
    TaskTokenUsage,
    build_verification_outcome,
)
from modules.backend.agents.mission_control.roster import RosterAgentEntry
from modules.backend.core.logging import get_logger
from modules.backend.schemas.task_plan import TaskDefinition

logger = get_logger(__name__)


async def execute_with_retry(
    task: TaskDefinition,
    roster_entry: RosterAgentEntry,
    resolved_inputs: dict[str, Any],
    execute_agent_fn: Any,
    execution_id: str = "",
    gate: GateReviewer | None = None,
    mission_id: str | None = None,
    budget_usd: float = 0.0,
    session_id: str | None = None,
) -> TaskResult:
    """Execute a task with 3-tier verification and retry-with-feedback.

    gate is always provided by dispatch() — defaults to NoOpGate there.
    """
    _gate: GateReviewer = gate or NoOpGate()
    retry_budget = roster_entry.constraints.retry_budget
    retry_history: list[RetryHistoryEntry] = []
    instructions = task.instructions

    for attempt in range(retry_budget + 1):
        task_start = time.monotonic()

        try:
            output = await execute_task(
                task=task,
                roster_entry=roster_entry,
                resolved_inputs=resolved_inputs,
                execute_agent_fn=execute_agent_fn,
                instructions=instructions,
            )
        except QuotaExhaustedError as e:
            # Provider quota exhausted — no retry. Log via the helper
            # so the structured-log shape (provider, model, request_id,
            # remediation) matches every other quota log site in the
            # codebase. Catch sites add their situational context.
            duration = time.monotonic() - task_start
            log_provider_error(
                logger,
                e,
                event="Task failed (no retry): provider quota exhausted",
                task_id=task.task_id,
                agent=task.agent,
                mission_id=mission_id,
                attempt=attempt,
            )
            retry_history.append(
                RetryHistoryEntry(
                    attempt=attempt + 1,
                    failure_tier=0,
                    failure_reason=f"{type(e).__name__}: {str(e)[:400]}",
                    feedback_provided="",
                )
            )
            return failed_result(
                task,
                f"{type(e).__name__}: {str(e)[:300]}",
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )
        except (TransientProviderError, RateLimitedError, asyncio.TimeoutError) as e:
            # Transient infrastructure failure: SDK session loss,
            # rate-limit hiccup, or wall-clock timeout. Retry with
            # feedback if budget remains. RateLimitedError SHOULD use
            # exponential backoff once we have any provider that
            # actually raises it — current implementation retries
            # immediately like other transients.
            duration = time.monotonic() - task_start
            is_timeout = isinstance(e, asyncio.TimeoutError)
            failure_label = "Timeout" if is_timeout else type(e).__name__
            feedback_msg = (
                "Previous attempt timed out. Complete the task more efficiently."
                if is_timeout
                else "Previous attempt produced no response (infrastructure hiccup). Retry."
            )
            if is_timeout:
                logger.warning(
                    "Task execution: timeout, will retry",
                    extra={
                        "task_id": task.task_id,
                        "agent": task.agent,
                        "attempt": attempt,
                        "attempts_remaining": retry_budget - attempt,
                        "mission_id": mission_id,
                    },
                )
            else:
                # Transient ProviderError — use the helper so the
                # provider/model/request_id make it into the log.
                log_provider_error(
                    logger,
                    e,
                    event="Task execution: transient provider failure, will retry",
                    task_id=task.task_id,
                    agent=task.agent,
                    attempt=attempt,
                    attempts_remaining=retry_budget - attempt,
                    mission_id=mission_id,
                )
            if attempt < retry_budget:
                retry_history.append(
                    RetryHistoryEntry(
                        attempt=attempt + 1,
                        failure_tier=0,
                        failure_reason=failure_label,
                        feedback_provided=feedback_msg,
                    )
                )
                instructions = append_feedback(task.instructions, feedback_msg)
                continue

            status = TaskStatus.TIMEOUT if is_timeout else TaskStatus.FAILED
            return TaskResult(
                task_id=task.task_id,
                agent_name=task.agent,
                status=status,
                output_reference={},
                token_usage=TaskTokenUsage(),
                cost_usd=0.0,
                duration_seconds=round(duration, 2),
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )
        except _CONTRACT_FAILURE_EXCEPTIONS as e:
            # The model responded but its output doesn't satisfy the
            # contract (wrong shape, missing required fields, didn't
            # call the output tool). PydanticAI has already retried
            # internally; another full retry here will almost always
            # produce the same wrong shape. Fail fast so the operator
            # sees the actual schema delta instead of three identical
            # errors in a row.
            duration = time.monotonic() - task_start
            logger.error(
                "Task failed: output contract violation (no retry)",
                extra={
                    "task_id": task.task_id,
                    "agent": task.agent,
                    "exception_type": type(e).__name__,
                    "error": str(e)[:2000],
                    "attempt": attempt,
                    "mission_id": mission_id,
                },
            )
            retry_history.append(
                RetryHistoryEntry(
                    attempt=attempt + 1,
                    failure_tier=0,
                    failure_reason=f"{type(e).__name__}: {str(e)[:500]}",
                    feedback_provided="",
                )
            )
            return failed_result(
                task,
                str(e),
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )
        except Exception as e:
            duration = time.monotonic() - task_start
            is_token_limit = isinstance(e, UsageLimitExceeded)
            logger.error(
                "Task execution failed",
                extra={
                    "task_id": task.task_id,
                    "error": str(e),
                    "attempt": attempt,
                    "token_limit_exceeded": is_token_limit,
                    "mission_id": mission_id,
                },
            )
            if attempt < retry_budget and not is_token_limit:
                retry_history.append(
                    RetryHistoryEntry(
                        attempt=attempt + 1,
                        failure_tier=0,
                        failure_reason=str(e),
                        feedback_provided=f"Previous attempt failed: {e}",
                    )
                )
                instructions = append_feedback(
                    task.instructions,
                    f"Previous attempt failed with error: {e}. Avoid this error.",
                )
                continue

            return failed_result(
                task,
                str(e),
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )

        duration = time.monotonic() - task_start

        # The executor returns {"output": <agent data>, "_meta": <tokens/cost>}.
        # Split once here — everything downstream uses agent_output (unwrapped).
        meta = output.get("_meta", {})
        agent_output = output.get("output", output)
        if not isinstance(agent_output, dict):
            agent_output = {"result": str(agent_output)}

        token_usage = TaskTokenUsage(
            input=meta.get("input_tokens", 0),
            output=meta.get("output_tokens", 0),
            thinking=meta.get("thinking_tokens", 0),
        )
        cost_usd = meta.get("cost_usd", 0.0)

        verification = await verify_task(
            task=task,
            output=agent_output,
            roster_entry=roster_entry,
            execute_agent_fn=execute_agent_fn,
        )

        if not verification.passed:
            result = await _handle_verification_failure(
                task=task,
                output=agent_output,
                token_usage=token_usage,
                cost_usd=cost_usd,
                duration=duration,
                verification=verification,
                attempt=attempt,
                retry_budget=retry_budget,
                retry_history=retry_history,
                instructions=instructions,
                resolved_inputs=resolved_inputs,
                gate=_gate,
                mission_id=mission_id,
                budget_usd=budget_usd,
                execution_id=execution_id,
                session_id=session_id,
            )
            if isinstance(result, TaskResult):
                return result
            instructions = result
            continue

        result = await _handle_post_task_gate(
            task=task,
            output=agent_output,
            token_usage=token_usage,
            cost_usd=cost_usd,
            duration=duration,
            verification=verification,
            attempt=attempt,
            retry_budget=retry_budget,
            retry_history=retry_history,
            instructions=instructions,
            resolved_inputs=resolved_inputs,
            gate=_gate,
            mission_id=mission_id,
            budget_usd=budget_usd,
            execution_id=execution_id,
            session_id=session_id,
        )
        if isinstance(result, str):
            instructions = result
            continue
        return result

    return failed_result(task, "Exhausted retry budget")


async def _handle_verification_failure(
    task: TaskDefinition,
    output: dict,
    token_usage: TaskTokenUsage,
    cost_usd: float,
    duration: float,
    verification: Any,
    attempt: int,
    retry_budget: int,
    retry_history: list[RetryHistoryEntry],
    instructions: str,
    resolved_inputs: dict,
    gate: GateReviewer,
    mission_id: str,
    budget_usd: float,
    execution_id: str,
    session_id: str | None = None,
) -> TaskResult | str:
    """Handle a verification failure. Returns TaskResult to stop, or str (new instructions) to retry."""
    from modules.backend.agents.mission_control.verification import build_retry_feedback

    feedback = build_retry_feedback(verification, attempt=attempt + 1)

    if attempt < retry_budget:
        gate_decision = await gate.review(
            GateContext(
                gate_type="verification_failed",
                mission_id=mission_id,
                session_id=session_id,
                task_id=task.task_id,
                task_output=output,
                verification=build_verification_outcome(verification).model_dump(),
                current_instructions=instructions,
                current_inputs=resolved_inputs,
                budget_usd=budget_usd,
            )
        )
        if gate_decision.action == GateAction.ABORT:
            return failed_result(
                task,
                "Aborted at verification gate",
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )
        if gate_decision.action == GateAction.SKIP:
            return skipped_result(task, gate_decision.reason, execution_id=execution_id)
        if gate_decision.action == GateAction.MODIFY:
            return TaskResult(
                task_id=task.task_id,
                agent_name=task.agent,
                status=TaskStatus.SUCCESS,
                output_reference=output,
                token_usage=token_usage,
                cost_usd=cost_usd,
                duration_seconds=round(duration, 2),
                verification_outcome=build_verification_outcome(verification),
                retry_count=attempt,
                retry_history=retry_history,
                execution_id=execution_id,
            )

        retry_history.append(
            RetryHistoryEntry(
                attempt=feedback.get("attempt", attempt + 1),
                failure_tier=feedback.get("failure_tier", 0),
                failure_reason=feedback.get("failure_reason", "Verification failed"),
                feedback_provided=feedback.get("feedback_provided", ""),
            )
        )
        new_instructions = append_feedback(
            task.instructions,
            f"--- VERIFICATION FEEDBACK (attempt {attempt + 1}) ---\n"
            f"{feedback.get('feedback_provided', '')}\n"
            f"Please address the issues above and try again.",
        )
        if gate_decision.modified_instructions:
            new_instructions = gate_decision.modified_instructions
        return new_instructions

    return TaskResult(
        task_id=task.task_id,
        agent_name=task.agent,
        status=TaskStatus.FAILED,
        output_reference=output,
        token_usage=token_usage,
        cost_usd=cost_usd,
        duration_seconds=round(duration, 2),
        verification_outcome=build_verification_outcome(verification),
        retry_count=attempt,
        retry_history=retry_history,
        execution_id=execution_id,
    )


async def _handle_post_task_gate(
    task: TaskDefinition,
    output: dict,
    token_usage: TaskTokenUsage,
    cost_usd: float,
    duration: float,
    verification: Any,
    attempt: int,
    retry_budget: int,
    retry_history: list[RetryHistoryEntry],
    instructions: str,
    resolved_inputs: dict,
    gate: GateReviewer,
    mission_id: str,
    budget_usd: float,
    execution_id: str,
    session_id: str | None = None,
) -> TaskResult | str:
    """Handle the post-task gate review. Returns TaskResult to finish, or str (new instructions) to retry."""
    gate_decision = await gate.review(
        GateContext(
            gate_type="post_task",
            mission_id=mission_id,
            session_id=session_id,
            task_id=task.task_id,
            task_output=output,
            verification=build_verification_outcome(verification).model_dump(),
            current_instructions=instructions,
            current_inputs=resolved_inputs,
            total_cost_usd=cost_usd,
            budget_usd=budget_usd,
        )
    )
    if gate_decision.action == GateAction.ABORT:
        return failed_result(
            task,
            "Aborted at post_task gate",
            retry_count=attempt,
            retry_history=retry_history,
            execution_id=execution_id,
        )
    if gate_decision.action == GateAction.SKIP:
        return skipped_result(task, gate_decision.reason, execution_id=execution_id)
    if gate_decision.action == GateAction.RETRY and attempt < retry_budget:
        retry_history.append(
            RetryHistoryEntry(
                attempt=attempt + 1,
                failure_tier=0,
                failure_reason="Reviewer requested retry",
                feedback_provided=gate_decision.reason or "",
            )
        )
        return gate_decision.modified_instructions or append_feedback(
            task.instructions,
            gate_decision.reason or "Reviewer requested retry.",
        )

    context_updates = output.pop("context_updates", [])

    pqi = output.get("pqi")
    if isinstance(pqi, dict) and pqi.get("composite") is not None:
        context_updates.append(
            {
                "op": "add",
                "path": "current_state.pqi_score",
                "value": {
                    "composite": pqi["composite"],
                    "quality_band": pqi.get("quality_band"),
                    "dimensions": {
                        name: dim.get("score") for name, dim in pqi.get("dimensions", {}).items()
                    },
                    "file_count": pqi.get("file_count"),
                    "line_count": pqi.get("line_count"),
                },
                "reason": "PQI score from code quality audit",
            }
        )

    return TaskResult(
        task_id=task.task_id,
        agent_name=task.agent,
        status=TaskStatus.SUCCESS,
        output_reference=output,
        token_usage=token_usage,
        cost_usd=cost_usd,
        duration_seconds=round(duration, 2),
        verification_outcome=build_verification_outcome(verification),
        retry_count=attempt,
        retry_history=retry_history,
        execution_id=execution_id,
        context_updates=context_updates if isinstance(context_updates, list) else [],
    )
