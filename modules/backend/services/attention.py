"""
Attention Service.

Collects what needs a person across the missions a user can see: gate requests waiting for a
decision, workflow steps waiting for input, tasks waiting for approval and tasks that failed.
One query per kind for all the missions, never one per mission.
"""

from modules.backend.models.mission_plan import AUTO_APPROVE_GATE_MODES
from modules.backend.models.task import TaskStatus
from modules.backend.repositories.mission import MissionRepository
from modules.backend.repositories.task import TaskGroup, TaskRepository
from modules.backend.schemas.attention import AttentionItem, AttentionKind, AttentionResponse
from modules.backend.services.base import BaseService
from modules.backend.services.mission_plan import MissionPlanService
from modules.backend.services.workflow_run import WorkflowRunService

# Links the client follows as given. A gate is answered from the active run card on the
# mission's Overview; a workflow's human-input request from its workflows page.
_PLAN_HREF = "/missions/{mission_id}/plan"
_OVERVIEW_HREF = "/missions/{mission_id}/overview"
_WORKFLOWS_HREF = "/missions/{mission_id}/workflows"

_MAX_DETAIL_CHARS = 200

# Blocking items first (a run or workflow is waiting on them), then the tasks.
_KIND_ORDER: dict[AttentionKind, int] = {
    "gate": 0,
    "human_input": 1,
    "task_approval": 2,
    "retry": 3,
}


def _tasks(count: int) -> str:
    return f"{count} task" if count == 1 else f"{count} tasks"


class AttentionService(BaseService):
    """What needs attention for a user."""

    async def for_user(self, user_id: str | None) -> AttentionResponse:
        """The attention items for a user's missions. `None` is an admin: every open mission."""
        missions = await MissionRepository(self._session).list_open_for_user(user_id)
        names = {str(m.id): m.name for m in missions}
        mission_ids = list(names)

        items: list[AttentionItem] = []
        items += self._gates(
            await MissionPlanService(self._session).list_pending_gate_requests(mission_ids), names
        )
        items += self._human_input(
            await WorkflowRunService(self._session).list_pending_human_input(mission_ids), names
        )
        tasks = TaskRepository(self._session)
        items += self._task_groups(
            await tasks.summarise_for_missions(
                mission_ids, TaskStatus.PROPOSED, exclude_gate_modes=AUTO_APPROVE_GATE_MODES
            ),
            names,
            kind="task_approval",
        )
        items += self._task_groups(
            await tasks.summarise_for_missions(mission_ids, TaskStatus.FAILED), names, kind="retry"
        )

        items.sort(key=lambda i: (_KIND_ORDER[i.kind], i.created_at, i.mission_name))
        pending_counts: dict[str, int] = {}
        for item in items:
            pending_counts[item.mission_id] = pending_counts.get(item.mission_id, 0) + 1
        return AttentionResponse(items=items, pending_counts=pending_counts)

    @staticmethod
    def _gates(requests: list, names: dict[str, str]) -> list[AttentionItem]:
        return [
            AttentionItem(
                mission_id=str(r.mission_id),
                mission_name=names[str(r.mission_id)],
                kind="gate",
                title="A gate is waiting for a decision",
                detail=r.gate_type.replace("_", " "),
                count=1,
                created_at=r.created_at,
                href=_OVERVIEW_HREF.format(mission_id=r.mission_id),
            )
            for r in requests
        ]

    @staticmethod
    def _human_input(requests: list, names: dict[str, str]) -> list[AttentionItem]:
        return [
            AttentionItem(
                mission_id=str(r.mission_id),
                mission_name=names[str(r.mission_id)],
                kind="human_input",
                title="A workflow is asking for input",
                detail=r.prompt_message[:_MAX_DETAIL_CHARS],
                count=1,
                created_at=r.created_at,
                href=_WORKFLOWS_HREF.format(mission_id=r.mission_id),
            )
            for r in requests
        ]

    @staticmethod
    def _task_groups(
        groups: list[TaskGroup],
        names: dict[str, str],
        *,
        kind: AttentionKind,
    ) -> list[AttentionItem]:
        approval = kind == "task_approval"
        return [
            AttentionItem(
                mission_id=g.mission_id,
                mission_name=names[g.mission_id],
                kind=kind,
                title=(
                    f"{_tasks(g.count)} awaiting approval"
                    if approval
                    else f"{_tasks(g.count)} failed"
                ),
                detail=(
                    "Approve or reject them on the Plan board."
                    if approval
                    else "Retry or review them on the Plan board."
                ),
                count=g.count,
                # Approvals are as old as the oldest one waiting; failures as recent as the latest.
                created_at=g.oldest_created_at if approval else g.latest_updated_at,
                href=_PLAN_HREF.format(mission_id=g.mission_id),
            )
            for g in groups
        ]
