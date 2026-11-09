"""steps_to_task_definitions (Plan 88 step 88.1.7)."""

import pytest

from modules.backend.core.exceptions import ValidationError
from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.services.workflow_task_mapping import steps_to_task_definitions

_OBJECTIVE = {
    "statement": "Test objective",
    "category": "testing",
    "owner": "test-owner",
    "priority": "normal",
}


def _workflow(steps: list[dict], parameters: list[dict] | None = None) -> WorkflowSchema:
    return WorkflowSchema(
        workflow_name="test.mapping.workflow",
        description="Mapping test",
        objective=_OBJECTIVE,
        parameters=parameters or [],
        steps=steps,
    )


def test_parameters_resolved_with_defaults():
    workflow = _workflow(
        [{"id": "fetch", "capability": "test.fetch", "input": {"limit": 5}}],
        parameters=[
            {"key": "topic", "label": "Topic", "type": "string", "required": True},
            {"key": "depth", "label": "Depth", "type": "number", "default": 2},
        ],
    )

    (task,) = steps_to_task_definitions(workflow, {"topic": "solar"})

    assert task.inputs.static == {
        "limit": 5,
        "workflow_parameters": {"topic": "solar", "depth": 2},
    }
    assert task.agent == "test.fetch.agent"


def test_human_input_step_rejected():
    workflow = _workflow(
        [
            {"id": "fetch", "capability": "test.fetch"},
            {
                "id": "confirm",
                "node_type": "human_input",
                "depends_on": ["fetch"],
                "human_input_config": {"prompt_message": "Proceed?"},
            },
        ]
    )

    with pytest.raises(ValidationError, match="confirm"):
        steps_to_task_definitions(workflow, {})


def test_dependencies_mapped_to_uuids():
    workflow = _workflow(
        [
            {"id": "fetch", "capability": "test.fetch"},
            {"id": "summarise", "capability": "test.summarise", "depends_on": ["fetch"]},
        ]
    )

    fetch, summarise = steps_to_task_definitions(workflow, {})

    assert fetch.task_id != "fetch"
    assert len(fetch.task_id) == 36
    assert summarise.dependencies == [fetch.task_id]
    assert fetch.dependencies == []
