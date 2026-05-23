"""
Workflow Architect Agent.

Conversational agent that designs workflows from mission briefs and
team composition. Uses tools to browse the agent catalog, validate
proposals, render graphs, and persist confirmed designs.

Entry points:
    create_agent(model) — for dispatch/registry integration
    run_conversational(agent, deps, message, message_history) — for service layer
"""

import json
import uuid
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from modules.backend.agents.mission.workflow.architect.deps import ArchitectAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.adapters import workflow_design
from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.logging import get_logger
from modules.backend.events.types import WorkflowGraphEvent

logger = get_logger(__name__)


def create_agent(model: Model, tool_names: list[str] | None = None) -> Agent:
    """Create the Workflow Architect agent instance.

    Model is always pre-built by the caller (AgentRegistry.get_instance).
    """
    system_prompt = assemble_instructions("mission.workflow.architect")

    agent: Agent[ArchitectAgentDeps, str] = Agent(
        model,
        instructions=system_prompt,
        deps_type=ArchitectAgentDeps,
    )

    # -- Tool: browse_catalog ------------------------------------------------

    @agent.tool
    async def browse_catalog(
        ctx: RunContext[ArchitectAgentDeps],
        agent_type: str | None = None,
        keyword: str | None = None,
    ) -> str:
        """Browse the agent catalog to discover available agents.

        Args:
            agent_type: Filter by type — 'vertical', 'horizontal', or 'system'.
            keyword: Search keyword to match against agent capabilities.

        Returns:
            JSON array of agent summaries with name, type, description,
            tools, keywords, and interface contract.
        """
        if ctx.deps.db_session is None:
            return json.dumps({"error": "No database session available"})

        agents = await workflow_design.browse_agent_catalog(
            ctx.deps.db_session,
            agent_type=agent_type,
            keyword=keyword,
            mission_id=ctx.deps.mission_id or None,
        )
        return json.dumps(agents, indent=2, default=str)

    # -- Tool: validate_workflow ---------------------------------------------

    @agent.tool
    async def validate_workflow(
        ctx: RunContext[ArchitectAgentDeps],
        steps: list[dict[str, Any]],
        objective: dict[str, Any] | None = None,
    ) -> str:
        """Validate a proposed workflow for correctness.

        Checks step schemas (field constraints, required fields),
        dependency graph (no cycles, no missing references, no self-deps),
        and output key uniqueness.

        Args:
            steps: Array of step definition dicts.
            objective: Optional workflow objective dict.

        Returns:
            JSON with 'valid' (bool), 'errors' (list), 'step_count' (int).
        """
        result = workflow_design.validate_workflow_proposal(steps, objective)
        return json.dumps(result, indent=2)

    # -- Tool: render_graph --------------------------------------------------

    @agent.tool
    async def render_graph(
        ctx: RunContext[ArchitectAgentDeps],
        steps: list[dict[str, Any]],
        workflow_name: str = "draft",
    ) -> str:
        """Emit the workflow graph for visual rendering in the UI.

        Converts the step list into a nodes + edges structure and
        publishes a WorkflowGraphEvent for the frontend.

        Args:
            steps: Array of step definition dicts.
            workflow_name: Display name for the graph.

        Returns:
            Confirmation message with node and edge counts.
        """
        graph = workflow_design.build_graph_structure(steps)

        if ctx.deps.on_event and ctx.deps.session_id:
            event = WorkflowGraphEvent(
                session_id=uuid.UUID(ctx.deps.session_id)
                if isinstance(ctx.deps.session_id, str)
                else ctx.deps.session_id,
                source="workflow_architect",
                graph_data=graph,
                workflow_name=workflow_name,
                step_count=len(graph.get("nodes", [])),
            )
            await ctx.deps.on_event(event)

        return json.dumps({
            "rendered": True,
            "nodes": len(graph.get("nodes", [])),
            "edges": len(graph.get("edges", [])),
        })

    # -- Tool: list_workflows ------------------------------------------------

    @agent.tool
    async def list_workflows(
        ctx: RunContext[ArchitectAgentDeps],
    ) -> str:
        """List all workflow definitions in the current mission.

        Use this to see what workflows already exist before creating
        or updating one.

        Returns:
            JSON array of workflow summaries with id, name, version,
            step_count, enabled, locked_at, and designed_by.
        """
        if ctx.deps.db_session is None:
            return json.dumps({"error": "No database session available"})
        if not ctx.deps.mission_id:
            return json.dumps({"error": "No mission_id in context"})

        workflows = await workflow_design.list_mission_workflows(
            ctx.deps.db_session,
            mission_id=ctx.deps.mission_id,
        )
        return json.dumps(workflows, indent=2, default=str)

    # -- Tool: save_workflow -------------------------------------------------

    @agent.tool
    async def save_workflow(
        ctx: RunContext[ArchitectAgentDeps],
        name: str,
        description: str,
        objective: dict[str, Any],
        steps: list[dict[str, Any]],
        trigger_type: str = "on_demand",
        max_cost_usd: float | None = None,
    ) -> str:
        """Save and lock the confirmed workflow definition.

        Only call this when the user has explicitly confirmed the design.
        The workflow is validated, saved to the database, and locked.

        Args:
            name: Workflow name (lowercase, hyphens, underscores).
            description: Human-readable description.
            objective: Workflow objective dict with statement, category, owner, priority.
            steps: Validated array of step definition dicts.
            trigger_type: 'on_demand', 'schedule', or 'event'.
            max_cost_usd: Budget ceiling for the workflow.

        Returns:
            JSON with saved workflow id, name, and confirmation.
        """
        max_cost_usd = max_cost_usd or get_default_budget_usd()

        if ctx.deps.db_session is None:
            return json.dumps({"error": "No database session available"})

        if not ctx.deps.mission_id:
            return json.dumps({"error": "No mission_id in context"})

        validation = workflow_design.validate_workflow_proposal(steps, objective)
        if not validation["valid"]:
            return json.dumps({
                "error": "Workflow validation failed",
                "details": validation["errors"],
            })

        try:
            result = await workflow_design.persist_workflow(
                ctx.deps.db_session,
                mission_id=ctx.deps.mission_id,
                name=name,
                description=description,
                objective=objective,
                steps=steps,
                trigger_config={"type": trigger_type},
                budget_config={"max_cost_usd": max_cost_usd},
            )
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(
                "Failed to save workflow",
                extra={"error": str(e), "mission_id": ctx.deps.mission_id},
            )
            return json.dumps({"error": str(e)})

    # -- Tool: get_workflow --------------------------------------------------

    @agent.tool
    async def get_workflow(
        ctx: RunContext[ArchitectAgentDeps],
        name: str,
    ) -> str:
        """Fetch the full step and edge definitions of an existing workflow.

        Use this before proposing changes so you have the current state.

        Args:
            name: Workflow name to fetch.

        Returns:
            JSON with full workflow definition including all steps and edges,
            or an error message if not found.
        """
        if ctx.deps.db_session is None:
            return json.dumps({"error": "No database session available"})
        if not ctx.deps.mission_id:
            return json.dumps({"error": "No mission_id in context"})

        result = await workflow_design.get_workflow_definition(
            ctx.deps.db_session,
            mission_id=ctx.deps.mission_id,
            name=name,
        )
        if result is None:
            return json.dumps({"error": f"Workflow '{name}' not found"})
        return json.dumps(result, indent=2, default=str)

    # -- Tool: update_workflow -----------------------------------------------

    @agent.tool
    async def update_workflow(
        ctx: RunContext[ArchitectAgentDeps],
        name: str,
        description: str | None = None,
        objective: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        trigger_type: str | None = None,
        max_cost_usd: float | None = None,
    ) -> str:
        """Update an existing workflow definition.

        Looks up the workflow by name in the current mission, applies
        the provided changes, re-validates the step graph, bumps the
        version, and re-locks. Only call this when the user has
        explicitly confirmed the changes.

        Args:
            name: Name of the existing workflow to update.
            description: New description (omit to keep current).
            objective: New objective dict (omit to keep current).
            steps: New step array (omit to keep current).
            trigger_type: New trigger type (omit to keep current).
            max_cost_usd: New budget ceiling (omit to keep current).

        Returns:
            JSON with updated workflow id, name, version, and confirmation.
        """
        if ctx.deps.db_session is None:
            return json.dumps({"error": "No database session available"})
        if not ctx.deps.mission_id:
            return json.dumps({"error": "No mission_id in context"})

        updates: dict[str, Any] = {}
        if description is not None:
            updates["description"] = description
        if objective is not None:
            updates["objective"] = objective
        if steps is not None:
            updates["steps"] = steps
        if trigger_type is not None:
            updates["trigger_config"] = {"type": trigger_type}
        if max_cost_usd is not None:
            updates["budget_config"] = {"max_cost_usd": max_cost_usd}

        if not updates:
            return json.dumps({"error": "No changes provided"})

        try:
            result = await workflow_design.update_workflow(
                ctx.deps.db_session,
                mission_id=ctx.deps.mission_id,
                name=name,
                updates=updates,
            )
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error(
                "Failed to update workflow",
                extra={"error": str(e), "mission_id": ctx.deps.mission_id},
            )
            return json.dumps({"error": str(e)})

    logger.info("Workflow architect agent created", extra={"model": str(model)})
    return agent


async def run_conversational(
    agent: Agent,
    deps: ArchitectAgentDeps,
    message: str,
    *,
    message_history: list | None = None,
    usage_limits: UsageLimits | None = None,
) -> dict[str, Any]:
    """Run the architect agent with conversation history.

    Returns the response text, usage stats, and any tool results.
    Used by the architect service for multi-turn chat.
    """
    result = await agent.run(
        message,
        deps=deps,
        message_history=message_history,
        usage_limits=usage_limits,
    )

    return {
        "response": result.output,
        "usage": result.usage() if hasattr(result, "usage") else None,
        "all_messages": result.all_messages() if hasattr(result, "all_messages") else [],
    }
