# Plan 29 — Frontend Design Specification

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-03-21 |
| **Updated** | 2026-03-23 — aligned with Plan 30 (User Management & Authentication) |
| **Depends on** | Plan 28 (Mission Control Platform Architecture), Plan 30 (User Management & Authentication) |
| **Target** | `modules/frontend/` — React + Vite + Tailwind |

---

## 1  Objective

Define the complete frontend layout, navigation, and screen-by-screen design for the
Mission Control web application. This spec covers every screen in the user journey
(Plan 28 §4.2), maps each to its backend API endpoints, and specifies the information
architecture, interaction patterns, and component responsibilities.

**Design philosophy:**
- Desktop-first. Technical operators on 1440px+ screens. Tablet acceptable. No mobile.
- Dark mode default (CSS variables ready). Light mode via settings toggle.
- AI-first: agent activity is the hero, not buried behind navigation.
- The mission workspace is the primary environment — users spend 90% of time here.

---

## 2  Technology Stack

Already scaffolded in `modules/frontend/`:

| Library | Purpose |
|---------|---------|
| React 18 | UI framework |
| Vite 5 | Build tooling |
| Tailwind CSS 3.4 | Styling (shadcn-style CSS variable theming) |
| TanStack React Query 5 | Server state management |
| Zustand 4 | Client state management |
| React Hook Form 7 + Zod | Form handling and validation |
| Lucide React | Icon library |
| CVA + clsx + tailwind-merge | Component variant styling |

**To add:**

| Library | Purpose |
|---------|---------|
| React Router 6 | Client-side routing |
| @xyflow/react (React Flow) | DAG graph visualization |
| react-markdown + remark-gfm | Agent output rendering |
| react-hot-toast | Toast notifications |
| date-fns | Date formatting |

---

## 3  Information Architecture

### 3.1  Global layout

```
┌──────────────────┬────────────────────────────────────────────┐
│                  │                                            │
│     Sidebar      │           Main Content Area                │
│   (persistent)   │     (route-dependent, full height)         │
│                  │                                            │
│                  │                                     ┌──────┤
│                  │                                     │Right │
│                  │                                     │Drawer│
│                  │                                     │(opt) │
│                  │                                     └──────┤
│                  │                                            │
├──────────────────┴────────────────────────────────────────────┤
│                        Status Bar                             │
└───────────────────────────────────────────────────────────────┘
```

Three persistent elements:
1. **Sidebar** — navigation, mission list, global actions
2. **Main content** — route-driven, takes remaining width
3. **Status bar** — global activity indicator, always visible

Plus one contextual element:
4. **Right drawer** — slides in from right, compresses main content (not overlay)

### 3.2  Sidebar structure

```
┌──────────────────┐
│  MISSION CONTROL │  ← logo / wordmark
│                  │
│  ◉ Dashboard     │  ← global landing page
│                  │
│ ── MISSIONS ──── │  ← section header
│                  │
│  ● Mission A  ●  │  ← selected + has active run indicator
│  ○ Mission B     │
│  ○ Mission C     │
│                  │
│  [+ New Mission] │
│                  │
│ ── PLATFORM ──── │  ← section header
│                  │
│  ○ Catalog       │  ← global agent browse (read-only)
│  ○ Admin         │  ← sysadmin only (hidden for non-admins)
│                  │
│                  │
│                  │
│     ⚙  🔔(3)  👤 │  ← settings, notifications (dropdown), profile
└──────────────────┘
```

**Collapsed mode** (toggle or responsive): icons + 2-letter mission initials.
Hovering shows full name tooltip.

**Mission indicators:**
- `●` filled = selected (you're inside this mission workspace)
- `●` dot beside name = has active run (even when not selected)
- Archived missions hidden by default; "Show archived" toggle at bottom

**Notification bell:** Unread count badge. Click opens a **dropdown popover**
(not the right drawer). Shows recent notifications grouped by type.

### 3.3  Status bar

Always visible at the bottom. Shows cross-mission activity:

```
● 1 active · Daily CTI #47 · Research Agent · web_search · $0.20
```

Multiple active runs:

```
● 2 active · Daily CTI #47 (2/5) · SOC Ops #13 (1/3 steps)
```

No active runs:

```
All quiet · Last run: Daily CTI #46 · 6h ago
```

Click any run reference → jumps to that mission's Overview tab.

Connection status indicator: `● Connected` / `○ Reconnecting...` (small, right-aligned).

### 3.4  Right drawer

Contextual panel that slides in from the right. Compresses main content
(does not overlay — both remain interactive). Approximately 400px wide.

Only one drawer open at a time. Closing returns full width to main content.

| Active tab | Drawer content | Trigger |
|---|---|---|
| Overview | Full run event stream or per-agent filtered stream | Click run card or agent row |
| Team | Prompt version history with diffs | Click "History" on a prompt |
| Chat | (not used — chat IS the main content) | — |
| Workflows | Workflow Architect chat | Auto-opens when designing |
| Runs | Historical event log or rendered output preview | Click "Event Log" or "View Output" |
| Workshop | Full output preview (rendered markdown) | Click "Full Preview" |
| Catalog | Agent detail card | Click "Details" on an agent |

---

## 4  Route Structure

```
/                          → Dashboard
/missions/new              → Create Mission modal (over Dashboard)
/missions/:id              → Mission workspace, default to Overview tab
/missions/:id/overview     → Overview tab
/missions/:id/team         → Team tab
/missions/:id/chat         → Chat tab
/missions/:id/chat/:threadId → Specific chat thread
/missions/:id/workflows    → Workflows tab
/missions/:id/runs         → Runs tab
/missions/:id/runs/:runId  → Run detail expanded
/missions/:id/workshop     → Workshop tab
/missions/:id/context      → Context tab
/catalog                   → Global agent catalog
/profile                   → Current user profile, security, API keys
/admin                     → Admin section, default to Catalog tab
/admin/catalog             → Admin agent catalog CRUD
/admin/metrics             → Platform metrics
/admin/config              → Platform configuration
/admin/health              → System health
/admin/users               → User management
/login                     → Authentication
```

---

## 5  Screens — Detailed Specifications

### 5.1  Login

Email/password authentication with JWT tokens. Full-screen, no sidebar.

**Layout:**
- Centered card on dark background
- "MISSION CONTROL" wordmark + tagline
- Two fields: email input, password input (masked)
- "Sign In" button
- Error state: "Invalid email or password" inline (same message for both — no credential enumeration)

**Behaviour:**
- On submit, `POST /api/v1/auth/login` with `{ email, password }`
- On success: store `access_token` in memory only (`useAuthStore`) and `refresh_token` in
  localStorage. Populate `user: UserResponse` in auth store.
- Redirect to Dashboard
- On page load / hard refresh: if a `refresh_token` exists in localStorage, attempt a silent
  re-auth via `POST /api/v1/auth/refresh`. On success, restore auth state and continue.
  On failure, clear localStorage and show login.
- If auth state is already valid, skip login and redirect to Dashboard

**API:**
- `POST /api/v1/auth/login` — authenticate, receive JWT pair + `UserResponse`
- `POST /api/v1/auth/refresh` — silent re-auth on page load using stored refresh token
- `GET /api/v1/auth/me` — validate existing token and hydrate user state

---

### 5.2  Dashboard (Landing Page)

Global overview. No mission selected.

**Route:** `/`

**Layout sections (top to bottom):**

1. **Active runs banner** — if any runs are in progress across any mission.
   Shows mission name, run number, current agent, step progress.
   Click → jumps to that mission's Overview.

2. **Mission cards grid** — all missions the user has access to.
   Each card shows: name, brief (truncated), agent count, workflow count,
   status badge (Active/Paused/Archived), lifetime cost, last run timestamp.
   Click card → enters mission workspace.

3. **Cost summary** — 30-day cost with progress bar against total budgets.
   Top spending agents. Simple bar chart or spark line.

4. **Recent runs** — chronological list across all missions.
   Status icon, mission name, workflow name, cost, duration.

5. **System health** — three dots: DB, Redis, API (green/red).

**Empty state (no missions):**
```
Welcome to Mission Control
Create your first mission to get started.
[+ Create Mission]
```

**API endpoints consumed:**
- `GET /api/v1/missions` — mission list
- `GET /api/v1/admin/metrics/overview` — cost summary (or lighter public endpoint)
- `GET /api/v1/admin/metrics/activity` — recent runs
- `GET /health/ready` — system health

---

### 5.3  Create Mission

Modal overlay on the current page (preserves context).

**Trigger:** `+ New Mission` in sidebar.

**Fields:**
- Name (slug format, e.g. `daily-cti-brief`)
- Brief (textarea, multi-line — the strategic directive agents read)
- Budget ceiling USD (optional number input)
- Repository URL (optional text input)

**Buttons:** Cancel | Create & Assemble Team →

**Behaviour:** On submit, `POST /api/v1/missions`, then navigate to
`/missions/:id/team` to begin team assembly.

**API:** `POST /api/v1/missions`

---

### 5.4  Mission Workspace — Overview Tab

The live operational dashboard for the active mission.

**Route:** `/missions/:id/overview`

**Layout sections:**

**A) Mission header** (persistent across all tabs):
```
Mission Name                    Status: [Active ▾]
Brief text (truncated)...       [Pause] [Archive] [⋮ More]
```
Status dropdown visible to Owner only. Actions hidden for Viewer role.

**B) Active run card** (when a run is in progress):
- Run identifier: workflow name + run number
- Agent rows, each showing:
  - Status icon: `✓` done, `●` running, `◌` queued, `✗` failed, `⏸` gate
  - Agent name
  - Current activity (tool name, thinking summary)
  - Step position, duration, cost
- Progress bar: steps completed / total, cost / budget
- Click run card header → opens right drawer with full run event stream
- Click specific agent row → opens right drawer filtered to that agent

**C) Gate approval card** (when a gate fires):
- Replaces or overlays the active run card with an amber/warning treatment
- Shows gate name, agent message, preview button
- Action buttons: Approve | Retry with feedback (textarea) | Reject & Stop
- Preview button opens rendered output in right drawer

**D) Idle state** (no active run):
```
No active runs
Last run: #46 daily-brief · completed 6h ago · $1.20
Next scheduled: daily-brief · in 18h (05:00 UTC)
                                              [▶ Run Now]
```

**E) Quick stats card:**
- Agent count, workflow count, total runs, lifetime cost, budget usage

**F) Recent runs list:**
- Last 5-10 runs with status, workflow, cost, duration
- Click → navigates to Runs tab with that run expanded

**G) Mission summary card:**
- Brief (full text), budget ceiling, repository link

**API endpoints consumed:**
- `GET /api/v1/missions/:id` — mission detail
- `GET /api/v1/executions` (filtered by mission) — run status
- SSE stream for real-time events during active runs
- `POST /api/v1/executions/:id/approve` — gate approval

**Right drawer content:**
- Full run event stream (all events, chronological)
- Per-agent filtered view (toggle tabs at drawer top)
- Tool call results: collapsed by default, expandable inline

---

### 5.5  Mission Workspace — Team Tab

Agent roster management and user prompt editing.

**Route:** `/missions/:id/team`

**Layout sections:**

**A) AI recommendation banner** (for new missions with no team):
```
Based on your brief, the Workflow Architect recommends these agents:
"The mission requires intelligence gathering, analysis, and reporting."

[Get AI Recommendation]  or  [Browse Catalog]
```
Clicking "Get AI Recommendation" calls the Architect (loading state while thinking),
then populates the team with recommended agents and explanations.

**B) Team member cards** (expandable, one per agent):
Each card shows:
- Agent name, type badge, version
- Recommendation reason (if AI-recommended)
- System prompt (read-only, collapsed by default, expandable)
- User prompt textarea (editable)
  - Version indicator: `v3 · History` — "History" opens right drawer
  - Save button (saves prompt, increments version)
- Remove button (hidden for auto-included agents)

**C) Auto-included agents** (non-removable):
- Planning Agent, Verification Agent
- Displayed as collapsed, non-editable cards at the bottom

**D) `+ Add from Catalog` button:**
- Opens a slide-over panel from the right (not the drawer — full-height panel)
- Shows searchable, filterable agent catalog
- Each agent has an `+ Add` button
- Adding closes the slide-over and inserts the agent card into the team list

**Empty state:**
```
Your mission has no agents yet.
The Workflow Architect recommends a team based on your brief.
[Get AI Recommendation]  or  [Browse Catalog]
```

**API endpoints consumed:**
- `GET /api/v1/missions/:id/team` — team members
- `POST /api/v1/missions/:id/team` — add agent
- `DELETE /api/v1/missions/:id/team/:memberId` — remove agent
- `PUT /api/v1/missions/:id/team/:memberId/prompt` — update user prompt
- `GET /api/v1/catalog/agents` — catalog for browse
- `POST /api/v1/missions/:id/architect/chat` — AI recommendation

**Right drawer content:**
- Prompt version history with diffs and restore buttons

---

### 5.6  Mission Workspace — Chat Tab

Threaded conversations with any agent on the mission team.

**Route:** `/missions/:id/chat` and `/missions/:id/chat/:threadId`

**Layout: split panel (thread list + conversation)**

**Left sub-panel (~250px): Thread list**
- `+ New Chat` button → dropdown of team agents
- Thread items: agent name, short label (first message truncated), timestamp
- Active thread highlighted
- Threads sorted by last activity (most recent first)

**Right sub-panel: Conversation**
- Agent name and avatar at top
- Message bubbles:
  - User messages: right-aligned
  - Agent messages: left-aligned, rendered as markdown
  - Thinking traces: muted, collapsible (`▸ Thinking: "I need to..."`)
  - Tool calls: card format, collapsible results
    ```
    ▸ Tool: web_search
      query: "ransomware IOCs 2026-03-20"
      ✓ 12 results (340ms)
      ▾ [Show results]
    ```
  - Cost per message: small muted text below agent response
- Input bar at bottom: textarea + send button (Cmd+Enter to send)
- Streaming: agent responses render token-by-token via SSE

**Empty state:**
```
Start a conversation with any agent on your team.
[+ New Chat]
```

**API endpoints consumed:**
- `POST /api/v1/sessions` — create session for new thread
- `POST /api/v1/sessions/:sessionId/messages` — send message (SSE response)
- `GET /api/v1/sessions/:sessionId/messages` — message history

---

### 5.7  Mission Workspace — Workflows Tab

Workflow design, visualization, and schedule management.

**Route:** `/missions/:id/workflows`

**Layout: split panel (workflow list + detail)**

**Left sub-panel (~250px): Workflow list**
- Workflow items showing: name, trigger type icon (clock/lightning/hand),
  budget per run, next scheduled time, enabled/disabled badge
- `+ New Workflow` button
- Click to select → detail loads in right panel

**Right sub-panel: Workflow detail**

**A) DAG graph visualization** (React Flow):
- Step nodes showing: step name, assigned agent, status icon
- Edges showing data flow direction
- Click a node → popover with step details:
  - Agent name, termination mode, max refinement rounds
  - Input wiring (which upstream step), output fields
  - Gate configuration (if any)
  - [Edit Step] button (Owner/Maintainer only)

**B) Workflow metadata bar** (below graph):
- Schedule summary (cron expression, human-readable)
- Budget per run
- Status: Armed / Disabled / Manual only
- Last run reference
- Action buttons: [Edit] [Edit Schedule] [▶ Run Now] [Enable/Disable]

**C) Schedule configuration** (modal, triggered by "Edit Schedule"):
- Trigger type: radio buttons (Cron / Event / Manual only)
- Cron expression input with human-readable preview
- Budget per run (USD)
- Max iterations
- Cooldown (seconds)
- Timezone selector
- Event trigger fields (event type, match patterns) — enabled only for event trigger

**D) New workflow flow:**
- `+ New Workflow` → Architect chat drawer opens automatically
- Main panel shows empty graph area with guidance text
- As the Architect proposes a workflow, the graph renders live
- User refines via chat
- "Lock In Workflow" button saves to database

**Empty state:**
```
No workflows yet.
Start a conversation with the Architect to design one, or import a template.
[Design with Architect]  [Import Template]
```

**API endpoints consumed:**
- `GET /api/v1/missions/:id/workflows` — workflow list
- `GET /api/v1/workflows/:name` — workflow detail with steps
- `POST /api/v1/missions/:id/architect/chat` — Architect conversation
- `GET /api/v1/missions/:id/schedules` — schedule list
- `POST /api/v1/missions/:id/schedules` — create schedule
- `PATCH /api/v1/missions/:id/schedules/:id` — update schedule
- `DELETE /api/v1/missions/:id/schedules/:id` — delete schedule
- `POST /api/v1/missions/:id/workflows/import` — import template

**Right drawer content:**
- Workflow Architect chat (auto-opens during design, closable after)

---

### 5.8  Mission Workspace — Runs Tab

Completed run history, audit trail, and output viewing.

**Route:** `/missions/:id/runs` and `/missions/:id/runs/:runId`

**Layout sections:**

**A) Run history table:**
- Columns: Run #, Workflow, Status (✓/✗), Cost, Duration, Trigger, Timestamp
- Sortable by any column. Filterable by workflow name, status.
- Click row → expands inline with run detail

**B) Run detail (expanded row or sub-view):**

**B1) DAG progress graph:**
- Same graph as Workflows tab but with per-step execution data:
  - Color-coded nodes: green (done), red (failed), grey (skipped)
  - Cost label on each node
  - Click node → popover with: agent, duration, cost, tokens, pass/fail, error

**B2) Run summary:**
- Total cost, duration, token counts
- Trigger type and triggered_by
- Decision audit trail: list of MC decisions (approve, retry, fail, skip)

**B3) Action buttons:**
- [View Event Log] → opens right drawer with full chronological event stream
- [View Output] → opens right drawer with final step's rendered output
- [Cost Detail] → opens right drawer with token-level breakdown per agent/step

**Empty state:**
```
No runs yet.
Go to Workflows to trigger your first run.
[Go to Workflows →]
```

**API endpoints consumed:**
- `GET /api/v1/executions` (filtered by mission) — execution list
- `GET /api/v1/executions/:id` — execution detail
- `GET /api/v1/executions/:id/decisions` — decision audit trail
- `GET /api/v1/executions/:id/cost` — cost breakdown

**Right drawer content:**
- Historical event stream (non-live, scrollable)
- Rendered output (markdown) for any step
- Cost breakdown table

---

### 5.9  Mission Workspace — Workshop Tab

Single-agent prompt iteration and testing.

**Route:** `/missions/:id/workshop`

**Layout sections (vertical stack):**

**A) Agent and source selectors:**
- Agent dropdown: lists all team members
- Source run dropdown: completed runs for the selected agent's workflow
  (defaults to most recent)

**B) System prompt** (read-only, collapsed by default):
- Expandable accordion showing the agent's system prompt from catalog

**C) User prompt editor:**
- Textarea with current user prompt
- Version indicator: `v3 (draft)` while editing, `v3` when saved
- Buttons: [Save] (persists to team member) | [▶ Test] (runs with current text)

**D) Cached inputs** (collapsible):
- Shows upstream output data that will feed into this agent
- Source: the selected run's upstream step output
- [View] button to expand the full JSON/data

**E) Test output:**
- Latest test run result rendered as markdown
- Header: `Run #3 · $0.08 · 12s · 1.4k tokens`
- [Full Preview] → opens rendered output in right drawer
- Previous test links: `[Run #2 · $0.09] [Run #1 · $0.12]` — click to compare

**Empty state (no completed runs):**
```
Workshop needs a completed workflow run to provide cached inputs.
Run your workflow at least once first.
[Go to Workflows →]
```

**API endpoints consumed:**
- `GET /api/v1/missions/:id/team` — team members for dropdown
- `GET /api/v1/workshop/:agentName/cached-inputs` — cached upstream data
- `POST /api/v1/workshop/:agentName/run` — execute test run
- `GET /api/v1/workshop/runs` — workshop run history

**Right drawer content:**
- Full output preview (rendered markdown)

---

### 5.10  Mission Workspace — Context Tab

Mission Context Document — accumulated knowledge from all runs.

**Route:** `/missions/:id/context`

**Layout sections:**

**A) Context document** (main area):
- Rendered markdown (read-only)
- Contains: domain knowledge, established facts, active decisions, current state
- This is what agents read at runtime to stay grounded across runs

**B) Change history** (below or side panel):
- Chronological list of context changes
- Each entry: timestamp, change type, summary, which execution triggered it
- Click to see full diff of what changed

**C) Milestones** (below or side panel):
- Milestone summaries marking significant accumulated progress
- Timestamp, summary text

**Empty state (new mission, no runs yet):**
```
No context accumulated yet.
Context builds automatically as your workflows run.
The mission brief serves as initial context for your agents.
```

**API endpoints consumed:**
- `GET /api/v1/missions/:id` — mission detail includes context fields
- Mission context and history endpoints (from the context layer)

---

### 5.11  Catalog Page

Global agent catalog. Read-only for regular users. Separate from admin.

**Route:** `/catalog`

**Layout:**
- Search bar + filter dropdowns (type: vertical/horizontal/system, keywords)
- Agent cards in a grid or list:
  - Agent name, type badge, version
  - Description (truncated)
  - Keywords as tags
  - Tools list
  - [Details →] button

**Right drawer (on "Details" click):**
- Full agent description
- Capabilities / interface schema (input/output fields)
- Tool list with descriptions
- Constraints (timeout, cost ceiling, retry budget)
- System prompt: **not shown** (sysadmin only — visible in Admin)

**API:** `GET /api/v1/catalog/agents` and `GET /api/v1/catalog/agents/:name`

---

### 5.12  Admin Section

Separate workspace for sysadmins (`user.system_role === 'admin'`). Own tab set within the main content area.

**Route:** `/admin/*`

**Tab set:** Catalog | Metrics | Config | Health | Users

**5.12.1  Admin — Catalog Tab**

CRUD table for agent management.

- Sortable/filterable table: name, type, version, enabled, visibility
- Click row → inline expand or navigate to edit form
- Edit form: all agent fields (description, system prompt, model config, tools,
  scope, interface, constraints, keywords, enabled, visibility)
- System prompt editor: full-height textarea with version history
  - [History] button → shows versions with diffs and restore
- Create agent: form with all fields
- Delete: confirmation modal

**API:**
- `GET /api/v1/admin/catalog` — list all agents
- `POST /api/v1/admin/catalog` — create
- `PATCH /api/v1/admin/catalog/:name` — update
- `DELETE /api/v1/admin/catalog/:name` — delete
- `PUT /api/v1/admin/catalog/:name/prompt` — update system prompt
- `GET /api/v1/admin/catalog/:name/prompt-history` — version history
- `POST /api/v1/admin/seed-catalog` — seed from YAML

**5.12.2  Admin — Metrics Tab**

Platform-wide dashboards.

- Overview cards: total missions, sessions, executions, workflow runs, agents, total cost
- Cost breakdown: by agent (bar chart), by status (pie/donut)
- Agent utilisation table: agent name, total runs, total cost, avg duration
- Recent activity: latest executions and workflow runs

**API:**
- `GET /api/v1/admin/metrics/overview`
- `GET /api/v1/admin/metrics/costs`
- `GET /api/v1/admin/metrics/agents`
- `GET /api/v1/admin/metrics/activity`

**5.12.3  Admin — Config Tab**

Read-only platform configuration display.

- Sections: application, workflows, sessions, notifications, features
- Rendered as structured cards/tables (no editing in UI — config changes via CLI/files)

**API:** `GET /api/v1/admin/config`

**5.12.4  Admin — Health Tab**

System health checks.

- Database: status + latency
- Redis: status + latency
- Overall: healthy/degraded/unhealthy
- Manual check trigger button

**API:** `POST /api/v1/admin/system/health` and `GET /health/detailed`

**5.12.5  Admin — Users Tab**

Full user management. Create, edit, deactivate users. Manage API keys. Reset passwords.

**Layout: table + detail panel**

- Sortable/filterable table: display name, email, system role, active status, last login, created date
- Status badge: Active (green) / Inactive (red) / Service Account (muted)
- Click row → inline expand or detail panel with full user info

**User detail actions:**
- Edit display name, system role (`viewer / user / admin`) via inline form
- Deactivate user (soft delete with confirmation modal — cannot deactivate self)
- Reset password (modal with new password field, min 12 chars)

**API keys sub-section** (in expanded row):
- Table: key name, prefix, expires, last used, status (Active / Revoked / Expired)
- [+ Create Key] → modal with name field and optional expiry (1–365 days)
  - On success: display full key in a copy-to-clipboard dialog — **shown once only**
- [Revoke] button on each active key with confirmation

**Create user** (button at table top):
- Modal fields: email, display name, password (optional — omit for API-key-only users), system role, service account checkbox
- On submit: `POST /api/v1/admin/users`

**API:**
- `GET /api/v1/admin/users` — list users (query: `limit`, `offset`)
- `POST /api/v1/admin/users` — create user
- `PATCH /api/v1/admin/users/{id}` — update display name / role / active status
- `DELETE /api/v1/admin/users/{id}` — deactivate user
- `POST /api/v1/admin/users/{id}/reset-password` — admin reset password
- `GET /api/v1/admin/users/{id}/api-keys` — list user's keys
- `POST /api/v1/admin/users/{id}/api-keys` — create key for user
- `DELETE /api/v1/admin/users/{id}/api-keys/{keyId}` — revoke key

---

### 5.13  Profile Page

Current user's own account management. Accessible via the `👤` icon in the sidebar footer.

**Route:** `/profile`

**Layout sections (vertical stack):**

**A) Profile info:**
- Display name (editable inline)
- Email address (read-only)
- System role badge (read-only — changed by admins only)
- Last login timestamp

**B) Security:**
- Change password form: current password, new password (min 12 chars), confirm
- [Change Password] button → `POST /api/v1/auth/change-password`
- Hidden if the account has no password set (API-key-only / service account)

**C) API Keys:**
- Table: key name, prefix (first 8 chars), expires, last used, status
- [+ Create Key] → modal with name + optional expiry. On success: display and copy full key once.
- [Revoke] on each active key with confirmation
- This is the user-facing equivalent of the admin API key management

**API:**
- `GET /api/v1/auth/me` — load profile (display name, email, role)
- `POST /api/v1/auth/change-password`
- `GET /api/v1/auth/api-keys`
- `POST /api/v1/auth/api-keys`
- `DELETE /api/v1/auth/api-keys/{keyId}`

---

### 6.1  Notification types

| Type | Trigger | Urgency |
|---|---|---|
| Gate approval | Gate fires during a run | High — also shows toast |
| Run failed | Execution or workflow run fails | High — also shows toast |
| Run completed | Workflow run finishes successfully | Normal |
| Budget warning | Mission or run cost exceeds 80% of ceiling | Normal |

### 6.2  Notification UI

**Bell icon** in sidebar footer with unread count badge.

**Dropdown popover** (not the right drawer):
- Grouped by time (today, yesterday, older)
- Each item: icon, title, mission reference, timestamp, [Go →] link
- "Mark all read" action
- "View all" link (future: dedicated notifications page)

**Toasts** (bottom-right):
- Appear for high-urgency notifications (gates, failures)
- Auto-dismiss after 8 seconds, or click to jump to context
- Stack if multiple arrive simultaneously

### 6.3  Delivery mechanism

Notifications arrive via SSE. The frontend maintains a persistent SSE connection
for the authenticated user. Events include notification payloads that trigger
both the bell badge update and toast display.

---

## 7  Event Stream Rendering

The event stream is the most information-dense component. It appears in:
- Overview right drawer (live run monitoring)
- Chat tab (inline in conversation)
- Runs tab right drawer (historical replay)

### 7.1  Event types and rendering

| Event | Rendering |
|---|---|
| Agent started | `09:15:39  Research Agent started (step 2)` — muted, timestamped |
| Thinking | `▸ Thinking: "I need to cross-reference..."` — muted italic, collapsible |
| Tool call start | `▸ Tool: web_search` with args — card format |
| Tool call result | `✓ 12 results (340ms)` — appended to tool card, results collapsible |
| Tool call error | `✗ ConnectionTimeout after 30s` — red text, appended to tool card |
| Agent response | Rendered markdown — full width, left-aligned |
| Agent completed | `09:16:51  Research Agent completed · $0.18 · 1m 12s` — muted |
| Gate fired | Amber card with approval actions (in Overview) |
| Error / failure | Red card with error message, stack trace collapsible |
| Cost update | Running total in stream footer |

### 7.2  Filtering

In the Overview right drawer, a tab bar at the top filters the stream:

```
[All Events]  [Intel Gatherer ✓]  [Research Agent ●]  [Report Writer ◌]
```

"All Events" shows the full chronological stream. Agent tabs filter to that agent only.

### 7.3  Tool result expansion

Tool call results are collapsed by default to keep the stream scannable:

```
▸ Tool: web_search
  query: "ransomware IOCs 2026-03-20"
  ✓ 12 results (340ms)
  ▾ [Show results]
     1. "New LockBit variant..." — bleepingcomputer.com
     2. "Lazarus targets crypto..." — thehackernews.com
     ... 10 more
```

Click `[Show results]` to expand. Click again to collapse. State is local
(not persisted). When viewing historical streams, all results start collapsed.

---

## 8  Role-Based UI

The backend enforces permissions. The frontend reflects them by conditionally
rendering actions.

### 8.1  Two-tier role system

Two separate, orthogonal role systems are in play:

**System-level roles** (`user.system_role` from `useAuthStore`):
- `viewer` — read-only platform access
- `user` — standard platform access (default)
- `admin` — full platform access; gates the Admin section

**Mission-level roles** (from `MissionMember` for the current mission):
- `Owner` — full control of the mission
- `Maintainer` — can operate but not configure
- `Viewer` — read-only

A user can be a system-level `admin` but a `Viewer` on a specific mission.
A user can be a system-level `user` but the `Owner` of a mission they created.

### 8.2  Hook design

```typescript
// System-level: reads user.system_role from useAuthStore
const { isAdmin } = useAuthStore()

// Mission-level: reads MissionMember role for the current mission
const { role } = useRole(missionId)  // returns 'Owner' | 'Maintainer' | 'Viewer'
```

### 8.3  Action visibility matrix

| Element | Owner | Maintainer | Viewer |
|---|---|---|---|
| + New Mission | Visible | Hidden | Hidden |
| Mission Pause/Archive | Visible | Hidden | Hidden |
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
| Admin section | `isAdmin` only | Hidden | Hidden |

Implementation: `useRole(missionId)` reads the mission member role from React Query
cache (loaded with the mission). `useAuthStore` provides `isAdmin` directly from
`user.system_role`. Components use both to conditionally render buttons/actions.
Read-only views are always accessible.

---

## 9  Empty States

Every screen has a meaningful empty state that guides the user forward.

| Screen | Empty state message | Action |
|---|---|---|
| Dashboard (no missions) | "Welcome to Mission Control. Create your first mission." | [+ Create Mission] |
| Team (no agents) | "Your mission has no agents yet." | [Get AI Recommendation] or [Browse Catalog] |
| Chat (no threads) | "Start a conversation with any agent on your team." | [+ New Chat] |
| Workflows (none) | "No workflows yet. Design one with the Architect." | [Design with Architect] or [Import Template] |
| Runs (none) | "No runs yet. Go to Workflows to trigger your first run." | [Go to Workflows →] |
| Workshop (no runs) | "Workshop needs a completed run for cached inputs." | [Go to Workflows →] |
| Context (no runs) | "Context builds automatically as workflows run." | — |

---

## 10  Component Hierarchy

### 10.1  Shared / infrastructure

| Component | Purpose |
|---|---|
| `AppShell` | Sidebar + main content + status bar + drawer layout |
| `Sidebar` | Navigation, mission list, footer actions |
| `StatusBar` | Global activity indicator |
| `RightDrawer` | Slide-in contextual panel |
| `TabBar` | Mission workspace tab navigation |
| `NotificationDropdown` | Bell icon popover with notification list |
| `Toast` | Transient notification popup |

### 10.2  Data display

| Component | Purpose |
|---|---|
| `EventStream` | Renders SSE events (thinking, tools, responses) |
| `ToolCallCard` | Tool invocation with collapsible results |
| `MarkdownRenderer` | Renders agent output as formatted markdown |
| `DagGraph` | Workflow DAG visualization (React Flow) |
| `StepPopover` | Node click popover with step details |
| `CostBadge` | Formatted cost display with color coding |
| `StatusBadge` | Run/agent/mission status indicator |
| `AgentCard` | Agent info card (used in Team, Catalog, Admin) |

### 10.3  Forms

| Component | Purpose |
|---|---|
| `MissionForm` | Create/edit mission fields |
| `PromptEditor` | User prompt textarea with save/version/history |
| `ScheduleForm` | Cron/event/manual schedule configuration |
| `ChatInput` | Message input with send button |

### 10.4  State management

| Store | Purpose |
|---|---|
| `useAuthStore` (Zustand) | `access_token` (memory only), `refresh_token` (localStorage), `user: UserResponse \| null`, derived `isAdmin` |
| `useNotificationStore` (Zustand) | Unread count, notification list |
| `useDrawerStore` (Zustand) | Drawer open/closed state, content type |
| React Query | All server state (missions, teams, runs, etc.) |

---

## 11  API Client Layer

A typed fetch wrapper that all hooks use:

```typescript
// Injects Authorization: Bearer <access_token> header on every request.
// On 401, attempts a silent token refresh via POST /api/v1/auth/refresh,
// updates the auth store, and retries the request once.
// If the refresh also fails, clears auth state and redirects to /login.
const api = {
  get<T>(path: string): Promise<T>,
  post<T>(path: string, body?: unknown): Promise<T>,
  patch<T>(path: string, body: unknown): Promise<T>,
  put<T>(path: string, body: unknown): Promise<T>,
  delete(path: string): Promise<void>,
  // SSE: EventSource does not support custom headers natively.
  // Pass the access token as a query parameter: ?token=<access_token>
  // The backend validates it identically to the Bearer header.
  sse(path: string, body?: unknown): EventSource,
}
```

React Query hooks wrap each endpoint:

```typescript
useMissions()           // GET /api/v1/missions
useMission(id)          // GET /api/v1/missions/:id
useMissionTeam(id)      // GET /api/v1/missions/:id/team
useWorkflows(missionId) // GET /api/v1/missions/:id/workflows
useExecutions(missionId)// GET /api/v1/executions?mission_id=...
useCatalog()            // GET /api/v1/catalog/agents
useCurrentUser()        // GET /api/v1/auth/me
// ... etc
```

Mutations use `useMutation` with optimistic updates where appropriate.

---

## 12  Real-Time Architecture

### 12.1  SSE connections

Two persistent SSE connections per authenticated user:

1. **Notification stream** — user-scoped, delivers notification events
   (gate requests, run completions, failures, budget warnings)

2. **Run stream** — opened on demand when viewing a live run on the Overview tab.
   Delivers execution events (agent start/stop, tool calls, thinking, responses).

### 12.2  Chat streaming

Chat messages use a per-request SSE connection:
`POST /api/v1/sessions/:id/messages` returns an SSE stream for the agent's response.
The connection closes when the response completes.

### 12.3  Reconnection

All SSE connections implement automatic reconnection with exponential backoff.
The status bar shows connection state (`● Connected` / `○ Reconnecting...`).

---

## 13  Build Phases

### Phase F1 — Foundation

Establish the shell, routing, API client, and auth.

- AppShell layout (sidebar, main, status bar, drawer)
- React Router with all routes (including `/profile` and `/admin/users`)
- API client layer: typed fetch wrapper with `Authorization: Bearer` header injection,
  automatic token refresh interceptor on 401, SSE token-as-query-param helper
- Auth flow: email/password login form, JWT token storage (`access_token` memory only,
  `refresh_token` localStorage), silent re-auth on page load via `/auth/refresh`
- Zustand stores: `useAuthStore` (`access_token`, `refresh_token`, `user`, `isAdmin`),
  `useNotificationStore`, `useDrawerStore`
- Shared UI primitives (badges, cards, buttons)

### Phase F2 — Dashboard + Mission CRUD

The landing page and mission lifecycle.

- Dashboard page with mission cards
- Create mission modal
- Mission workspace shell (tab bar, header with status/actions)
- Empty states for all tabs

### Phase F3 — Team + Catalog

Agent management within a mission.

- Team tab with agent cards and prompt editing
- Catalog browse page (global)
- Add-from-catalog slide-over panel
- Prompt version history drawer

### Phase F4 — Workflows + Architect

Workflow design and DAG visualization.

- Workflow list/detail split panel
- DAG graph rendering (React Flow)
- Step node popovers
- Schedule configuration modal
- Architect chat in right drawer
- Workflow template import

### Phase F5 — Runs + Event Stream

Historical runs and the live event stream.

- Run history table with inline expansion
- DAG progress visualization (color-coded nodes)
- Event stream component (shared across Overview, Runs, Chat)
- Tool call cards with collapsible results
- Output preview (markdown renderer)
- Cost breakdown view

### Phase F6 — Live Monitoring + Gates

Real-time run monitoring on the Overview tab.

- Active run card with agent status rows
- SSE integration for real-time events
- Gate approval UI (approve, retry with feedback, reject)
- Status bar live updates
- Notification system (bell, dropdown, toasts)

### Phase F7 — Chat + Workshop

Agent conversations and prompt iteration.

- Chat tab with thread list and conversation view
- SSE streaming for chat responses
- Workshop tab with prompt editor, test runner, cached inputs
- Output comparison across test runs

### Phase F8 — Admin + Profile + Polish

Admin section and cross-cutting refinements.

- Admin catalog CRUD with system prompt editor
- Admin metrics dashboard
- Admin config and health pages
- Admin Users tab: user list, create/edit/deactivate, API key management, password reset
- Profile page: display name, change password, own API key management
- Role-based UI conditional rendering (both system-level `isAdmin` and mission-level `useRole`)
- Dark mode toggle
- Loading states (skeleton loaders)
- Error boundaries and fallback UI

---

## 14  Dependencies on Backend

| Frontend Feature | Backend Requirement | Status |
|---|---|---|
| Login | `POST /api/v1/auth/login` | Exists |
| Token refresh / silent re-auth | `POST /api/v1/auth/refresh` | Exists |
| Auth validation / user hydration | `GET /api/v1/auth/me` | Exists |
| Profile page | `GET /api/v1/auth/me`, `POST /api/v1/auth/change-password` | Exists |
| Own API key management | `GET/POST/DELETE /api/v1/auth/api-keys` | Exists |
| Dashboard | `GET /api/v1/missions` | Exists |
| Mission CRUD | `POST/GET/PATCH /api/v1/missions` | Exists |
| Team management | `GET/POST/DELETE /api/v1/missions/:id/team` | Exists |
| User prompt editing | `PUT /api/v1/missions/:id/team/:id/prompt` | Exists |
| Catalog browse | `GET /api/v1/catalog/agents` | Exists |
| Workflow list/detail | `GET /api/v1/missions/:id/workflows`, `GET /api/v1/workflows/:name` | Exists |
| Schedule management | `GET/POST/PATCH/DELETE /api/v1/missions/:id/schedules` | Exists |
| Architect chat | `POST /api/v1/missions/:id/architect/chat` | Exists |
| Template import | `POST /api/v1/missions/:id/workflows/import` | Exists |
| Execution list/detail | `GET /api/v1/executions` | Exists |
| Cost breakdown | `GET /api/v1/executions/:id/cost` | Exists |
| Gate approval | `POST /api/v1/executions/:id/approve` | Exists |
| Chat (sessions) | `POST /api/v1/sessions/:id/messages` (SSE) | Exists |
| Workshop | `POST /api/v1/workshop/:agent/run` | Exists |
| Admin catalog | `/api/v1/admin/catalog/*` | Exists |
| Admin metrics | `/api/v1/admin/metrics/*` | Exists |
| Admin config | `GET /api/v1/admin/config` | Exists |
| Admin health | `GET /health/detailed` | Exists |
| Admin user management | `GET/POST/PATCH/DELETE /api/v1/admin/users/*` | Exists |
| Health | `/health/*` | Exists |
| Notification SSE | User-scoped notification stream | **Needs endpoint** |
| Run SSE | Execution event stream | **Needs endpoint** |
| Prompt version history | User-facing `GET /api/v1/missions/:id/team/:id/prompt-history` | **Needs endpoint** (admin equivalent exists) |

---

## 15  Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| React Flow (DAG) adds bundle size | ~150KB gzipped | Lazy load only on Workflows/Runs tabs |
| SSE connections may leak on navigation | Memory/connection leaks | Cleanup in useEffect return; connection manager |
| Event stream gets very long during runs | DOM performance | Virtualized scrolling (react-window) for streams > 500 events |
| Seven tabs may feel crowded | Cognitive overload | Icons + text on wide screens; icons-only with tooltips when compressed |
| Right drawer conflicts with small screens | Layout breaks < 1200px | Drawer becomes overlay (not compress) below breakpoint |
| Chat threads accumulate without cleanup | Data bloat | Pagination on thread list; archive old threads |

---

## 16  What This Spec Does NOT Cover

- Mobile responsive layouts (desktop-first tool)
- Internationalization / localization (English only)
- Offline support (requires live backend)
- Browser compatibility beyond modern evergreen browsers
- Performance benchmarks (premature at design phase)
- Visual design tokens (colors, spacing, typography) — Tailwind + CSS variables handle this
- Animation/transition specifications — implement tastefully, no spec needed
- Keyboard shortcuts — add during polish phase
- Accessibility (a11y) — follow semantic HTML and ARIA best practices during implementation
