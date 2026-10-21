"""
Tool: approve_plan_tasks

Auto-approve plan tasks on the mission owner's behalf, where the plan's
gate mode permits it.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import (
    ToolRefusal,
    run_tool,
    schedule_director_followup,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

_MAX_REASON_CHARS = 500


# Guarded so the agent layer does not import sqlalchemy at runtime (rule 011.1).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _validate_reason(reason: str) -> None:
    """Reject a missing or over-long approval reason."""
    if not reason or not reason.strip():
        raise ToolRefusal("reason is required — explain why you are approving")
    if len(reason) > _MAX_REASON_CHARS:
        raise ToolRefusal(f"reason too long ({len(reason)} chars, max {_MAX_REASON_CHARS})")


def _check_gate_mode(gate_mode: str | None) -> None:
    """Refuse auto-approval unless the gate mode delegates it to the Director.

    `interactive` (and an unset mode, which defaults to it) means the user
    opted into approving every task themselves, and must not be bypassed.
    """
    if gate_mode == "interactive" or gate_mode is None:
        raise ToolRefusal(
            "Plan is in interactive mode — the user approves "
            "tasks manually. Tell them to switch the plan to "
            "ai_assisted if they want you to auto-approve on "
            "their behalf.",
            {"gate_mode": gate_mode},
        )
    # Imported here, like the service below, so the agent layer does not load sqlalchemy at import.
    from modules.backend.services.mission_plan import gate_mode_auto_approves

    if not gate_mode_auto_approves(gate_mode):
        raise ToolRefusal(f"Unsupported gate_mode for auto-approval: {gate_mode}")


async def _approve_each(
    plan_service,
    plan_id: str,
    task_ids: list[str],
    user_id: str,
    mission_id: str,
) -> list[str]:
    """Approve each task, skipping any the service rejects.

    Skips are non-fatal by design: the aggregate outcome is reported
    accurately via the returned list, so a task_id that is absent from
    the plan or not in `proposed` state simply does not appear.

    Returns:
        Ids of every task the service transitioned, including the
        transitive upstream dependencies it approved as a side effect.
        May contain duplicates.
    """
    transitioned_ids: list[str] = []
    for task_id in task_ids:
        try:
            transitioned = await plan_service.approve_task(plan_id, task_id, user_id=user_id)
            transitioned_ids.extend(task.id for task in transitioned)
        except Exception as exc:  # noqa: BLE001
            # best-effort — non-fatal, this task is simply skipped; the
            # aggregate outcome is already reported accurately via the
            # returned ids, so no mission event is emitted (rule 014.1).
            logger.warning(
                "approve_plan_tasks: skipping task",
                extra={
                    "task_id": task_id,
                    "error": str(exc),
                    "mission_id": mission_id,
                },
            )
    return transitioned_ids


def _dedupe_preserving_order(task_ids: list[str]) -> list[str]:
    """Drop duplicates while keeping first-seen order."""
    seen: set[str] = set()
    return [t for t in task_ids if not (t in seen or seen.add(t))]


async def approve_plan_tasks(
    db_session: AsyncSession,
    mission_id: str,
    session_id: str | None,
    task_ids: list[str],
    reason: str,
) -> dict:
    """Approve plan tasks on the mission owner's behalf.

    Args:
        db_session: Active async session.
        mission_id: Mission owning the plan.
        session_id: Transport session, used to schedule the followup (P15).
        task_ids: Tasks to approve. Unknown or non-proposed ids are skipped.
        reason: Why these tasks are being approved. 1 to 500 characters.

    Returns:
        The plan id, gate mode, requested and transitioned task ids, and a
        message for the user.

    Raises:
        ToolRefusal: The reason is missing or too long, or the plan's gate
            mode does not permit auto-approval.
    """
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan import MissionPlanService

    _validate_reason(reason)

    mission = await MissionService(db_session).get_mission(mission_id)
    plan_service = MissionPlanService(db_session)
    plan = await plan_service.get_or_create_plan(mission_id)

    _check_gate_mode(plan.gate_mode)

    # The Director acts on behalf of the mission owner — use the owner's
    # user id so the tasks.approved_by_user_id FK is satisfied and the
    # audit trail attributes the approval to a real user, not an agent.
    transitioned = await _approve_each(
        plan_service,
        plan.id,
        task_ids,
        user_id=mission.owner_id,
        mission_id=mission_id,
    )

    # Save plan attributes before commit — commit() expires all ORM
    # attributes and any later access raises MissingGreenlet.
    plan_id = plan.id
    gate_mode = plan.gate_mode
    await db_session.commit()

    unique_transitioned = _dedupe_preserving_order(transitioned)

    logger.info(
        "Director auto-approved plan tasks",
        extra={
            "plan_id": plan_id,
            "requested_task_ids": task_ids,
            "transitioned_task_ids": unique_transitioned,
            "gate_mode": gate_mode,
            "reason": reason,
        },
    )

    # Wake the Director when the supervisor decides, so it reports back
    # to the user unprompted (Plan 51 Phase E).
    if unique_transitioned:
        await schedule_director_followup(
            db_session=db_session,
            session_id=session_id,
            mission_id=mission_id,
            trigger_event_types=["mission_plan.supervisor_decision"],
            prompt_template=(
                "The tasks I approved have been dispatched and the "
                "supervisor just decided: {action}. Reason: {reason}. "
                "Summarise the outcome for the user and suggest "
                "next steps."
            ),
        )

    return {
        "plan_id": plan_id,
        "gate_mode": gate_mode,
        "requested_task_ids": task_ids,
        "transitioned_task_ids": unique_transitioned,
        "reason": reason,
        "message": (
            f"Auto-approved {len(unique_transitioned)} task(s) "
            f"(including transitive dependencies). The user can "
            f"still veto by rejecting any task in the Plan tab."
        ),
    }


# ── Registry integration ─────────────────────────────────

_impl = approve_plan_tasks


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def approve_plan_tasks(
        ctx: RunContext[MissionDirectorDeps],
        task_ids: list[str],
        reason: str,
    ) -> str:
        """Auto-approve plan tasks on the user's behalf (ai_assisted /
        autonomous modes only — Plan 42 §10.4).

        Refuses when the plan is in `interactive` mode. In that mode the
        user has explicitly opted into approving every task themselves,
        and you must NOT bypass them. Tell the user to flip the plan
        to `ai_assisted` if they want you to auto-approve.

        The service's transitive dependency walk still runs — approving
        one task auto-approves its upstream dependencies if they were
        in `proposed` state. The returned transitioned_task_ids list
        reflects the full closure.

        When you call this tool, always explain WHY you are approving
        these tasks in the `reason` string. In `ai_assisted` mode this
        reason is surfaced to the user as part of the veto window UI
        (Phase 4b will wire the window itself; for now the reason is
        recorded in the tool log).

        Args:
            task_ids: List of task_id strings to approve. Each is
                approved individually via the service — if any task_id
                is not in the plan or is not in `proposed` state, it
                is silently skipped.
            reason: Short natural-language explanation of why you are
                approving these tasks. Must be 1-500 characters.
        """
        return await run_tool(
            ctx,
            "approve_plan_tasks",
            partial(
                _impl,
                ctx.deps.db_session,
                ctx.deps.mission_id,
                ctx.deps.session_id,
                task_ids,
                reason,
            ),
            rollback_on_error=True,
        )
