"""
Workflow Service.

Loads workflow YAML files from config/workflow_templates/, validates against
WorkflowSchema, resolves capability references to agent names, and
generates Mission briefs from workflow steps.

This service is stateless — it reads from the filesystem and agent
registry. It does not touch the database.
"""

from pathlib import Path
from typing import Any

import yaml

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.schemas.workflow import WorkflowSchema, WorkflowStepSchema

logger = get_logger(__name__)


class WorkflowService:
    """Load, validate, and resolve workflows from config/workflow_templates/."""

    def __init__(self, agent_registry: dict[str, Any] | None = None) -> None:
        self._project_root = find_project_root()
        self._agent_registry = agent_registry
        self._workflows: dict[str, WorkflowSchema] = {}

    def load_workflows(self) -> dict[str, WorkflowSchema]:
        """Load all workflow YAML files from the configured directory.

        Scans recursively for *.yaml files, validates each against
        WorkflowSchema, and returns a dict keyed by workflow_name.
        Invalid workflows are logged and skipped (not fatal).
        """
        app_config = get_app_config()
        workflows_dir = self._project_root / app_config.workflows.workflows_dir

        if not workflows_dir.exists():
            logger.warning(
                "Workflows directory not found",
                extra={"path": str(workflows_dir)},
            )
            return {}

        loaded: dict[str, WorkflowSchema] = {}

        for yaml_path in sorted(workflows_dir.rglob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if not raw or not isinstance(raw, dict):
                    continue

                workflow = WorkflowSchema(**raw)

                if workflow.workflow_name in loaded:
                    logger.warning(
                        "Duplicate workflow name, skipping",
                        extra={
                            "workflow_name": workflow.workflow_name,
                            "path": str(yaml_path),
                        },
                    )
                    continue

                max_steps = app_config.workflows.max_steps_per_workflow
                if len(workflow.steps) > max_steps:
                    logger.warning(
                        "Workflow exceeds max steps, skipping",
                        extra={
                            "workflow_name": workflow.workflow_name,
                            "step_count": len(workflow.steps),
                            "max_steps": max_steps,
                        },
                    )
                    continue

                max_budget = app_config.workflows.max_budget_usd
                if workflow.budget.max_cost_usd > max_budget:
                    logger.warning(
                        "Workflow budget exceeds system cap, capping",
                        extra={
                            "workflow_name": workflow.workflow_name,
                            "requested": workflow.budget.max_cost_usd,
                            "capped_to": max_budget,
                        },
                    )
                    workflow.budget.max_cost_usd = max_budget

                loaded[workflow.workflow_name] = workflow
                logger.debug(
                    "Workflow loaded",
                    extra={
                        "workflow_name": workflow.workflow_name,
                        "version": workflow.version,
                        "steps": len(workflow.steps),
                        "enabled": workflow.enabled,
                    },
                )

            except (OSError, ValueError, KeyError, yaml.YAMLError) as e:
                logger.warning(
                    "Failed to load workflow",
                    extra={"path": str(yaml_path), "error": str(e)},
                )
                continue

        self._workflows = loaded
        logger.info(
            "Workflows loaded",
            extra={"count": len(loaded), "names": list(loaded.keys())},
        )
        return loaded

    def list_workflows(self, enabled_only: bool = True) -> list[WorkflowSchema]:
        """List available workflows."""
        if not self._workflows:
            self.load_workflows()

        workflows = list(self._workflows.values())
        if enabled_only:
            workflows = [w for w in workflows if w.enabled]
        return workflows

    def get_workflow(self, workflow_name: str) -> WorkflowSchema | None:
        """Get a specific workflow by name."""
        if not self._workflows:
            self.load_workflows()
        return self._workflows.get(workflow_name)

    def resolve_capability(self, capability: str) -> str:
        """Resolve a capability string to an agent name.

        Convention: capability 'content.summarizer' resolves to
        agent 'content.summarizer.agent'.

        Raises:
            ValueError: If no agent found for the capability.
        """
        agent_name = f"{capability}.agent"

        if self._agent_registry is not None:
            if agent_name not in self._agent_registry:
                raise ValueError(
                    f"No agent found for capability '{capability}' "
                    f"(expected agent '{agent_name}' in registry)"
                )
            agent_config = self._agent_registry[agent_name]
            if not agent_config.get("enabled", True):
                raise ValueError(
                    f"Agent '{agent_name}' for capability '{capability}' "
                    f"is disabled"
                )
            return agent_name

        # Fallback: scan config/agents/ for the agent YAML
        agents_dir = self._project_root / "config" / "agents"
        if not agents_dir.exists():
            raise ValueError(
                f"No agent found for capability '{capability}' "
                f"(agents directory not found)"
            )

        for yaml_path in agents_dir.rglob("agent.yaml"):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if raw and raw.get("agent_name") == agent_name:
                    if not raw.get("enabled", True):
                        raise ValueError(
                            f"Agent '{agent_name}' for capability "
                            f"'{capability}' is disabled"
                        )
                    return agent_name
            except yaml.YAMLError:
                continue

        raise ValueError(
            f"No agent found for capability '{capability}' "
            f"(expected agent '{agent_name}')"
        )

    def validate_workflow_capabilities(
        self, workflow: WorkflowSchema,
    ) -> list[str]:
        """Validate that all capabilities in a workflow resolve to agents.

        Returns list of error messages. Empty list means all resolve.
        """
        errors: list[str] = []
        for step in workflow.steps:
            try:
                self.resolve_capability(step.capability)
            except ValueError as e:
                errors.append(f"Step '{step.id}': {e}")
        return errors

    def generate_mission_briefs(
        self, workflow: WorkflowSchema,
    ) -> list[dict[str, Any]]:
        """Convert workflow steps into Mission brief definitions."""
        step_index_map: dict[str, int] = {}
        for i, step in enumerate(workflow.steps):
            step_index_map[step.id] = i

        briefs: list[dict[str, Any]] = []
        app_config = get_app_config()

        for i, step in enumerate(workflow.steps):
            agent_name = self.resolve_capability(step.capability)

            brief: dict[str, Any] = {
                "step_id": step.id,
                "objective": step.description or f"Execute: {step.id}",
                "primary_capability": step.capability,
                "resolved_agent": agent_name,
                "roster_ref": step.roster,
                "complexity_tier": step.complexity_tier,
                "cost_ceiling_usd": (
                    step.cost_ceiling_usd
                    or app_config.workflows.default_budget_usd
                ),
                "environment": step.environment,
                "input_context": dict(step.input),
                "output_mapping": (
                    step.output_mapping.model_dump()
                    if step.output_mapping
                    else None
                ),
                "timeout_seconds": (
                    step.timeout_seconds
                    or app_config.workflows.default_step_timeout_seconds
                ),
                "dependencies": [
                    {
                        "depends_on_step": dep_id,
                        "depends_on_index": step_index_map.get(dep_id),
                    }
                    for dep_id in step.depends_on
                ],
                "sort_order": i,
            }
            briefs.append(brief)

        return briefs

    def match_workflow(self, user_input: str) -> WorkflowSchema | None:
        """Match user input against workflow trigger patterns.

        Used by Mission Control for deterministic fast-path routing (P2).
        """
        if not self._workflows:
            self.load_workflows()

        input_lower = user_input.lower()

        for workflow in self._workflows.values():
            if not workflow.enabled:
                continue
            if not workflow.trigger.match_patterns:
                continue

            for pattern in workflow.trigger.match_patterns:
                if pattern.lower() in input_lower:
                    logger.info(
                        "Workflow matched by pattern",
                        extra={
                            "workflow_name": workflow.workflow_name,
                            "pattern": pattern,
                        },
                    )
                    return workflow

        return None

    def resolve_upstream_context(
        self,
        step: WorkflowStepSchema,
        completed_outcomes: dict[str, dict],
        workflow_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build upstream_context for a Mission from completed prior missions.

        The Workflow is the anti-corruption layer: it extracts specific
        fields from prior MissionOutcomes via output_mapping and merges
        them with the workflow's initial context.
        """
        upstream: dict[str, Any] = dict(workflow_context)

        for dep_id in step.depends_on:
            if dep_id in completed_outcomes:
                upstream.update(completed_outcomes[dep_id])

        # Resolve @context.* references in step input
        resolved_input: dict[str, Any] = {}
        for key, value in step.input.items():
            if isinstance(value, str) and value.startswith("@context."):
                context_key = value[len("@context."):]
                if context_key in upstream:
                    resolved_input[key] = upstream[context_key]
                else:
                    raise ValueError(
                        f"Step '{step.id}' has unresolvable @context reference: "
                        f"'{value}' (available: {list(upstream.keys())})"
                    )
            else:
                resolved_input[key] = value

        upstream["_step_input"] = resolved_input
        return upstream
