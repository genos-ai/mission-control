"""
mc run / mc retry — execution handlers for the user CLI.

Handles auto-detection (workflow vs ad-hoc objective), gate resolution,
dry-run preview, and live display during execution.
"""

import sys
from uuid import uuid4

import click

from modules.clients.common.display import get_console


async def run(
    objective_or_workflow: str,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    context_overrides: dict[str, str],
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Run a workflow (if name matches) or an ad-hoc objective."""
    from modules.backend.services.workflow import WorkflowService

    svc = WorkflowService()
    workflow = svc.get_workflow(objective_or_workflow)

    if workflow:
        await _run_workflow(
            workflow,
            mission_id=mission_id,
            budget=budget,
            gate_override=gate_override,
            context_overrides=context_overrides,
            dry_run=dry_run,
            quiet=quiet,
            verbose=verbose,
        )
    else:
        await _run_adhoc(
            objective_or_workflow,
            mission_id=mission_id,
            budget=budget,
            gate_override=gate_override,
            dry_run=dry_run,
            quiet=quiet,
            verbose=verbose,
        )


async def retry(n: int, *, mission_id: str, gate_override: str | None) -> None:
    """Re-run the Nth most recent execution."""
    from modules.backend.services.execution import ExecutionService

    async with ExecutionService.factory() as svc:
        executions, _ = await svc.list_executions(mission_id=mission_id, limit=n)

    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    original = executions[n - 1]
    await _run_adhoc(
        original.objective,
        mission_id=mission_id,
        budget=original.cost_ceiling_usd,
        gate_override=gate_override,
        dry_run=False,
        quiet=False,
        verbose=False,
    )


# =============================================================================
# Internal
# =============================================================================


async def _resolve_gate(mission_id: str, gate_override: str | None):
    """Resolve gate via MissionService."""
    from modules.backend.services.mission import MissionService

    async with MissionService.factory() as svc:
        return await svc.resolve_gate(mission_id, gate_override)


async def _run_workflow(
    workflow,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    context_overrides: dict[str, str],
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Execute a named workflow."""
    if dry_run:
        _show_dry_run(workflow)
        return

    gate = await _resolve_gate(mission_id, gate_override)

    # Resolve mission name for WorkflowRunService
    from modules.backend.services.mission import MissionService

    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)
    mission_name = mission.name

    from modules.clients.cli.live_display import LiveExecutionDisplay
    from modules.backend.services.execution import ExecutionService
    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.clients.cli.report import render_workflow_completion

    console = get_console()
    console.print(f"[bold]Running workflow:[/bold] {workflow.workflow_name}\n")

    display = LiveExecutionDisplay(show_thinking=not quiet)
    event_bus = display.create_event_bus()

    # Merge context overrides
    merged_context = {**(workflow.context or {}), **context_overrides} if context_overrides else None

    async with WorkflowRunService.factory(event_bus=event_bus) as run_service:
        with display.start():
            wf_run = await run_service.run_workflow(
                workflow_name=workflow.workflow_name,
                triggered_by="user:mc",
                on_progress=display.handle_progress,
                mission_name=mission_name,
                gate=gate,
                context_overrides=merged_context,
            )

    async with ExecutionService.factory() as execution_service:
        executions, _ = await execution_service.list_executions(
            workflow_run_id=wf_run.id,
        )

    await render_workflow_completion(console, wf_run, executions)


async def _run_adhoc(
    objective: str,
    *,
    mission_id: str,
    budget: float | None,
    gate_override: str | None,
    dry_run: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Execute an ad-hoc objective."""
    if dry_run:
        console = get_console()
        console.print(f"[bold]Dry run:[/bold] {objective}\n")
        console.print(f"  Mission: {mission_id}")
        if budget:
            console.print(f"  Budget: ${budget:.2f}")
        console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
        return

    gate = await _resolve_gate(mission_id, gate_override)

    from modules.clients.cli.live_display import LiveExecutionDisplay
    from modules.backend.services.execution import ExecutionService
    from modules.clients.cli.report import render_execution

    console = get_console()
    console.print(f"[bold]Running:[/bold] {objective}\n")

    display = LiveExecutionDisplay(show_thinking=not quiet)
    event_bus = display.create_event_bus()

    async with ExecutionService.factory(event_bus=event_bus) as svc:
        execution = await svc.create_adhoc_execution(
            objective=objective,
            triggered_by="user:mc",
            session_id=str(uuid4()),
            mission_id=mission_id,
            cost_ceiling_usd=budget,
        )
        with display.start():
            execution = await svc.run_execution(execution.id, gate=gate)

    await render_execution(execution, "human")


def _show_dry_run(workflow) -> None:
    """Show workflow plan without executing."""
    console = get_console()
    console.print(f"[bold]Dry run:[/bold] {workflow.workflow_name}\n")
    console.print(f"  Steps: {len(workflow.steps)}")
    console.print(f"  Budget: ${workflow.budget.max_cost_usd:.2f}")
    console.print(f"  Trigger: {workflow.trigger.type}\n")
    for step in workflow.steps:
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        console.print(f"  {step.id}: {step.capability}{deps}")
    console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
