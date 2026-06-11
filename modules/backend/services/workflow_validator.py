"""
Workflow validators.

Two layers of pre-execution validation for workflow definitions:

  validate_workflow_graph(steps, edges)
    Structural integrity of the graph (cycles, orphans, condition/
    branch/merge constraints). Catches what per-step schema validation
    cannot.

  validate_output_mappings(workflow)
    Output-mapping schema check: for every agent_step, verify each
    `output_mapping.field_mappings.source_field` actually exists on
    the source agent's declared `output_type` Pydantic schema. Catches
    the schema-drift class of bug at seed time, before the workflow
    ever runs — instead of letting the runtime "Output mapping source
    field not found" warning silently degrade downstream agents to
    fabricating output from missing inputs.

    The schema validator at WorkflowSchema.validate_steps explicitly
    punted on this ("field-path typos are runtime-checked since we
    don't know output schemas statically"). We CAN know statically —
    agents declare `output_type=SomeSchema` on Agent(...), and that
    class's `model_fields` is the canonical contract.

Both are called by the seeder before persisting a template, and by
admin code paths that ingest workflow YAML.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from modules.backend.core.logging import get_logger

if TYPE_CHECKING:
    from modules.backend.schemas.workflow import (
        WorkflowSchema, WorkflowStepSchema,
    )

logger = get_logger(__name__)


def validate_workflow_graph(
    steps: list[dict],
    edges: list[dict],
    current_workflow_id: str | None = None,
) -> list[str]:
    """Validate a workflow graph and return a list of error messages.

    Returns an empty list if the graph is valid.
    """
    errors: list[str] = []
    if not steps:
        return ["Workflow must have at least one step"]

    step_ids = {s["id"] for s in steps}
    step_types = {s["id"]: s.get("node_type", "agent_step") for s in steps}

    errors += _check_duplicate_step_ids(steps)
    errors += _check_self_loops(edges)
    errors += _check_duplicate_edges(edges)
    errors += _check_edge_references(edges, step_ids)
    errors += _check_cycles(step_ids, edges)
    errors += _check_orphan_nodes(step_ids, edges)
    errors += _check_condition_outputs(step_types, edges)
    errors += _check_decision_edges(steps, edges)
    errors += _check_branch_outputs(step_types, edges)
    errors += _check_merge_inputs(step_types, edges)
    if current_workflow_id:
        errors += _check_sub_workflow_self_reference(steps, current_workflow_id)

    return errors


def _check_duplicate_step_ids(steps: list[dict]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for s in steps:
        sid = s["id"]
        if sid in seen:
            dupes.append(sid)
        seen.add(sid)
    if dupes:
        return [f"Duplicate step IDs: {', '.join(dupes)}"]
    return []


def _check_self_loops(edges: list[dict]) -> list[str]:
    errors = []
    for e in edges:
        if e.get("source") == e.get("target"):
            errors.append(f"Self-loop on node '{e['source']}'")
    return errors


def _check_duplicate_edges(edges: list[dict]) -> list[str]:
    seen: set[tuple[str, str, str, str]] = set()
    dupes = []
    for e in edges:
        key = (e.get("source", ""), e.get("target", ""),
               e.get("source_handle", "output"), e.get("target_handle", "input"))
        if key in seen:
            dupes.append(f"{key[0]} -> {key[1]}")
        seen.add(key)
    if dupes:
        return [f"Duplicate edges: {', '.join(dupes)}"]
    return []


def _check_edge_references(edges: list[dict], step_ids: set[str]) -> list[str]:
    errors = []
    for e in edges:
        src = e.get("source", "")
        tgt = e.get("target", "")
        if src and src not in step_ids:
            errors.append(f"Edge references unknown source node '{src}'")
        if tgt and tgt not in step_ids:
            errors.append(f"Edge references unknown target node '{tgt}'")
    return errors


def _check_cycles(step_ids: set[str], edges: list[dict]) -> list[str]:
    """Detect cycles using Kahn's algorithm on the edge graph."""
    in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if src in step_ids and tgt in step_ids:
            adj[src].append(tgt)
            in_degree[tgt] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(step_ids):
        return ["Workflow graph contains a cycle"]
    return []


def _check_orphan_nodes(step_ids: set[str], edges: list[dict]) -> list[str]:
    """Warn about nodes with no connections (except single-node workflows)."""
    if len(step_ids) <= 1:
        return []
    connected: set[str] = set()
    for e in edges:
        connected.add(e.get("source", ""))
        connected.add(e.get("target", ""))
    orphans = step_ids - connected
    if orphans:
        return [f"Disconnected nodes: {', '.join(sorted(orphans))}"]
    return []


def _check_condition_outputs(
    step_types: dict[str, str], edges: list[dict],
) -> list[str]:
    """Condition nodes should have exactly 2 outgoing edges (yes/no)."""
    errors = []
    outgoing: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src = e.get("source", "")
        handle = e.get("source_handle", "output")
        outgoing[src].append(handle)

    for sid, ntype in step_types.items():
        if ntype != "condition":
            continue
        handles = outgoing.get(sid, [])
        if len(handles) < 1:
            errors.append(f"Condition '{sid}' has no outgoing edges (needs yes/no branches)")
        elif len(handles) == 1:
            errors.append(f"Condition '{sid}' has only 1 outgoing edge (needs both yes and no branches)")
    return errors


def _check_decision_edges(
    steps: list[dict], edges: list[dict],
) -> list[str]:
    """Decision nodes: outgoing edges must have labels covering all options."""
    errors = []
    decision_ids = {
        s["id"] for s in steps if s.get("node_type") == "decision"
    }
    if not decision_ids:
        return []

    # Every outgoing edge from a decision node must have a label
    for e in edges:
        if e.get("source") in decision_ids and not e.get("label"):
            errors.append(
                f"Edge from decision '{e['source']}' to '{e.get('target', '?')}' "
                f"must have a label matching an option key"
            )

    # Every option key must appear as a label on at least one outgoing edge
    for s in steps:
        if s.get("node_type") != "decision":
            continue
        config = s.get("decision_config") or {}
        option_keys = {o["key"] for o in config.get("options", [])}
        outgoing_labels = {
            e.get("label") for e in edges
            if e.get("source") == s["id"] and e.get("label")
        }
        missing = option_keys - outgoing_labels
        if missing:
            errors.append(
                f"Decision '{s['id']}': options {sorted(missing)} "
                f"have no matching outgoing edge labels"
            )
    return errors


def _check_branch_outputs(
    step_types: dict[str, str], edges: list[dict],
) -> list[str]:
    """Branch (fork) nodes should have ≥2 outgoing edges."""
    errors = []
    out_count: dict[str, int] = defaultdict(int)
    for e in edges:
        out_count[e.get("source", "")] += 1
    for sid, ntype in step_types.items():
        if ntype != "branch":
            continue
        if out_count.get(sid, 0) < 2:
            errors.append(f"Branch '{sid}' needs at least 2 outgoing edges (has {out_count.get(sid, 0)})")
    return errors


def _check_merge_inputs(
    step_types: dict[str, str], edges: list[dict],
) -> list[str]:
    """Merge (join) nodes should have ≥2 incoming edges."""
    errors = []
    in_count: dict[str, int] = defaultdict(int)
    for e in edges:
        in_count[e.get("target", "")] += 1
    for sid, ntype in step_types.items():
        if ntype != "merge":
            continue
        if in_count.get(sid, 0) < 2:
            errors.append(f"Merge '{sid}' needs at least 2 incoming edges (has {in_count.get(sid, 0)})")
    return errors


def _check_sub_workflow_self_reference(
    steps: list[dict], current_workflow_id: str,
) -> list[str]:
    """Sub-workflow nodes must not reference the current workflow (direct recursion)."""
    errors = []
    for s in steps:
        if s.get("node_type") != "sub_workflow":
            continue
        config = s.get("sub_workflow_config") or {}
        if config.get("workflow_id") == current_workflow_id:
            errors.append(f"Sub-workflow '{s['id']}' references itself (direct recursion)")
    return errors


# =============================================================================
# Output-mapping schema validator (seed-time + admin paths)
# =============================================================================


@dataclass
class OutputMappingViolation:
    """One specific violation of the workflow / agent-schema contract."""

    step_id: str
    source_task: str
    source_field: str
    available_fields: list[str] = field(default_factory=list)
    reason: str = ""

    def __str__(self) -> str:
        return (
            f"step '{self.step_id}' → output_mapping references "
            f"source_task='{self.source_task}' source_field="
            f"'{self.source_field}': {self.reason}. "
            f"Available: {self.available_fields}"
        )


# Cache: agent_name → set of valid field names on its output_type schema.
# Built lazily, scoped to a single validation pass so a workflow with
# multiple steps referencing the same agent only pays the import once.
_FieldCache = dict[str, "set[str] | None"]


def _resolve_module_path(agent_name: str) -> str:
    """Derive the Python module import path from an agent name.

    Mirrors AgentRegistry.resolve_module_path so the validator works
    without spinning up the full registry (which needs a DB session).
    `mission.director.agent` → `modules.backend.agents.mission.director.agent`.
    """
    parts = agent_name.replace(".agent", "").split(".")
    return f"modules.backend.agents.{'.'.join(parts)}.agent"


def _agent_output_fields(
    agent_name: str, cache: _FieldCache,
) -> set[str] | None:
    """Return the set of valid output-schema field names for an agent.

    Imports the agent module, constructs the agent with a TestModel so
    no real LLM is consulted, reads `agent.output_type.model_fields`.

    Returns `None` if the agent has no structured output (output_type
    is `str` / absent) or introspection fails — in either case the
    caller treats the field as acceptable, since we can't enforce a
    contract that wasn't declared.
    """
    if agent_name in cache:
        return cache[agent_name]

    fields: set[str] | None = None
    try:
        from pydantic_ai.models.test import TestModel

        module_path = _resolve_module_path(agent_name)
        module = importlib.import_module(module_path)
        if not hasattr(module, "create_agent"):
            cache[agent_name] = None
            return None
        agent = module.create_agent(TestModel())
        output_type = getattr(agent, "output_type", None)
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            # `model_dump()` (used by extract_outputs) includes both
            # declared fields and @computed_field properties, so the
            # validator must accept both as valid source_field values.
            fields = (
                set(output_type.model_fields.keys())
                | set(output_type.model_computed_fields.keys())
            )
    except Exception as exc:
        # Agent introspection failed — log but don't block. Runtime
        # extract_outputs still catches bad mappings; we lose only the
        # seed-time guarantee for this specific agent.
        logger.warning(
            "Could not introspect agent output_type",
            extra={"agent": agent_name, "error": str(exc)[:300]},
        )

    cache[agent_name] = fields
    return fields


def _resolve_source_agent(
    source_task: str, steps: "list[WorkflowStepSchema]",
) -> str | None:
    """Map a workflow `source_task` reference to an agent name.

    `source_task` is either a step.id (e.g. "decompose") or a
    fully-qualified agent name (e.g. "research.searcher.agent").
    """
    if source_task.endswith(".agent"):
        return source_task
    for step in steps:
        if step.id == source_task and step.capability:
            return f"{step.capability}.agent"
    return None


def validate_output_mappings(
    workflow: "WorkflowSchema",
) -> list[OutputMappingViolation]:
    """Validate every step's output_mapping against the live agent schemas.

    Returns a list of violations. Empty list means the workflow is
    well-formed against current agent contracts. Callers (seeder,
    admin CLI) decide what to do — usually refuse to persist the
    workflow.
    """
    violations: list[OutputMappingViolation] = []
    cache: _FieldCache = {}

    for step in workflow.steps:
        if not step.output_mapping or not step.output_mapping.field_mappings:
            continue

        for mapping in step.output_mapping.field_mappings:
            agent_name = _resolve_source_agent(
                mapping.source_task, workflow.steps,
            )
            if agent_name is None:
                violations.append(OutputMappingViolation(
                    step_id=step.id,
                    source_task=mapping.source_task,
                    source_field=mapping.source_field,
                    reason="source_task could not be resolved to an agent",
                ))
                continue

            valid_fields = _agent_output_fields(agent_name, cache)
            if valid_fields is None:
                # Agent has no structured output_type, or introspection
                # failed (warning already logged). Can't enforce.
                continue

            if mapping.source_field not in valid_fields:
                violations.append(OutputMappingViolation(
                    step_id=step.id,
                    source_task=mapping.source_task,
                    source_field=mapping.source_field,
                    available_fields=sorted(valid_fields),
                    reason=(
                        f"field '{mapping.source_field}' is not on "
                        f"{agent_name}.output_type"
                    ),
                ))

    return violations


def format_violations(
    workflow_name: str, violations: list[OutputMappingViolation],
) -> str:
    """Human-readable summary for log lines and CLI output."""
    if not violations:
        return f"workflow '{workflow_name}': output_mappings OK"
    lines = [
        f"workflow '{workflow_name}': "
        f"{len(violations)} output_mapping violation(s):",
    ]
    for v in violations:
        lines.append(f"  - {v}")
    return "\n".join(lines)
