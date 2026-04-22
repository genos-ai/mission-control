"""
mc run / mc retry — execution handlers for the user CLI.

Handles auto-detection (workflow vs ad-hoc objective), gate resolution,
dry-run preview, and live display during execution.
"""

import sys

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


async def retry(
    n: int,
    *,
    mission_id: str,
    gate_override: str | None,
    quiet: bool = False,
    verbose: bool = False,
) -> None:
    """Retry failed tasks in the mission's plan.

    Plan 62: retry now re-approves failed tasks and re-dispatches via
    the plan path, preserving completed task results. If the plan has no
    failed tasks, falls back to re-running the Nth most recent objective.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_plan import MissionPlanService

    # Try plan-based retry first
    async with get_async_session() as db:
        svc = MissionPlanService(db)
        plan = await svc.get_or_create_plan(mission_id)

        if plan.task_plan_json is not None:
            from modules.backend.schemas.mission_plan import PlanTaskStatus

            failed_states = await svc.get_task_states(
                plan.id, status=PlanTaskStatus.FAILED,
            )

            if failed_states:
                console = get_console()
                failed_ids = [s.task_id for s in failed_states]
                console.print(
                    f"[bold]Retrying {len(failed_ids)} failed task(s):[/bold] "
                    f"{', '.join(failed_ids)}"
                )

                for state in failed_states:
                    await svc.retry_task(plan.id, state.task_id, "system:cli")

                result = await svc.dispatch_approved(
                    plan.id, "system:cli",
                )
                await db.commit()

                console.print(
                    f"\n[bold]Retry complete:[/bold] {result.get('outcome_status', 'unknown')}"
                    f" | ${result.get('total_cost_usd', 0):.4f}"
                )
                console.print("[dim]Run 'mc status' for full details.[/dim]")
                return

    # Fallback: no plan or no failed tasks — re-run the Nth most recent objective
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
        quiet=quiet,
        verbose=verbose,
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

    from modules.backend.services.execution import ExecutionService
    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.clients.cli.report import render_workflow_completion

    # Merge context overrides
    merged_context = {**(workflow.context or {}), **context_overrides} if context_overrides else None

    if verbose:
        from modules.clients.cli.live_display import VerboseEventBus

        click.echo(f"Running workflow: {workflow.workflow_name}\n")
        event_bus = VerboseEventBus()

        async with WorkflowRunService.factory(event_bus=event_bus) as run_service:
            wf_run = await run_service.run_workflow(
                workflow_name=workflow.workflow_name,
                triggered_by="system:cli",
                on_progress=lambda e: click.echo(f"progress: {e}"),
                mission_name=mission_name,
                gate=gate,
                context_overrides=merged_context,
            )
    else:
        from modules.clients.cli.live_display import LiveExecutionDisplay

        console = get_console()
        console.print(f"[bold]Running workflow:[/bold] {workflow.workflow_name}\n")

        display = LiveExecutionDisplay(show_thinking=not quiet)
        event_bus = display.create_event_bus()

        async with WorkflowRunService.factory(event_bus=event_bus) as run_service:
            with display.start():
                wf_run = await run_service.run_workflow(
                    workflow_name=workflow.workflow_name,
                    triggered_by="system:cli",
                    on_progress=display.handle_progress,
                    mission_name=mission_name,
                    gate=gate,
                    context_overrides=merged_context,
                )

    async with ExecutionService.factory() as execution_service:
        executions, _ = await execution_service.list_executions(
            workflow_run_id=wf_run.id,
        )

    console = get_console()
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
    """Execute an ad-hoc objective via the plan path (Plan 62).

    Creates/refines a mission plan, auto-approves tasks, and dispatches
    synchronously. All runs go through the plan infrastructure — supervisor,
    budget tracking, task states, and audit trail.
    """
    if dry_run:
        console = get_console()
        console.print(f"[bold]Dry run:[/bold] {objective}\n")
        console.print(f"  Mission: {mission_id}")
        if budget:
            console.print(f"  Budget: ${budget:.2f}")
        console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
        return

    from modules.backend.core.database import get_async_session
    from modules.backend.services.mission_plan import MissionPlanService

    console = get_console()
    console.print(f"[bold]Running:[/bold] {objective}\n")

    if verbose:
        from modules.clients.cli.live_display import VerboseEventBus
        event_bus = VerboseEventBus()
    else:
        from modules.clients.cli.live_display import LiveExecutionDisplay
        display = LiveExecutionDisplay(show_thinking=not quiet)
        event_bus = display.create_event_bus()

    result: dict = {}
    async with get_async_session() as db:
        svc = MissionPlanService(db, event_bus=event_bus)

        if verbose:
            result = await svc.run_objective(
                mission_id=mission_id,
                objective=objective,
                user_id="system:cli",
                gate_mode=gate_override,
                budget_ceiling_usd=budget,
                async_dispatch=False,
            )
            await db.commit()
        else:
            with display.start():
                try:
                    result = await svc.run_objective(
                        mission_id=mission_id,
                        objective=objective,
                        user_id="system:cli",
                        gate_mode=gate_override,
                        budget_ceiling_usd=budget,
                        async_dispatch=False,
                    )
                    await db.commit()
                except Exception as exc:
                    display.add_error(str(exc))
                    import asyncio
                    await asyncio.sleep(2)
                    raise
                finally:
                    outcome = result.get("outcome_status", "failed")
                    display.set_status("success" if outcome == "success" else "failed" if outcome == "failed" else outcome)

    # Render summary
    status = result.get("outcome_status", "unknown")
    cost = result.get("total_cost_usd", 0)
    task_count = result.get("task_count", 0)
    dispatched = result.get("dispatched_task_ids", [])

    console.print(f"\n[bold]Plan dispatch complete:[/bold] {status}")
    console.print(f"  Tasks: {len(dispatched)}/{task_count} dispatched")
    console.print(f"  Cost: ${cost:.4f}")
    if status == "awaiting_approval":
        console.print("[dim]Gate mode is interactive — approve tasks in the Plan tab.[/dim]")
    else:
        console.print("[dim]Run 'mc status' for full task breakdown.[/dim]")


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
