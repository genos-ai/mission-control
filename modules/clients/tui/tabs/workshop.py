"""WorkshopTab — single-agent prompt iteration and testing.

Vertical stack layout: agent selector, prompt editors, cached inputs,
test output. Lets operators iterate on prompts using cached inputs from
previous workflow runs.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static, TextArea

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


class WorkshopTab(Static):
    """Prompt workshop — iterate and test agent prompts."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._selected_agent: str = ""
        self._cached_inputs: list[dict[str, Any]] = []
        self._test_runs: list[dict[str, Any]] = []
        self._system_prompt_expanded = False
        self._cached_inputs_expanded = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="workshop-container"):
            yield Label(
                "[bold]WORKSHOP[/bold]",
                markup=True,
                classes="sidebar-heading",
            )

            # ── Agent + source selectors ──────────────────────────
            with Horizontal(id="workshop-selectors"):
                yield Label("Agent: ", id="workshop-agent-label")
                yield Select(
                    [],
                    id="workshop-agent-select",
                    prompt="Select agent...",
                )

            # ── System prompt (collapsible) ───────────────────────
            yield Button(
                "▸ System Prompt",
                id="workshop-sys-toggle",
                variant="default",
            )
            yield TextArea(
                "",
                id="workshop-sys-prompt",
                read_only=True,
                classes="workshop-hidden",
            )

            # ── User prompt editor ────────────────────────────────
            yield Label(
                "[bold]User Prompt[/bold]",
                markup=True,
                id="workshop-user-label",
            )
            yield TextArea(
                "",
                id="workshop-user-prompt",
            )
            with Horizontal(id="workshop-prompt-actions"):
                yield Button(
                    "Save",
                    id="workshop-save-btn",
                    variant="default",
                )
                yield Button(
                    "▶ Test",
                    id="workshop-test-btn",
                    variant="primary",
                )

            # ── Cached inputs (collapsible) ───────────────────────
            yield Button(
                "▸ Cached Inputs",
                id="workshop-inputs-toggle",
                variant="default",
            )
            yield Static(
                "[dim]No cached inputs loaded[/dim]",
                id="workshop-inputs-content",
                markup=True,
                classes="workshop-hidden",
            )

            # ── Test output ───────────────────────────────────────
            yield Label(
                "[bold]── TEST OUTPUT ──[/bold]",
                markup=True,
                id="workshop-output-label",
            )
            yield Static(
                "[dim]Run a test to see output here[/dim]",
                id="workshop-output",
                markup=True,
            )

            # ── Previous runs ─────────────────────────────────────
            yield Static(
                "",
                id="workshop-prev-runs",
                markup=True,
            )

    async def on_mount(self) -> None:
        self.run_worker(self._load_agents(), thread=False)

    async def _load_agents(self) -> None:
        """Populate agent selector from team members."""
        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            team = await self.app.bridge.get_team(mission_id)
            self.app.state.team.members = team
            if not team:
                self._show_empty_state()
                return

            options = [
                (m.get("agent_name", "unknown"), m.get("agent_name", ""))
                for m in team
            ]
            try:
                select = self.query_one(
                    "#workshop-agent-select", Select,
                )
                select.set_options(options)
            except Exception:
                logger.debug("workshop agent select population failed", exc_info=True)
        except Exception as exc:
            logger.warning("Could not load team for workshop", exc_info=True)

    def _show_empty_state(self) -> None:
        """Show placeholder when no agents/runs available."""
        try:
            output = self.query_one("#workshop-output", Static)
            output.update(
                "Workshop needs a completed workflow run to provide "
                "cached inputs.\nRun your workflow at least once first.\n"
                "[dim]Press Alt+4 to go to Workflows[/dim]",
            )
        except Exception:
            logger.debug("workshop empty state display failed", exc_info=True)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle agent selection."""
        if event.select.id != "workshop-agent-select":
            return
        if event.value is Select.BLANK:
            return

        self._selected_agent = str(event.value)
        await self._load_agent_data()

    async def _load_agent_data(self) -> None:
        """Load prompts and cached inputs for selected agent."""
        if not self._selected_agent:
            return

        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        # Load prompts from team member data
        team = self.app.state.team.members or []
        member = next(
            (m for m in team if m.get("agent_name") == self._selected_agent),
            None,
        )
        if member:
            try:
                sys_prompt = self.query_one(
                    "#workshop-sys-prompt", TextArea,
                )
                sys_prompt.load_text(member.get("system_prompt", ""))
            except Exception:
                logger.debug("workshop system prompt load failed", exc_info=True)
            try:
                user_prompt = self.query_one(
                    "#workshop-user-prompt", TextArea,
                )
                user_prompt.load_text(member.get("user_prompt", ""))
            except Exception:
                logger.debug("workshop user prompt load failed", exc_info=True)

        # Load cached inputs
        try:
            self._cached_inputs = await self.app.bridge.get_cached_inputs(
                agent_name=self._selected_agent,
                mission_id=mission_id,
            )
            self._render_cached_inputs()
        except Exception as exc:
            logger.warning("Could not load cached inputs", exc_info=True)

        # Load previous workshop runs
        try:
            self._test_runs = await self.app.bridge.list_workshop_runs(
                agent_name=self._selected_agent,
            )
            self._render_prev_runs()
        except Exception as exc:
            logger.warning("Could not load workshop runs", exc_info=True)

    def _render_cached_inputs(self) -> None:
        """Render cached inputs section."""
        try:
            content = self.query_one(
                "#workshop-inputs-content", Static,
            )
            if not self._cached_inputs:
                content.update("[dim]No cached inputs from previous runs[/dim]")
                return

            lines: list[str] = []
            for ci in self._cached_inputs[:5]:
                task_id = ci.get("task_id", "?")
                agent = ci.get("agent_name", "?")
                data = ci.get("output_data", "")
                preview = (str(data)[:80] + "...") if len(str(data)) > 80 else str(data)
                lines.append(
                    f"  [bold]{task_id}[/bold] ({agent}): "
                    f"[dim]{preview}[/dim]",
                )
            content.update("\n".join(lines))
        except Exception:
            logger.debug("workshop cached inputs render failed", exc_info=True)

    def _render_prev_runs(self) -> None:
        """Render previous workshop runs."""
        try:
            panel = self.query_one("#workshop-prev-runs", Static)
            if not self._test_runs:
                panel.update("")
                return

            parts: list[str] = ["[bold]Previous runs:[/bold]  "]
            for run in self._test_runs[:5]:
                cost = run.get("cost_usd", 0.0)
                run_id = run.get("id", "?")[:8]
                parts.append(f"[dim]#{run_id} · ${cost:.3f}[/dim]  ")
            panel.update("".join(parts))
        except Exception:
            logger.debug("workshop prev runs render failed", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workshop-sys-toggle":
            self._toggle_system_prompt()
        elif event.button.id == "workshop-inputs-toggle":
            self._toggle_cached_inputs()
        elif event.button.id == "workshop-save-btn":
            await self._save_prompt()
        elif event.button.id == "workshop-test-btn":
            await self._run_test()

    def _toggle_system_prompt(self) -> None:
        """Toggle system prompt visibility."""
        self._system_prompt_expanded = not self._system_prompt_expanded
        try:
            area = self.query_one("#workshop-sys-prompt", TextArea)
            btn = self.query_one("#workshop-sys-toggle", Button)
            if self._system_prompt_expanded:
                area.remove_class("workshop-hidden")
                btn.label = "▾ System Prompt"
            else:
                area.add_class("workshop-hidden")
                btn.label = "▸ System Prompt"
        except Exception:
            logger.debug("workshop system prompt toggle failed", exc_info=True)

    def _toggle_cached_inputs(self) -> None:
        """Toggle cached inputs visibility."""
        self._cached_inputs_expanded = not self._cached_inputs_expanded
        try:
            content = self.query_one(
                "#workshop-inputs-content", Static,
            )
            btn = self.query_one("#workshop-inputs-toggle", Button)
            if self._cached_inputs_expanded:
                content.remove_class("workshop-hidden")
                btn.label = "▾ Cached Inputs"
            else:
                content.add_class("workshop-hidden")
                btn.label = "▸ Cached Inputs"
        except Exception:
            logger.debug("workshop cached inputs toggle failed", exc_info=True)

    async def _save_prompt(self) -> None:
        """Save current user prompt to team member."""
        if not self._selected_agent:
            self.app.notify("Select an agent first", severity="warning")
            return

        mission_id = self.app.state.current_mission_id
        if not mission_id:
            return

        try:
            user_prompt = self.query_one(
                "#workshop-user-prompt", TextArea,
            )
            content = user_prompt.text

            # Find team member ID
            team = self.app.state.team.members or []
            member = next(
                (m for m in team
                 if m.get("agent_name") == self._selected_agent),
                None,
            )
            if not member:
                self.app.notify(
                    "Agent not found on team", severity="error",
                )
                return

            await self.app.bridge.update_team_member_prompt(
                mission_id,
                member_id=member["id"],
                user_prompt=content,
            )
            self.app.notify("Prompt saved", severity="information")
        except Exception as exc:
            logger.error("Failed to save prompt", exc_info=True)
            self.app.notify(f"Save failed: {exc}", severity="error")

    async def _run_test(self) -> None:
        """Run workshop test with current prompt."""
        if not self._selected_agent:
            self.app.notify("Select an agent first", severity="warning")
            return

        try:
            output_panel = self.query_one("#workshop-output", Static)
            output_panel.update("[yellow]Running test...[/yellow]")
        except Exception:
            logger.debug("workshop test status display failed", exc_info=True)

        try:
            user_prompt = self.query_one(
                "#workshop-user-prompt", TextArea,
            )
            prompt_text = user_prompt.text

            # Use first cached input if available
            inputs = None
            if self._cached_inputs:
                inputs = self._cached_inputs[0].get("output_data")
                if isinstance(inputs, str):
                    inputs = {"input": inputs}

            result = await self.app.bridge.run_workshop_test(
                agent_name=self._selected_agent,
                prompt_override=prompt_text or None,
                inputs=inputs,
                budget_usd=1.0,
            )

            # Display result
            cost = result.get("cost_usd", 0.0)
            tokens_in = result.get("input_tokens", 0)
            tokens_out = result.get("output_tokens", 0)
            output_text = result.get("output", "")

            try:
                output_panel = self.query_one("#workshop-output", Static)
                output_panel.update(
                    f"[bold]${cost:.4f}[/bold] · "
                    f"{tokens_in}/{tokens_out} tokens\n\n"
                    f"{output_text}",
                )
            except Exception:
                logger.debug("workshop test result display failed", exc_info=True)

            # Refresh previous runs
            self._test_runs = await self.app.bridge.list_workshop_runs(
                agent_name=self._selected_agent,
            )
            self._render_prev_runs()

            self.app.notify(
                f"Test complete · ${cost:.4f}",
                severity="information",
            )
        except Exception as exc:
            logger.error("Workshop test failed", exc_info=True)
            try:
                output_panel = self.query_one("#workshop-output", Static)
                output_panel.update(f"[red]Test failed: {exc}[/red]")
            except Exception:
                logger.debug("workshop test error display failed", exc_info=True)
            self.app.notify(f"Test failed: {exc}", severity="error")
