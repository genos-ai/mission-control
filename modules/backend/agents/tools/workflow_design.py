"""
Workflow design tool implementations.

Pure functions for the Workflow Architect's tools. Each function
receives a database session (or schema objects) and returns structured
data. No PydanticAI dependency — tools in agent.py delegate here.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def browse_agent_catalog(
    session: AsyncSession,
    *,
    agent_type: str | None = None,
    keyword: str | None = None,
    mission_id: str | None = None,
) -> list[dict[str, Any]]:
    """Query the agent catalog and return full agent profiles.

    Filters by agent_type and/or keyword. When mission_id is provided,
    each entry includes an ``on_team`` boolean indicating whether the
    agent is assigned to the mission.
    """
    from modules.backend.services.agent_catalog import AgentCatalogService

    svc = AgentCatalogService(session)

    if keyword:
        agents = await svc.search_by_keyword(keyword)
    elif agent_type:
        agents = await svc.list_by_type(agent_type, enabled_only=True)
    else:
        agents = await svc.list_catalog(enabled_only=True, visibility="public")

    # Resolve team membership if mission_id is available
    team_names: set[str] = set()
    if mission_id:
        from modules.backend.repositories.agent_catalog import AgentCatalogRepository
        from modules.backend.services.mission_team import MissionTeamService

        team_svc = MissionTeamService(session)
        catalog_repo = AgentCatalogRepository(session)
        members = await team_svc.list_team(mission_id)
        for m in members:
            entry = await catalog_repo.get_by_id_or_none(m.agent_catalog_id)
            if entry:
                team_names.add(entry.agent_name)

    return [
        {
            "agent_name": a.agent_name,
            "agent_type": a.agent_type,
            "description": a.description,
            "version": a.version,
            "tools": a.tools or [],
            "keywords": a.keywords or [],
            "scope": a.scope or {},
            "interface": a.interface,
            "constraints": a.constraints or {},
            "enabled": a.enabled,
            "chat_enabled": a.chat_enabled,
            "on_team": a.agent_name in team_names,
        }
        for a in agents
    ]


def validate_workflow_proposal(
    steps: list[dict[str, Any]],
    objective: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a proposed workflow's step definitions and dependency graph.

    Returns a dict with 'valid' (bool) and 'errors' (list of strings).
    Uses the same validation logic as the production WorkflowSchema.
    """
    errors: list[str] = []

    if not steps:
        return {"valid": False, "errors": ["Workflow must have at least one step"]}

    from modules.backend.schemas.workflow import WorkflowStepSchema

    validated_steps = []
    for i, step_data in enumerate(steps):
        try:
            validated = WorkflowStepSchema(**step_data)
            validated_steps.append(validated)
        except (TypeError, ValueError, KeyError) as e:
            errors.append(f"Step {i} (id={step_data.get('id', '?')}): {e}")

    if errors:
        return {"valid": False, "errors": errors}

    step_ids = {s.id for s in validated_steps}

    if len(step_ids) != len(validated_steps):
        seen: set[str] = set()
        for s in validated_steps:
            if s.id in seen:
                errors.append(f"Duplicate step ID: '{s.id}'")
            seen.add(s.id)

    for s in validated_steps:
        for dep_id in s.depends_on:
            if dep_id not in step_ids:
                errors.append(
                    f"Step '{s.id}' depends on '{dep_id}' which does not exist"
                )
        if s.id in s.depends_on:
            errors.append(f"Step '{s.id}' depends on itself")

    if not errors:
        in_degree: dict[str, int] = {s.id: 0 for s in validated_steps}
        graph: dict[str, list[str]] = {s.id: [] for s in validated_steps}
        for s in validated_steps:
            for dep_id in s.depends_on:
                graph[dep_id].append(s.id)
                in_degree[s.id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        sorted_count = 0
        while queue:
            node = queue.pop(0)
            sorted_count += 1
            for child in graph[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if sorted_count != len(validated_steps):
            errors.append("Dependency cycle detected in step graph")

    output_keys: set[str] = set()
    for s in validated_steps:
        if s.output_mapping and s.output_mapping.summary_key:
            if s.output_mapping.summary_key in output_keys:
                errors.append(
                    f"Duplicate output key '{s.output_mapping.summary_key}' "
                    f"in step '{s.id}'"
                )
            output_keys.add(s.output_mapping.summary_key)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "step_count": len(validated_steps),
    }


def build_graph_structure(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert a step list into a graph structure for frontend rendering.

    Returns {nodes: [...], edges: [...]} where each node has id, label,
    capability, and each edge has source, target.
    """
    nodes = []
    edges = []

    for step in steps:
        step_id = step.get("id", "unknown")
        nodes.append({
            "id": step_id,
            "label": step.get("description", step_id),
            "capability": step.get("capability", ""),
            "complexity_tier": step.get("complexity_tier", "simple"),
            "environment": step.get("environment", "local"),
        })

        for dep_id in step.get("depends_on", []):
            edges.append({
                "source": dep_id,
                "target": step_id,
            })

    return {"nodes": nodes, "edges": edges}


async def persist_workflow(
    session: AsyncSession,
    *,
    mission_id: str,
    name: str,
    description: str,
    objective: dict[str, Any],
    steps: list[dict[str, Any]],
    trigger_config: dict[str, Any] | None = None,
    budget_config: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and save a workflow definition to the database.

    Returns the saved workflow's id and name, or raises on failure.
    """
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    svc = WorkflowDefinitionService(session)
    workflow = await svc.create_workflow(
        mission_id=mission_id,
        name=name,
        description=description,
        objective=objective,
        steps=steps,
        trigger_config=trigger_config,
        budget_config=budget_config,
        context=context,
        designed_by="architect:workflow_architect",
    )

    locked = await svc.lock_workflow(workflow.id)

    logger.info(
        "Workflow saved by architect",
        extra={
            "workflow_id": locked.id,
            "workflow_name": locked.name,
            "mission_id": mission_id,
        },
    )

    return {
        "id": locked.id,
        "name": locked.name,
        "mission_id": locked.mission_id,
        "locked_at": locked.locked_at,
        "step_count": len(steps),
    }
