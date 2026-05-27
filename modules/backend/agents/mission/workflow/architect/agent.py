"""
Workflow Architect Agent.

Conversational agent that designs workflows from mission briefs and
team composition. Uses tools to browse the agent catalog, validate
proposals, render graphs, and persist confirmed designs.

Entry points:
    create_agent(model) — for dispatch/registry integration
    run_conversational(agent, deps, message, message_history) — for service layer
"""

import functools
import json
import uuid
from typing import Any, Callable

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from modules.backend.agents.mission.workflow.architect.deps import ArchitectAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.adapters import workflow_design
from modules.backend.core.config import get_default_budget_usd
from modules.backend.core.logging import get_logger
from modules.backend.events.types import (
    AgentToolCallEvent,
    AgentToolResultEvent,
    WorkflowGraphEvent,
)

logger = get_logger(__name__)

_ARCHITECT_AGENT_ID = "mission.workflow.architect"


def _observed(tool_name: str) -> Callable:
    """Wrap an architect tool to emit AgentToolCall/Result events.

    Surfaces every tool invocation to the chat endpoint via deps.on_event,
    so the user can see exactly which tools ran and what they returned.
    Without this, the architect can hallucinate tool calls that never
    happened (e.g. fabricated "permission denied" errors on tools it does
    not have).
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(ctx: RunContext[ArchitectAgentDeps], *args, **kwargs):
            sid = _session_uuid(ctx.deps.session_id)
            # Skip emission when there is no listener or no valid session.
            # Session_id is None for stateless HTTP architect calls; the
            # endpoint still captures events via on_event regardless.
            should_emit = ctx.deps.on_event is not None
            call_id = str(uuid.uuid4())
            if should_emit and sid is not None:
                await _emit(ctx, AgentToolCallEvent(
                    session_id=sid,
                    source="workflow_architect",
                    agent_id=_ARCHITECT_AGENT_ID,
                    tool_name=tool_name,
                    tool_args=kwargs or {},
                    tool_call_id=call_id,
                ))
            try:
                result = await fn(ctx, *args, **kwargs)
            except Exception as e:
                if should_emit and sid is not None:
                    await _emit(ctx, AgentToolResultEvent(
                        session_id=sid,
                        source="workflow_architect",
                        agent_id=_ARCHITECT_AGENT_ID,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        result=None,
                        status="error",
                        error_detail=str(e)[:500],
                    ))
                raise
            if should_emit and sid is not None:
                status = "error" if _looks_like_error(result) else "success"
                await _emit(ctx, AgentToolResultEvent(
                    session_id=sid,
                    source="workflow_architect",
                    agent_id=_ARCHITECT_AGENT_ID,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    result=str(result)[:500],
                    status=status,
                ))
            return result

        return wrapper

    return decorator


async def _emit(ctx: RunContext[ArchitectAgentDeps], event: Any) -> None:
    """Best-effort event emission — never blocks the tool."""
    try:
        await ctx.deps.on_event(event)
    except Exception:
        logger.debug("Failed to emit architect tool event", exc_info=True)


def _session_uuid(session_id: Any) -> uuid.UUID | None:
    """Coerce a session id to UUID, returning None for missing/invalid input
    so the caller can skip event emission gracefully."""
    if session_id is None:
        return None
    if isinstance(session_id, uuid.UUID):
        return session_id
    try:
        return uuid.UUID(str(session_id))
    except (ValueError, TypeError):
        return None


def _looks_like_error(result: Any) -> bool:
    """Detect tool error returns. Architect tools return json.dumps({'error': ...})
    on failure rather than raising — flag those as status=error."""
    if not isinstance(result, str):
        return False
    head = result[:80].lower()
    return '"error"' in head


def _summarise_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full workflow definition to a compact, model-friendly shape.

    Each step keeps id, node_type, capability/resolver/condition,
    depends_on, and (when present) output_mapping in its exact schema
    shape — so a round-trip through update_workflow preserves every
    field. Strips only the heavy content fields (step `input`, prompts,
    schemas, full edge labels) that bloat context without helping the
    model explain or modify the workflow.
    """
    steps = workflow.get("steps") or []
    edges = workflow.get("edges") or []

    step_summaries: list[dict[str, Any]] = []
    for step in steps:
        node_type = step.get("node_type") or "agent_step"
        entry: dict[str, Any] = {
            "id": step.get("id"),
            "node_type": node_type,
            "depends_on": step.get("depends_on") or [],
        }
        if node_type == "agent_step" and step.get("capability"):
            entry["capability"] = step["capability"]
        # Pass decision/condition configs through whole — they carry
        # required cross-field invariants (e.g. agent resolver needs
        # model+prompt) that a partial copy would silently violate.
        if node_type == "decision" and step.get("decision_config"):
            entry["decision_config"] = step["decision_config"]
        if node_type == "condition" and step.get("condition_config"):
            entry["condition_config"] = step["condition_config"]
        # Preserve output_mapping in its exact schema shape so the model
        # can copy the step into an update_workflow payload without
        # restructuring. (`step.output_mapping.summary_key` is the schema
        # path — hoisting it broke round-trip updates in v2 of
        # research.deep-research-pipeline.)
        output_mapping = step.get("output_mapping") or {}
        if output_mapping.get("summary_key") or output_mapping.get("field_mappings"):
            preserved: dict[str, Any] = {}
            if output_mapping.get("summary_key"):
                preserved["summary_key"] = output_mapping["summary_key"]
            if output_mapping.get("field_mappings"):
                preserved["field_mappings"] = output_mapping["field_mappings"]
            entry["output_mapping"] = preserved
        step_summaries.append(entry)

    return {
        "id": workflow.get("id"),
        "name": workflow.get("name"),
        "description": workflow.get("description"),
        "version": workflow.get("version"),
        "enabled": workflow.get("enabled"),
        "step_count": len(steps),
        "edge_count": len(edges),
        "steps": step_summaries,
        "hint": (
            "Summary view: step fields use their exact schema shape so "
            "you can copy them straight into an update_workflow payload. "
            "Call get_workflow(name, verbose=True) when you need step "
            "inputs, prompts, full configs, or edges."
        ),
    }


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
    @_observed("browse_catalog")
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
    @_observed("validate_workflow")
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
    @_observed("render_graph")
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
    @_observed("list_workflows")
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
    @_observed("save_workflow")
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
    @_observed("get_workflow")
    async def get_workflow(
        ctx: RunContext[ArchitectAgentDeps],
        name: str,
        verbose: bool = False,
    ) -> str:
        """Fetch an existing workflow definition.

        Default returns a compact summary (~1–2 KB) — enough to explain
        the pipeline to the user. Pass verbose=True only when you need
        full step inputs, prompts, and configs (e.g. before calling
        update_workflow with a precise edit). Full payloads can exceed
        20 KB and bloat the conversation.

        Args:
            name: Workflow name to fetch.
            verbose: When True, return full step/edge JSON. Default False.

        Returns:
            JSON summary or full definition. Includes a `hint` field
            pointing at verbose mode when summary is returned.
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

        if verbose:
            return json.dumps(result, indent=2, default=str)
        return json.dumps(_summarise_workflow(result), indent=2, default=str)

    # -- Tool: update_workflow -----------------------------------------------

    @agent.tool
    @_observed("update_workflow")
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
