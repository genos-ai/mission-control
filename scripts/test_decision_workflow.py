#!/usr/bin/env python3
"""Create and run a test workflow with a decision node.

Usage:
    python scripts/test_decision_workflow.py --mission <mission_name_or_id> [--topic "quantum computing"]

Creates a workflow with:
  1. check-mcd     (tool_call)  — checks whether the mission MCD exists
  2. route-mcd     (decision)   — rule resolver: "exists" skips init, "missing" creates MCD
  3. init-mcd      (tool_call)  — creates a seed MCD (only on "missing" path)
  4. mcd-ok        (merge)      — gate: waits for route-mcd + init-mcd before proceeding
  5. read-context  (llm_call)   — reads and echoes the workflow run context
  6. read-knowledge (tool_call) — queries the knowledge base for existing entries on the topic
  7. classify      (llm_call)   — classifies the topic as technical or creative
  8. route         (decision)   — picks the downstream path (agent/human/rule resolver)
  9. technical-path (llm_call)  — technical analysis (if routed technical)
 10. creative-path  (llm_call)  — creative brainstorm (if routed creative)
 11. collect       (merge)      — waits for both branches (only one runs)
 12. summarize        (llm_call)   — synthesizes a final report
 13. store-artifact   (tool_call)  — persists the report as a mission artifact
 14. update-knowledge (tool_call)  — stores a learning in the knowledge base
 15. update-context   (tool_call)  — writes routing outcome to the MCD

Only the chosen branch (technical or creative) runs; the other is skipped.
"""

import argparse
import asyncio
import json
import sys

# Ensure project root is on sys.path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


WORKFLOW_NAME = "test.decision-routing"
WORKFLOW_DESCRIPTION = "Test workflow: decision node routes between technical and creative paths"

STEPS = [
    {
        "id": "check-mcd",
        "label": "Check MCD",
        "description": "Check whether a Mission Context Document exists for this mission",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "check_mcd",
            "tool_args": {},
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": [],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "route-mcd",
        "label": "MCD Gate",
        "description": "Route to init-mcd if MCD is missing, or proceed directly if it exists",
        "node_type": "decision",
        "decision_config": {
            "resolver": "rule",
            "expression": "@node.check-mcd.output",
            "model": None,
            "prompt": None,
            "temperature": 0.0,
            "prompt_message": None,
            "channel": None,
            "timeout_hours": None,
            "default_option": None,
            "options": [
                {"key": "exists", "label": "MCD already exists — skip initialisation"},
                {"key": "missing", "label": "MCD not found — create a seed document"},
            ],
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["check-mcd"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "init-mcd",
        "label": "Initialise MCD",
        "description": "Create a seed Mission Context Document for this mission",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "create_mcd",
            "tool_args": {},
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["route-mcd"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "mcd-ok",
        "label": "MCD Ready",
        "description": "Gate: MCD is guaranteed to exist after this merge",
        "node_type": "merge",
        "merge_config": {"strategy": "wait_all"},
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["init-mcd"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "read-context",
        "label": "Read Context",
        "description": "Read and echo the current workflow run context",
        "node_type": "llm_call",
        "llm_call_config": {
            "model": "quick",
            "system_prompt": None,
            "prompt_template": (
                "You are a workflow context inspector.\n"
                "Summarize the following workflow run context in one short paragraph.\n\n"
                "Context variables:\n"
                "- topic: {{@context.topic}}\n"
                "- resolver: {{@context.resolver}}\n\n"
                "State exactly what the workflow is about to do with these inputs."
            ),
            "temperature": 0.0,
            "max_tokens": 150,
            "structured_output": None,
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["mcd-ok"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "read-knowledge",
        "label": "Read Knowledge",
        "description": "Query the mission knowledge base for existing entries on the topic",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "query_knowledge",
            "tool_args": {
                "query": "{{@context.topic}}",
                "limit": 5,
                "mode": "hybrid",
            },
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["mcd-ok"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "classify",
        "label": "Classify Topic",
        "description": "Classify the topic as technical or creative",
        "node_type": "llm_call",
        "llm_call_config": {
            "model": "quick",
            "system_prompt": None,
            "prompt_template": (
                "Classify the following topic into exactly one category.\n"
                "Return ONLY the word 'technical' or 'creative', nothing else.\n\n"
                "Topic: {{@context.topic}}\n\n"
                "Existing knowledge about this topic:\n{{@node.read-knowledge.output}}"
            ),
            "temperature": 0.0,
            "max_tokens": 10,
            "structured_output": None,
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["read-context", "read-knowledge"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "route",
        "label": "Route Decision",
        "description": "Decide which path to take based on classification",
        "node_type": "decision",
        "decision_config": {
            "resolver": "agent",
            "model": "quick",
            "prompt": (
                "The topic '{{@context.topic}}' was classified as: {{@node.classify.output}}\n\n"
                "Based on this classification, choose the appropriate processing path."
            ),
            "temperature": 0.0,
            "prompt_message": None,
            "channel": None,
            "timeout_hours": None,
            "default_option": None,
            "expression": None,
            "options": [
                {"key": "technical", "label": "Topic is technical — run structured analysis"},
                {"key": "creative", "label": "Topic is creative — run brainstorm session"},
            ],
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["classify"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "technical-path",
        "label": "Technical Analysis",
        "description": "Produce a structured technical analysis",
        "node_type": "llm_call",
        "llm_call_config": {
            "model": "quick",
            "system_prompt": None,
            "prompt_template": (
                "Provide a brief technical analysis (3-4 bullet points) of:\n"
                "{{@context.topic}}"
            ),
            "temperature": 0.0,
            "max_tokens": 500,
            "structured_output": None,
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["route"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "creative-path",
        "label": "Creative Brainstorm",
        "description": "Brainstorm creative ideas",
        "node_type": "llm_call",
        "llm_call_config": {
            "model": "quick",
            "system_prompt": None,
            "prompt_template": (
                "Brainstorm 3-4 creative and unconventional ideas about:\n"
                "{{@context.topic}}"
            ),
            "temperature": 0.7,
            "max_tokens": 500,
            "structured_output": None,
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["route"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "collect",
        "label": "Collect Results",
        "description": "Merge parallel branches",
        "node_type": "merge",
        "merge_config": {"strategy": "wait_all"},
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["technical-path", "creative-path"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "summarize",
        "label": "Synthesize Report",
        "description": "Synthesize a short report from the analysis",
        "node_type": "llm_call",
        "llm_call_config": {
            "model": "moderate",
            "system_prompt": (
                "You are a concise technical writer. "
                "Produce clear, structured reports from analysis inputs. "
                "Be direct — no filler, no preamble."
            ),
            "prompt_template": (
                "Write a short report (3-5 paragraphs) on the following topic.\n\n"
                "Topic: {{@context.topic}}\n\n"
                "Prior knowledge:\n{{@node.read-knowledge.output}}\n\n"
                "Analysis:\n{{@node.collect.output}}\n\n"
                "Structure: one sentence summary, key findings as bullet points, "
                "one sentence conclusion."
            ),
            "temperature": 0.2,
            "max_tokens": 600,
            "structured_output": None,
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["collect"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "store-artifact",
        "label": "Store Artifact",
        "description": "Persist the synthesized report as a mission artifact",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "store_artifact",
            "tool_args": {
                "title": "Decision Routing Report: {{@context.topic}}",
                "content": "{{@node.summarize.output}}",
                "artifact_type": "report",
                "content_type": "markdown",
            },
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["summarize"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "update-knowledge",
        "label": "Update Knowledge",
        "description": "Store a learning from this workflow run in the mission knowledge base",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "store_learning",
            "tool_args": {
                "title": "Decision routing result: {{@context.topic}}",
                "body": "{{@node.summarize.output}}",
                "recommendation": "Use the {{@node.route.chosen}} path for topics classified as {{@node.classify.output}}.",
                "kind": "learning",
                "domain_tags": ["workflow", "decision-routing"],
                "confidence": 0.8,
            },
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["summarize"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
    {
        "id": "update-context",
        "label": "Update Context",
        "description": "Write the workflow outcome back to the Mission Context Document",
        "node_type": "tool_call",
        "tool_call_config": {
            "tool_name": "update_context",
            "tool_args": {
                "path": "workflow.last_decision_routing",
                "value": "topic={{@context.topic}} classification={{@node.classify.output}} path={{@node.route.chosen}}",
                "reason": "Decision workflow completed — recording routing outcome",
            },
        },
        "capability": None,
        "roster": "default",
        "complexity_tier": "simple",
        "cost_ceiling_usd": None,
        "environment": "local",
        "input": {},
        "output_mapping": None,
        "depends_on": ["summarize"],
        "timeout_seconds": None,
        "max_refinement_rounds": 1,
        "termination": "completion",
        "max_iterations": None,
    },
]

EDGES = [
    {"id": "check-mcd->route-mcd", "source": "check-mcd", "target": "route-mcd"},
    {"id": "route-mcd->init-mcd", "source": "route-mcd", "target": "init-mcd", "label": "missing", "source_handle": "missing"},
    {"id": "route-mcd->mcd-ok", "source": "route-mcd", "target": "mcd-ok", "label": "exists", "source_handle": "exists"},
    {"id": "init-mcd->mcd-ok", "source": "init-mcd", "target": "mcd-ok"},
    {"id": "mcd-ok->read-context", "source": "mcd-ok", "target": "read-context"},
    {"id": "mcd-ok->read-knowledge", "source": "mcd-ok", "target": "read-knowledge"},
    {"id": "read-context->classify", "source": "read-context", "target": "classify"},
    {"id": "read-knowledge->classify", "source": "read-knowledge", "target": "classify"},
    {"id": "classify->route", "source": "classify", "target": "route"},
    {"id": "route->technical-path", "source": "route", "target": "technical-path", "label": "technical", "source_handle": "technical"},
    {"id": "route->creative-path", "source": "route", "target": "creative-path", "label": "creative", "source_handle": "creative"},
    {"id": "technical-path->collect", "source": "technical-path", "target": "collect"},
    {"id": "creative-path->collect", "source": "creative-path", "target": "collect"},
    {"id": "collect->summarize", "source": "collect", "target": "summarize"},
    {"id": "summarize->store-artifact", "source": "summarize", "target": "store-artifact"},
    {"id": "summarize->update-knowledge", "source": "summarize", "target": "update-knowledge"},
    {"id": "summarize->update-context", "source": "summarize", "target": "update-context"},
]

OBJECTIVE = {
    "statement": "Test decision node routing between technical and creative paths",
    "category": "test",
    "owner": "user",
    "priority": "normal",
}

BUDGET = {"max_cost_usd": 1.0, "max_tokens": None}
TRIGGER = {"type": "on_demand"}


async def main():
    parser = argparse.ArgumentParser(description="Test decision node workflow")
    parser.add_argument("--mission", required=True, help="Mission name or ID")
    parser.add_argument("--topic", default="quantum computing", help="Topic to classify and route")
    parser.add_argument("--create-only", action="store_true", help="Create workflow but don't run it")
    parser.add_argument("--resolver", default="agent", choices=["agent", "rule", "human"], help="Resolver type to test")
    parser.add_argument("--timeout", type=float, default=0.01, help="Timeout in hours for human resolver (default: 0.01 = 36s)")
    args = parser.parse_args()

    # Swap the decision config based on resolver type
    steps = [dict(s) for s in STEPS]
    if args.resolver == "rule":
        for step in steps:
            if step["id"] == "route":
                step["decision_config"] = {
                    "resolver": "rule",
                    "expression": "@node.classify.output",
                    "model": None,
                    "prompt": None,
                    "temperature": 0.0,
                    "prompt_message": None,
                    "channel": None,
                    "timeout_hours": None,
                    "default_option": None,
                    "options": [
                        {"key": "technical", "label": "Topic is technical"},
                        {"key": "creative", "label": "Topic is creative"},
                    ],
                }
                print("Using RULE resolver (expression: @node.classify.output)")
                break
    elif args.resolver == "human":
        for step in steps:
            if step["id"] == "route":
                step["decision_config"] = {
                    "resolver": "human",
                    "prompt_message": (
                        "The topic '{{@context.topic}}' was classified as: {{@node.classify.output}}\n\n"
                        "Which path should we take?"
                    ),
                    "channel": "chat",
                    "timeout_hours": args.timeout,
                    "default_option": "technical",
                    "model": None,
                    "prompt": None,
                    "temperature": 0.0,
                    "expression": None,
                    "options": [
                        {"key": "technical", "label": "Topic is technical — run structured analysis"},
                        {"key": "creative", "label": "Topic is creative — run brainstorm session"},
                    ],
                }
                print(f"Using HUMAN resolver (timeout: {args.timeout}h, default: technical)")
                print("  Requires Temporal to be running (HumanInputWorkflow)")
                break
    else:
        print("Using AGENT resolver (LLM picks path)")

    from modules.backend.core.database import get_async_session
    from modules.backend.repositories.mission import MissionRepository
    from modules.backend.services.workflow_definition import WorkflowDefinitionService
    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.backend.services.workflow_run_waves import StepContext

    async with get_async_session() as db:
        # Resolve mission
        mission_repo = MissionRepository(db)
        try:
            from uuid import UUID
            UUID(args.mission)
            mission = await mission_repo.get_by_id(args.mission)
        except (ValueError, Exception):
            mission = await mission_repo.get_by_name(args.mission)

        mission_id = mission.id
        print(f"Mission: {mission.name} ({mission_id})")

        # Create or update workflow definition
        defn_svc = WorkflowDefinitionService(db)
        try:
            existing = await defn_svc.get_workflow(mission_id, WORKFLOW_NAME)
            print(f"Workflow '{WORKFLOW_NAME}' already exists (id={existing.id}), updating steps...")
            await defn_svc.save_graph(
                existing.id,
                canvas_state={},
                edges_json=EDGES,
                steps=steps,
            )
            workflow_id = existing.id
        except Exception:
            wf = await defn_svc.create_workflow(
                mission_id=mission_id,
                name=WORKFLOW_NAME,
                description=WORKFLOW_DESCRIPTION,
                objective=OBJECTIVE,
                steps=steps,
                trigger_config=TRIGGER,
                budget_config=BUDGET,
                context={"topic": args.topic, "resolver": args.resolver},
                designed_by="script:test_decision_workflow",
            )
            # Save edges separately (create_workflow doesn't take edges)
            await defn_svc.save_graph(
                wf.id,
                canvas_state={},
                edges_json=EDGES,
                steps=steps,
            )
            workflow_id = wf.id
            print(f"Created workflow '{WORKFLOW_NAME}' (id={workflow_id})")

        await db.commit()

        if args.create_only:
            print(f"\nWorkflow created. Open the editor to inspect it:")
            print(f"  /missions/{mission_id}/workflows/{workflow_id}")
            return

        # Run the workflow
        print(f"\nRunning workflow with topic: '{args.topic}'")
        print("-" * 50)

        def on_progress(event: dict):
            etype = event.get("type", "")
            if etype == "step_start":
                print(f"  -> Starting: {event.get('step_id')}")
            elif etype == "step_done":
                print(f"  <- Done: {event.get('step_id')} ({event.get('status')}) ${event.get('cost_usd', 0):.4f}")
            elif etype == "step_skipped":
                print(f"  -- Skipped: {event.get('step_id')} ({event.get('reason')})")

        run_svc = WorkflowRunService(
            session=db,
            step_context_factory=StepContext.factory,
            event_bus=None,
        )

        run = await run_svc.run_workflow(
            workflow_name=WORKFLOW_NAME,
            mission_id=mission_id,
            triggered_by="script:test_decision_workflow",
            context_overrides={"topic": args.topic, "resolver": args.resolver},
            on_progress=on_progress,
        )
        await db.commit()

        print("-" * 50)
        status = run.status if isinstance(run.status, str) else run.status.value
        print(f"Result: {status}")
        print(f"Cost:   ${run.total_cost_usd:.4f}")
        if run.result_summary:
            print(f"Summary: {run.result_summary}")
        if run.error_data:
            print(f"Error: {json.dumps(run.error_data, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
