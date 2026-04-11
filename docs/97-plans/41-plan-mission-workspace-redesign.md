# Plan 41 — Mission Workspace Redesign

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-09 |
| **Depends on** | Plan 29 (Frontend Design), Plan 34 (Frontend F1 Foundation) |
| **Supersedes** | Plan 29 §3 (mission workspace layout) |
| **Target** | `modules/frontend/` |
| **Reference** | [Cline Kanban](https://github.com/cline/kanban) — task board interaction patterns |
| **Reference** | `/Users/herman.young/development/zeblit` — prior project, same core concept; kanban board as central AI task view |

---

## 1  Motivation

The current mission layout uses a tab-bar with 8 tabs (Overview, Team, Chat, Workflows,
Runs, Console, Workshop, Context). This worked as a scaffold but has three fundamental
problems:

**1. Tabs fragment a unified experience.** Watching a run happen (Console) and directing
the mission (Chat) are the same activity — but they require navigating away from each
other. The user must choose: watch or steer.

**2. The live run is buried.** The most important moment — an agent actively working —
receives a developer-grade event log in a tab that most users don't understand. The
narrative of what's happening is invisible.

**3. The toolbar is misplaced.** Pause/Archive buttons sit in the mission header
regardless of whether anything is running. They have no relationship to run state.

**Design goal:** Replace the tab-bar workspace with a three-panel command center that
shows agent activity, artifacts, and the conversation in a single view — with navigation
for setup/config concerns in drawers rather than separate pages.

---

## 2  Design Principles

1. **The live run is the hero.** Everything in the workspace is oriented around what
   agents are doing right now. Setup and config are secondary.

2. **One view, two modes.** The workspace has an idle mode (no active run) and a live
   mode (run in progress). Same layout, different content. No navigation change.

3. **Steer without leaving.** The user can redirect agents, ask questions, or pause at
   any point from inside the workspace. No tab switch required.

4. **Collapse the sidebar in context.** The global sidebar (240px) is useful for app
   navigation but wastes space inside the mission. It collapses to a 48px icon rail
   when inside a mission workspace, recovered width feeds the panels.

5. **Drawers over pages for secondary concerns.** Director chat, run history, mission
   settings — these open as drawers over the workspace, not as separate routes.

6. **Desktop-first, 1280px minimum.** Following Plan 29 §2. Panel widths are chosen
   for 1280px comfortable, 1440px ideal.

---

## 3  Layout Specification

### 3.1  Global shell (AppShell)

```
┌─────────────────────────────────────────────────────────────────────┐
│ GLOBAL SHELL                                                        │
│  ┌────┬──────────────────────────────────────────────────────────┐  │
│  │ SB │  MAIN CONTENT AREA                                       │  │
│  │    │  (dashboard / catalog / admin / mission workspace)       │  │
│  │ 48 │                                                          │  │
│  │ px │                                                          │  │
│  │(24 │  (240px when outside a mission workspace)                │  │
│  │0px │                                                          │  │
│  │out)│                                                          │  │
│  └────┴──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

The global sidebar renders in two states controlled by a route match:
- **Outside mission** (`/`, `/catalog`, `/admin/*`): full width, 240px, mission list
  visible, "New Mission" button visible.
- **Inside mission** (`/missions/:id/*`): collapsed to 48px icon rail — logo mark,
  back-to-dashboard icon, catalog icon, admin icon (if admin), user avatar.

Mission switching from inside a workspace: click the logo mark or use `⌘K` command
palette (future). No mission list in the collapsed rail — navigate to dashboard first.

### 3.2  Mission Workspace layout

Triggered by route `/missions/:id`. Replaces the current `MissionLayout` component.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  WORKSPACE TOP BAR                                              ~44px    │
│  [←] Mission Name   [active]      Run #3 · 00:42 · $0.12  [Pause] [■]  │
├─────────────┬──────────────────────────────────┬────────────────────────┤
│  LEFT       │  CENTER — LIVE FEED              │  RIGHT — ARTIFACTS     │
│  CONTROL    │                                  │                        │
│  220px      │  flexible (~640px @ 1280px)      │  280px                 │
│             │                                  │                        │
│  Agents     │  [Narrative ▾] [Stream]          │  Results  Sources  Raw │
│  ─────────  │  ─────────────────────────────── │  ─────────────────     │
│  ● health   │  ◉ Starting health check…        │  📄 Health Report      │
│    running  │  ◉ Scanning 47 Python files      │  overall: warning      │
│  ○ arch     │  ◎ Tool: scan_log_errors         │  3 errors, 5 warns     │
│    waiting  │    └ 3 errors found (expand)     │  ──────────────        │
│  ○ quality  │  ◉ Completed — health check      │  📦 Architecture       │
│    waiting  │                                  │  (assembling…)         │
│             │  ◉ Starting architecture…        │                        │
│  ─────────  │  ◎ Reading src/agents/…          │                        │
│  Budget     │  ◎ Reading 12 more files…        │                        │
│  ▓▓▓░░ 12% │                                  │                        │
│  $0.12      │                                  │                        │
│  ─────────  │                                  │                        │
│  [Director] │  ─────────────────────────────── │                        │
│  [History]  │  ┌──────────────────────────┐    │                        │
│  [Plan]     │  │ Redirect or ask…   [⏎]   │    │                        │
│  [Settings] │  └──────────────────────────┘    │                        │
└─────────────┴──────────────────────────────────┴────────────────────────┘
```

**Width budget — two states:**

In **Plan Board mode** the right panel starts collapsed (board needs width):

| Zone | Width | Notes |
|------|-------|-------|
| Sidebar (collapsed) | 48px | Icon rail |
| Left control panel | 220px | Fixed |
| Center board | ~1012px | `flex-1` — right panel collapsed |
| Right artifacts | 0px → 320px | Collapsed; auto-expands on first artifact |

→ 1012px / 4 columns / gaps ≈ **240px per column** — comfortable card width.

In **Narrative / Stream mode** the right panel is open by default:

| Zone | Width | Notes |
|------|-------|-------|
| Sidebar (collapsed) | 48px | Icon rail |
| Left control panel | 220px | Fixed |
| Center feed | ~692px | `flex-1` |
| Right artifacts | 320px | Fixed, collapsible |

At 1440px board mode: center = ~1172px → 285px per column. At 1920px: 1652px → 400px.

Right panel toggle chevron is always visible. In board mode it starts collapsed and
auto-expands when the first `mission.artifact.found` event arrives. In narrative/stream
mode it starts open. Width fixed at 320px (wider than the original 280px — necessary
for readable artifact text previews).

### 3.3  Workspace Top Bar

Single ~44px bar replaces the current `px-6 py-4` mission header block.

```
[←]  Mission Name  [active badge]            Run #3 · 00:42 · $0.12  [Pause]  [■]
```

Left:
- Back arrow → `/` (dashboard)
- Mission name (truncated, click to edit inline — same `InlineBrief` behaviour)
- Status badge (active / paused / archived)

Right (only when a run is active):
- **Progress:** `3 of 7 tasks · 1m 42s` — task count from `plan.created`, completed
  count incremented on each `plan.step.completed` event
- **Cost:** `$0.12` — live, updates on each `session.cost.updated`
- **Pause** button (suspends current run)
- **Stop** button (■, terminates — requires confirmation popover)

```
[←] Architecture Review  [active]    3 of 7 tasks · 1m 42s · $0.12  [Pause] [■]
```

When idle (no active run):
- Right side shows "No active run" + "▶ Start Run" button

### 3.4  Left Control Panel

220px fixed. Content adapts based on active feed mode.

**Section 1 — Agent Roster (mode-aware)**

- **In Narrative / Stream mode:** Full roster — each agent as a row with status dot,
  name, and "thinking…" / current tool if running. Populated from `plan.step.started`
  / `plan.step.completed` SSE events during a live run; from team API at rest.
- **In Plan Board mode:** Condensed to a single summary line — agents are already
  visible on cards, so the roster doesn't duplicate. Shows:
  `3 agents  ·  ● 1 running  ·  ◌ 2 waiting`
  This recovers ~80px of height for budget and stats.

**Section 2 — Budget & Time**

- Progress bar: cost consumed / budget ceiling (from mission config)
- `$0.12 / $5.00` and elapsed time
- Updates on `session.cost.updated`

**Section 3 — Navigation buttons**

Three icon+label buttons that open drawers over the workspace:

| Button | Drawer contents |
|--------|-----------------|
| Director | Full director chat thread (replaces Chat tab) |
| History | Run list with status + cost badges (replaces Runs tab) |
| Settings | Mission settings: name, brief, team, context, tier |

These drawers slide in from the right over the workspace. Only one open at a time.

### 3.5  Center Panel — Live Feed

The hero of the workspace. Contains:

**Mode toggle (top right of panel):**
- `Plan` (default when run active) — kanban task board (see §3.5a)
- `Narrative` — `MissionNarrativeEvent` rows with expandable tool calls
- `Stream` — raw event console (the current ConsolePage content)

The Plan board is the default view when a run starts. It is the primary way the human
reads what the agents are doing. Narrative is an alternative for users who prefer a
prose feed. Stream is for debugging.

**Idle mode (no active run):**

Center panel shows an overview layout:
- Mission brief (editable)
- Recent runs list (last 5, with status and cost)
- Start Run button (prominent)
- Any pinned artifacts from previous runs

This replaces today's OverviewPage and RunsPage for the common case.

**Live mode (run active):**

Scrolling feed of events, newest at bottom, auto-scroll on:
- `MissionNarrativeEvent` → `NarrativeRow` (coloured left border, inline markdown)
- `mission.artifact.found` → inline artifact preview card (also mirrored to right panel)
- `agent.tool.called` → collapsed by default, click to expand with args
- `agent.tool.returned` → collapsed, shows result preview
- `plan.step.started` / `plan.step.completed` → compact phase marker rows
- `agent.thinking.started` → subtle "thinking…" indicator (not a full row)

Tool call rows are grouped under the narrative event that preceded them — indented
beneath the narrative row that announced the step, collapsed by default. Click the row
to expand. This gives Tiered Transparency: narrative always visible, tool detail on
demand.

**Command bar (bottom of panel, always visible during a run):**

Single-line textarea with send button. Sends a message to the mission director agent
mid-run. The director can then redirect, inject context, or acknowledge. This replaces
the Chat tab for in-run communication. It is not a full chat thread — just a steering
input. Clicking "Director" in the left panel opens the full thread in a drawer.

### 3.5a  Center Panel — Plan Board Mode

The Plan Board is the **primary live view** when a run is active. It is the central
idea — the way the human reads what agents are doing, sees tasks get assigned, watches
execution, and sees completion. Inspired by Cline's Kanban project and the unbuilt
kanban concept from the prior Zeblit project (same developer, same core insight).

This is the **Editable Plan** UX pattern from the design research — the one that
makes an AI agent system feel collaborative rather than opaque.

#### The human story — what you see in real time

```
0. [Start Run clicked] → pre-run review gate appears (see §3.5b)
   → user reviews pre-staged tasks or sees empty board
   → clicks "Confirm & Run" to proceed

1. Planning phase (PlanningPhaseEvent fires)
   → Planned column shows animated placeholder: "Assembling plan…"
   → spinner in column header
   → as plan.created fires: placeholder dissolves, real cards materialise
     one by one, each stamped with an agent badge
   → dependency curves draw between blocked tasks
   → user sees the full plan before any work starts

2. Dispatch starts each task (plan.step.started)
   → card slides from Planned → Running with a translate animation
   → agent badge pulses (CSS animation)
   → card body shows "starting…"
   → Running column header: "⚡ 2 agents" if multiple cards present

3. Agent works (agent.tool.called / agent.tool.returned)
   → card shows live tool call name + truncated result (updates in place)
   → progress bar fills from tool count / expected tool count
   → every tool event updates the card without re-rendering the column

4. Approval gate hit (agent.approval.requested)
   → Running card transforms: amber border, "⚠ Awaiting approval"
   → inline Approve / Deny buttons appear on card
   → board is otherwise unblocked (other agents continue)

5. Task completes (plan.step.completed / task.*)
   → card slides Running → Verifying (if verification tiers enabled)
   → then → Done ✓ or ✗
   → card shows cost + duration + result_summary
   → if artifact emitted: card has "View →" link, right panel auto-expands

6. Plan revised mid-run (plan.revised)
   → cancelled cards fade out with a dissolve animation
   → new cards slide into Planned with a highlight flash
   → dependency curves redraw
   → top bar shows "Plan updated" for 3 seconds
```

#### Column structure

```
CENTER PANEL — PLAN BOARD (live run, 2 agents in parallel)

  PLANNED (3)          RUNNING  ⚡ 2       VERIFYING (0)     DONE (1)
  ─────────────────    ─────────────────   ───────────────   ──────────────

  ┌─────────────┐      ┌─────────────┐                      ┌────────────┐
  │ [health]    │      │ [health]    │                      │ [planning] │
  │ Audit logs  │      │ Audit logs  │                      │ Build plan │
  │ & config    │      │             │                      │            │
  │             │      │ ◉ scan_logs │                      │ ✓ $0.04   │
  │ waiting     │      │ ████░░ 60%  │                      │ 0m 32s    │
  └─────────────┘      └─────────────┘                      └────────────┘

  ┌─────────────┐      ┌─────────────┐
  │ [arch]  🔒  │      │ [arch]  ⚠  │  ← awaiting approval (amber)
  │ Review arch │      │ Review arch │
  │ patterns    │      │             │
  │ blocked by  │      │ Awaiting    │
  │ health      │      │ approval    │
  └─────────────┘      │ [✓] [✕]   │
                       └─────────────┘
  ┌─────────────┐
  │ [quality]   │
  │ Run quality │
  │ waiting     │
  └─────────────┘

  [+ Add task]        (SVG Bezier curves connect blocking→blocked cards)
```

The Running column header shows `⚡ 2` when multiple agents execute in parallel —
making parallelism immediately obvious, not just implied by two cards being present.

#### Columns

| Column | States | Description |
|--------|--------|-------------|
| Planned | `pending`, `assigned`, `blocked` | Tasks not yet dispatched. Assigned = agent known. Blocked = depends_on not met |
| Running | `running` | Currently executing |
| Verifying | `verifying` | Agent done, tier-1/2/3 verification in progress |
| Done | `success`, `failed` | Terminal states |

The `blocked` state (from Zeblit's `PlanTask` model) renders within the Planned column
as a visually dimmed card with a 🔒 icon and "blocked by [task]" label. Blocked cards
become normal Planned cards automatically when their dependency moves to Done.

#### Task card anatomy

**Planned card (assigned, not blocked):**
```
┌────────────────────────────────────────┐
│  [health]  platform.health.agent       │  ← agent badge (prominent)
│  Audit log errors and config           │  ← task description
│                                        │
│  waiting to start                      │
│                                        │
│  [✕ Cancel]  [✎ Edit]                 │  ← actions
└────────────────────────────────────────┘
```

**Running card:**
```
┌────────────────────────────────────────┐
│  [health] ●  platform.health.agent     │  ← pulsing dot
│  Audit log errors and config           │
│                                        │
│  ◉ scan_log_errors                     │  ← current tool (live)
│    → 3 errors found in system.jsonl    │  ← result preview (truncated)
│                                        │
│  ████████░░░░  [2 tools]  0m 42s      │  ← progress bar + stats
└────────────────────────────────────────┘
```

**Done card (success):**
```
┌────────────────────────────────────────┐
│  [health] ✓  platform.health.agent     │
│  Audit log errors and config           │
│                                        │
│  3 errors, 5 warnings found            │  ← result_summary
│                                        │
│  $0.09  ·  1m 14s  ·  6 tools         │
│                          [View report →]│  ← opens artifact in right panel
└────────────────────────────────────────┘
```

**Done card (failed):**
```
┌────────────────────────────────────────┐
│  [arch] ✗  software.architecture       │
│  Review architectural patterns         │
│                                        │
│  Timed out after 3 attempts            │  ← failureReason
│                                        │
│  $0.31  ·  4m 02s  ·  2 retries       │
│  [↺ Retry]  [✎ Edit & Retry]  [Skip]  │  ← failure recovery actions
└────────────────────────────────────────┘
```

**Running card awaiting approval:**
```
┌────────────────────────────────────────┐
│  [health] ⚠  platform.health.agent    │  ← amber border
│  Audit log errors and config           │
│                                        │
│  Awaiting approval to proceed          │
│  "Delete 3 stale log files?"           │  ← approval action description
│                                        │
│  [✓ Approve]         [✕ Deny]         │  ← inline gate buttons
└────────────────────────────────────────┘
```

**Planned column — planning phase (before plan.created):**
```
┌────────────────────────────────────────┐
│  ⟳  Assembling plan…                  │  ← shimmer animation
│                                        │
│  Planning agent is breaking down       │
│  the mission into tasks                │
└────────────────────────────────────────┘
```

#### Dependency curves

Tasks with `depends_on` relationships from the Planning Agent's DAG output are
connected by SVG cubic Bezier curves drawn over the board — same approach as Cline
Kanban. Curves:
- Originate from the right edge of the blocking card
- Terminate at the left edge of the dependent card
- Are grey when both cards are in Planned
- Turn amber when the blocker is Running (dependency almost resolved)
- Turn green and fade out when the blocker moves to Done

On hover: curve highlights and shows a ✕ delete button (sends a plan edit instruction
to the director). Dependency management is advisory — the director processes the
change; the system won't apply cycles.

#### Interactions

**Drag-to-reorder** (within Planned column only):
- Changes execution priority of pending tasks
- Optimistic UI update + director send ("move [task] before [task]")
- Blocked cards cannot be reordered above their blockers

**Right-click a Planned card:**
- Edit instructions (opens inline editor on card)
- Reassign to different agent (dropdown of available agents)
- Cancel (removes from plan)

**Click a Running card:**
- Expands to show full tool call log for that task (scoped from console events)
- Collapses on second click

**Click a Done card (success):**
- If artifact available: opens it in right panel and highlights the card

**Click a Done card (failed):**
- Expands inline to show full failure reason + retry options:
  - **↺ Retry** — re-dispatches the same task with the same instructions
  - **✎ Edit & Retry** — opens inline instruction editor on the card first
  - **Skip** — removes from plan, marks dependencies as unblocked, continues

**Inline approval on a Running card:**
- When `agent.approval.requested` fires, the card transforms (amber border)
- Approve / Deny buttons are tappable directly on the card — no modal, no navigation
- Decision sends `UserApprovalEvent` and the card returns to running state

**Add task (bottom of Planned column):**
- Single-line input: type a task description + pick an agent
- Sends instruction to director to insert the task into the plan
- Card appears immediately (optimistic) with subtle "pending" opacity until confirmed

#### Idle mode (no active run)

The board shows the last run's completed plan — all cards in Done with costs and
durations. This makes the board useful as a historical view. The Planned column is
empty but shows the "+ Add task" prompt. Pre-staging tasks before a run is supported:
the user can queue up tasks and sequencing hints that the Planning Agent will consider
when building the next plan.

#### What we borrow

From **Cline Kanban**:
- 4-column state machine (renamed to match our lifecycle)
- Card design with agent name, live activity, status dot, action buttons
- SVG Bezier dependency curves
- Drag-to-reorder within a column

From **Zeblit** (`PlanTask` model):
- `assigned` state — cards show agent before task starts
- `blocked` state — dimmed cards with dependency label
- `progress_percentage` — progress bar on running cards
- `result_summary` — card body on completion
- `depends_on` / `blocks` arrays driving the curve overlay
- `order_index` for stable ordering within columns

**Not borrowed:**
- Git worktrees per card (irrelevant)
- Terminal per card (we scope console events instead)
- Auto-commit/PR workflows
- `@hello-pangea/dnd` (use `@dnd-kit/core` — lighter, no deprecated Atlassian dep)

### 3.5b  Pre-Run Review Gate

Inspired by GitHub Copilot Workspace's confirm-before-execute step. Before the first
task dispatches, the user sees what is about to run and can modify or confirm.

**Trigger:** User clicks "▶ Start Run" from idle mode.

**What appears:** A non-blocking overlay on the center panel (not a modal — the rest
of the workspace remains visible):

```
┌────────────────────────────────────────────────────────┐
│  Ready to run                                          │
│  Architecture Review · 3 agents · est. $0.40          │
│                                                        │
│  PLANNED                                               │
│  [health]  Audit log errors and config                 │
│  [arch]    Review architectural patterns  (→ health)  │
│  [quality] Run quality checks             (→ arch)    │
│                                                        │
│  Pre-stage additional tasks:                           │
│  [+ Add task before running…]                         │
│                                                        │
│  [Edit Plan]              [✓ Confirm & Run]            │
└────────────────────────────────────────────────────────┘
```

- Shows the proposed plan (from last run, pre-staged tasks, or Planning Agent preview)
- User can add tasks, reorder, or edit instructions before confirming
- "Edit Plan" opens the full Plan Board in idle mode for deeper editing
- "Confirm & Run" dismisses the overlay and starts execution

This gate is skipped on subsequent runs if the user checks "Don't ask again for this
mission." Configurable in Settings.

### 3.6  Right Panel — Artifacts

320px, collapsible. Starts collapsed in Plan Board mode, open in Narrative/Stream
mode. Auto-expands on first artifact or streaming content arrival.

Three tabs:

| Tab | Content |
|-----|---------|
| Results | Streaming + completed artifact cards, newest-first |
| Sources | Reserved for research system (web sources, citations) |
| Raw | JSON output of the latest completed task (for debugging) |

**Progressive artifact assembly — streaming:**

Inspired by OpenAI Deep Research and Claude.ai: artifact content should appear as it
is generated, not materialise complete when done. The right panel subscribes to
`AgentResponseChunkEvent` for the currently-running agent. When a long-form output is
streaming:

1. A placeholder card appears immediately: `[report]  Generating…  ⟳`
2. As `AgentResponseChunkEvent` chunks arrive, the card body fills with the streaming
   text rendered through `MarkdownRenderer`
3. When `MissionArtifactFoundEvent` fires, the card locks to its final content and
   the streaming indicator disappears

This means the user reads the report *as it is written*, not after a wait.

**Completed artifact card:**
```
┌──────────────────────────────────────┐
│  📄 [report]  platform.health.agent  │
│  Health Audit — Apr 9                │
│  ─────────────────────────────────── │
│  **Overall: Warning**                │
│  3 critical errors in log output,    │
│  5 config warnings detected…         │
│                                [▾]   │  ← expand for full content
└──────────────────────────────────────┘
```

Expanded view opens full `MarkdownRenderer` output. No modal — expands in-panel with
a max-height + overflow-y-auto scroll area.

Tab label pulses `Results ●` when new content arrives while not focused.

---

## 4  Navigation & Routing

### 4.1  Route table

| Route | Component | Notes |
|-------|-----------|-------|
| `/` | `DashboardPage` | Mission list + New Mission CTA |
| `/missions/new` | `NewMissionPage` | Full-page form (unchanged) |
| `/missions/:id` | `MissionWorkspace` | New unified workspace |
| `/missions/:id/workflows` | `WorkflowsPage` | Full-page, design-time tool |
| `/missions/:id/workshop` | `WorkshopPage` | Full-page, ad-hoc testing |
| `/catalog` | `CatalogPage` | Unchanged |
| `/admin/*` | `AdminLayout` | Unchanged |

Routes removed: `overview`, `team`, `chat`, `runs`, `console`, `context`.
These are absorbed into the workspace and its drawers.

### 4.2  Where mission creation and selection live

**Selection:** The dashboard (`/`) is the primary mission hub — a grid/list of missions
with status indicators, cost to date, last active time, and a link into the workspace.
The collapsed sidebar inside a mission shows only a back-to-dashboard arrow; the user
navigates to dashboard to switch missions.

**Creation:** "New Mission" button on the dashboard (top right). Navigates to
`/missions/new` full-page form — this page is not changing.

The sidebar mission list is removed from the collapsed rail entirely. It only appears
in the full 240px sidebar (outside of missions: dashboard, catalog, admin).

### 4.3  Drawer routing

Drawers are not routes — they are controlled by a `workspaceStore` Zustand slice:

```ts
type DrawerType = 'director' | 'history' | 'settings' | null
type FeedMode = 'narrative' | 'plan' | 'stream'

interface WorkspaceState {
  activeDrawer: DrawerType
  artifactsPanelOpen: boolean
  feedMode: FeedMode
  openDrawer: (d: DrawerType) => void
  closeDrawer: () => void
}
```

Deep-linking to a specific drawer is not required in Phase 1.

---

## 5  Component Map

```
AppShell
├── Sidebar (240px full / 48px collapsed based on route match)
└── main
    ├── DashboardPage
    ├── CatalogPage
    ├── NewMissionPage
    ├── MissionWorkspace                         ← new top-level component
    │   ├── WorkspaceTopBar
    │   ├── LeftControlPanel
    │   │   ├── AgentRoster
    │   │   ├── BudgetMeter
    │   │   └── WorkspaceNavButtons
    │   ├── CenterPanel
    │   │   ├── FeedModeToggle              (Plan | Narrative | Stream)
    │   │   ├── PreRunReviewGate            ← new; overlay before first dispatch
    │   │   ├── LiveFeed (narrative mode)
    │   │   │   ├── NarrativeRow
    │   │   │   ├── ToolCallRow (collapsible)
    │   │   │   ├── PhaseMarkerRow
    │   │   │   └── ArtifactInlineCard
    │   │   ├── PlanBoard (plan mode)           ← new
    │   │   │   ├── PlanColumnHeader (title, count, ⚡ parallel badge)
    │   │   │   ├── PlanColumn (×4: planned/running/verifying/done)
    │   │   │   │   ├── PlanningPlaceholder     ← "Assembling plan…" shimmer
    │   │   │   │   └── TaskCard
    │   │   │   │       ├── TaskCardHeader (agent badge, name, description)
    │   │   │   │       ├── TaskCardActivity (live tool call + progress bar)
    │   │   │   │       ├── TaskCardApproval    ← amber state, inline approve/deny
    │   │   │   │       ├── TaskCardMeta (cost, duration, tools)
    │   │   │   │       └── TaskCardActions (retry, edit & retry, skip, cancel)
    │   │   │   └── DependencyOverlay (SVG Bezier curves, colour-coded by state)
    │   │   ├── EventStream (stream mode — current ConsolePage)
    │   │   ├── IdleOverview (when no active run)
    │   │   └── CommandBar
    │   ├── RightArtifactsPanel
    │   │   ├── StreamingArtifactCard       ← live chunk accumulator
    │   │   ├── ArtifactCard (completed)
    │   │   └── RawOutputView
    │   └── WorkspaceDrawer (portal)
    │       ├── DirectorChatDrawer   (current ChatPage refactored)
    │       ├── RunHistoryDrawer     (current RunsPage refactored)
    │       └── MissionSettingsDrawer
    ├── WorkflowsPage                            ← kept as full-page
    └── WorkshopPage                             ← kept as full-page
```

---

## 6  State Management

### 6.1  WorkspaceStore (Zustand)

New store — `stores/workspace.ts`:

```ts
type AgentStatus = 'waiting' | 'running' | 'verifying' | 'done' | 'failed'

// Mirrors Zeblit's PlanTaskStatus — extended with our verification step
type PlanTaskStatus =
  | 'pending'    // in plan, agent not yet assigned
  | 'assigned'   // agent assigned by planning agent, not yet dispatched
  | 'blocked'    // depends_on not satisfied
  | 'running'    // dispatch loop executing
  | 'verifying'  // tier-1/2/3 verification running
  | 'success'    // complete
  | 'failed'     // terminal failure

interface PlanTask {
  taskId: string
  agentName: string
  description: string
  status: PlanTaskStatus
  orderIndex: number                 // execution order within Planned column
  costUsd: number
  durationSeconds: number
  progressPct: number                // 0–100, shown as progress bar on running cards
  currentTool: string | null         // from agent.tool.called events
  currentToolResult: string | null   // from agent.tool.returned events
  dependsOn: string[]                // task IDs this task is blocked by (→ blocked state)
  blocks: string[]                   // task IDs this task is blocking (for curve rendering)
  retryCount: number
  resultSummary: string | null       // shown on Done card body
  artifactEmitted: boolean           // if true, Done card shows "View →" link
  failureReason: string | null
}

interface WorkspaceState {
  // Panel state
  activeDrawer: DrawerType
  artifactsPanelOpen: boolean
  feedMode: FeedMode

  // Live run state (populated from SSE)
  activeRunId: string | null
  runStartedAt: Date | null
  runCostUsd: number
  agentStatuses: Record<string, AgentStatus>   // agent_id → status

  // Plan board
  planTasks: PlanTask[]                        // ordered; drives Plan mode board

  // Plan board — phase tracking
  planningPhase: 'idle' | 'planning' | 'ready' | 'running' | 'complete'
  planTotalTasks: number
  planCompletedTasks: number

  // Approval gate
  pendingApproval: {
    approvalRequestId: string
    taskId: string
    action: string
  } | null

  // Artifacts + streaming
  artifacts: ArtifactEvent[]
  streamingArtifact: {
    agentId: string
    content: string          // accumulated chunk text
    title: string
  } | null

  // Actions
  openDrawer: (d: DrawerType) => void
  closeDrawer: () => void
  toggleArtifactsPanel: () => void
  setFeedMode: (m: FeedMode) => void
  onRunStarted: (runId: string) => void
  onRunCompleted: () => void
  onCostUpdate: (costUsd: number) => void
  onAgentStatus: (agentId: string, status: AgentStatus) => void
  onArtifactFound: (artifact: ArtifactEvent) => void
  onArtifactChunk: (agentId: string, chunk: string) => void  // AgentResponseChunkEvent
  onPlanCreated: (tasks: PlanTask[]) => void
  onPlanRevised: (added: PlanTask[], removedIds: string[]) => void
  onTaskStatusChange: (taskId: string, status: PlanTask['status']) => void
  onTaskToolUpdate: (taskId: string, tool: string, result?: string) => void
  onApprovalRequested: (requestId: string, taskId: string, action: string) => void
  onApprovalResolved: () => void
  reorderPlannedTasks: (fromIndex: number, toIndex: number) => void
}
```

### 6.2  ConsoleStore (existing)

The existing `stores/console.ts` drives the Stream mode (raw event view). No changes
needed — it's passed as a child of the center panel when `feedMode === 'stream'`.

### 6.3  SSE event routing in MissionWorkspace

`MissionWorkspace` subscribes to `useMissionStream`. Incoming events are dispatched to:
1. `workspaceStore` — for run state, agent roster, cost, artifacts
2. `consoleStore` — for the raw stream mode (unchanged)

This means both stores are always up to date regardless of which mode is active.

---

## 7  Idle Mode — Center Panel Layout

When no run is active, the center panel renders an overview. The left and right panels
remain but show resting state (agent roster from team API, empty artifacts panel).

```
CENTER PANEL — IDLE

  ┌────────────────────────────────────────────────────────┐
  │  Architecture Review                                   │
  │  "Audit the dispatch layer for boundary violations"    │
  │                                          [Start Run ▶] │
  ├────────────────────────────────────────────────────────┤
  │  Recent Runs                                           │
  │  ─────────────────────────────────────────────────     │
  │  ● Run #3   completed   $0.43   2m 14s   Apr 9        │
  │  ○ Run #2   failed      $0.12   0m 42s   Apr 8        │
  │  ● Run #1   completed   $0.31   1m 58s   Apr 7        │
  │                                        [View all →]   │
  ├────────────────────────────────────────────────────────┤
  │  Pinned Artifacts (from Run #3)                        │
  │  ─────────────────────────────────────────────────     │
  │  📄 Architecture Report  [report]  expand ▾            │
  └────────────────────────────────────────────────────────┘
```

---

## 8  Migration Strategy

The current codebase has 8 tab pages. Migration is non-destructive:

### Phase 1 — New workspace shell (layout only)
- Create `MissionWorkspace` with the 3-panel skeleton (no content yet)
- Collapse sidebar when inside `/missions/:id`
- Move current `ConsolePage` content into the center panel "Stream" mode
- Move current `ChatPage` content into the `DirectorChatDrawer`
- Route `/missions/:id` → `MissionWorkspace`
- Keep old tab routes alive (they still work)

### Phase 2 — Live feed
- Implement `NarrativeRow`, `ToolCallRow`, `PhaseMarkerRow` in center panel
- Implement `AgentRoster` in left panel using SSE events
- Implement `ArtifactCard` in right panel using `mission.artifact.found`
- Implement `CommandBar` wired to director send

### Phase 3 — Plan Board
- Implement `PlanBoard` with 4 columns and `TaskCard`
- Implement `PlanningPlaceholder` — shimmer card in Planned during `plan.phase` events
- Wire `plan.created` → `onPlanCreated` → cards materialise one by one in Planned
- Wire `plan.step.started` → card translate-animates Planned → Running
- Wire `plan.step.completed` / `task.*` → card moves to Verifying → Done/Failed
- Wire `agent.tool.called` / `agent.tool.returned` → `onTaskToolUpdate` → live card
- Wire `plan.revised` → `onPlanRevised` → cancelled cards dissolve, new cards slide in
- Wire `agent.approval.requested` → `onApprovalRequested` → card transforms to amber approval state
- Implement `PlanColumnHeader` with `⚡ N` parallel badge when N > 1 in Running
- Implement `DependencyOverlay` (SVG Bezier curves, state-coloured)
- Implement failure recovery actions (Retry / Edit & Retry / Skip) on failed cards
- Implement drag-to-reorder in Planned column (`@dnd-kit/core`)
- Implement `PreRunReviewGate` overlay triggered by "Start Run"

### Phase 4 — Streaming artifacts + idle overview
- Implement `StreamingArtifactCard` in right panel — subscribes to `AgentResponseChunkEvent`
  for the active agent, accumulates chunks, locks to `MissionArtifactFoundEvent` on complete
- Implement `IdleOverview` with recent runs and pinned artifacts
- Remove the Overview and Runs tab pages (replaced)
- Remove the Chat tab page (replaced by drawer + command bar)
- Remove the Console tab page (replaced by stream mode toggle)

### Phase 5 — Drawers
- `RunHistoryDrawer` (refactored from RunsPage)
- `MissionSettingsDrawer` (from Overview + Team + Context pages merged)

### Phase 6 — Remove old routes
- Delete tab route pages that are fully replaced
- Clean up `MissionLayout`, replace with `MissionWorkspace`

---

## 9  Design Decisions & Reasoning

**Why collapse the sidebar inside a mission?**
At 1280px: sidebar (240) + left panel (220) + right panel (280) = 740px overhead.
Center feed gets only 540px — too narrow. Collapsing sidebar to 48px gives 192px back,
center gets 732px. Comfortable. The sidebar's mission list is redundant inside a
mission — the back arrow + dashboard serve the same purpose.

**Why drawers instead of tabs for Director/History/Settings?**
Drawers preserve workspace context. When you open the chat history you can still see
the live feed behind it. Tab navigation destroys that — you lose the run state view.
Drawers also make it clear these are secondary concerns, not primary views.

**Why keep Workflows and Workshop as full pages?**
Both are design-time tools that have nothing to do with a live run. Embedding them as
panels would confuse the purpose of the workspace (run-time) vs. design-time. They
stay as separate routes, accessible via the Settings drawer or direct link.

**Why a command bar instead of the full chat as the default?**
During a live run, users want to redirect with a sentence, not scroll through chat
history. The command bar is fast and contextual. The full history is one click away
(Director drawer). This mirrors how Devin and Cursor Agent work — steering input is
distinct from full conversation history.

**Why auto-expand the right panel on first artifact?**
Empty panels are confusing. Starting collapsed and revealing on content arrival makes
the panel feel purposeful rather than placeholder.

**Why keep idle mode in the same workspace?**
The workspace IS the mission. Whether something is running or not, the workspace is
where you configure and launch. Having a separate "overview" URL and then a "live"
URL would fragment the experience and require state-preserving navigation.

**Why is the Plan Board the default mode, not Narrative?**
The Zeblit project (same developer) established this as the core insight: the kanban
board is for the human to see tasks get assigned to agents, see agents execute them,
and see them move to done. That story — assignment → execution → completion — is best
told visually as cards moving across columns. Narrative text is a good secondary view
for users who prefer prose, but the board is the primary contract between the system
and the human during a run.

**Why a Plan Board mode instead of a separate Plan page or drawer?**
The plan is not a secondary concern — it IS the execution. Showing it as a first-class
center panel mode puts it on equal footing with the narrative feed. A drawer would
hide it behind a button and you couldn't watch the board update as tasks move through
states. A full page would break workspace context (you'd have to navigate away from
the live feed to see the plan). A center panel toggle gives you the choice without
sacrificing either.

**Why map mission tasks to kanban columns rather than a list or DAG view?**
A DAG (directed acyclic graph) view is more technically accurate but requires
significant visual real estate and mental translation — users need to understand graph
theory to read it. A kanban column layout is universally understood: left is pending,
right is done. The dependency curves add the DAG structure on top of a familiar base.
A list is simpler but gives no sense of parallel execution or current state at a glance.

**Why allow drag-to-reorder but not drag-to-column?**
Dragging a card from Planned to Running would start an agent — a high-impact action
that shouldn't happen by accident mid-drag. Cards move to Running only via the system
(when the dispatch loop starts that task) or via an explicit "Start" button on the card.
Drag is limited to reordering within Planned, which is low-stakes (just priority).

**Why borrow from Cline Kanban rather than build from scratch?**
The Cline project solved the core UX problems around AI task boards: how to show
dependency relationships without cluttering, how to make live activity visible on a
card without overwhelming it, and how to handle drag with multiple disabled transitions.
Their approach — SVG Bezier curves drawn over the board, activity text on each card,
4-column state machine — maps cleanly onto our task lifecycle. We adapt rather than
reinvent.

**Why show a "Assembling plan…" placeholder before cards appear?**
Without it the board is empty for 5–30 seconds while the Planning Agent works. An
empty board with no feedback looks broken. The placeholder tells the user the system
is active and something is coming. Dissolving the placeholder into real cards as the
plan arrives makes the plan feel like it was constructed, not just appeared — which
accurately reflects what the Planning Agent did.

**Why show approval gates inline on the running card rather than as a modal?**
Modals are disruptive — they pause everything visually and force the user's attention
away from the board. The approval is scoped to one task; the rest of the run may
continue (other agents are unblocked). Keeping the approval on the card means the
user can see the board state, understand why one agent is waiting, and approve without
losing context of the full execution.

**Why handle Retry / Edit & Retry / Skip on failed cards rather than just Retry?**
Retry alone is only useful when the failure was transient (timeout, network). Often
the task failed because the instructions were ambiguous or the agent was given the
wrong scope — in that case Edit & Retry lets the user fix the root cause without
restarting the whole run. Skip is for cases where the task was optional or the user
decides the mission can complete without it. Three options match the three real failure
scenarios.

**Why animate plan revisions (cards dissolving and appearing)?**
`PlanRevisedEvent` is one of the most powerful signals in the system — it means the
agents discovered something unexpected and adjusted. Without animation, this event is
invisible. The board looks the same before and after. With animation, the user sees
the plan change in front of them — which builds trust (the system is adapting) rather
than confusion (why did some cards disappear?).

**Why show ⚡ N in the Running column header?**
Two cards in a column looks the same whether they're running in parallel or one is
waiting for the other. The badge makes parallelism explicit and impressive. It's one
of the most compelling things to show in a demo — multiple agents working
simultaneously — but only if the UI makes it legible.

**Why stream artifacts into the right panel before completion?**
Waiting for an agent to finish before showing any output creates a dead period where
the user stares at a spinner. Streaming the text as it generates keeps the interface
alive and lets the user start reading and evaluating the output before it is done.
OpenAI Deep Research and Claude.ai both do this for exactly this reason — it makes
generation feel fast even when it takes 60+ seconds.

**Why collapse the right panel by default in Plan Board mode?**
At 1280px, four columns at 165px each are too narrow for comfortable card reading.
Collapsing the right panel gives ~240px per column — workable. The right panel is
not needed during active execution until an artifact arrives; auto-expanding on first
artifact means the user gets it exactly when it becomes useful.

**Why a pre-run review gate?**
The first run of a mission is often uncertain — the user may not know exactly what the
Planning Agent will propose. Showing the plan before execution starts and allowing
edits before the first task dispatches gives the user a moment of control at low cost
(the run hasn't started yet, nothing to undo). Inspired by GitHub Copilot Workspace.
Dismissible for subsequent runs once the user trusts the system.

**Why condense the agent roster in Plan Board mode?**
The full roster (one row per agent with status dot) duplicates information that is
already visible on every card in the board. Showing it condensed (`3 agents · 1
running`) keeps the left panel useful (budget, nav) without wasting 80px on redundant
status indicators. In Narrative/Stream mode — where there is no board — the full
roster is the primary way to understand which agents are active, so it stays full.

---

## 10  Narrative Feed — Implementation Decision Note (2026-04-11)

**Spec vs. shipped:** §3.4 specified a Narrative mode rendered within the workspace
center panel as a toggle alongside Plan Board and Stream — with tool call rows
*grouped and indented* under the narrative event that preceded them (Tiered
Transparency), collapsed by default.

**What shipped:** The workspace was implemented as URL-routed tabs (Plan 49 mission
navigation consolidation, 2026-04-11). The Narrative feed exists as its own tab
(`pages/mission/tabs/narrative-tab.tsx`) rather than a center-panel mode toggle.
It renders a flat event feed with distinct row types per event:
`mission.narrative`, `mission.artifact.found`, `plan.step.started/completed`,
`agent.thinking.started`, `agent.tool.called`, `system.execution.*`.

**What was not implemented:** Tool call rows are not grouped/indented under the
narrative row that announced the step. Each event type appears as a flat row. The
"Tiered Transparency" grouping from §3.4 was not implemented.

**Decision:** The flat feed is retained as the v1 implementation. The tiered grouping
adds meaningful UX value (reduces cognitive load during a run with many tool calls)
but is not load-bearing for correctness. It is deferred to a future polish pass
rather than holding up Phase 2 of the roadmap. At that point, the logical home is
still `narrative-tab.tsx` — group consecutive `agent.tool.called` events under the
nearest preceding `mission.narrative` row with matching `agent_id`.
