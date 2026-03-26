# Plan 35 — mc.py: User-Facing CLI

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-03-26 |
| **Depends on** | Plan 28 (Platform Architecture), Plan 31 (Current Mission Selection) |
| **Target** | `mc.py`, `modules/clients/cli/mc_*.py` |

---

## 1  Context

Users interact with Mission Control through `cli.py` — a 1300-line monolith mixing daily user tasks (run, chat, check history) with admin ops (server start, db queries, migrations). The result: users must navigate 20+ command groups and think in system abstractions (execution vs workflow vs workflow-run) rather than their own intent.

This plan creates `mc.py` — a focused CLI for the daily user workflow: run tasks, chat with agents, check results. `cli.py` becomes `admin.py` for ops/infrastructure. The two share all backend services and display primitives — no logic duplication.

The key UX shift: **users see agents thinking and working in real-time**, including reasoning text, tool calls, and handoffs between agents.

---

## 2  Command Map

```
mc                                 Quick-start guide (not Click help dump)

mc run <objective|workflow>        Run work against current mission
    --budget FLOAT                 Cost ceiling override
    --gate MODE                    off | interactive | ai_assisted | autonomous
    --step                         Alias for --gate interactive
    --set KEY=VALUE                Workflow context override (repeatable)
    --dry-run                      Show plan + estimated cost, don't execute
    --quiet                        Minimal output (steps + cost only)
    --verbose                      Full reasoning stream

mc retry N                         Re-run Nth most recent execution
    --gate MODE                    Override gate mode for retry

mc status                          Current mission snapshot
mc history [N]                     Recent runs (or detail for run #N)

mc chat [AGENT] [MESSAGE]          Talk to coordinator or specific agent
mc design [DESCRIPTION]            Workflow Architect interactive session

mc mission create                  --name, --description, --brief, --gate, --budget
mc mission list
mc mission use NAME|ID
mc mission info                    Current mission detail + context summary
mc mission set-gate MODE           Change default gate mode

mc team list                       Agents on current mission
mc team available [--search Q]     Browse global agent catalog
mc team add AGENT
mc team remove AGENT

mc context show                    View the Mission Context Document
mc context history                 MCD change audit trail

mc console monitor                 Live terminal dashboard
    --view user|developer
    --refresh FLOAT
```

---

## 3  Architecture

```
mc.py                          Click command tree (~250 lines)
  |
  +-- modules/clients/cli/
  |     cli_context.py         (create) Shared CliContext — used by mc.py and cli.py
  |     mc_run.py              mc run, mc retry handlers
  |     mc_chat.py             mc chat, mc design REPL handlers
  |     mc_status.py           mc status, mc history handlers
  |     live_display.py        (modify) Add agent thinking stream
  |     mission_cmds.py        (modify) Add set-gate action
  |     console_cmds.py        (reuse) Console monitor
  |     gate.py                (reuse) CliGateReviewer
  |     report.py              (reuse) Execution/workflow rendering
  |     mission_context.py     (reuse) Current mission resolution
  |
  +-- modules/clients/common/
  |     event_rendering.py     (modify) Thinking text formatter
  |     display.py             (reuse) Panels, tables, status
  |     gate_helpers.py        (reuse) STATUS_ICONS, cost_color
  |
  +-- modules/backend/
        models/mission.py      (modify) Add gate_mode column
        services/mission.py    (modify) set_gate_mode method
        services/execution.py  (modify) mission_id filter on list
        repos/execution.py     (modify) mission_id filter on list
        migrations/            New alembic migration
```

---

## 4  Implementation Phases

### Phase 1: Backend changes (gate_mode, mission_id filter)

These are prerequisites for later phases.

#### 4.1.1  Add `gate_mode` to Mission model

**File: `modules/backend/models/mission.py`**

Add after `repo_root`:
```python
gate_mode: Mapped[str | None] = mapped_column(
    String(20), nullable=True, default=None,
    comment="Default gate mode: off, interactive, ai_assisted, autonomous",
)
```

#### 4.1.2  Alembic migration

Generate and run:
```bash
alembic -c modules/backend/migrations/alembic.ini revision --autogenerate -m "Add gate_mode to missions"
alembic -c modules/backend/migrations/alembic.ini upgrade head
```

#### 4.1.3  MissionService: accept gate_mode, add set_gate_mode

**File: `modules/backend/services/mission.py`**

- `create_mission()` — add `gate_mode: str | None = None` parameter, pass to model constructor
- New method:
```python
async def set_gate_mode(self, mission_id: str, mode: str) -> Mission:
    """Update the default gate mode for a mission."""
    mission = await self._get_mission(mission_id)
    mission.gate_mode = mode
    await self._session.flush()
    return mission
```

#### 4.1.4  ExecutionRepository: add mission_id filter

**File: `modules/backend/repositories/execution.py`**

`list_executions()` — add `mission_id: str | None = None` parameter:
```python
if mission_id:
    conditions.append(Execution.mission_id == mission_id)
```

**File: `modules/backend/services/execution.py`**

`list_executions()` — add `mission_id: str | None = None` parameter, pass through to repo.

#### 4.1.5  mission_cmds.py: add set-gate action

**File: `modules/clients/cli/mission_cmds.py`**

- Add `gate_mode` parameter to `run_mission()` signature
- Add `"set-gate": _action_set_gate` to actions dict
- `_action_create`: pass `gate_mode` to `MissionService.create_mission()`
- New `_action_set_gate`: calls `MissionService.set_gate_mode()`

---

### Phase 2: Event rendering — show agent thinking

Currently `AgentResponseChunkEvent` is in `NOISY_EVENT_TYPES` and filtered everywhere. We need to show it as agent thinking text.

#### 4.2.1  Update event_rendering.py

**File: `modules/clients/common/event_rendering.py`**

- Remove `agent.response.chunk` from `NOISY_EVENT_TYPES`
- Add new category: `STREAMING_EVENT_TYPES = {"agent.response.chunk"}`
- Add `is_streaming(event)` function — returns True for chunk events
- Update `summarize_event` for chunk events to truncate to 60 chars
- Add `format_thinking_line(event)` — formats chunk content as `[dim italic]{content}[/dim italic]`

#### 4.2.2  Update LiveExecutionDisplay

**File: `modules/clients/cli/live_display.py`**

Add thinking stream support:

- New `__init__` parameter: `show_thinking: bool = True`
- New field: `_thinking_buffer: dict[str, str]` — keyed by agent_id, accumulates chunk content
- In `handle_event()`:
  - If `show_thinking` and event is `AgentResponseChunkEvent`: append `event.content` to `_thinking_buffer[agent_id]`
  - If event is `AgentResponseCompleteEvent`: clear `_thinking_buffer[agent_id]`
  - Continue adding non-streaming events to `_events` deque as before
- In `_render()`, add a "Thinking" section in the activity panel:
  - If `_thinking_buffer` has content, show last 200 chars per agent as `💭 [dim italic]...[/dim italic]`
  - Active thinking appears above the event log

Result display:
```
┌─ Agent Activity ──────────────────────────────────┐
│ 💭 code.qa.agent:                                 │
│   [dim italic]I need to check the auth module     │
│   for injection vulnerabilities. Let me read      │
│   the query builder...[/dim italic]               │
│                                                   │
│ 14:30:05 🧠 code.qa.agent thinking                │
│ 14:30:07 🔧 read_files                            │
│ 14:30:08 📎 read_files -> success                  │
│ 14:30:09 ✓ code.qa.agent done $0.034              │
└───────────────────────────────────────────────────┘
```

---

### Phase 3: mc.py shell + mission commands

#### 4.3.1  Extract CliContext to shared module

**File: `modules/clients/cli/cli_context.py`** (new, ~30 lines)

Extract `CliContext` from `cli.py` into a shared module so both `cli.py` and `mc.py` reuse it:

```python
"""Shared CLI context — used by both mc.py and cli.py (admin.py)."""

from modules.backend.core.config import validate_project_root
from modules.backend.core.logging import bind_context, get_logger, setup_logging


class CliContext:
    """Shared context passed to all subcommands."""

    def __init__(
        self,
        verbose: bool = False,
        debug: bool = False,
        quiet: bool = False,
        output_format: str = "human",
        source: str = "cli",
    ):
        level = "DEBUG" if debug else "INFO" if verbose else "WARNING"
        validate_project_root()
        setup_logging(level=level, format_type="console")
        bind_context(source=source)
        self.logger = get_logger(source)
        self.output_format = output_format
        self.quiet = quiet
        self.verbose = verbose
```

**File: `cli.py`** — replace inline `CliContext` class with:
```python
from modules.clients.cli.cli_context import CliContext
```

#### 4.3.2  Create mc.py

**File: `mc.py`** (~250 lines)

Structure:
```python
#!/usr/bin/env python3
"""Mission Control — user CLI."""

import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.clients.cli.cli_context import CliContext


class McGroup(click.Group):
    """Custom group: shows quick-start when invoked without subcommand."""
    def resolve_command(self, ctx, args):
        # Same ShowHelpOnMissingArgs logic from cli.py
        ...


@click.group(cls=McGroup, invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", "-d", is_flag=True)
@click.option("--quiet", "-q", is_flag=True)
@click.pass_context
def mc(ctx, verbose, debug, quiet):
    ctx.ensure_object(dict)
    ctx.obj = CliContext(verbose=verbose, debug=debug, quiet=quiet, source="mc")
    if ctx.invoked_subcommand is None:
        _show_quickstart()


def _show_quickstart():
    """Formatted quick-start guide."""
    from modules.clients.common.display import get_console
    console = get_console()
    console.print("""
[bold cyan]Mission Control[/bold cyan]

  [bold]Quick Start:[/bold]
    mc mission create --name my-app --description "My project"
    mc mission use my-app
    mc run "audit the auth module"

  [bold]Work:[/bold]
    mc run <objective|workflow>   Run a task or workflow
    mc chat                      Talk to your AI team
    mc design                    Design a workflow with the Architect
    mc status                    Current mission snapshot
    mc history [N]               Recent runs (detail for run #N)

  [bold]Setup:[/bold]
    mc mission list              List missions
    mc team list                 Your agent team
    mc context show              Mission Context Document

  [dim]Use mc <command> --help for details.[/dim]
""")
```

#### 4.3.3  Mission guard helper

**File: `mc.py`** (or inline in mc_run.py)

```python
def _require_mission() -> str:
    """Resolve current mission or exit with helpful error."""
    from modules.clients.cli.mission_context import _resolve_current_mission_id
    mid = _resolve_current_mission_id()
    if not mid:
        click.echo(click.style(
            "No mission selected.\n\n"
            "  Set one with:  mc mission use <name>\n"
            "  Or create:     mc mission create --name my-project --description '...'\n",
            fg="yellow",
        ))
        sys.exit(1)
    return mid

async def _async_require_mission() -> str:
    """Async version for handlers already in asyncio.run()."""
    from modules.clients.cli.mission_context import _async_resolve_current_mission_id
    mid = await _async_resolve_current_mission_id()
    if not mid:
        click.echo(click.style(
            "No mission selected.\n\n"
            "  Set one with:  mc mission use <name>\n"
            "  Or create:     mc mission create --name my-project --description '...'\n",
            fg="yellow",
        ))
        raise SystemExit(1)
    return mid
```

#### 4.3.4  Wire mission commands in mc.py

Thin wrappers calling `run_mission()` from `modules/clients/cli/mission_cmds.py`:

```python
@mc.group("mission", cls=McGroup, invoke_without_command=True)
@click.pass_context
def mission(ctx): ...

@mission.command("create")
@click.option("--name", required=True)
@click.option("--description", required=True)
@click.option("--brief", default=None)
@click.option("--gate", "gate_mode", type=click.Choice(["off","interactive","ai_assisted","autonomous"]), default=None)
@click.option("--budget", type=float, default=None)
@click.pass_obj
def mission_create(ctx, name, description, brief, gate_mode, budget): ...

@mission.command("use")
@click.argument("name_or_id")
@click.pass_obj
def mission_use(ctx, name_or_id): ...

@mission.command("info")
@click.pass_obj
def mission_info(ctx):
    mid = _require_mission()
    run_mission(ctx.logger, "detail", mission_id=mid)

@mission.command("set-gate")
@click.argument("mode", type=click.Choice(["off","interactive","ai_assisted","autonomous"]))
@click.pass_obj
def mission_set_gate(ctx, mode): ...
```

#### 4.3.5  Wire team, context, console commands

Same pattern — thin Click wrappers delegating to existing service calls:

- `mc team list/available/add/remove` — calls `MissionTeamService` and `AgentCatalogService`
- `mc context show/history` — calls `run_mission(logger, "context-show"/"context-history", ...)`
- `mc console monitor` — calls `run_monitor()` from `console_cmds.py`

---

### Phase 4: mc run

**File: `modules/clients/cli/mc_run.py`** (~200 lines)

#### 4.4.1  Auto-detection logic

```python
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
    # 1. Check if it's a registered workflow name
    from modules.backend.services.workflow import WorkflowService
    svc = WorkflowService()
    workflow = svc.get_workflow(objective_or_workflow)

    if workflow:
        await _run_workflow(workflow, mission_id=mission_id, ...)
    else:
        await _run_adhoc(objective_or_workflow, mission_id=mission_id, ...)
```

#### 4.4.2  Gate resolution

```python
async def _resolve_gate(mission_id: str, gate_override: str | None):
    """Resolve gate: CLI flag > mission default > off."""
    mode = gate_override
    if mode is None:
        from modules.backend.services.mission import MissionService
        async with MissionService.factory() as svc:
            mission = await svc.get_mission(mission_id)
            mode = getattr(mission, "gate_mode", None)

    if not mode or mode == "off":
        return None

    from modules.backend.agents.mission_control.gate import create_gate
    return create_gate(mode_override=mode)
```

#### 4.4.3  Workflow run path

Reuses the pattern from `workflow_cmds.py::_action_run` but simplified:

```python
async def _run_workflow(workflow, *, mission_id, budget, gate_override, context_overrides, dry_run, quiet, verbose):
    gate = await _resolve_gate(mission_id, gate_override)

    if dry_run:
        _show_dry_run(workflow)
        return

    display = LiveExecutionDisplay(show_thinking=not quiet)
    event_bus = display.create_event_bus()

    # Merge context overrides
    merged_context = {**(workflow.context or {}), **context_overrides}

    async with WorkflowRunService.factory(event_bus=event_bus) as run_service:
        with display.start():
            run = await run_service.run_workflow(
                workflow_name=workflow.workflow_name,
                triggered_by="user:mc",
                on_progress=display.handle_progress,
                mission_name=None,   # resolved by mission_id
                gate=gate,
                context_overrides=merged_context if context_overrides else None,
            )

    # Post-run report (reuse from report.py)
    ...
```

Note: `WorkflowRunService.run_workflow` resolves mission by name. We need to pass mission name, not ID. Resolve mission name from ID first:
```python
async with MissionService.factory() as svc:
    mission = await svc.get_mission(mission_id)
    mission_name = mission.name
```

#### 4.4.4  Ad-hoc run path

```python
async def _run_adhoc(objective, *, mission_id, budget, gate_override, dry_run, quiet, verbose):
    gate = await _resolve_gate(mission_id, gate_override)
    display = LiveExecutionDisplay(show_thinking=not quiet)
    event_bus = display.create_event_bus()

    async with ExecutionService.factory(event_bus=event_bus) as svc:
        execution = await svc.create_adhoc_execution(
            objective=objective,
            triggered_by="user:mc",
            session_id=str(uuid4()),
            mission_id=mission_id,
        )
        with display.start():
            execution = await svc.run_execution(execution.id, gate=gate)

    await render_execution(execution, "human")
```

#### 4.4.5  --dry-run

```python
def _show_dry_run(workflow):
    console = get_console()
    console.print(f"[bold]Dry run:[/bold] {workflow.workflow_name}\n")
    console.print(f"  Steps: {len(workflow.steps)}")
    console.print(f"  Budget: ${workflow.budget.max_cost_usd:.2f}")
    console.print(f"  Trigger: {workflow.trigger.type}\n")
    for step in workflow.steps:
        deps = f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        console.print(f"  {step.id}: {step.capability}{deps}")
    console.print(f"\n[dim]Run without --dry-run to execute.[/dim]")
```

#### 4.4.6  mc retry

```python
async def retry(n: int, *, mission_id: str, gate_override: str | None) -> None:
    # Load Nth most recent execution for this mission
    async with ExecutionService.factory() as svc:
        executions, _ = await svc.list_executions(mission_id=mission_id, limit=n)
    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    original = executions[n - 1]

    # Re-run with same objective
    await _run_adhoc(
        original.objective,
        mission_id=mission_id,
        budget=original.cost_ceiling_usd,
        gate_override=gate_override,
        dry_run=False, quiet=False, verbose=False,
    )
```

#### 4.4.7  Wire in mc.py

```python
@mc.command()
@click.argument("objective_or_workflow")
@click.option("--budget", type=float, default=None)
@click.option("--gate", "gate_override", type=click.Choice([...]), default=None)
@click.option("--step", is_flag=True, help="Alias for --gate interactive")
@click.option("--set", "overrides", multiple=True, help="key=value context override")
@click.option("--dry-run", is_flag=True)
@click.pass_obj
def run(ctx, objective_or_workflow, budget, gate_override, step, overrides, dry_run):
    """Run a task or workflow against the current mission."""
    if step:
        gate_override = "interactive"
    mission_id = _require_mission()
    context_overrides = dict(kv.split("=", 1) for kv in overrides)
    from modules.clients.cli.mc_run import run as mc_run
    asyncio.run(mc_run(
        objective_or_workflow,
        mission_id=mission_id,
        budget=budget,
        gate_override=gate_override,
        context_overrides=context_overrides,
        dry_run=dry_run,
        quiet=ctx.quiet,
        verbose=ctx.verbose,
    ))
```

---

### Phase 5: mc chat + mc design

**File: `modules/clients/cli/mc_chat.py`** (~180 lines)

#### 4.5.1  Chat REPL — in-process, streaming

```python
async def chat_repl(
    agent_name: str | None = None,
    initial_message: str | None = None,
    mission_id: str,
) -> None:
    from modules.backend.agents.mission_control.mission_control import handle
    from modules.backend.services.session import SessionService
    from modules.backend.events.types import (
        AgentThinkingEvent, AgentResponseChunkEvent, AgentResponseCompleteEvent,
        AgentToolCallEvent, AgentToolResultEvent,
    )

    console = get_console()

    # Create session for multi-turn conversation
    async with get_async_session() as db:
        session_svc = SessionService(db)
        session = await session_svc.create_session(...)
        session_id = str(session.id)
        await db.commit()

    # Load mission brief
    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)
    mission_brief = mission.brief

    console.print(f"[bold cyan]Mission Control[/bold cyan] — {mission.name}")
    console.print(f"[dim]Type /exit to quit. Ctrl+C to cancel current response.[/dim]\n")

    while True:
        # Get user input
        if initial_message:
            user_input = initial_message
            initial_message = None
        else:
            try:
                user_input = click.prompt("you", prompt_suffix=" > ")
            except (click.Abort, EOFError):
                break

        if user_input.strip().lower() in ("/exit", "/quit", "exit", "quit"):
            break

        # Stream response
        console.print()
        try:
            async with get_async_session() as db:
                session_svc = SessionService(db)
                async for event in handle(
                    session_id=session_id,
                    message=user_input,
                    session_service=session_svc,
                    channel="mc",
                    mission_brief=mission_brief if not agent_name else None,
                ):
                    _render_chat_event(console, event)
                await db.commit()
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")

        console.print()


def _render_chat_event(console, event):
    """Render a SessionEvent inline in the chat stream.

    Reuses format_event_line() from event_rendering.py for all
    non-streaming events. Only AgentResponseChunkEvent needs special
    handling (raw text output without line formatting).
    """
    from modules.clients.common.event_rendering import format_event_line

    if isinstance(event, AgentResponseChunkEvent):
        # Stream text inline — no newline, builds up the response
        console.file.write(event.content)
        console.file.flush()

    elif isinstance(event, AgentResponseCompleteEvent):
        console.print()  # newline after streamed chunks
        if event.cost_usd > 0:
            console.print(f"[dim]  ${event.cost_usd:.4f} | {event.input_tokens + event.output_tokens:,} tokens[/dim]")

    else:
        # All other events: use shared formatter
        console.print(f"  {format_event_line(event)}")
```

#### 4.5.2  Design REPL — wraps WorkflowArchitectService

```python
async def design_repl(description: str | None, mission_id: str) -> None:
    console = get_console()
    message_history = []

    console.print("[bold cyan]Workflow Architect[/bold cyan]")
    console.print("[dim]Describe what you want to automate. Type /exit to quit.[/dim]\n")

    user_input = description
    if not user_input:
        user_input = click.prompt("you", prompt_suffix=" > ")

    while True:
        async with WorkflowArchitectService.factory() as svc:
            result = await svc.chat(
                mission_id=mission_id,
                message=user_input,
                message_history=message_history,
            )

        response = result.get("response", "")
        new_history = result.get("message_history", [])
        if new_history:
            message_history = new_history

        console.print(f"\n[bold cyan]architect:[/bold cyan] {response}\n")

        # Check if a workflow was generated
        workflow_yaml = result.get("workflow_yaml")
        if workflow_yaml:
            console.print("[green]Workflow generated. Save with /save <name>[/green]")

        try:
            user_input = click.prompt("you", prompt_suffix=" > ")
        except (click.Abort, EOFError):
            break

        if user_input.strip().lower() in ("/exit", "/quit"):
            break
```

#### 4.5.3  Wire in mc.py

```python
@mc.command()
@click.argument("agent_or_message", nargs=-1)
@click.pass_obj
def chat(ctx, agent_or_message):
    """Talk to your AI team. Interactive REPL or single-shot."""
    mission_id = _require_mission()
    # Parse: mc chat → REPL
    #        mc chat "question" → single-shot to coordinator
    #        mc chat agent-name → REPL with specific agent
    #        mc chat agent-name "question" → single-shot to agent
    agent_name, message = _parse_chat_args(agent_or_message)
    from modules.clients.cli.mc_chat import chat_repl
    asyncio.run(chat_repl(agent_name=agent_name, initial_message=message, mission_id=mission_id))

@mc.command()
@click.argument("description", required=False)
@click.pass_obj
def design(ctx, description):
    """Design a workflow with the Architect."""
    mission_id = _require_mission()
    from modules.clients.cli.mc_chat import design_repl
    asyncio.run(design_repl(description=description, mission_id=mission_id))
```

---

### Phase 6: mc status + mc history

**File: `modules/clients/cli/mc_status.py`** (~150 lines)

#### 4.6.1  mc status

```python
async def show_status(mission_id: str) -> None:
    console = get_console()

    # Load mission
    async with MissionService.factory() as svc:
        mission = await svc.get_mission(mission_id)

    # Load recent executions
    async with ExecutionService.factory() as svc:
        executions, total = await svc.list_executions(mission_id=mission_id, limit=10)

    # Render
    gate_str = mission.gate_mode or "off"
    budget_str = f"${mission.budget_ceiling_usd:.2f}" if mission.budget_ceiling_usd else "unlimited"
    total_cost = sum(e.total_cost_usd for e in executions)

    console.print(f"[bold]{mission.name}[/bold]  [{gate_str}]  Budget: {budget_str}")
    console.print(f"  {mission.description}")
    console.print()

    running = [e for e in executions if str(getattr(e.status, 'value', e.status)) == "running"]
    if running:
        console.print(f"[yellow bold]Active runs: {len(running)}[/yellow bold]")
        for e in running:
            console.print(f"  [yellow]●[/yellow] {e.objective[:60]}")
        console.print()

    recent = executions[:5]
    if recent:
        console.print(f"[bold]Recent ({total} total)  |  Spend: ${total_cost:.4f}[/bold]")
        for e in recent:
            status_val = e.status.value if hasattr(e.status, 'value') else str(e.status)
            icon = {"completed": "[green]✓[/green]", "failed": "[red]✗[/red]",
                    "running": "[yellow]●[/yellow]"}.get(status_val, "·")
            when = e.created_at.strftime("%m-%d %H:%M") if e.created_at else ""
            console.print(f"  {icon} {e.objective[:50]}  [dim]${e.total_cost_usd:.4f}  {when}[/dim]")
```

#### 4.6.2  mc history

```python
async def show_history(n: int | None, mission_id: str) -> None:
    if n is not None:
        await _show_detail(n, mission_id)
        return

    console = get_console()
    async with ExecutionService.factory() as svc:
        executions, total = await svc.list_executions(mission_id=mission_id, limit=20)

    table = build_table(f"History ({total} total)", columns=[
        ("#",      {"width": 4, "justify": "right"}),
        ("When",   {"width": 14, "style": "dim"}),
        ("Status", {"width": 10}),
        ("Cost",   {"width": 8, "justify": "right"}),
        ("What",   {"ratio": 1}),
    ])

    for i, e in enumerate(executions, 1):
        when = e.created_at.strftime("%m-%d %H:%M") if e.created_at else "—"
        table.add_row(str(i), when, styled_status(e.status),
                      f"${e.total_cost_usd:.4f}", e.objective[:60])

    console.print(table)
    console.print(f"[dim]  mc history N for detail[/dim]")


async def _show_detail(n: int, mission_id: str) -> None:
    async with ExecutionService.factory() as svc:
        executions, _ = await svc.list_executions(mission_id=mission_id, limit=n)

    if len(executions) < n:
        click.echo(f"Only {len(executions)} runs in history.")
        sys.exit(1)

    execution = executions[n - 1]
    from modules.clients.cli.report import render_execution
    await render_execution(execution, "human")
```

---

### Phase 7: cli.py to admin.py rename

1. `cp cli.py admin.py`
2. In `admin.py`: remove commands that duplicate mc.py (mission group, team commands). Keep: server, worker, health, credits, db, admin, catalog, schedule, architect, workshop, test, tree, agent, execution, workflow, context, event-worker, telegram, console.
3. Create stub `cli.py`:
```python
#!/usr/bin/env python3
"""Deprecated — use mc.py (user) or admin.py (ops)."""
import click
@click.command()
def main():
    click.echo("cli.py is deprecated.\n")
    click.echo("  For daily use:  python mc.py")
    click.echo("  For admin/ops:  python admin.py")
if __name__ == "__main__":
    main()
```
4. Update references in `chat.py`, docstrings, README, CLAUDE.md.

---

## 5  Files Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `mc.py` | Create | ~250 |
| `modules/clients/cli/cli_context.py` | Create (extract from cli.py) | ~30 |
| `modules/clients/cli/mc_run.py` | Create | ~200 |
| `modules/clients/cli/mc_chat.py` | Create | ~180 |
| `modules/clients/cli/mc_status.py` | Create | ~150 |
| `modules/clients/cli/live_display.py` | Modify | +40 (thinking buffer) |
| `modules/clients/common/event_rendering.py` | Modify | +15 (streaming category) |
| `modules/backend/models/mission.py` | Modify | +4 (gate_mode column) |
| `modules/backend/services/mission.py` | Modify | +15 (set_gate_mode) |
| `modules/backend/repositories/execution.py` | Modify | +3 (mission_id filter) |
| `modules/backend/services/execution.py` | Modify | +3 (mission_id passthrough) |
| `modules/clients/cli/mission_cmds.py` | Modify | +30 (gate_mode, set-gate) |
| `modules/backend/migrations/versions/` | Create | ~20 (alembic migration) |
| `admin.py` | Create (copy from cli.py) | ~1100 |
| `cli.py` | Modify (import CliContext from cli_context.py), then rewrite as deprecation stub in Phase 7 | ~10 |

---

## 6  Verification

After each phase, verify:

1. **Phase 1**: `python -c "from modules.backend.models.mission import Mission; print('gate_mode' in Mission.__table__.columns)"` → True. Run migration. `mc mission create --name test --description test --gate interactive` stores gate_mode.

2. **Phase 2**: Run `mc run "check code"` and confirm agent thinking text (💭) appears in the live display, tool calls show, and handoffs between agents are visible.

3. **Phase 3**: `python mc.py` shows quick-start. `python mc.py mission list` works. Running any command without `mission use` shows clear guard message.

4. **Phase 4**: `mc run ops.platform-audit` detects workflow. `mc run "free text"` runs ad-hoc. `mc run --dry-run ops.platform-audit` shows plan. `mc run --gate interactive "do X"` pauses at gate points.

5. **Phase 5**: `mc chat` enters REPL, streams agent thinking inline, multi-turn works. `mc chat "one-shot"` returns answer. `mc design` enters architect REPL.

6. **Phase 6**: `mc status` shows snapshot. `mc history` shows numbered list. `mc history 3` shows detail.

7. **Phase 7**: `python admin.py server start` works. `python cli.py` shows deprecation. No broken imports anywhere.

---

## 7  What This Does NOT Include

- Web frontend chat (Plan 34 / separate plan)
- New event types (existing hierarchy is sufficient)
- Redis event bus for CLI (CliEventBus is in-process, sufficient for CLI)
- Agent routing changes (coordinator uses existing routing)
- Workflow YAML changes
- Schedule/cron management (stays in admin.py)
