"""Workflow step to task mapping (Plan 88 step 88.1.7).

Turns a workflow definition's steps into TaskDefinitions. Shared by
WorkflowRunService (Kanban persistence) and MissionRunService.plan
(workflow-definition runs). Pure: no I/O.
"""

import uuid

from modules.backend.core.exceptions import ValidationError
from modules.backend.schemas.task_plan import TaskDefinition, TaskInputs
from modules.backend.schemas.workflow import WorkflowSchema


def steps_to_task_definitions(workflow: WorkflowSchema, parameters: dict) -> list[TaskDefinition]:
    """One TaskDefinition per step, in step order, with fresh UUID task ids.

    Each task's static inputs carry the step input plus the resolved
    workflow parameters (supplied value, else the parameter default).
    Dependencies map step ids to the new task ids. Only agent steps are
    supported; any other node type raises ValidationError naming the step.
    """
    for step in workflow.steps:
        if step.node_type != "agent_step":
            raise ValidationError(
                f"Workflow step {step.id!r} has node type {step.node_type!r}; "
                "only agent_step can become a task"
            )

    resolved = {p.key: parameters.get(p.key, p.default) for p in workflow.parameters}
    step_uuid_map = {step.id: str(uuid.uuid4()) for step in workflow.steps}

    tasks: list[TaskDefinition] = []
    for step in workflow.steps:
        # capability is the short form (e.g. "research.synthesizer");
        # the roster keys agents by full name "<capability>.agent".
        # Must match the dispatch path in workflow_run_waves.py
        # so retry/redispatch validates against the same name.
        agent = f"{step.capability}.agent" if step.capability else f"workflow:{step.node_type}"
        tasks.append(
            TaskDefinition(
                task_id=step_uuid_map[step.id],
                agent=agent,
                description=step.description or step.label or step.id,
                instructions=step.description or f"Workflow step: {step.id}",
                dependencies=[step_uuid_map[d] for d in step.depends_on if d in step_uuid_map],
                inputs=TaskInputs(static={**(step.input or {}), "workflow_parameters": resolved}),
            )
        )
    return tasks
