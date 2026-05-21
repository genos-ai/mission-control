"""AdminScreen — platform administration with sub-tabs.

Accessible via Ctrl+A. Only for admin users. Contains five sub-tabs:
Catalog, Metrics, Config, Health, Users.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ── Admin Catalog Tab ────────────────────────────────────────────────


class _AdminCatalogTab(Static):
    """CRUD table for agent catalog management."""

    def compose(self) -> ComposeResult:
        yield Button(
            "+ Create Agent",
            id="admin-create-agent-btn",
            variant="primary",
        )
        yield DataTable(id="admin-catalog-table")

    async def on_mount(self) -> None:
        table = self.query_one("#admin-catalog-table", DataTable)
        table.add_columns(
            "Name", "Type", "Version", "Enabled", "Visibility",
        )
        self.run_worker(self._load_agents(), thread=False)

    async def _load_agents(self) -> None:
        try:
            agents = await self.app.bridge.list_catalog_agents(
                enabled_only=False,
            )
            table = self.query_one("#admin-catalog-table", DataTable)
            table.clear()
            for a in agents:
                enabled = "✓" if a.get("enabled") else "✗"
                table.add_row(
                    a.get("agent_name", ""),
                    a.get("agent_type", ""),
                    a.get("version", ""),
                    enabled,
                    a.get("visibility", "public"),
                    key=a.get("agent_name", ""),
                )
        except Exception as exc:
            logger.warning("Could not load admin catalog", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "admin-create-agent-btn":
            self.app.notify(
                "Create agent: use CLI `mc catalog create`",
                severity="information",
            )


# ── Admin Metrics Tab ────────────────────────────────────────────────


class _AdminMetricsTab(Static):
    """Platform-wide metrics and cost breakdown."""

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]PLATFORM METRICS[/bold]",
            markup=True,
            classes="sidebar-heading",
        )
        yield Static(
            "[dim]Loading metrics...[/dim]",
            id="admin-metrics-overview",
            markup=True,
        )
        yield Static(
            "",
            id="admin-metrics-cost",
            markup=True,
        )
        yield Static(
            "",
            id="admin-metrics-activity",
            markup=True,
        )

    async def on_mount(self) -> None:
        self.run_worker(self._load_metrics(), thread=False)

    async def _load_metrics(self) -> None:
        try:
            overview = await self.app.bridge.admin_get_metrics_overview()
            self._render_overview(overview)
        except Exception as exc:
            logger.warning("Could not load metrics", exc_info=True)
            try:
                panel = self.query_one(
                    "#admin-metrics-overview", Static,
                )
                panel.update(f"[red]Error: {exc}[/red]")
            except Exception:
                logger.debug("metrics error panel update failed", exc_info=True)

        try:
            cost = await self.app.bridge.admin_get_cost_breakdown()
            self._render_cost(cost)
        except Exception:
            logger.debug("cost breakdown load failed", exc_info=True)

        try:
            activity = await self.app.bridge.admin_get_activity(limit=10)
            self._render_activity(activity)
        except Exception:
            logger.debug("activity load failed", exc_info=True)

    def _render_overview(self, data: dict[str, Any]) -> None:
        try:
            panel = self.query_one("#admin-metrics-overview", Static)
            missions = data.get("mission_count", 0)
            sessions = data.get("session_count", 0)
            executions = data.get("execution_count", 0)
            agents = data.get("agent_count", 0)
            cost = data.get("total_cost_usd", 0.0)
            panel.update(
                f"Missions: [bold]{missions}[/bold]  │  "
                f"Sessions: [bold]{sessions}[/bold]  │  "
                f"Executions: [bold]{executions}[/bold]  │  "
                f"Agents: [bold]{agents}[/bold]  │  "
                f"Cost: [bold]${cost:.2f}[/bold]",
            )
        except Exception:
            logger.debug("metrics overview render failed", exc_info=True)

    def _render_cost(self, data: dict[str, Any]) -> None:
        try:
            panel = self.query_one("#admin-metrics-cost", Static)
            by_agent = data.get("by_agent", {})
            if not by_agent:
                panel.update("[dim]No cost data yet[/dim]")
                return

            total = sum(by_agent.values()) or 1.0
            lines = ["[bold]── COST BY AGENT ──[/bold]"]
            for agent, cost in sorted(
                by_agent.items(), key=lambda x: x[1], reverse=True,
            ):
                pct = (cost / total) * 100
                bar_len = int(pct / 5)
                bar = "━" * bar_len
                lines.append(
                    f"  {agent:<20s} {bar}  ${cost:.2f}  ({pct:.0f}%)",
                )
            panel.update("\n".join(lines))
        except Exception:
            logger.debug("cost breakdown render failed", exc_info=True)

    def _render_activity(self, data: dict[str, Any]) -> None:
        try:
            panel = self.query_one("#admin-metrics-activity", Static)
            recent = data.get("recent_executions", [])
            if not recent:
                panel.update("[dim]No recent activity[/dim]")
                return

            lines = ["[bold]── RECENT ACTIVITY ──[/bold]"]
            for r in recent[:10]:
                obj = (r.get("objective", "") or "")[:30]
                status = r.get("status", "?")
                cost = r.get("total_cost_usd", 0.0)
                lines.append(
                    f"  {obj}  {status}  ${cost:.2f}",
                )
            panel.update("\n".join(lines))
        except Exception:
            logger.debug("activity render failed", exc_info=True)


# ── Admin Config Tab ─────────────────────────────────────────────────


class _AdminConfigTab(Static):
    """Read-only platform configuration display."""

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]PLATFORM CONFIGURATION[/bold] (read-only)",
            markup=True,
            classes="sidebar-heading",
        )
        yield VerticalScroll(
            Static(
                "[dim]Loading config...[/dim]",
                id="admin-config-content",
                markup=True,
            ),
            id="admin-config-scroll",
        )

    async def on_mount(self) -> None:
        self.run_worker(self._load_config(), thread=False)

    async def _load_config(self) -> None:
        try:
            config = await self.app.bridge.admin_get_config()
            self._render_config(config)
        except Exception as exc:
            logger.warning("Could not load config", exc_info=True)
            try:
                panel = self.query_one(
                    "#admin-config-content", Static,
                )
                panel.update(f"[red]Error: {exc}[/red]")
            except Exception:
                logger.debug("config error panel update failed", exc_info=True)

    def _render_config(self, config: dict[str, Any]) -> None:
        try:
            panel = self.query_one("#admin-config-content", Static)
            lines = self._format_dict(config, indent=0)
            panel.update("\n".join(lines))
        except Exception:
            logger.debug("config render failed", exc_info=True)

    def _format_dict(
        self, d: dict, indent: int = 0,
    ) -> list[str]:
        lines: list[str] = []
        prefix = "  " * indent
        for key, val in d.items():
            if isinstance(val, dict):
                lines.append(f"{prefix}[bold]{key}:[/bold]")
                lines.extend(self._format_dict(val, indent + 1))
            elif isinstance(val, list):
                lines.append(f"{prefix}[bold]{key}:[/bold]")
                for item in val:
                    lines.append(f"{prefix}  - {item}")
            else:
                lines.append(f"{prefix}{key}: {val}")
        return lines


# ── Admin Health Tab ─────────────────────────────────────────────────


class _AdminHealthTab(Static):
    """System health checks."""

    def compose(self) -> ComposeResult:
        yield Label(
            "[bold]SYSTEM HEALTH[/bold]",
            markup=True,
            classes="sidebar-heading",
        )
        yield Static(
            "[dim]Checking health...[/dim]",
            id="admin-health-content",
            markup=True,
        )
        yield Button(
            "Refresh",
            id="admin-health-refresh",
            variant="default",
        )

    async def on_mount(self) -> None:
        self.run_worker(self._load_health(), thread=False)

    async def _load_health(self) -> None:
        try:
            health = await self.app.bridge.get_health()
            self._render_health(health)
        except Exception as exc:
            logger.warning("Could not load health", exc_info=True)
            try:
                panel = self.query_one(
                    "#admin-health-content", Static,
                )
                panel.update(f"[red]Health check failed: {exc}[/red]")
            except Exception:
                logger.debug("health error panel update failed", exc_info=True)

    def _render_health(self, health: dict[str, Any]) -> None:
        try:
            panel = self.query_one("#admin-health-content", Static)
            overall = health.get("overall_status", "unknown")
            color = "green" if overall == "healthy" else "red"

            lines = [f"Overall: [{color}]● {overall}[/{color}]", ""]

            for comp in health.get("components", []):
                name = comp.get("name", "?")
                status = comp.get("status", "?")
                latency = comp.get("latency_ms", 0)
                error = comp.get("error", "")
                c = "green" if status == "healthy" else "red"
                line = f"  {name:<12s} [{c}]● {status}[/{c}]"
                if latency:
                    line += f"  latency: {latency}ms"
                if error:
                    line += f"  [red]{error}[/red]"
                lines.append(line)

            panel.update("\n".join(lines))
        except Exception:
            logger.debug("health render failed", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "admin-health-refresh":
            self.run_worker(self._load_health(), thread=False)


# ── Admin Users Tab ──────────────────────────────────────────────────


class _AdminUsersTab(Static):
    """User management table."""

    def compose(self) -> ComposeResult:
        yield Button(
            "+ Create User",
            id="admin-create-user-btn",
            variant="primary",
        )
        yield DataTable(id="admin-users-table")

    async def on_mount(self) -> None:
        table = self.query_one("#admin-users-table", DataTable)
        table.add_columns(
            "Name", "Email", "Role", "Status", "Service Acct",
        )
        self.run_worker(self._load_users(), thread=False)

    async def _load_users(self) -> None:
        try:
            users = await self.app.bridge.admin_list_users()
            table = self.query_one("#admin-users-table", DataTable)
            table.clear()
            for u in users:
                status = "Active" if u.get("is_active") else "Inactive"
                svc = "Yes" if u.get("is_service_account") else "No"
                table.add_row(
                    u.get("display_name", ""),
                    u.get("email", ""),
                    u.get("system_role", ""),
                    status,
                    svc,
                    key=u.get("id", ""),
                )
        except Exception as exc:
            logger.warning("Could not load users", exc_info=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "admin-create-user-btn":
            self.app.notify(
                "Create user: use CLI `mc user create`",
                severity="information",
            )


# ── AdminScreen ──────────────────────────────────────────────────────


class AdminScreen(Screen):
    """Admin section with sub-tabs."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="admin-body"):
            yield Label(
                "[bold]ADMINISTRATION[/bold]",
                markup=True,
                id="admin-title",
            )
            with TabbedContent(
                "Catalog", "Metrics", "Config", "Health", "Users",
                id="admin-tabs",
            ):
                with TabPane("Catalog", id="admin-catalog-pane"):
                    yield _AdminCatalogTab()
                with TabPane("Metrics", id="admin-metrics-pane"):
                    yield _AdminMetricsTab()
                with TabPane("Config", id="admin-config-pane"):
                    yield _AdminConfigTab()
                with TabPane("Health", id="admin-health-pane"):
                    yield _AdminHealthTab()
                with TabPane("Users", id="admin-users-pane"):
                    yield _AdminUsersTab()
        yield Footer()

    def action_go_back(self) -> None:
        self.app.pop_screen()
