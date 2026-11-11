"""Centralized TUI state — plain dataclass read by widgets, updated by App.

Widgets never mutate state directly. The App updates state on events
and triggers widget refreshes via Textual's reactive/message system.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from modules.backend.agents.mission_control.gate import GateContext
from modules.backend.agents.mission_control.outcome import ExecutionOutcome
from modules.backend.agents.mission_control.roster import RosterAgentEntry
from modules.backend.schemas.task_plan import TaskPlan

# ── Client-side task view ─────────────────────────────────────────────


@dataclass(frozen=True)
class TaskStatusView:
    """What the TUI knows about a finished task from its plan.step.completed event.

    A display record only: the backend TaskResult (and its failure record)
    is never rebuilt from SSE events.
    """

    task_id: str
    agent_name: str
    status: str  # a TaskStatus value: success, failed, timeout or skipped


# ── Tab-specific sub-dataclasses ──────────────────────────────────────


@dataclass
class ChatState:
    """Chat tab state."""

    sessions: list[dict] = field(default_factory=list)
    active_session_id: str | None = None
    messages: list[dict] = field(default_factory=list)


@dataclass
class WorkflowState:
    """Workflows tab state."""

    workflows: list[dict] = field(default_factory=list)
    selected_workflow: str | None = None
    schedules: list[dict] = field(default_factory=list)


@dataclass
class TeamState:
    """Team tab state."""

    members: list[dict] = field(default_factory=list)
    selected_member: str | None = None


@dataclass
class ContextState:
    """Context tab state."""

    document: str = ""
    history: list[dict] = field(default_factory=list)


# ── Main state ────────────────────────────────────────────────────────


@dataclass
class TuiState:
    """Plain dataclass held by the App. Widgets read from it."""

    # ── Mission ──────────────────────────────────────────────────────
    current_mission_id: str | None = None
    current_mission_name: str | None = None

    # ── Session ──────────────────────────────────────────────────────
    current_session_id: str | None = None

    # ── Roster ───────────────────────────────────────────────────────
    roster_agents: list[RosterAgentEntry] = field(default_factory=list)

    # ── Active mission ───────────────────────────────────────────────
    mission_id: str | None = None
    mission_status: str = "idle"  # idle|planning|running|completed|failed
    task_plan: TaskPlan | None = None
    task_layers: list[list[str]] = field(default_factory=list)
    task_results: dict[str, TaskStatusView] = field(default_factory=dict)
    current_layer: int = 0
    execution_outcome: ExecutionOutcome | None = None

    # ── Agent tracking (keyed by task_id) ────────────────────────────
    active_agents: set[str] = field(default_factory=set)
    selected_agent: str | None = None
    agent_thinking: dict[str, str] = field(default_factory=dict)
    agent_output: dict[str, str] = field(default_factory=dict)
    agent_tool_calls: dict[str, list[dict]] = field(default_factory=dict)
    agent_verification: dict[str, dict] = field(default_factory=dict)

    # ── Cost ─────────────────────────────────────────────────────────
    total_cost_usd: float = 0.0
    budget_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # ── Events (ring buffer for the event stream widget) ─────────────
    events: deque = field(default_factory=lambda: deque(maxlen=500))

    # ── Gate ─────────────────────────────────────────────────────────
    pending_gate: GateContext | None = None
    gate_history: list[dict] = field(default_factory=list)

    # ── Notifications ────────────────────────────────────────────────
    notifications: deque = field(default_factory=lambda: deque(maxlen=50))

    # ── Workflow ─────────────────────────────────────────────────────
    workflow_name: str | None = None
    workflow_progress: dict[str, dict] = field(default_factory=dict)
    workflow_waves: list[list[str]] = field(default_factory=list)

    # ── Navigation (Plan 32) ─────────────────────────────────────────
    active_screen: str = "dashboard"  # dashboard|workspace|catalog|admin|profile
    active_tab: str = "overview"  # overview|team|chat|workflows|runs|workshop|context

    # ── Auth/Role (Plan 32) ──────────────────────────────────────────
    system_role: str = "admin"  # viewer|user|admin
    mission_role: str = "Owner"  # Owner|Maintainer|Viewer

    # ── Tab-specific state (Plan 32 sub-dataclasses) ─────────────────
    team: TeamState = field(default_factory=TeamState)
    chat: ChatState = field(default_factory=ChatState)
    workflow: WorkflowState = field(default_factory=WorkflowState)
    context: ContextState = field(default_factory=ContextState)

    # ── Helpers ──────────────────────────────────────────────────────

    def reset_mission(self) -> None:
        """Clear mission-specific state for a new run."""
        self.mission_id = None
        self.mission_status = "idle"
        self.task_plan = None
        self.task_layers = []
        self.task_results = {}
        self.current_layer = 0
        self.execution_outcome = None
        self.active_agents = set()
        self.agent_thinking = {}
        self.agent_output = {}
        self.agent_tool_calls = {}
        self.agent_verification = {}
        self.total_cost_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.pending_gate = None
        self.gate_history = []
        self.notifications = deque(maxlen=50)

    @property
    def tasks_completed(self) -> int:
        """Number of tasks with a result."""
        return len(self.task_results)

    @property
    def tasks_total(self) -> int:
        """Total tasks in the plan."""
        if self.task_plan:
            return len(self.task_plan.tasks)
        return 0

    @property
    def budget_fraction(self) -> float:
        """Cost as a fraction of budget (0.0-1.0). Returns 0 if no budget."""
        if self.budget_usd <= 0:
            return 0.0
        return min(self.total_cost_usd / self.budget_usd, 1.0)
