"""
Workflow graph validator.

Validates the structural integrity of a workflow graph (steps + edges)
before save or execution. Catches issues that per-step schema validation
cannot: cycles via edges, orphan nodes, handle compatibility, and
node-type constraints (condition needs 2 outputs, branch ≥2, merge ≥2 inputs).

Called by WorkflowDefinitionService.save_graph when both steps and edges
are provided. Returns a list of error strings — empty means valid.
"""

from __future__ import annotations

from collections import defaultdict


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
