"""
Mission Director Agent.

Conversational delegate that manages the mission on behalf of the user.
Uses tools to query mission state (team, history, context, workflows)
and trigger actions (run objectives, run workflows).

Entry point:
    create_agent(model) — for registry/chat integration

Plan 84 Phase 5.3: tool bodies live in sibling tools_*.py modules that
create_agent imports and registers, per P7 (implementation vs
registration). This file keeps create_agent itself plus the three
@agent.instructions hooks, which inject runtime context rather than
act as callable tools.
"""

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tools_knowledge import register_knowledge_tools
from modules.backend.agents.mission.director.tools_mission import register_mission_tools
from modules.backend.agents.mission.director.tools_plan import register_plan_tools
from modules.backend.agents.mission.director.tools_workflow import register_workflow_tools
from modules.backend.agents.mission_control.helpers import _build_model, assemble_instructions
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(model: str | Model, tool_names: list[str] | None = None) -> Agent:
    """Create the Mission Director agent with all tools registered."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("mission", "director")

    agent: Agent[MissionDirectorDeps, str] = Agent(
        model,
        instructions=system_prompt,
        deps_type=MissionDirectorDeps,
    )

    register_mission_tools(agent)
    register_workflow_tools(agent)
    register_knowledge_tools(agent)
    register_plan_tools(agent)

    # ── Runtime Context Injection (Plan 57 Phase C) ────────

    @agent.instructions
    async def inject_current_intent(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Inject the current intent into every Director turn."""
        from modules.backend.agents.adapters.intent import restate_current_intent

        try:
            intent_text = await restate_current_intent(ctx.deps.mission_id)
            if intent_text and "No intent set" not in intent_text:
                return f"\n[Mission Intent]\n{intent_text}\n"
        except Exception:
            logger.debug("intent restatement failed", exc_info=True)
        return ""

    @agent.instructions
    async def inject_capabilities(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Inject team capabilities so the Director knows what it can delegate.

        Groups agents by domain and summarises what the team can do.
        The Director sees this before thinking, so it knows:
        - "I have research agents → I can delegate research via run_objective"
        - "I have no security agents → I cannot run scans"
        - "I do NOT have web access, code tools, or search — I delegate ALL work"
        """
        if not ctx.deps.db_session or not ctx.deps.mission_id:
            return ""

        try:
            from modules.backend.services.mission_team import MissionTeamService

            svc = MissionTeamService(ctx.deps.db_session)
            details = await svc.list_team_with_details(ctx.deps.mission_id)
            if not details:
                return ""

            # Group by domain, skip self (director) and infrastructure agents
            skip = {"mission.director.agent", "mission.supervisor.agent"}
            domains: dict[str, list[str]] = {}
            for d in details:
                name = d["agent_name"]
                if name in skip:
                    continue
                domain = name.split(".")[0]
                desc = (d["description"] or "")[:80]
                domains.setdefault(domain, []).append(f"{name}: {desc}")

            if not domains:
                return ""

            parts = ["[Team Capabilities]"]
            parts.append(
                "You are a COORDINATOR. You do NOT research, code, scan, or fetch URLs. "
                "You delegate ALL work to these agents via run_objective or refine_plan:"
            )
            for domain, agents in sorted(domains.items()):
                parts.append(f"  {domain}:")
                for a in agents:
                    parts.append(f"    - {a}")

            # Summarise what domains are available
            can_do = sorted(domains.keys())
            parts.append(f"You CAN delegate: {', '.join(can_do)}")
            parts.append("[End Team Capabilities]")
            return "\n".join(parts)

        except Exception:
            return ""

    @agent.instructions
    async def inject_orientation(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Inject plan state, active runs, and recent artifacts every turn.

        Gives the Director situational awareness without tool calls.
        The model sees this in the system prompt before it starts thinking,
        so it knows whether to plan, dispatch, show artifacts, or wait.
        """
        if not ctx.deps.db_session or not ctx.deps.mission_id:
            return ""

        parts: list[str] = []
        mission_id = ctx.deps.mission_id

        try:
            from modules.backend.services.mission_plan import MissionPlanService

            plan_svc = MissionPlanService(ctx.deps.db_session)
            plan = await plan_svc.get_or_create_plan(mission_id)

            # Plan summary
            tasks = await plan_svc.get_tasks(plan.id)
            counts: dict[str, int] = {}
            for t in tasks:
                s = t.status.value if hasattr(t.status, "value") else str(t.status)
                counts[s] = counts.get(s, 0) + 1

            gate = plan.gate_mode or "autonomous"
            parts.append("[Plan State]")
            parts.append(f"Version: {plan.version} | Gate: {gate} | Tasks: {len(tasks)}")
            if counts:
                parts.append("Status: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
            if plan.budget_usd_ceiling:
                parts.append(
                    f"Budget: ${plan.total_spent_usd:.2f} / ${plan.budget_usd_ceiling:.2f}"
                )

            # Active runs
            from sqlalchemy import func, select

            from modules.backend.models.execution_record import (
                ExecutionRecord,
                ExecutionRecordStatus,
            )

            stmt = (
                select(func.count())
                .select_from(ExecutionRecord)
                .where(
                    ExecutionRecord.mission_id == mission_id,
                    ExecutionRecord.status == ExecutionRecordStatus.RUNNING,
                )
            )
            active_count = (await ctx.deps.db_session.execute(stmt)).scalar() or 0
            if active_count:
                parts.append(
                    f"Active runs: {active_count} (agents are executing — do NOT start new work)"
                )

            # Recent artifacts
            from modules.backend.models.mission_artifact import MissionArtifact

            stmt = (
                select(MissionArtifact.title, MissionArtifact.artifact_type)
                .where(MissionArtifact.mission_id == mission_id)
                .order_by(MissionArtifact.created_at.desc())
                .limit(3)
            )
            artifacts = (await ctx.deps.db_session.execute(stmt)).all()
            if artifacts:
                parts.append("Recent artifacts:")
                for title, atype in artifacts:
                    parts.append(f"  - [{atype}] {title}")

            parts.append("[End Plan State]")
        except Exception:
            logger.debug("plan state injection failed", exc_info=True)

        return "\n".join(parts) if parts else ""

    # Populate list_tools with the registered tool names + descriptions
    # so the Director can introspect its own capabilities at runtime.
    # list_tools itself now lives in tools_mission.py — reach its raw
    # function via the toolset (not a closure variable) to set the
    # attribute it reads back at call time.
    tool_info = []
    for t in agent._function_toolset.tools.values():
        tool_info.append(
            {
                "name": t.name,
                "description": (t.description or "")[:120],
            }
        )
    list_tools_fn = agent._function_toolset.tools["list_tools"].function
    list_tools_fn._registered_tools = sorted(tool_info, key=lambda x: x["name"])

    return agent
