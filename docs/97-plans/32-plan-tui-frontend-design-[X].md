# Plan 32 — TUI Frontend Design Specification

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **Created** | 2026-03-25 |
| **Updated** | 2026-03-25 — adversarial review: enforced BFF-thin-client boundary, moved bridge orchestration to backend gaps, unified async interface |
| **Depends on** | Plan 23 (TUI: Interactive Mission Control Dashboard — partial impl), Plan 28 (Platform Architecture), Plan 29 (Web Frontend Design), Plan 30 (User Management & Auth), Plan 31 (Current Mission Selection) |
| **Supersedes** | Plan 23 screen/widget specs (Plan 23 remains valid for gate reviewer and event routing architecture) |
| **Target** | `modules/clients/tui/` — Textual (Python) |

---

## 1  Objective

Extend the existing TUI (`modules/clients/tui/`) to achieve feature parity with the
web frontend (Plan 29) in a terminal-native way. The TUI currently covers mission
execution monitoring, gate review, and event streaming (Plan 23 scope). This plan adds
the full mission workspace experience: dashboard, team management, chat, workflow design,
run history, workshop, context viewing, catalog browse, admin, and profile screens.

**Design philosophy:**
- Terminal-native. Every Plan 29 screen is adapted for terminal interaction, not ported literally.
- Keyboard-first. Every action reachable via keyboard. Mouse is optional.
- In-process service calls via `ServiceBridge` — no HTTP. The TUI imports backend services directly.
- Thin client. Zero business logic. All state from backend services. Presentation layer only.
- Desktop terminal on 120+ column screens. Minimum 80×24 for degraded mode.

**Relationship to Plan 23:**
Plan 23 defined the core execution monitoring loop (gate reviewer, event routing, DAG
visualization, agent detail). That architecture remains unchanged. This plan adds the
screens and navigation that surround it — the workspace tabs, CRUD operations, and
administrative functions that Plan 29 specifies for the web frontend.

---

## 2  Technology Stack

**Already in use** (`modules/clients/tui/`):

| Library | Purpose |
|---------|---------|
| Textual >= 1.0.0 | TUI framework |
| Rich | Terminal rendering (Textual dependency) |

**Already in use** (`modules/clients/common/`):

| Module | Purpose |
|--------|---------|
| `display.py` | `build_table()`, `styled_status()`, formatters — Rule 006 mandated |
| `gate_helpers.py` | `cost_color()`, `status_icon()`, `ACTION_COLORS`, `gate_header()`, `safe_css_id()` |

**No additional dependencies required.** Textual provides all needed widgets (DataTable,
TabbedContent, TextArea, Input, OptionList, Tree, RichLog, MarkdownViewer, etc.) out of
the box.

---

## 3  Information Architecture

### 3.1  Global layout

The existing three-column layout (Plan 23) becomes a tabbed workspace:

```
┌──────────────────────────────────────────────────────────────────┐
│  MISSION CONTROL   │  [Mission Name ▾]   │   ⚙  🔔(3)  👤       │
├────────────────────┴─────────────────────┴──────────────────────┤
│  [Overview] [Team] [Chat] [Workflows] [Runs] [Workshop] [Ctx]  │
├──────────────────┬───────────────────────┬──────────────────────┤
│                  │                       │                      │
│   Left Panel     │   Center Content      │   Right Panel        │
│   (contextual)   │   (tab-dependent)     │   (contextual)       │
│                  │                       │                      │
│                  │                       │                      │
│                  │                       │                      │
├──────────────────┴───────────────────────┴──────────────────────┤
│  $0.18 │ 4.2k/1.1k tokens │ Layer 2/4 │ ● 1 gate │ connected  │
└─────────────────────────────────────────────────────────────────┘
```

**Four persistent elements:**
1. **Header bar** — mission selector, app title, settings/notifications/profile shortcuts
2. **Tab bar** — workspace tabs (only visible when inside a mission)
3. **Content area** — up to three columns depending on active tab
4. **Status bar** — cost, tokens, layer progress, gate count, connection status (existing `CostBar`)

### 3.2  Screen hierarchy

```
MissionControlApp
├── DashboardScreen          (default on launch if no mission selected)
│   └── MissionCardsGrid
├── MissionPickerScreen      (modal — existing, needs enhancement)
├── MissionWorkspaceScreen   (replaces existing MainScreen)
│   ├── OverviewTab          (existing Plan 23 layout — 3-column)
│   ├── TeamTab              (new)
│   ├── ChatTab              (new)
│   ├── WorkflowsTab         (new)
│   ├── RunsTab              (new)
│   ├── WorkshopTab          (new)
│   └── ContextTab           (new)
├── CatalogScreen            (new — global agent browse)
├── AdminScreen              (new — admin section with sub-tabs)
│   ├── AdminCatalogTab
│   ├── AdminMetricsTab
│   ├── AdminConfigTab
│   ├── AdminHealthTab
│   └── AdminUsersTab
├── ProfileScreen            (new)
├── GateReviewModal          (existing — no changes)
└── MissionHistoryScreen     (existing — absorbed into RunsTab)
```

### 3.3  Navigation model

The TUI uses a screen stack plus tab navigation within screens:

```
Global shortcuts:
  Ctrl+D  → Dashboard
  Ctrl+P  → Mission picker (modal)
  Ctrl+G  → Catalog
  Ctrl+A  → Admin (admin only)
  Ctrl+U  → Profile
  Ctrl+Q  → Quit

Mission workspace tab shortcuts:
  Alt+1   → Overview tab
  Alt+2   → Team tab
  Alt+3   → Chat tab
  Alt+4   → Workflows tab
  Alt+5   → Runs tab
  Alt+6   → Workshop tab
  Alt+7   → Context tab

Existing shortcuts (preserved from Plan 23):
  Ctrl+M  → New execution (focus chat input on Overview)
  Ctrl+K  → Cancel active execution
  Ctrl+/  → Focus chat input
  F1      → Overview (same as Alt+1)
  Tab     → Next agent in sidebar
  Shift+Tab → Previous agent
```

### 3.4  Right panel

The right panel replaces Plan 29's "right drawer" concept. It is always visible but its
content changes based on context:

| Active tab | Right panel content | Trigger |
|---|---|---|
| Overview | Event stream (existing `EventStreamWidget`) | Always visible |
| Team | Prompt version history | Click "History" on a prompt |
| Chat | (not used — chat IS the center content) | — |
| Workflows | Workflow step detail or Architect chat log | Click step node or "Design" |
| Runs | Historical event log or cost breakdown | Click "Events" or "Cost" on a run |
| Workshop | Full output preview (rendered markdown) | Click "Preview" |
| Context | Change history diffs | Click a change entry |

---

## 4  Route Equivalent (Screen + Tab)

The TUI has no URL routing. Navigation is tracked via `TuiState.active_screen` and
`TuiState.active_tab`:

| Web Route (Plan 29) | TUI Equivalent |
|---|---|
| `/` | `DashboardScreen` |
| `/missions/new` | `MissionPickerScreen` (modal, create tab) |
| `/missions/:id` | `MissionWorkspaceScreen` → OverviewTab |
| `/missions/:id/overview` | `MissionWorkspaceScreen` → OverviewTab |
| `/missions/:id/team` | `MissionWorkspaceScreen` → TeamTab |
| `/missions/:id/chat` | `MissionWorkspaceScreen` → ChatTab |
| `/missions/:id/chat/:threadId` | `MissionWorkspaceScreen` → ChatTab (thread selected) |
| `/missions/:id/workflows` | `MissionWorkspaceScreen` → WorkflowsTab |
| `/missions/:id/runs` | `MissionWorkspaceScreen` → RunsTab |
| `/missions/:id/runs/:runId` | `MissionWorkspaceScreen` → RunsTab (run expanded) |
| `/missions/:id/workshop` | `MissionWorkspaceScreen` → WorkshopTab |
| `/missions/:id/context` | `MissionWorkspaceScreen` → ContextTab |
| `/catalog` | `CatalogScreen` |
| `/profile` | `ProfileScreen` |
| `/admin` | `AdminScreen` → CatalogTab |
| `/admin/catalog` | `AdminScreen` → CatalogTab |
| `/admin/metrics` | `AdminScreen` → MetricsTab |
| `/admin/config` | `AdminScreen` → ConfigTab |
| `/admin/health` | `AdminScreen` → HealthTab |
| `/admin/users` | `AdminScreen` → UsersTab |
| `/login` | Not applicable — TUI uses system:cli service account (in-process) |

---

## 5  Screens — Detailed Specifications

### 5.1  DashboardScreen

Global overview. Shown on launch when no mission is selected, or via Ctrl+D.

**Layout (single column, vertically scrolled):**

```
┌──────────────────────────────────────────────────────────────────┐
│  MISSION CONTROL DASHBOARD                            [Ctrl+D]  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ── ACTIVE RUNS ─────────────────────────────────────────────── │
│  ● Daily CTI #47 · Research Agent · web_search · $0.20          │
│  ● SOC Ops #13 · step 1/3 · $0.45                              │
│                                                                  │
│  ── MISSIONS ────────────────────────────────────────────────── │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │ Daily CTI Brief      │  │ SOC Operations       │            │
│  │ Active · 5 agents    │  │ Active · 3 agents    │            │
│  │ 46 runs · $12.50     │  │ 13 runs · $8.20      │            │
│  │ Last: 6h ago         │  │ Last: 2d ago         │            │
│  └──────────────────────┘  └──────────────────────┘            │
│                                                                  │
│  ── COST SUMMARY ────────────────────────────────────────────── │
│  Total: $45.80 / $100.00  ████████████░░░░░░  46%              │
│  Top: Research Agent $18.40 · Planning $12.20 · Synthesis $8.00 │
│                                                                  │
│  ── RECENT RUNS ─────────────────────────────────────────────── │
│  ✓ Daily CTI #46   daily-brief   $1.20   3m 12s   6h ago       │
│  ✓ SOC Ops #12     soc-monitor   $0.80   1m 45s   2d ago       │
│  ✗ Daily CTI #45   daily-brief   $0.40   0m 30s   1d ago       │
│                                                                  │
│  ── SYSTEM HEALTH ───────────────────────────────────────────── │
│  ● DB: healthy (2ms) · ● Redis: healthy (1ms) · ● API: ok     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Empty state (no missions):**
```
Welcome to Mission Control
Create your first mission to get started.
Press Ctrl+P to create a mission.
```

**Implementation:**
- `DashboardScreen` extends `Screen`
- Calls `ServiceBridge.list_missions()` for mission cards
- Calls `ServiceBridge.list_executions(limit=10)` for recent runs
- Calls `ServiceBridge.get_health()` for system health (new bridge method)
- Calls `ServiceBridge.get_cost_summary()` for cost data (new bridge method)
- Mission cards are clickable `Static` widgets — click → `MissionSelected` message → enter workspace
- Active runs section updates if execution events arrive via `TuiEventBus`

**ServiceBridge methods needed:**
```python
async def get_health(self) -> dict[str, Any]:
    """Wraps HealthCheckService.check_readiness(). Returns HealthReport
    with overall_status and per-component (DB, Redis) status + latency."""

async def get_cost_summary(self) -> dict[str, Any]:
    """Wraps PlatformMetricsService.get_cost_summary(). Returns all-time
    cost breakdown by agent and by status. Note: no date range parameter
    exists in the backend — the '30-day' label in the dashboard layout
    is aspirational. Display all-time totals until the backend adds
    date-windowed queries."""
```

---

### 5.2  MissionPickerScreen (enhancement of existing)

The existing `MissionPickerScreen` shows a list of missions. Enhance it with:

**Layout:**
```
┌──────────────────────────────────────────────────────────────────┐
│  Select or Create Mission                              [Esc]    │
├──────────────────────────────────────────────────────────────────┤
│  [Existing ▪] [Create New ○]                                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Filter: [________________]                                      │
│                                                                  │
│  > Daily CTI Brief        Active   5 agents   $12.50            │
│    SOC Operations         Active   3 agents   $8.20             │
│    Threat Hunting         Paused   4 agents   $3.10             │
│    ─── Archived ───                                              │
│    Old Project            Archived 2 agents   $1.00             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Create tab fields:**
- Name (Input — slug format)
- Brief (TextArea — multi-line)
- Budget ceiling USD (Input — optional number)
- Repository URL (Input — optional)
- Buttons: `[Cancel]` `[Create & Go →]`

**Behaviour:**
- On create: calls `ServiceBridge.create_mission()` then posts `MissionSelected`
- On select: posts `MissionSelected` → App enters workspace
- Filter input narrows the mission list (case-insensitive substring match on name)
- Archived missions shown below a separator, togglable with `a` key

**ServiceBridge method changes:**
```python
async def create_mission(
    self, *, name: str, description: str,
    budget_ceiling_usd: float | None = None,
    repository_url: str | None = None,
) -> dict[str, str]:
    """Create a mission with optional budget and repo.
    Wraps MissionService.create_mission().
    Bridge resolves owner_id internally to the TUI user (system:cli)."""
```

---

### 5.3  MissionWorkspaceScreen (replaces existing MainScreen)

The core mission workspace with tabbed navigation. Replaces the current `MainScreen`.

**Layout:**
```
┌──────────────────────────────────────────────────────────────────┐
│  MISSION CONTROL   │  Daily CTI Brief [Active ▾]  │  ⚙ 🔔 👤   │
├──────────────────────────────────────────────────────────────────┤
│  [Overview] [Team] [Chat] [Workflows] [Runs] [Workshop] [Ctx]  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│                    (tab-specific content)                         │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  $0.18 │ 4.2k/1.1k │ Layer 2/4 │ ● 1 gate │ connected         │
└──────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- Extends `Screen`, uses Textual's `TabbedContent` for the tab bar
- Each tab's `TabPane` mounts the appropriate tab widget
- The status bar (`CostBar`) and header are outside `TabbedContent` (always visible)
- On tab switch, the right panel content updates (see §3.4)
- `TuiState.active_tab` tracks the current tab name

**Header bar:**
- Mission name from `TuiState.current_mission_name`
- Status dropdown: `Static` that cycles `Active → Paused → Archived` on click (Owner only)
- Settings icon: opens `ProfileScreen`
- Bell icon: shows notification count from `TuiState.notifications`; click opens notification list modal
- Profile icon: opens `ProfileScreen`

**Tab visibility based on role:**
All tabs always visible. Read-only users see data but action buttons are hidden
(same as Plan 29 §8.3 matrix). Role checking uses `TuiState.mission_role`.

---

### 5.4  OverviewTab

The live operational dashboard for the active mission. **This is the existing Plan 23
three-column layout, preserved as-is.**

**Layout:** Exactly the existing `MainScreen` content — left `AgentSidebar`, center
`MissionPanel`/`AgentDetailWidget`, right `EventStreamWidget`.

**What changes:** Nothing. The existing implementation from Plan 23 moves into a `TabPane`
within `MissionWorkspaceScreen`. All existing widgets, event routing, and gate review
continue to work unchanged.

**Additions (minor):**
- **Active run card** above the DAG when a run is in progress (mission name, run number,
  agent count, step progress, cost/budget bar)
- **Idle state** when no active run:
  ```
  No active runs
  Last run: #46 daily-brief · completed 6h ago · $1.20
                                                [▶ Run Now]
  ```
- **Quick stats** below the DAG: agent count, workflow count, total runs, lifetime cost

**ServiceBridge methods needed:**
```python
async def get_mission_stats(self, mission_id: str) -> dict[str, Any]:
    """Wraps MissionService.get_stats(mission_id). Returns dict with
    agent_count, workflow_count, run_count, lifetime_cost_usd.
    **Backend gap (see §15.5):** This backend method does not exist yet.
    Temporary workaround: bridge aggregates from MissionTeamService +
    WorkflowService + ExecutionPersistenceService. This orchestration
    MUST move to a backend service method before shipping."""
```
Note: "Next scheduled run" is not implemented. Omit until a ScheduleService with
`get_next_run()` exists, or parse cron expressions client-side from schedule data.

---

### 5.5  TeamTab

Agent roster management and user prompt editing.

**Layout (two columns):**

```
┌──────────────────────┬───────────────────────────────────────────┐
│  TEAM MEMBERS        │  AGENT DETAIL                             │
│                      │                                           │
│  > Research Agent    │  Research Agent  v2.1  horizontal         │
│    Planning Agent    │  ──────────────────────────────────────── │
│    Synthesis Agent   │                                           │
│    Verification ◇    │  System Prompt  [▸ Expand]                │
│                      │  ──────────────────────────────────────── │
│                      │  User Prompt (v3 · History)               │
│  ─────────────────── │  ┌────────────────────────────────────┐  │
│  [+ Add from Catalog]│  │ Analyze the latest threat intel... │  │
│                      │  │ Focus on ransomware indicators...  │  │
│                      │  └────────────────────────────────────┘  │
│                      │  [Save Prompt]  [Remove Agent]            │
│                      │                                           │
│                      │  Recommendation reason:                   │
│                      │  "Required for threat analysis phase"     │
│                      │                                           │
└──────────────────────┴───────────────────────────────────────────┘
```

**Left panel — Team member list:**
- Each entry: agent name, type badge (horizontal/vertical/system), `◇` for auto-included
- Click to select → detail loads in right panel
- `d` key to remove selected agent (with confirmation, hidden for auto-included)

**Right panel — Agent detail:**
- Agent name, version, type
- System prompt: collapsed by default, expand with `Enter` or click. Read-only `TextArea`.
- User prompt: editable `TextArea` with version indicator
  - `[Save Prompt]` button saves via `ServiceBridge.update_team_member_prompt()`
  - `[History]` opens a modal with version list. Each version shows timestamp and diff.
    `[Restore]` button on each version.
- `[Remove Agent]` button (hidden for auto-included agents like Planning, Verification)
- Recommendation reason text (if agent was AI-recommended)

**AI recommendation banner** (for new missions with no team):
```
Based on your brief, the Workflow Architect recommends these agents.
[Get AI Recommendation]  or  [Browse Catalog]
```
- "Get AI Recommendation" calls `ServiceBridge.architect_recommend()` with loading spinner
- Populates team list with recommended agents

**`[+ Add from Catalog]` action:**
- Opens `CatalogBrowseModal` (full-screen modal)
- Shows searchable/filterable agent list
- Each agent has `[+ Add]` button
- Adding calls `ServiceBridge.add_team_member()` and returns to TeamTab

**ServiceBridge methods needed:**
```python
async def get_team(self, mission_id: str) -> list[dict[str, Any]]:
    """Wraps MissionTeamService.list_team(mission_id)."""

async def add_team_member(
    self, mission_id: str, *, agent_name: str,
) -> dict[str, Any]:
    """Wraps MissionTeamService.add_agent_by_name(mission_id, agent_name).
    **Backend gap (see §15.5):** This backend method does not exist yet.
    Temporary workaround: bridge resolves agent_name → agent_catalog_id
    via AgentCatalogService.get_by_name(), then calls
    MissionTeamService.add_agent(mission_id, agent_catalog_id).
    This name-to-ID resolution MUST move to the backend service."""

async def remove_team_member(
    self, mission_id: str, *, member_id: str,
) -> None:
    """Wraps MissionTeamService.remove_agent(member_id)."""

async def update_team_member_prompt(
    self, mission_id: str, *, member_id: str, user_prompt: str,
) -> dict[str, Any]:
    """Wraps MissionTeamService.update_user_prompt(member_id, content,
    changed_by='system:cli')."""

async def architect_recommend(
    self, mission_id: str,
) -> list[dict[str, Any]]:
    """Wraps WorkflowArchitectService.recommend_team(mission_id).
    **Backend gap (see §15.5):** This backend method does not exist yet.
    Temporary workaround: bridge calls WorkflowArchitectService.chat()
    with a team-recommendation prompt and parses the response. Prompt
    construction and response parsing are business logic and MUST move
    to a dedicated backend method."""
```

**Backend gap — user prompt version history:**
`MissionTeamService` does not currently track prompt versions. Only
`AgentCatalogService.get_prompt_history()` exists (for system prompts).
User prompt versioning requires a backend migration to add a
`team_member_prompt_versions` table. Until then, the "History" button
on user prompts is disabled with a "Coming soon" tooltip. Mark as
**Needs backend endpoint**.

---

### 5.6  ChatTab

Threaded conversations with any agent on the mission team.

**Layout (two columns):**

```
┌────────────────────┬─────────────────────────────────────────────┐
│  THREADS           │  Research Agent                              │
│                    │  ─────────────────────────────────────────── │
│  + New Chat ▾      │                                              │
│                    │  You: What ransomware IOCs appeared today?   │
│  > Research Agent  │                                              │
│    "What ransom.." │  Agent: I'll search for recent indicators.  │
│    3m ago          │  ▸ Tool: web_search                          │
│                    │    query: "ransomware IOCs 2026-03-25"       │
│    Planning Agent  │    ✓ 12 results (340ms)                      │
│    "Analyze the.." │    ▾ [Show results]                          │
│    1h ago          │                                              │
│                    │  Based on my search, here are the key...     │
│                    │  • LockBit variant targeting healthcare      │
│                    │  • Lazarus group phishing campaign           │
│                    │                              $0.08 · 12s     │
│                    │                                              │
│                    ├─────────────────────────────────────────────│
│                    │  [> Type message...              ] [Send]    │
└────────────────────┴─────────────────────────────────────────────┘
```

**Left panel — Thread list:**
- `[+ New Chat]` button → opens dropdown (Textual `OptionList`) of team agents
- Thread items: agent name, first message truncated, timestamp
- Sorted by last activity (most recent first)
- Click to select thread → conversation loads in right panel

**Right panel — Conversation:**
- Agent name at top
- Message display in a `RichLog`:
  - User messages: prefixed with `You:` (no special alignment in terminal)
  - Agent messages: prefixed with agent name, rendered as markdown via `MarkdownViewer`
  - Thinking traces: dim/italic, collapsible (`▸ Thinking: "I need to..."`)
  - Tool calls: card format using `ToolCallCard` pattern from existing `AgentDetailWidget`
  - Cost per message: dim text below agent response
- Input bar at bottom: `Input` widget + `[Send]` button
- `Ctrl+Enter` to send (same as Plan 29)
- Streaming: agent responses append to `RichLog` via SSE events from `TuiEventBus`

**Empty state:**
```
Start a conversation with any agent on your team.
Press Enter on [+ New Chat] to begin.
```

**ServiceBridge methods needed:**
```python
async def create_session(
    self, *, mission_id: str, agent_name: str,
) -> dict[str, Any]:
    """Create a new chat session and return session_id."""

async def send_message(
    self, *, session_id: str, content: str,
) -> None:
    """Wraps SessionService.send_message(session_id, content).
    The backend handles both persistence and agent dispatch internally.
    Response streams back via TuiEventBus."""

async def list_sessions(
    self, *, mission_id: str,
) -> list[dict[str, Any]]:
    """List chat sessions for a mission."""

async def get_session_messages(
    self, *, session_id: str,
) -> list[dict[str, Any]]:
    """Get message history for a session."""
```

---

### 5.7  WorkflowsTab

Workflow design, visualization, and schedule management.

**Layout (two columns):**

```
┌────────────────────┬─────────────────────────────────────────────┐
│  WORKFLOWS         │  daily-brief                                 │
│                    │  ─────────────────────────────────────────── │
│  > daily-brief 🕐  │                                              │
│    soc-monitor ⚡   │  DAG:                                       │
│    threat-hunt ✋   │  [intel-gather ✓] ──→ [research ●]          │
│                    │                         ├──→ [verify ◌]     │
│  [+ New Workflow]  │                         └──→ [report ◌]     │
│                    │                                              │
│                    │  Schedule: 0 5 * * * (daily at 05:00 UTC)   │
│                    │  Budget: $5.00/run │ Status: Armed           │
│                    │  Last run: #46 · 6h ago                      │
│                    │                                              │
│                    │  [Edit] [Schedule] [▶ Run Now] [Disable]     │
│                    │                                              │
│                    │  ── STEPS ──────────────────────────────     │
│                    │  1. intel-gather  → Research Agent           │
│                    │     Gate: post_task │ Max rounds: 3          │
│                    │  2. research      → Analysis Agent           │
│                    │     Input: intel-gather.output               │
│                    │  3. verify        → Verification Agent       │
│                    │  4. report        → Synthesis Agent           │
│                    │     Input: research.output                   │
│                    │                                              │
└────────────────────┴─────────────────────────────────────────────┘
```

**Left panel — Workflow list:**
- Each entry: workflow name, trigger type icon (`🕐` cron, `⚡` event, `✋` manual),
  enabled/disabled badge
- Click to select → detail loads in right panel
- `[+ New Workflow]` button → Architect chat flow (see below)

**Right panel — Workflow detail:**

**A) ASCII DAG visualization:**
- Render using the existing `topological_sort()` output
- Each node: `[step-name status-icon]` with `──→` edges
- Status icons from `gate_helpers.status_icon()`: `✓` done, `●` running, `◌` pending, `✗` failed
- This is view-only (no interactive click on nodes — details shown in step list below)

**B) Metadata bar:**
- Schedule: cron expression + human-readable description
- Budget per run, status (Armed/Disabled/Manual only), last run reference

**C) Step list (DataTable or vertical list below DAG):**
- Each step: step name, assigned agent, gate config, max refinement rounds
- Input wiring (which upstream step), output fields
- Select a step to see full detail in the right panel (replaces Plan 29's node popover)

**D) Action buttons:**
- `[Edit]` → opens step editor modal (Owner only)
- `[Schedule]` → opens schedule configuration modal (Owner only)
- `[▶ Run Now]` → triggers workflow execution via `ServiceBridge.run_workflow()` (Owner/Maintainer)
- `[Enable/Disable]` → toggles workflow armed state (Owner only)

**E) Schedule configuration modal:**
- Trigger type: radio buttons (Cron / Event / Manual)
- Cron expression: `Input` with human-readable preview text below
- Budget per run (USD): `Input`
- Max iterations: `Input`
- Cooldown (seconds): `Input`
- Timezone: `Input` with common timezone suggestions
- Event trigger fields (event type, match patterns) — enabled only for event trigger

**F) New workflow flow:**
- `[+ New Workflow]` → opens a chat-like interface in the center panel
- User describes desired workflow to the Architect agent
- As the Architect proposes steps, they appear as a DAG above the chat
- `[Lock In Workflow]` button saves to database
- This reuses the `ServiceBridge.architect_chat()` method

**Empty state:**
```
No workflows yet.
Design one with the Architect or import a template.
[Design with Architect]  [Import Template]
```

**ServiceBridge methods needed:**
```python
async def list_workflows(
    self, mission_id: str,
) -> list[dict[str, Any]]:
    """Wraps WorkflowService.list_workflows(). Internally synchronous
    (WorkflowService loads from YAML, not DB) but exposed as async for
    uniform bridge interface. Use WorkflowService.to_list_item() for
    dict conversion."""

async def get_workflow_detail(
    self, workflow_name: str,
) -> dict[str, Any]:
    """Wraps WorkflowService.get_workflow() + to_detail(). Internally
    synchronous but exposed as async for uniform bridge interface."""

async def run_workflow(
    self, mission_id: str, *, workflow_name: str,
    gate: GateReviewer | None = None,
) -> dict[str, Any]:
    """Wraps WorkflowRunService.run_workflow(workflow_name,
    triggered_by='tui', gate=gate). Must pass TuiGateReviewer
    for human-in-the-loop gates during workflow execution."""

async def list_schedules(
    self, mission_id: str,
) -> list[dict[str, Any]]:
    """Wraps schedule listing endpoint. Check if ScheduleService exists
    or if this is handled via MissionService/REST layer."""

async def create_schedule(
    self, mission_id: str, *, schedule_data: dict,
) -> dict[str, Any]:
    """Create a workflow schedule."""

async def update_schedule(
    self, mission_id: str, *, schedule_id: str, schedule_data: dict,
) -> dict[str, Any]:
    """Update a workflow schedule."""

async def delete_schedule(
    self, mission_id: str, *, schedule_id: str,
) -> None:
    """Delete a workflow schedule."""

async def import_workflow_template(
    self, mission_id: str, *, template_data: dict,
) -> dict[str, Any]:
    """Import a workflow from a template."""

async def architect_chat(
    self, mission_id: str, *, message: str,
    session_id: str | None = None,
    message_history: list | None = None,
) -> dict[str, Any]:
    """Wraps WorkflowArchitectService.chat(mission_id, message,
    session_id=..., message_history=...). Returns dict with
    response, usage, all_messages."""
```

---

### 5.8  RunsTab

Completed run history, audit trail, and output viewing.

**Layout (single scrollable panel with expandable rows):**

```
┌──────────────────────────────────────────────────────────────────┐
│  RUN HISTORY                                                     │
│  ────────────────────────────────────────────────────────────── │
│  Filter: [All ▾]  Status: [All ▾]  Sort: [Newest ▾]            │
│                                                                  │
│  Run#  Workflow      Status  Cost    Duration  Trigger   Time   │
│  ═══════════════════════════════════════════════════════════════ │
│  #47   daily-brief   ●      $1.20   3m 12s    cron      6h ago │
│  ▸ #46  daily-brief   ✓      $1.18   3m 05s    cron      1d ago │
│  │  DAG: [intel ✓] → [research ✓] → [verify ✓] → [report ✓]  │
│  │  Cost: intel $0.30 · research $0.45 · verify $0.18 · report $0.25 │
│  │  Decisions: 4 gates approved (auto)                          │
│  │  [View Events]  [View Output]  [Cost Detail]                 │
│  #45   daily-brief   ✗      $0.40   0m 30s    manual    1d ago │
│  #44   soc-monitor   ✓      $0.80   1m 45s    cron      2d ago │
│                                                                  │
│  ◄ 1 2 3 ►                                                      │
└──────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- `DataTable` with sortable columns: Run #, Workflow, Status, Cost, Duration, Trigger, Time
- Click/Enter on a row → expands inline with run detail (does not navigate away)
- Pressing Escape on expanded row → collapses it

**Expanded row content:**
- **ASCII DAG** with per-step status coloring (green ✓, red ✗, grey ◌) and cost labels
- **Run summary:** total cost, duration, token counts, trigger type, triggered_by
- **Decision audit trail:** list of gate decisions with action taken
- **Action buttons:**
  - `[View Events]` → replaces right panel with historical event stream (scrollable `RichLog`)
  - `[View Output]` → replaces right panel with final step's output rendered as markdown
  - `[Cost Detail]` → replaces right panel with token-level breakdown per agent/step

**Filters:**
- Workflow name dropdown
- Status filter (All / Completed / Failed)
- Sort: Newest first / Oldest first / Most expensive

**Pagination:** cursor-based, 20 per page. `◄` `►` keys or `n`/`p` to navigate.

**Empty state:**
```
No runs yet.
Go to Workflows (Alt+4) to trigger your first run.
```

**ServiceBridge methods (already partially exist):**
```python
# Existing: get_execution_detail(), get_execution_cost_breakdown()

async def list_executions(
    self, *, status: str | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Wraps ExecutionPersistenceService.list_executions().
    NOTE: Backend returns tuple[list, total_count] for pagination.
    The existing bridge method drops total_count — must be fixed to
    return the tuple so RunsTab can render pagination controls."""

async def get_execution_decisions(
    self, execution_id: str,
) -> list[dict[str, Any]]:
    """Wraps ExecutionPersistenceService.get_decisions(execution_id).
    Returns list of ExecutionDecision records."""
```

---

### 5.9  WorkshopTab

Single-agent prompt iteration and testing.

**Layout (vertical stack):**

```
┌──────────────────────────────────────────────────────────────────┐
│  WORKSHOP                                                        │
│  ────────────────────────────────────────────────────────────── │
│  Agent: [Research Agent ▾]   Source run: [#46 daily-brief ▾]    │
│                                                                  │
│  ── SYSTEM PROMPT [▸ Expand] ─────────────────────────────────  │
│                                                                  │
│  ── USER PROMPT (v3 draft) ───────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Analyze the latest threat intelligence feeds...            │ │
│  │ Focus on ransomware indicators and APT activity...         │ │
│  └────────────────────────────────────────────────────────────┘ │
│  [Save]  [▶ Test]                                                │
│                                                                  │
│  ── CACHED INPUTS [▸ Expand] ─────────────────────────────────  │
│  Source: #46 intel-gather step output (2.1KB)                   │
│                                                                  │
│  ── TEST OUTPUT ──────────────────────────────────────────────  │
│  Run #3 · $0.08 · 12s · 1.4k tokens                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ## Threat Intelligence Summary                             │ │
│  │ Based on analysis of 12 sources...                         │ │
│  │ ### Key Findings                                           │ │
│  │ 1. LockBit variant targeting healthcare...                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│  [Full Preview]  Previous: [Run #2 · $0.09]  [Run #1 · $0.12]  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Components:**
- **Agent selector:** `Select` widget listing team members
- **Source run selector:** `Select` widget listing completed runs for the selected agent's workflow
- **System prompt:** collapsible read-only `TextArea` (collapsed by default)
- **User prompt editor:** editable `TextArea` with version indicator
  - `[Save]` persists to team member (same as TeamTab)
  - `[▶ Test]` runs the agent with current prompt text + cached inputs
- **Cached inputs:** collapsible section showing upstream data from selected source run
- **Test output:** rendered markdown of latest test result
  - Header: `Run #N · $cost · duration · tokens`
  - `[Full Preview]` → opens output in right panel as full `MarkdownViewer`
  - Previous run links: clickable to load and compare

**Empty state (no completed runs):**
```
Workshop needs a completed workflow run to provide cached inputs.
Run your workflow at least once first.
Press Alt+4 to go to Workflows.
```

**ServiceBridge methods needed:**
```python
async def get_cached_inputs(
    self, *, agent_name: str, mission_id: str,
) -> list[dict[str, Any]]:
    """Wraps WorkshopService.get_cached_inputs(agent_name,
    mission_id=mission_id). Returns list of cached input sets
    from previous successful runs."""

async def run_workshop_test(
    self, *, agent_name: str,
    prompt_override: str | None = None,
    inputs: dict[str, Any] | None = None,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    """Wraps WorkshopService.run_agent(agent_name,
    prompt_override=..., inputs=..., budget_usd=...).
    Returns dict with output, cost, tokens, execution_record_id."""

async def list_workshop_runs(
    self, *, agent_name: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Wraps WorkshopService.list_runs_as_dicts(agent_name, limit).
    Returns formatted dicts for display."""
```

---

### 5.10  ContextTab

Mission Context Document — accumulated knowledge from all runs.

**Layout (two columns):**

```
┌────────────────────────────────────────┬─────────────────────────┐
│  MISSION CONTEXT                       │  CHANGE HISTORY         │
│  ────────────────────────────────────  │                         │
│  ## Domain Knowledge                   │  #47 · 6h ago           │
│  The threat landscape as of 2026-03... │  Added: 3 IOC entries   │
│                                        │  Modified: threat model │
│  ## Established Facts                  │                         │
│  - LockBit variants active since...   │  #46 · 1d ago           │
│  - APT29 targeting energy sector...   │  Added: initial context  │
│                                        │                         │
│  ## Active Decisions                   │                         │
│  - Monitor LockBit IOCs daily         │                         │
│  - Escalate APT29 findings to SOC     │                         │
│                                        │                         │
│  ## Current State                      │                         │
│  Last updated: 6h ago by #47          │                         │
│                                        │                         │
└────────────────────────────────────────┴─────────────────────────┘
```

**Left panel — Context document:**
- Rendered using Textual's `MarkdownViewer` widget (read-only)
- Scrollable
- Contains: domain knowledge, established facts, active decisions, current state

**Right panel — Change history:**
- Chronological list of context changes (from `MissionContextManager.get_history()`)
- Each entry: execution reference, timestamp, change summary
- Click entry → shows full diff in a modal (before/after with highlighting)

**Empty state:**
```
No context accumulated yet.
Context builds automatically as your workflows run.
The mission brief serves as initial context for your agents.
```

**ServiceBridge methods needed:**
```python
async def get_mission_context(
    self, mission_id: str,
) -> dict[str, Any]:
    """Wraps MissionContextManager.get_context(mission_id).
    Returns the mission context document as a dict."""

async def get_context_history(
    self, mission_id: str, *, limit: int = 50,
) -> list[dict[str, Any]]:
    """Wraps MissionContextManager.get_history(mission_id, limit).
    Note: backend method is named get_history(), not get_context_history().
    Returns list of ContextChange records."""
```

**Note:** No milestone concept exists in the backend (`MissionContextManager` has
no milestone methods). Milestones are omitted from the layout and implementation.
If needed later, a backend migration would add a `context_milestones` table.

---

### 5.11  CatalogScreen

Global agent catalog. Read-only for regular users. Accessible via Ctrl+G.

**Layout (two columns):**

```
┌────────────────────────────────────────┬─────────────────────────┐
│  AGENT CATALOG                  [Esc]  │  AGENT DETAIL           │
│  ──────────────────────────────────── │                         │
│  Search: [________________]            │  Research Agent         │
│  Type: [All ▾]                         │  Type: horizontal      │
│                                        │  Version: 2.1          │
│  > Research Agent   horizontal  v2.1  │                         │
│    Planning Agent   system      v1.0  │  Description:           │
│    Synthesis Agent  horizontal  v2.0  │  Analyzes threat intel  │
│    Verification     system      v1.0  │  feeds and produces...  │
│    Code QA          vertical    v1.5  │                         │
│    Code Architect   vertical    v1.3  │  Keywords: threat,      │
│    System Health    vertical    v1.0  │  intelligence, analysis │
│                                        │                         │
│                                        │  Tools:                 │
│                                        │  • web_search           │
│                                        │  • file_read            │
│                                        │                         │
│                                        │  Constraints:           │
│                                        │  Timeout: 300s          │
│                                        │  Cost ceiling: $2.00    │
│                                        │                         │
└────────────────────────────────────────┴─────────────────────────┘
```

**Left panel:**
- Search `Input` for filtering by name/description/keywords
- Type filter: `Select` widget (All / Horizontal / Vertical / System)
- Agent list as `OptionList` or `DataTable`
- Click to select → detail loads in right panel

**Right panel — Agent detail:**
- Name, type, version
- Full description
- Keywords as comma-separated tags
- Tools list
- Constraints (timeout, cost ceiling, retry budget)
- System prompt: **not shown** (sysadmin only — visible in AdminScreen)

**ServiceBridge method:**
```python
async def list_catalog_agents(
    self, *, enabled_only: bool = True,
    visibility: str | None = None,
    agent_type: str | None = None,
) -> list[dict[str, Any]]:
    """Wraps AgentCatalogService.list_catalog(enabled_only, visibility,
    agent_type). Supports the filter dropdowns in the catalog UI.
    Note: load_roster() loads from YAML config; this loads from the
    database catalog — different data sources for different purposes."""
```

---

### 5.12  AdminScreen

Admin section. Only accessible when user is a sysadmin. Ctrl+A.

**Layout:** Uses `TabbedContent` with sub-tabs: Catalog | Metrics | Config | Health | Users

#### 5.12.1  AdminCatalogTab

CRUD table for agent management.

```
┌──────────────────────────────────────────────────────────────────┐
│  ADMIN CATALOG                                                   │
│  ────────────────────────────────────────────────────────────── │
│  [+ Create Agent]                                                │
│                                                                  │
│  Name              Type        Version  Enabled  Visibility     │
│  ═══════════════════════════════════════════════════════════════ │
│  research-agent    horizontal  2.1      ✓        public         │
│  planning-agent    system      1.0      ✓        internal       │
│  synthesis-agent   horizontal  2.0      ✓        public         │
│                                                                  │
│  [Enter] to edit · [d] to delete · [p] to edit system prompt    │
└──────────────────────────────────────────────────────────────────┘
```

- `DataTable` with sortable/filterable columns
- `Enter` on a row → opens edit form modal (all agent fields)
- `d` → delete with confirmation
- `p` → opens system prompt editor modal (full-height `TextArea` with version history)
- `[+ Create Agent]` → opens create form modal

**ServiceBridge methods needed:**
```python
async def admin_list_agents(
    self, *, enabled_only: bool = False,
) -> list[dict[str, Any]]:
    """Wraps AgentCatalogService.list_catalog(enabled_only=False).
    Admin view shows all agents including disabled."""

async def admin_create_agent(self, *, data: dict) -> dict[str, Any]:
    """Wraps AgentCatalogService.create_entry(**data)."""

async def admin_update_agent(
    self, agent_name: str, *, data: dict,
) -> dict[str, Any]:
    """Wraps AgentCatalogService.update_entry(agent_name, **data)."""

async def admin_delete_agent(self, agent_name: str) -> None:
    """Wraps AgentCatalogService.delete_entry(agent_name)."""

async def admin_update_system_prompt(
    self, agent_name: str, *, prompt: str,
    change_reason: str | None = None,
) -> dict[str, Any]:
    """Wraps AgentCatalogService.update_system_prompt(agent_name,
    content=prompt, changed_by='system:cli', change_reason=...)."""

async def admin_get_prompt_history(
    self, agent_name: str, *, limit: int = 50,
) -> list[dict[str, Any]]:
    """Wraps AgentCatalogService.get_prompt_history(agent_name, limit)."""
```

#### 5.12.2  AdminMetricsTab

Platform-wide dashboards.

```
┌──────────────────────────────────────────────────────────────────┐
│  PLATFORM METRICS                                                │
│  ────────────────────────────────────────────────────────────── │
│  Missions: 12 │ Sessions: 340 │ Executions: 189 │ Cost: $245   │
│                                                                  │
│  ── COST BY AGENT ───────────────────────────────────────────── │
│  Research Agent  ████████████████████  $98.40  (40%)            │
│  Planning Agent  ████████████         $62.00  (25%)            │
│  Synthesis Agent ████████             $45.00  (18%)            │
│  Others          ████                 $39.60  (16%)            │
│                                                                  │
│  ── RECENT ACTIVITY ─────────────────────────────────────────── │
│  #189  Daily CTI    ✓  $1.20   3m   6h ago                     │
│  #188  SOC Ops      ✓  $0.80   2m   1d ago                     │
│  #187  Daily CTI    ✗  $0.40   1m   1d ago                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

- Overview cards: total missions, sessions, executions, cost (use `Static` widgets)
- Cost breakdown: horizontal bar chart using `━` characters with percentages
- Agent utilization table: `DataTable` with agent name, total runs, total cost, avg duration
- Recent activity: last 10 executions

**ServiceBridge methods needed:**
```python
async def admin_get_metrics_overview(self) -> dict[str, Any]:
    """Wraps PlatformMetricsService.get_overview(). Returns dict with
    mission/session/execution/agent counts + total_cost_usd."""

async def admin_get_cost_breakdown(self) -> dict[str, Any]:
    """Wraps PlatformMetricsService.get_cost_summary(). Returns dict
    with cost breakdown by agent and by status. Note: no date range
    parameter — returns all-time aggregates."""

async def admin_get_agent_utilisation(self) -> list[dict[str, Any]]:
    """Wraps PlatformMetricsService.get_agent_utilisation(). Returns
    per-agent stats: total runs, total cost, avg duration."""

async def admin_get_activity(self, *, limit: int = 10) -> list[dict[str, Any]]:
    """Wraps PlatformMetricsService.get_recent_activity(limit).
    Returns recent executions and workflow runs."""
```

#### 5.12.3  AdminConfigTab

Read-only platform configuration display.

```
┌──────────────────────────────────────────────────────────────────┐
│  PLATFORM CONFIGURATION (read-only)                              │
│  ────────────────────────────────────────────────────────────── │
│  application:                                                    │
│    name: mission-control                                         │
│    version: 1.0.0                                                │
│    debug: false                                                  │
│  workflows:                                                      │
│    max_concurrent: 5                                             │
│    default_budget_usd: 10.00                                     │
│  sessions:                                                       │
│    max_active: 100                                               │
│    timeout_seconds: 3600                                         │
└──────────────────────────────────────────────────────────────────┘
```

- Rendered as a `Tree` widget or `RichLog` with YAML-style formatting
- No editing — config changes via CLI/files only

**ServiceBridge method:**
```python
async def admin_get_config(self) -> dict[str, Any]:
    """Return platform configuration."""
```

#### 5.12.4  AdminHealthTab

System health checks.

```
┌──────────────────────────────────────────────────────────────────┐
│  SYSTEM HEALTH                                                   │
│  ────────────────────────────────────────────────────────────── │
│  Overall: ● healthy                                              │
│                                                                  │
│  Database:  ● healthy  latency: 2ms                              │
│  Redis:     ● healthy  latency: 1ms                              │
│  API:       ● healthy                                            │
│                                                                  │
│  [Refresh]                                     Last check: 12s  │
└──────────────────────────────────────────────────────────────────┘
```

- Status indicators using colored `●` via Rich markup
- `[Refresh]` button calls health endpoint
- Auto-refresh every 30 seconds while tab is active

**ServiceBridge method:**
```python
## Reuses get_health() from §5.1 — no separate admin method needed.
```

#### 5.12.5  AdminUsersTab

Full user management.

```
┌──────────────────────────────────────────────────────────────────┐
│  USER MANAGEMENT                               [+ Create User]  │
│  ────────────────────────────────────────────────────────────── │
│  Name             Email               Role    Status  Last Login│
│  ═══════════════════════════════════════════════════════════════ │
│  Admin User       admin@example.com   admin   Active  2h ago    │
│  John Smith       john@example.com    user    Active  1d ago    │
│  Service Bot      bot@system          user    Active  5m ago    │
│                                                                  │
│  [Enter] edit · [d] deactivate · [k] manage API keys · [r] reset│
└──────────────────────────────────────────────────────────────────┘
```

- `DataTable` with sortable columns
- `Enter` → edit modal (display name, system role dropdown)
- `d` → deactivate with confirmation (cannot deactivate self)
- `k` → API key management modal:
  - Table of keys: name, prefix, expires, last used, status
  - `[+ Create Key]` → name input + optional expiry. Shows full key once in copy dialog.
  - `[Revoke]` on each active key with confirmation
- `r` → reset password modal (new password input, min 12 chars)
- `[+ Create User]` → modal: email, display name, password, role selector, service account checkbox

**ServiceBridge methods needed:**

All admin user methods require a `requesting_user: User` parameter in the backend.
The bridge resolves this internally by loading the `system:cli` user (same pattern
as `set_current_mission()`). This is a cross-cutting concern for all admin methods.

```python
async def _get_requesting_user(self) -> User:
    """Internal helper: load the system:cli User object for
    requesting_user parameters. Must be loaded fresh within each
    active DB session context (not cached across sessions — a
    detached SQLAlchemy object will raise)."""

async def admin_list_users(
    self, *, limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    """Wraps UserService.list_users(requesting_user, limit, offset)."""

async def admin_create_user(self, *, data: dict) -> dict[str, Any]:
    """Wraps UserService.create_user(email, display_name, password,
    system_role, is_service_account, requesting_user)."""

async def admin_update_user(
    self, user_id: str, *, data: dict,
) -> dict[str, Any]:
    """Wraps UserService.update_user(user_id, requesting_user, **data)."""

async def admin_deactivate_user(self, user_id: str) -> None:
    """Wraps UserService.deactivate_user(user_id, requesting_user)."""

async def admin_reset_password(
    self, user_id: str, *, new_password: str,
) -> None:
    """Wraps UserService.admin_reset_password(user_id, new_password,
    requesting_user)."""

async def admin_list_user_api_keys(
    self, user_id: str,
) -> list[dict[str, Any]]:
    """Wraps AuthService.list_api_keys(user_id, requesting_user)."""

async def admin_create_user_api_key(
    self, user_id: str, *, name: str, expires_in_days: int | None = None,
) -> dict[str, Any]:
    """Wraps AuthService.create_api_key(user_id, name, expires_in_days,
    requesting_user). Returns tuple (full_key, ApiKey) — the full key
    string is shown to the user once and never stored."""

async def admin_revoke_user_api_key(
    self, user_id: str, *, key_id: str,
) -> None:
    """Wraps AuthService.revoke_api_key(key_id, requesting_user)."""
```

---

### 5.13  ProfileScreen

Current user's own account management. Accessible via Ctrl+U.

**Layout (vertical stack):**

```
┌──────────────────────────────────────────────────────────────────┐
│  PROFILE                                                 [Esc]  │
│  ────────────────────────────────────────────────────────────── │
│  Display Name: [Admin User        ]  [Save]                     │
│  Email:        admin@example.com (read-only)                     │
│  Role:         admin (read-only)                                 │
│  Last Login:   2026-03-25 14:30 UTC                             │
│                                                                  │
│  ── CHANGE PASSWORD ─────────────────────────────────────────── │
│  Current:  [________________]                                    │
│  New:      [________________]  (min 12 characters)               │
│  Confirm:  [________________]                                    │
│  [Change Password]                                               │
│                                                                  │
│  ── API KEYS ────────────────────────────────────────────────── │
│  Name        Prefix      Expires      Last Used  Status         │
│  ═══════════════════════════════════════════════════════════════ │
│  my-key      mc_abc123   2026-06-25   2h ago     Active         │
│  ci-key      mc_def456   never        5m ago     Active         │
│                                                                  │
│  [+ Create Key]  · select row + [r] to revoke                   │
└──────────────────────────────────────────────────────────────────┘
```

**Sections:**
- Profile info: display name (`Input`, editable), email/role/last login (read-only `Label`s)
- Change password: three `Input` widgets (password mode) + `[Change Password]` button
- API keys: `DataTable` + `[+ Create Key]` modal + `[Revoke]` per key

**Note:** The TUI currently uses the `system:cli` service account. If the TUI is launched
with a different authentication method in the future (e.g., API key auth), this screen
will show that user's profile. For now, it shows the CLI service account profile.

**Service account limitation:** The `system:cli` user is a service account with
`is_service_account=True` and no password. The "Change Password" section must be
**hidden** when `is_service_account=True`. Display name editing and API key management
remain functional.

**ServiceBridge methods needed:**
```python
async def get_profile(self) -> dict[str, Any]:
    """Wraps UserService.get_user('system:cli', requesting_user).
    Returns user profile dict."""

async def update_display_name(self, *, display_name: str) -> None:
    """Wraps UserService.update_user('system:cli', requesting_user,
    display_name=display_name)."""

async def change_password(
    self, *, current_password: str, new_password: str,
) -> None:
    """Wraps UserService.change_password('system:cli', old_password,
    new_password, requesting_user). Hidden for service accounts."""

async def list_api_keys(self) -> list[dict[str, Any]]:
    """Wraps AuthService.list_api_keys('system:cli', requesting_user)."""

async def create_api_key(
    self, *, name: str, expires_in_days: int | None = None,
) -> dict[str, Any]:
    """Wraps AuthService.create_api_key('system:cli', name,
    expires_in_days, requesting_user). Returns (full_key, ApiKey)."""

async def revoke_api_key(self, *, key_id: str) -> None:
    """Wraps AuthService.revoke_api_key(key_id, requesting_user)."""
```

---

## 6  Notification System

### 6.1  Notification types

Same as Plan 29 §6.1:

| Type | Trigger | Urgency |
|---|---|---|
| Gate approval | Gate fires during a run | High — flashes status bar |
| Run failed | Execution or workflow run fails | High — flashes status bar |
| Run completed | Workflow run finishes successfully | Normal |
| Budget warning | Cost exceeds 80% of ceiling | Normal |

### 6.2  Notification UI

**Status bar indicator:** The existing `CostBar` gains a notification count: `🔔 3`

**Notification list modal:** Pressing `Ctrl+N` or clicking the bell opens a modal:
```
┌──────────────────────────────────────────────────────────────────┐
│  NOTIFICATIONS                                           [Esc]  │
│  ────────────────────────────────────────────────────────────── │
│  ● Gate pending: Daily CTI #47 · post_task gate        3m ago   │
│  ● Run failed: SOC Ops #13 · timeout                   1h ago   │
│  ○ Run completed: Daily CTI #46 · $1.20                6h ago   │
│  ○ Budget warning: Daily CTI · 80% used                1d ago   │
│                                                                  │
│  [Mark all read]                                                 │
└──────────────────────────────────────────────────────────────────┘
```

- `●` unread, `○` read
- Click/Enter on a notification → navigate to relevant screen/tab
- Notifications arrive via `TuiEventBus` (existing infrastructure)

### 6.3  Terminal bell

For high-urgency notifications (gates, failures), the TUI triggers the terminal bell
character (`\a`) to alert the user if they're in another terminal tab.

---

## 7  Event Stream Rendering

No changes from existing implementation. The `EventStreamWidget` (Plan 23) already
handles all event types. The only addition is that it now appears in the right panel
of the OverviewTab rather than as a permanent right sidebar.

When viewing historical runs (RunsTab → `[View Events]`), a read-only copy of the
event stream is rendered in the right panel using the same widget but fed from
persisted event data rather than live `TuiEventBus`.

---

## 8  Role-Based UI

### 8.1  TUI role model

The TUI currently operates as the `system:cli` service account (in-process). For
role-based UI to work, `TuiState` tracks the effective role:

```python
# Added to TuiState:
system_role: str = "admin"       # viewer / user / admin
mission_role: str = "Owner"      # Owner / Maintainer / Viewer (per mission)
```

### 8.2  Action visibility matrix

Same matrix as Plan 29 §8.3. Implementation: each action widget checks
`self.app.state.mission_role` and `self.app.state.system_role` before rendering.
Hidden actions are not mounted (not merely invisible).

| Element | Owner | Maintainer | Viewer |
|---|---|---|---|
| Mission status change | Visible | Hidden | Hidden |
| Edit Brief | Visible | Hidden | Hidden |
| Manage Team (add/remove) | Visible | Hidden | Hidden |
| Edit User Prompts | Visible | Visible | Hidden |
| + New Workflow | Visible | Hidden | Hidden |
| Edit Schedule | Visible | Hidden | Hidden |
| ▶ Run Now | Visible | Visible | Hidden |
| Approve/Reject Gates | Visible | Visible | Hidden |
| Workshop (test runs) | Visible | Visible | Hidden |
| Chat with agents | Visible | Visible | Visible |
| View all data | Visible | Visible | Visible |
| Admin section (Ctrl+A) | `system_role == "admin"` only |

---

## 9  Empty States

Every tab has a meaningful empty state guiding the user forward. All empty states
use dim text with actionable keyboard shortcut hints:

| Tab/Screen | Empty state message | Hint |
|---|---|---|
| Dashboard (no missions) | "Welcome to Mission Control. Create your first mission." | `Ctrl+P` |
| Team (no agents) | "Your mission has no agents yet." | `[Get AI Recommendation]` or `[Browse Catalog]` |
| Chat (no threads) | "Start a conversation with any agent on your team." | `Enter on [+ New Chat]` |
| Workflows (none) | "No workflows yet. Design one with the Architect." | `[Design with Architect]` |
| Runs (none) | "No runs yet. Go to Workflows to trigger your first run." | `Alt+4` |
| Workshop (no runs) | "Workshop needs a completed run for cached inputs." | `Alt+4` |
| Context (no runs) | "Context builds automatically as workflows run." | — |

---

## 10  State Management

### 10.1  TuiState extensions

The existing `TuiState` dataclass gains new fields grouped into sub-dataclasses
to prevent the top-level class from becoming unwieldy:

```python
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

@dataclass
class TuiState:
    # ... existing fields from Plan 23 (unchanged) ...

    # ── Navigation ────────────────────────────────────────────────
    active_screen: str = "dashboard"   # dashboard|workspace|catalog|admin|profile
    active_tab: str = "overview"       # overview|team|chat|workflows|runs|workshop|context

    # ── Auth/Role ─────────────────────────────────────────────────
    system_role: str = "admin"         # viewer|user|admin
    mission_role: str = "Owner"        # Owner|Maintainer|Viewer

    # ── Tab-specific state (sub-dataclasses) ──────────────────────
    team: TeamState = field(default_factory=TeamState)
    chat: ChatState = field(default_factory=ChatState)
    workflow: WorkflowState = field(default_factory=WorkflowState)
    context: ContextState = field(default_factory=ContextState)
```

Access pattern: `self.app.state.chat.active_session_id`,
`self.app.state.team.members`, etc.

### 10.2  Data loading pattern

Each tab loads its data when activated (lazy loading). The `MissionWorkspaceScreen`
listens for tab switch events and calls the appropriate `ServiceBridge` method:

```python
async def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
    tab_id = event.tab.id
    self.app.state.active_tab = tab_id
    if tab_id == "team":
        await self._load_team()
    elif tab_id == "chat":
        await self._load_sessions()
    elif tab_id == "workflows":
        await self._load_workflows()
    elif tab_id == "runs":
        await self._load_runs()
    # ... etc
```

Data is cached in `TuiState` and only refreshed on explicit user action or
when an event indicates a change.

---

## 11  File Structure

New files are marked with `(new)`. Modified files with `(mod)`.

```
modules/clients/tui/
├── __init__.py
├── app.py                          (mod) — add screen navigation, Ctrl+D/G/A/U/N bindings
├── messages.py                     (mod) — add TabSwitched, WorkflowRunRequested, etc.
├── screens/
│   ├── __init__.py
│   ├── dashboard.py                (new) — DashboardScreen
│   ├── workspace.py                (new) — MissionWorkspaceScreen (replaces main.py)
│   ├── main.py                     (del) — replaced by workspace.py
│   ├── catalog.py                  (new) — CatalogScreen
│   ├── admin.py                    (new) — AdminScreen with sub-tabs
│   ├── profile.py                  (new) — ProfileScreen
│   ├── mission_picker.py           (mod) — add create tab, filters
│   └── mission_history.py          (mod) — minimal changes, mostly absorbed into RunsTab
├── tabs/                           (new directory)
│   ├── __init__.py                 (new)
│   ├── overview.py                 (new) — OverviewTab (wraps existing Plan 23 3-column layout)
│   ├── team.py                     (new) — TeamTab
│   ├── chat.py                     (new) — ChatTab
│   ├── workflows.py                (new) — WorkflowsTab
│   ├── runs.py                     (new) — RunsTab
│   ├── workshop.py                 (new) — WorkshopTab
│   └── context.py                  (new) — ContextTab
├── widgets/
│   ├── __init__.py
│   ├── agent_detail.py             (existing — no changes)
│   ├── agent_sidebar.py            (existing — no changes)
│   ├── chat_input.py               (existing — no changes)
│   ├── context_viewer.py           (mod) — enhance for ContextTab
│   ├── cost_bar.py                 (mod) — add notification count indicator
│   ├── event_stream.py             (existing — no changes)
│   ├── gate_modal.py               (existing — no changes)
│   ├── mission_panel.py            (existing — no changes)
│   ├── notification.py             (mod) — add notification list modal
│   ├── workflow_progress.py        (existing — no changes)
│   ├── dag_renderer.py             (new) — ASCII DAG rendering extracted from mission_panel.py
│   ├── prompt_editor.py            (new) — reusable prompt TextArea with save/version
│   ├── schedule_modal.py           (new) — schedule configuration modal
│   └── catalog_browse_modal.py     (new) — full-screen catalog browse modal
├── services/
│   ├── __init__.py
│   ├── event_listener.py           (existing — no changes)
│   ├── gate_reviewer.py            (existing — no changes)
│   ├── service_bridge.py           (mod) — add all new methods from §5
│   └── state.py                    (mod) — add new fields from §10.1
└── styles/
    └── tui.tcss                    (mod) — add styles for new screens/tabs
```

**~35 files total, ~8,000 lines estimated. All files under 500 lines.**

---

## 12  ServiceBridge Method Summary

All new methods that must be added to `ServiceBridge`. Each wraps a backend service
factory call. The TUI never sees raw SQLAlchemy sessions.

**Cross-cutting concern — `requesting_user`:** Many backend services (UserService,
AuthService) require a `requesting_user: User` parameter for authorization. The bridge
resolves this internally via a cached `_get_requesting_user()` helper that loads the
`system:cli` user once, following the pattern already established in
`service_bridge.py:set_current_mission()`.

### Internal helper
```python
async def _get_requesting_user(self) -> User:
    """Load system:cli User for requesting_user params. Must be loaded
    fresh within each active DB session context (not cached across
    sessions — a detached SQLAlchemy object will raise). Use a simple
    self._cached_user_id check per-session, not a cross-session LRU."""
```

### Dashboard & Health
```python
async def get_health(self) -> dict[str, Any]                          # ← HealthCheckService.check_readiness()
async def get_cost_summary(self) -> dict[str, Any]                    # ← PlatformMetricsService.get_cost_summary() (all-time, no date param)
```

### Mission (extensions to existing)
```python
async def get_mission_stats(self, mission_id: str) -> dict[str, Any]  # ← MissionService.get_stats() — BACKEND GAP: bridge aggregates as workaround
```

### Team
```python
async def get_team(self, mission_id: str) -> list[dict[str, Any]]                                         # ← MissionTeamService.list_team()
async def add_team_member(self, mission_id: str, *, agent_name: str) -> dict[str, Any]                     # ← MissionTeamService.add_agent_by_name() — BACKEND GAP: bridge resolves name→ID as workaround
async def remove_team_member(self, mission_id: str, *, member_id: str) -> None                             # ← MissionTeamService.remove_agent()
async def update_team_member_prompt(self, mission_id: str, *, member_id: str, user_prompt: str) -> dict    # ← MissionTeamService.update_user_prompt(changed_by='system:cli')
async def architect_recommend(self, mission_id: str) -> list[dict[str, Any]]                               # ← WorkflowArchitectService.recommend_team() — BACKEND GAP: bridge constructs prompt as workaround
```
**Backend gap:** User prompt version history (`get_prompt_history` for team members)
does not exist. `AgentCatalogService.get_prompt_history()` covers system prompts only.
Needs backend migration before TeamTab can show prompt history.

### Chat
```python
async def create_session(self, *, mission_id: str, agent_name: str) -> dict[str, Any]   # ← SessionService.create_session()
async def send_message(self, *, session_id: str, content: str) -> None                   # ← SessionService.send_message() (handles persistence + agent dispatch internally)
async def list_sessions(self, *, mission_id: str) -> list[dict[str, Any]]                # ← SessionService.list_sessions()
async def get_session_messages(self, *, session_id: str) -> list[dict[str, Any]]         # ← SessionService.get_messages()
```

### Workflows
```python
async def list_workflows(self, mission_id: str) -> list[dict[str, Any]]                                    # ← WorkflowService.list_workflows() — internally sync (YAML), async wrapper
async def get_workflow_detail(self, workflow_name: str) -> dict[str, Any]                                   # ← WorkflowService.get_workflow() + to_detail() — internally sync, async wrapper
async def run_workflow(self, mission_id: str, *, workflow_name: str, gate: GateReviewer | None) -> dict     # ← WorkflowRunService.run_workflow(triggered_by='tui', gate=gate)
async def list_schedules(self, mission_id: str) -> list[dict[str, Any]]                                    # ← Schedule endpoints (check ScheduleService existence)
async def create_schedule(self, mission_id: str, *, schedule_data: dict) -> dict[str, Any]
async def update_schedule(self, mission_id: str, *, schedule_id: str, schedule_data: dict) -> dict[str, Any]
async def delete_schedule(self, mission_id: str, *, schedule_id: str) -> None
async def import_workflow_template(self, mission_id: str, *, template_data: dict) -> dict[str, Any]
async def architect_chat(self, mission_id: str, *, message: str, session_id: str | None, message_history: list | None) -> dict  # ← WorkflowArchitectService.chat()
```

### Workshop
```python
async def get_cached_inputs(self, *, agent_name: str, mission_id: str) -> list[dict]     # ← WorkshopService.get_cached_inputs()
async def run_workshop_test(self, *, agent_name: str, prompt_override: str | None, inputs: dict | None, budget_usd: float | None) -> dict  # ← WorkshopService.run_agent()
async def list_workshop_runs(self, *, agent_name: str | None, limit: int = 20) -> list[dict]  # ← WorkshopService.list_runs_as_dicts()
```

### Context
```python
async def get_mission_context(self, mission_id: str) -> dict[str, Any]                   # ← MissionContextManager.get_context()
async def get_context_history(self, mission_id: str, *, limit: int = 50) -> list[dict]   # ← MissionContextManager.get_history() (note: method is named get_history, not get_context_history)
```

### Catalog
```python
async def list_catalog_agents(self, *, enabled_only: bool = True, visibility: str | None = None, agent_type: str | None = None) -> list[dict]  # ← AgentCatalogService.list_catalog()
```

### Admin — Catalog
```python
async def admin_list_agents(self, *, enabled_only: bool = False) -> list[dict]              # ← AgentCatalogService.list_catalog(enabled_only=False)
async def admin_create_agent(self, *, data: dict) -> dict[str, Any]                         # ← AgentCatalogService.create_entry(**data)
async def admin_update_agent(self, agent_name: str, *, data: dict) -> dict[str, Any]        # ← AgentCatalogService.update_entry()
async def admin_delete_agent(self, agent_name: str) -> None                                 # ← AgentCatalogService.delete_entry()
async def admin_update_system_prompt(self, agent_name: str, *, prompt: str, change_reason: str | None) -> dict  # ← AgentCatalogService.update_system_prompt(changed_by='system:cli')
async def admin_get_prompt_history(self, agent_name: str, *, limit: int = 50) -> list[dict] # ← AgentCatalogService.get_prompt_history()
```

### Admin — Metrics
```python
async def admin_get_metrics_overview(self) -> dict[str, Any]            # ← PlatformMetricsService.get_overview()
async def admin_get_cost_breakdown(self) -> dict[str, Any]              # ← PlatformMetricsService.get_cost_summary() (all-time)
async def admin_get_agent_utilisation(self) -> list[dict[str, Any]]     # ← PlatformMetricsService.get_agent_utilisation()
async def admin_get_activity(self, *, limit: int = 10) -> list[dict]    # ← PlatformMetricsService.get_recent_activity()
```

### Admin — Config & Health
```python
async def admin_get_config(self) -> dict[str, Any]                      # ← Config loading (same as GET /admin/config endpoint)
## admin_get_health() removed — reuse get_health() from Dashboard & Health section
```

### Admin — Users (all require requesting_user via _get_requesting_user())
```python
async def admin_list_users(self, *, limit: int = 50, offset: int = 0) -> list[dict]        # ← UserService.list_users()
async def admin_create_user(self, *, data: dict) -> dict[str, Any]                          # ← UserService.create_user()
async def admin_update_user(self, user_id: str, *, data: dict) -> dict[str, Any]            # ← UserService.update_user()
async def admin_deactivate_user(self, user_id: str) -> None                                 # ← UserService.deactivate_user()
async def admin_reset_password(self, user_id: str, *, new_password: str) -> None            # ← UserService.admin_reset_password()
async def admin_list_user_api_keys(self, user_id: str) -> list[dict]                        # ← AuthService.list_api_keys()
async def admin_create_user_api_key(self, user_id: str, *, name: str, expires_in_days: int | None) -> dict  # ← AuthService.create_api_key() returns (full_key, ApiKey)
async def admin_revoke_user_api_key(self, user_id: str, *, key_id: str) -> None             # ← AuthService.revoke_api_key()
```

### Profile (all use 'system:cli' user internally)
```python
async def get_profile(self) -> dict[str, Any]                                               # ← UserService.get_user('system:cli')
async def update_display_name(self, *, display_name: str) -> None                           # ← UserService.update_user()
async def change_password(self, *, current_password: str, new_password: str) -> None        # ← UserService.change_password() — hidden for service accounts
async def list_api_keys(self) -> list[dict]                                                 # ← AuthService.list_api_keys('system:cli')
async def create_api_key(self, *, name: str, expires_in_days: int | None) -> dict           # ← AuthService.create_api_key() returns (full_key, ApiKey)
async def revoke_api_key(self, *, key_id: str) -> None                                     # ← AuthService.revoke_api_key()
```

### Execution (extension to existing)
```python
async def list_executions(self, *, status: str | None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]  # ← FIX: return tuple (records, total_count) for pagination
async def get_execution_decisions(self, execution_id: str) -> list[dict]                    # ← ExecutionPersistenceService.get_decisions()
```

---

## 13  Keyboard Shortcuts — Complete Reference

### Global (available on all screens)

| Key | Action |
|-----|--------|
| `Ctrl+D` | Go to Dashboard |
| `Ctrl+P` | Mission picker (modal) |
| `Ctrl+G` | Go to Catalog |
| `Ctrl+A` | Go to Admin (admin only) |
| `Ctrl+U` | Go to Profile |
| `Ctrl+N` | Notification list (modal) |
| `Ctrl+M` | New execution (focus input on Overview) |
| `Ctrl+K` | Cancel active execution |
| `Ctrl+/` | Focus chat/command input |
| `Ctrl+Q` | Quit |
| `Esc` | Back / close modal / collapse |
| `?` | Help overlay |

### Mission workspace tabs

| Key | Action |
|-----|--------|
| `Alt+1` | Overview tab |
| `Alt+2` | Team tab |
| `Alt+3` | Chat tab |
| `Alt+4` | Workflows tab |
| `Alt+5` | Runs tab |
| `Alt+6` | Workshop tab |
| `Alt+7` | Context tab |

### Within lists/tables

| Key | Action |
|-----|--------|
| `j`/`↓` | Next item |
| `k`/`↑` | Previous item |
| `Enter` | Select / expand |
| `Esc` | Deselect / collapse |
| `/` | Search/filter |
| `n`/`p` | Next/previous page |

### Gate modal (unchanged from Plan 23)

| Key | Action |
|-----|--------|
| `c` | Continue |
| `s` | Skip |
| `r` | Retry |
| `m` | Modify (verification_failed only) |
| `a` | Abort |
| `o` | Inspect output |
| `v` | Inspect verification |
| `i` | Inspect inputs |

---

## 14  Build Phases

### Phase T1 — Screen Shell + Navigation (~6 files, ~1500 lines)

Establish the screen hierarchy, navigation, and tab framework.

**Create:**
- `screens/dashboard.py` — DashboardScreen (basic layout, mission cards from bridge)
- `screens/workspace.py` — MissionWorkspaceScreen with TabbedContent (7 empty tab panes)
- `tabs/overview.py` — OverviewTab wrapping existing Plan 23 three-column layout
- Update `app.py` — add Ctrl+D/G/A/U navigation, screen push/pop logic
- Update `messages.py` — add TabSwitched, ScreenChanged messages
- Update `state.py` — add `active_screen`, `active_tab`, `system_role`, `mission_role` fields

**Delivers:** Launch TUI → see Dashboard → pick mission → enter workspace with 7 tabs (only Overview functional). Navigate between Dashboard/Workspace. Existing Plan 23 functionality preserved in OverviewTab.

**Delete:** `screens/main.py` (replaced by `screens/workspace.py`)

### Phase T2 — Team + Catalog (~5 files, ~1500 lines)

Agent management within a mission and global catalog browsing.

**Create:**
- `tabs/team.py` — TeamTab with two-column layout, agent list, detail panel
- `widgets/prompt_editor.py` — reusable prompt TextArea with save/version
- `widgets/catalog_browse_modal.py` — full-screen catalog browse
- `screens/catalog.py` — CatalogScreen (global agent browse)
- Update `service_bridge.py` — add team, catalog, prompt methods

**Delivers:** Team tab with agent roster, prompt editing, version history. Add agents from catalog. Browse catalog via Ctrl+G. AI recommendation from Architect.

### Phase T3 — Workflows + Schedules (~4 files, ~1200 lines)

Workflow design, DAG visualization, and schedule management.

**Create:**
- `tabs/workflows.py` — WorkflowsTab with two-column layout
- `widgets/dag_renderer.py` — ASCII DAG rendering helper (shared by WorkflowsTab and RunsTab)
- `widgets/schedule_modal.py` — schedule configuration modal
- Update `service_bridge.py` — add workflow, schedule, architect methods

**Delivers:** Workflow list with ASCII DAG, step detail. Schedule configuration. Trigger workflow runs. Architect chat for workflow design.

### Phase T4 — Runs + Historical Event Stream (~2 files, ~800 lines)

Run history with inline expansion and historical event viewing.

**Create:**
- `tabs/runs.py` — RunsTab with DataTable, inline expansion, DAG progress
- Update `service_bridge.py` — add execution decisions method

**Delivers:** Sortable/filterable run history table. Expand rows to see DAG, decisions, actions. View historical events and outputs in right panel. Cost breakdown view.

**Breaking change:** `list_executions()` return type changes from `list[dict]` to `tuple[list[dict], int]`. Update all existing callers in `app.py` in this phase.

**Delete:** `screens/mission_history.py` (functionality absorbed into RunsTab)

### Phase T5 — Chat (~2 files, ~800 lines)

Agent conversations with streaming responses.

**Create:**
- `tabs/chat.py` — ChatTab with thread list and conversation panel
- Update `service_bridge.py` — add session/message methods

**Delivers:** Create chat threads with team agents. Send messages, see streaming responses. Tool call rendering. Thread list with recent activity.

### Phase T6 — Workshop + Context (~3 files, ~900 lines)

Prompt iteration and mission context viewing.

**Create:**
- `tabs/workshop.py` — WorkshopTab with prompt editor, test runner, output
- `tabs/context.py` — ContextTab with markdown viewer and change history
- Update `service_bridge.py` — add workshop, context methods
- Update `widgets/context_viewer.py` — enhance for ContextTab use

**Delivers:** Workshop prompt testing with cached inputs. Context document viewing with change history.

### Phase T7 — Admin + Profile (~3 files, ~1200 lines)

Administrative functions and user self-service.

**Create:**
- `screens/admin.py` — AdminScreen with 5 sub-tabs (Catalog, Metrics, Config, Health, Users)
- `screens/profile.py` — ProfileScreen (display name, password, API keys)
- Update `service_bridge.py` — add all admin and profile methods

**Delivers:** Full admin section: agent CRUD with system prompt editor, platform metrics with ASCII bar charts, config display, health checks, user management with API keys. Profile screen with password change and own API key management.

### Phase T8 — Notifications + Polish (~2 files, ~600 lines)

Notification system and cross-cutting refinements.

**Modify:**
- `widgets/cost_bar.py` — add notification count indicator, terminal bell
- `widgets/notification.py` — add notification list modal with Ctrl+N
- `styles/tui.tcss` — styling for all new screens/tabs
- Update `app.py` — Ctrl+N binding, notification routing from events

**Delivers:** Notification bell with count badge. Notification list modal. Terminal bell for high-urgency events. Loading states. Error boundaries. Help overlay (`?`).

---

## 15  Design Constraints

1. **Thin client mandate (BFF)**: Zero business logic. Every bridge method is a 1:1 pass-through to a single backend service method. No cross-service orchestration, no data aggregation, no prompt construction, no response parsing in the bridge. If a bridge method needs to call more than one backend service, that is a backend gap — file it in §15.5 and implement a single backend method to own the logic.
2. **Rule 006 compliance**: All tables via `build_table()`, all status icons via `status_icon()`, all cost colors via `cost_color()` from `modules/clients/common/`.
3. **500-line rule**: Every file under 500 lines. Split early.
4. **In-process, not HTTP**: The TUI calls service factories directly (Plan 23 architecture decision). No REST API calls. No HTTP client.
5. **Keyword-only APIs**: All new display helpers use keyword-only arguments (Rule 006.6).
6. **No new dependencies**: Textual provides all needed widgets. Do not add external charting or markdown libraries.
7. **Preserve Plan 23**: The gate reviewer, event routing, DAG visualization, and agent detail — all unchanged. This plan adds screens *around* them.

---

## 15.5  Backend Gaps

Features that require backend work before the TUI can implement them.

**BFF principle:** The bridge must be a pure pass-through — one bridge method = one backend
service method. Any orchestration, aggregation, or prompt construction in the bridge is a
temporary workaround that violates the thin-client mandate and must be resolved backend-side.

| TUI Feature | Backend Gap | Workaround | Priority |
|---|---|---|---|
| Mission stats aggregation (OverviewTab quick stats) | No `MissionService.get_stats(mission_id)` method. Stats require querying 3 separate services (team, workflow, execution). | Bridge aggregates from 3 services. **Violates BFF — orchestration logic in client.** | High — used on every workspace load |
| Add team member by name (TeamTab add agent) | `MissionTeamService.add_agent()` requires `agent_catalog_id`, not `agent_name`. No `add_agent_by_name()` method. | Bridge resolves name → ID via `AgentCatalogService.get_by_name()` then calls `add_agent()`. **Violates BFF — cross-service orchestration in client.** | High — core team management action |
| AI team recommendation (TeamTab recommendation) | No `WorkflowArchitectService.recommend_team(mission_id)` method. | Bridge constructs a recommendation prompt, calls `.chat()`, and parses the AI response. **Violates BFF — prompt construction and response parsing are business logic.** | Medium — nice-to-have feature |
| User prompt version history (TeamTab "History" button) | `MissionTeamService` does not track prompt versions. Only `AgentCatalogService.get_prompt_history()` exists for system prompts. | Disable "History" button with "Coming soon" tooltip. Needs `team_member_prompt_versions` table migration. | Low — feature disabled |
| Date-windowed cost summary (Dashboard cost label) | `PlatformMetricsService.get_cost_summary()` returns all-time aggregates, no date range parameter. | Display all-time totals. Label as "Total" instead of "30d". | Low — cosmetic |
| Context milestones (ContextTab milestones section) | `MissionContextManager` has no milestone concept. | Omit milestones section entirely. | Low — feature omitted |
| Next scheduled run time (OverviewTab idle state) | No `ScheduleService.get_next_run()` method. | Omit "Next scheduled" line. | Low — feature omitted |
| Schedule CRUD (WorkflowsTab schedule config) | No `ScheduleService` exists in the backend. All 4 schedule bridge methods (`list_schedules`, `create_schedule`, `update_schedule`, `delete_schedule`) have no backend to call. | Omit schedule configuration UI in Phase T3. Show schedule metadata as read-only from workflow YAML. Schedule editing requires a new backend service + DB tables. | High — blocks Phase T3 schedule features |
| Notification SSE endpoint | User-scoped notification stream does not exist (noted in Plan 29 §14). | Use `TuiEventBus` in-process events (already works for gate/cost/run events). | None — in-process approach is fine |

---

## 16  What This Spec Does NOT Cover

- Authentication flow (TUI uses `system:cli` in-process — no login screen)
- Textual Web deployment (see Reference Architecture 27 for that)
- Mobile/small terminal support (minimum 80×24, optimized for 120+ columns)
- Custom themes beyond dark mode (Textual CSS handles it)
- Performance benchmarks
- Accessibility beyond keyboard navigation (Textual handles screen readers natively)

---

## 17  Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 7 tabs may feel crowded on small terminals | Tab bar wraps or truncates | Use abbreviated tab names on <120 cols: `Ovw│Tm│Ch│Wf│Rn│Ws│Cx` |
| ServiceBridge grows too large with all new methods | File exceeds 500 lines | Split into `service_bridge_core.py`, `service_bridge_admin.py`, `service_bridge_team.py` when any single file exceeds 400 lines |
| ASCII DAG unreadable for complex workflows | Poor visualization of deep/wide DAGs | Fall back to numbered step list with indentation for >10 nodes |
| Tab content doesn't fit in 24-row terminal | Vertical scroll needed | Every tab content wraps in `VerticalScroll` container |
| Markdown rendering in terminal is lossy | Missing formatting fidelity | Use Textual's `MarkdownViewer` (good enough for agent output) |
