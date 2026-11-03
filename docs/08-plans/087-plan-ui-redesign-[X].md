# Plan 87 — Web UI Redesign, Grounded in the Current Repo

**Version:** 1.3.0
**Date:** 2026-10-16 (v1.0) · revised same day after `/prompt-check-plan-quality` (v1.1: reuse
inventory §2.4, phase-order fixes so no action is unreachable between commits, backend reuse);
v1.2 after second `/prompt-check-plan-quality`: no aliases (P3), no wrappers, active-plan scoping;
v1.3 after third pass: opacity and shadow tokens (C34, C35), shared ConfirmDialog, stale decision markers
**Author:** Herman + Opus 5.5 (`/prompt-get-context` → study of research 035 → repo grounding)
**Status:** Complete (2026-11-01) — Phases 0 to 12 delivered. Defects found by the Phase 12 sweep that were not fixed are listed in §5.
**Depends on:** None
**Unlocks:** One consistent visual system (dark + warm-white) across every web screen
**Workflow:** Commit directly to `main`, one commit per sub-phase, working code only (no PRs)

---

## 0. Problem Statement

`docs/09-research/035-ui-redesign-handoff.md` (the **handoff**) and
`docs/09-research/035-ui-redesign-reference.html` (the **reference**) describe a full reskin of the
web client. Claude Design produced both without access to this repo. The visual intent is sound,
but the handoff makes assumptions about the code, the data and the process that are wrong here.
Executing it literally would delete working features, emit Tailwind classes that do not exist,
show data the backend does not provide, and break the project rules.

This plan keeps the handoff's visual design and replaces its assumptions with the facts of the
current tree. Where this plan and the handoff disagree, **this plan wins**. Where this plan is
silent on a visual detail, the handoff's value applies. Where the handoff and the reference
disagree on a visual detail, the reference wins (it is the rendered design).

### Sources and precedence

| Source | Authority |
|---|---|
| Project rules (`AGENTS.md`, `docs/03-principles/`, `docs/04-rules/`) | Binding. Overrides everything below. |
| Reference architecture docs 01, 22, 23 | Binding for the web client. |
| This plan | Binding for scope, sequence and every correction in §2. |
| Reference HTML | Visual source of truth (colours, spacing, layout per screen). |
| Handoff | Visual detail where this plan and the reference are silent. |

### How to view the reference

The reference is a self-extracting bundle. It loads React 18.3.1 from unpkg and Geist from Google
Fonts, then renders a `<x-dc>` template with 20 screens marked `data-screen-label="…"`
(Login, Dashboard, New mission, Overview, Chat, Plan, Runs, Run live, Workflow editor, Costs,
Admin, Team, Narrative, Context, Knowledge, Artifacts, Console, Catalog, plus the shell).
Open it in a browser; the Tweaks panel switches theme (`dark`, `warm-white`, `light-neutral`)
and start screen. `light-neutral` is out of scope. The mock data in it (`daily-cti-brief`,
costs, agent names) is placeholder content, not a data contract.

---

## 1. Constraints

These apply to every phase. A phase is not done until all of them hold for the files it touched.

1. **Thin client (P1, P2, doc 22).** No business logic, calculation or aggregation in the
   frontend. Presentation mapping (status → tone, agent → icon) is allowed. Cross-mission
   aggregation is not: it belongs in a backend service (§3, Phase 8).
2. **No fabricated data.** A UI element that needs data the API does not return is either
   dropped or blocked on Phase 8. Never render placeholder numbers, and never compute
   a value the backend should own.
3. **No dead controls.** No buttons, inputs or menu items that do nothing. No `TODO` stubs
   (rule 002.6).
4. **Tokens only.** No raw hex, no `rgb()`/`rgba()` literals and no Tailwind palette classes
   (`slate-*`, `zinc-*`, `gray-*`, `red-*`, `green-*`, `blue-*`, `amber-*`, `emerald-*`,
   `rose-*`, `violet-*`, `cyan-*`, `orange-*`, `purple-*`, `sky-*`, `yellow-*`) in touched
   files. Every colour comes from a CSS variable in `src/index.css` via `tailwind.config.js`.
5. **Every class must exist.** Any utility that references a custom token (`bg-well`,
   `border-panel-border` …) must be defined in `tailwind.config.js`. Tailwind silently drops
   unknown classes, so the §6 grep gate checks this explicitly.
6. **File size (doc 23, AGENTS.md).** New components ≤ 300 lines, new hooks ≤ 150, new
   stores ≤ 200. Existing files over those limits must not grow. AGENTS.md's hard limit of
   1000 lines applies to everything.
7. **Fail fast.** No silent fallbacks. A stored theme value that is not a known theme is
   removed and replaced by the system preference — never cast with `as Theme`.
8. **Behaviour parity.** Every route, mutation, keyboard shortcut, drawer and
   modal that works today still works after each commit.
9. **Accessibility (doc 23).** Icon-only buttons have `aria-label` (not only `title`).
   Contrast: WCAG AA (4.5:1 body, 3:1 large). Pulse, shimmer and spin animations carry
   `motion-reduce:animate-none`.
10. **Backend changes follow the layers.** Endpoint → service → repository → model, responses
    wrapped in `ApiResponse`, config from YAML, tests against real Postgres (P12).

---

## 2. Corrections to the Handoff

Each row is a verified fact about the current tree. The implementing agent applies the
**Correction** column instead of the handoff text.

### 2.1 Paths, files and process

| # | Handoff says | Fact in repo | Correction |
|---|---|---|---|
| C1 | Scope is `frontend/` | Frontend lives at `modules/frontend/` | All paths are relative to `modules/frontend/`. |
| C2 | Reference is `Mission Control - Redesign.dc.html` | File is `docs/09-research/035-ui-redesign-reference.html` | Use the real path. |
| C3 | One PR per step | Project commits directly to `main`, no PRs | One commit per sub-phase. |
| C4 | Each PR passes the §10 checklist | `npm run lint` already fails (3 warnings vs `--max-warnings 0`); frontend is not in CI; no frontend tests exist | Phase 0 makes lint green first. Gates are in §6. |
| C5 | §5.1 `AppShell` renders `<Sidebar/>` + `<main>` only | `components/layout/app-shell.tsx:15` mounts `<RightDrawer/>`, which hosts six panels (agent detail, prompt history, event log, output preview, cost breakdown, run events) | Keep `RightDrawer`. Restyle it as a Panel (Phase 3.1). |
| C6 | §2.1 adds `@fontsource/geist` `@import` lines to `index.css` | Geist is already imported in `src/main.tsx:8-10`, but `src/index.css:75` overrides `body` to the system font stack, so Geist is loaded and unused | Keep font imports in `main.tsx` only. Add `@fontsource/geist-mono` 400/500 there. Remove the `font-family` override from `body`. |
| C7 | §5.4 tab list lives in `layout.tsx` | It does (`pages/mission/layout.tsx:64-79`), and `lib/constants.ts` already holds `ROUTES` | Move the grouped nav definition to `lib/constants.ts`, referencing `ROUTES`. |
| C8 | §5.4 brief moves to Overview, "reusing `InlineBrief`" | `InlineBrief` was a private function in `layout.tsx`: a single-line `<input>` editor shown on every mission tab. Overview already shows the brief in full as markdown, and its Settings modal already edits the brief in a text area. A single-line input cannot hold line breaks, so saving a multi-line brief through it would flatten the text | Decided 2026-10-19 (D9): `InlineBrief` is deleted with the header, not moved. The brief stays visible on Overview and editable through Overview's Settings modal. |

### 2.2 Tokens and styling

| # | Handoff says | Fact | Correction |
|---|---|---|---|
| C9 | §6 uses `bg-active` (§6.4), `border-border-x` (§6.2), `border-border-card` and `border-row` (§6.6) | None of these is defined in handoff §2.2 | Map: `bg-active` → `bg-sidebar-active`; `border-border-x` → `border-border-strong`; `border-border-card` → `border-panel-border`; `border-row` → `border-border/60`. |
| C10 | PR1 "app keeps working, just recolours" | §2.2 replaces the global `fontSize` scale (`sm` 14→12.5px, `lg` 18→15px, `2xl` 24→22px) and `borderRadius` (`sm`, `md`); `CardTitle` changes size in §4.3 | Phase 1 resizes and re-rounds every screen. Its verification is a visual check of all routes, not just colour. |
| C11 | §10 QA bans `#[0-9a-f]{6}`, but §6.9 keeps per-type workflow colours from `workflow-editor-types.ts` | That file holds 44 hard-coded colour occurrences | Convert workflow step-type colours to the semantic tones (`brand`, `info`, `warning`, `success`, `danger`, `violet`, `neutral`). No exemption. |
| C12 | §3 defaults theme to `dark`; reads `localStorage` with `\|\| 'dark'` and `as Theme` | Doc 23: "Respect system preference by default". Constraint 7 forbids the cast fallback | Default to `prefers-color-scheme` (`dark` → `dark`, else `warm-white`) when nothing valid is stored, effective from Phase 12 (D1 re-timed: `dark` until then). Validate stored values against the theme list; remove invalid ones. Decided (D1). |
| C13 | §4.2 restyles `Badge` `default` + `outline` only | `badge.tsx` has `default`, `secondary`, `destructive`, `outline`, `success`, `warning`; `success`/`warning` use `emerald-500`/`amber-500`; 57 files import `Card` or `Badge` | In the same commit as the restyle, every state usage moves to `StatusPill`, and every remaining variant gets a token-based style. No variant may be left using palette classes. |
| C14 | §7 is "the single source" for colour maps | Colour maps and colour functions exist in `components/workspace/plan-board-types.ts` (`AGENT_DOMAIN_COLORS`, `getAgentDomainClass`, `getAgentBadgeClass`, the task-border function above them, and `edgeColor`, which returns `rgb()` literals), `components/workspace/plan-board-task-card.tsx` (`StatusIcon`), `pages/mission/tabs/chat-constants.ts` (`AGENT_ICONS`, `getAgentIcon`), `pages/mission/tabs/knowledge-tab.tsx` (`KIND_CONFIG`), `pages/mission/layout.tsx` (`STATUS_VARIANT`), `pages/mission/console.tsx`, `lib/event-utils.ts`, `components/workflow/workflow-editor-types.ts` | Create `lib/status-tone.ts` (statuses) and `lib/agent-tone.ts` (agent → icon + tone). `agent-tone` keeps today's resolution rule from `getAgentDomainClass` (first `.`-segment of the agent name) and today's fallback from `getAgentIcon` (`Bot`, `neutral`). Every function and map listed here is deleted once its callers use the new modules. One map per concept. |
| C34 | §4.5 `IconTile` tone `bg-{tone}/12`; §6.5 running bar `bg-warning/12` | Installed Tailwind is 3.4.19; its opacity scale is multiples of 5, so `/12` is not a class (and `bg-{tone}` built from a template is invisible to Tailwind and to the D8 lint rule) | Use `/10`. `IconTile` selects from a map of whole class literals per tone. |
| C35 | §6.9 node shadow `shadow-[0_1px_2px_rgba(0,0,0,.4)]` in dark, `shadow-sm` in light | An `rgba()` literal in a component breaks Constraint 4 | Define `--shadow-node` per theme in `src/index.css` and `boxShadow: { node: 'var(--shadow-node)' }` in `tailwind.config.js`; nodes use `shadow-node`. Colour literals live only in `index.css`. |
| C36 | §2.2 defines `violet` as a single token colour | Tailwind's built-in `violet` palette (`violet-400`, `violet-500/20` …) is replaced by a single colour, so existing `violet-*` classes stop matching and render nothing. 22 usages in 8 files, 6 of them inside string constants that `no-custom-classname` cannot see | Done in Phase 1.1: `violet-400` → `violet`, `violet-500/N` → `violet/N` across `src/`. The old/new CSS selector diff in §6.1.4 is the check that catches classes the lint rule cannot see. |
| C37 | §2.2 `fontSize`, `borderRadius` overrides | Confirmed in Phase 1.1: no class from the old build is missing from the new one after C36 (selector diff, 666 old vs 673 new) | No further action. |
| C38 | §6.5 "Drag-and-drop (`@hello-pangea/dnd`) unchanged", drop-target highlight `ring-2 ring-brand/30`; §10 parity "drag-and-drop still works" | There is no drag-and-drop anywhere: `@hello-pangea/dnd` is a dependency but no file imports it, and none did at the original baseline. Cards change status through their buttons | Nothing to preserve or restyle. Do not add drag-and-drop (out of scope). |
| C39 | §3 Phase 5.2 "call the same mutations the detail panel uses"; §6.4 "approve/reject from card and panel" | The detail panel never had Approve, Reject or Retry (it is read-only). The mutations are `useApproveTask`, `useRejectTask` and `useRetryTask` in `hooks/use-mission-plan.ts`, and the card was already their only caller | The card keeps calling them; the detail panel stays read-only. Nothing was added to it. |
| C40 | §6.6 Runs table has a "Workflow" column (`daily-brief`) | A run record has no workflow name. `roster_name` is `default` on 457 of 459 local runs; `objective_statement` is set on 457 and is what a run was asked to do. `task_type` and `temporal_workflow_id` are almost always null | The column is "Objective" (truncated, full text on hover). `ExecutionRecord` gained `objective_statement` (the list endpoint already returned it). |
| C41 | §6.7 Steps "2 / 7", Elapsed, Cost from the live store | The store starts at page open, so a run joined late or finished shows 0 cost and 0 steps. `plan.created` is typed with `step_count`, but the store reads a `tasks` list, and no emitter of that event exists in `modules/` | Cost and finished steps are the larger of the stream's count and the polled record's (both only rise). The step total is shown only when the stream supplied one; otherwise just the finished count. Elapsed comes from the record's `started_at`. |
| C42 | §6.9 "Palette P (`node-palette.tsx`)" is the left list of step types, `cursor-grab` | In the repo `node-palette.tsx` is the Space-key command search that pops over the canvas. Nothing in the editor supports dragging a type onto the canvas; steps are added by click (`handleAddNode`) | The left list is a new `step-palette.tsx` (click to add, no drag, as C38). `node-palette.tsx` stays as the command search and is restyled. Both read `STEP_TYPES`. |
| C43 | §6.8 workflow cards show a last-run `StatusPill`, cron in words and a workflow enable toggle (`workflows-panel.tsx:377`) | `MissionWorkflow` has no last-run field and no hook returns one; the list carries `trigger_type`, not a schedule; the "toggle at line 377" is the schedule on/off button, and a workflow has no enable switch | Cards show the enabled/disabled pill, version, step count and trigger. The `Switch` replaces the schedule toggle, whose rows already show `describeCronExpression`. No new query, no invented toggle. |
| C44 | §6.8 card actions "on hover" | Hover-only actions are invisible at rest and unreachable by touch; the empty Schedules text tells the user to "use the clock icon on a workflow" | Card actions (run, edit, schedule, delete) stay visible, in the card footer so the name keeps the full row. |
| C45 | §6.1 mission card shows a last-activity time | `MissionResponse` has no last-activity field; `updated_at` moves on any edit, not on work | The card shows `created {relative}`. A last-activity time needs a backend field (an aggregate over runs or events) and is not added here. |
| C46 | §6.3 Recent runs row shows the workflow name | Same as C40: a run record has no workflow name. | The row shows the run's objective, truncated, with the id, cost and relative time. |
| C47 | §6.3 Overview "environment" and setup cards unchanged | `environment-status-card.tsx` fell back to the literal image `code-workspace:latest` when the mission named none, and `setup-checklist.tsx` told the user to "click the brief area in the header", which D9 removed | The image fallback is gone (the card shows nothing for an unset image, per no hard-coded fallbacks); the hint reads "Open Edit and write a brief" and opens the Edit modal. |
| C48 | §6.0 dev quick login is shown with the sign-in form | The three buttons carry the seeded sysadmin, admin and user passwords, and a production bundle would ship them | See D13: the list is built only when `import.meta.env.DEV` is true. The production bundle was grepped for the passwords and the seeded emails: absent. |
| C49 | §6.13 "existing knowledge search (`use-knowledge-search`) → search input at the top of Learnings" | The Knowledge tab has no search input; `useKnowledgeSearch` has no caller on that screen. The tab has no promote control either; it only displays `platform_promoted`. | No input or control is added (a new feature, Constraint 3). The kind chips and the promoted icon are restyled. |
| C50 | §6.13 learning item shows recommendation as headline; recent-failure rows show task title and time | A recent-failure item carries `task_id`, `agent_name`, `failure_tier`, `failure_reason`, `feedback_provided`, `domain_tags`: no title or time. A learning's recommendation and evidence run to many lines. | A failure row shows agent, reason and task id; a learning shows its title with a two-line preview and the full Recommendation and Evidence when opened. |
| C51 | §6.12 section header "by {agent} · {time}"; history row "+1.2 KB" and agent icon | The context document has no per-section author or time and a change record has no size delta. | Section headers show an item count only; the document-level "Updated by" stays in the description line; history rows show the change type's icon and tone, the path, the reason and `v{n} · time`. The bar value is the backend's `pct_of_max` (the same number as `size_characters / max_characters`, C22), with the handoff's 50 and 85 thresholds. |
| C52 | §6.14 artifact rows show a size; Copy and Download "unchanged" | The artifact record has no size field. The old viewer had neither Copy nor Download. | No size is shown. Copy and Download are built because the handoff specifies them and `content_text` supports both. The filter input is also new, from the handoff, and filters the loaded list in the client by title or agent. |
| C53 | §6.15 Console event detail as a right-hand panel (`event-log-panel.tsx`) | That panel was dead code and was deleted (defects table). Detail was always inline under a row. | A click opens the same inline detail under the row; the rich per-type rows are folded into it and every row is one mono grid row. The Live indicator and event count moved from the bottom footer into the toolbar. Accepted trade-offs of that grid: a row shows the raw event type (an error the emitter sends as `system.info` reads "system.info" in red, with its message beside it) and model and cost appear when a row is opened. |
| C54 | §6.16 Costs shows the budget "of $500 budget" for every range | The ceiling is measured against all-time spend. | The budget line shows only on All time and only when the mission has a ceiling. The old "Output Ratio" card is dropped for the four cards the handoff lists; each flagged agent keeps its ratio in the efficiency callout; Most expensive calls is kept. |
| C55 | §6.17 Catalog cards carry "Add to mission" or "On team"; type segments All / Director / Specialist / System | `/catalog` has no mission context and no add action (its one action is Details, which opens the agent-detail drawer); the API's types are `vertical`, `horizontal` and `supervisor`. | No add action is built (a new feature). The segments are the types the data has, with counts. Keywords stay searchable but are not shown; tool pills show four tools and "+N". |
| C56 | §6.19 Profile has a "Notifications" section | The page has no notification settings; the only notification UI is the bell in the sidebar footer. | No Notifications panel (it would be dead). Profile has Account (display name and password), Appearance (the theme `Segmented`, bound to the theme store) and API keys. |
| C57 | §6.18 Metrics shows a Users card and an Agent utilisation chart; Health statuses | The overview returns counts for missions, sessions, execution records, workflow runs and agents, and `total_cost_usd`, but no user count and no utilisation percentage. The health service reports `healthy`, `unhealthy` and `not_configured` per component and `healthy` or `degraded` overall. | No Users card. Utilisation bars are run counts against the busiest agent. Health statuses map to success, danger, neutral and warning; an unknown status throws through `styleFor`. |
| C58 | §6.18 Admin catalog has no layout in the handoff | It says only that tables follow the Runs table pattern. | A Panel table with the Switch (the enable toggle), type, version and model columns, with edit and prompt editors as before. Delete still has no confirmation (it had none). |
| C33 | §6.11 Narrative `Segmented` All / Agents / Runs / Decisions | `narrative-tab.tsx:38-49` filters by a persisted set of hidden event types (`mc:narrative-hidden-types`); there is no Agents/Runs/Decisions categorisation | Keep the existing hidden-types filter and its storage key. Restyle its controls with `FilterChip` (§2.4). The four-way segment would be a new feature; it is out of scope. |

### 2.3 Data contracts

| # | Handoff says | Fact | Correction |
|---|---|---|---|
| C15 | §7 `taskTone` has `proposed, approved, running, completed, failed, skipped, vetoed` | Real `TaskStatus` (`modules/backend/models/task.py:48-55`, `PlanTaskStatus` in `hooks/use-mission-plan.ts`): `proposed, approved, queued, running, completed, failed, skipped, cancelled`. There is no `vetoed`. | `taskTone`: proposed `neutral`, approved `brand`, queued `brand`, running `warning`, completed `success`, failed `danger`, skipped `neutral`, cancelled `neutral`. Type it as `Record<PlanTaskStatus, Tone>` so a new status fails compilation. |
| C16 | §6.5 gate `Segmented` has Manual / AI-assisted / Autonomous | `VALID_GATE_MODES` (`modules/backend/models/mission_plan.py:48`) and `GateMode` (`hooks/use-mission-plan.ts:29`) have four: `interactive`, `manual`, `ai_assisted`, `autonomous` | Four segments: Interactive / Manual / AI-assisted / Autonomous. |
| C17 | §7 `missionTone` keys | `MissionStatus` = `active, paused, archived` (`types/mission.ts:8`) | Matches. Type as `Record<MissionStatus, Tone>`. |
| C18 | §6.5 board columns | `COLUMN_DEFS` (`plan-board-types.ts`) already put `queued` in Approved and `completed, failed, skipped, cancelled` in Done | Keep `COLUMN_DEFS`. Restyle only. |
| C19 | §6.16 Costs range: 7 days / 30 days / All time | `costs-tab.tsx:12-14` and the API support `24h`, `7d`, `30d`, all-time | Four segments: Today / 7 days / 30 days / All time. |
| C20 | §6.16 stat "Avg per call (−8% vs prior)" | The costs endpoint (`api/v1/endpoints/missions_costs.py`) returns `summary`, `by_agent`, `cache_performance`, `output_efficiency`, `expensive_calls`; no prior-period figure | Show only fields the response contains. Drop the "vs prior" delta. |
| C21 | §6.7 Run live summary shows Tokens | `stores/live-run.ts` tracks cost per agent, not tokens | Show Elapsed, Cost, Steps. Show Tokens only if the run response already contains a token total; verify before implementing, never estimate. |
| C22 | §6.12 Context size "18.4 / 32 KB" | `hooks/use-context.ts` returns `size_characters`, `size_tokens`, `max_characters`; `context-panel.tsx:50` already renders KB from characters | Keep the existing computation and fields. Bar = `size_characters / max_characters`. |
| C23 | §6.14 artifact groups: Reports, Findings, Responses, Data, Code | `ArtifactType` = `report, finding, response, code, data, file` (`hooks/use-mission-artifacts.ts:22`) | Six groups; add Files (`File` icon). |
| C24 | §6.13 learning kinds | `KIND_CONFIG` keys match: `failure_pattern, success_pattern, anti_pattern, retry_strategy, capability_gap` | Matches. Move the map to tokens. |
| C25 | §9.3 needs a new `useAgentStates` selector | `stores/workspace.ts` already holds `agentStatuses: Record<string, AgentStatusEntry>` with `idle, thinking, running, done, failed` and `currentTool` | Use the existing store selector. No new hook. |
| C26 | §6.10 Team card has an enable/disable `Switch` | `MissionTeamMember.enabled` exists and dispatch honours it (`agents/mission_control/roster.py:114` lists `enabled_only=True`). `MissionTeamService.toggle_enabled` (`services/mission_team.py:286`) exists but no endpoint calls it, and `hooks/use-team.ts` has no mutation. `GET /missions/{id}/team` defaults to `enabled_only=True` and `useTeam` does not override it, so a disabled member disappears from the Team page and could never be re-enabled | Decided (D6): build the switch. Backend in §3.3, frontend in Phase 10.1. |
| C27 | §6.2 New mission has a "1 Details — 2 Team" stepper | `pages/mission/new.tsx` has no team step | Per the handoff's own fallback: single step, no stepper. |
| C28 | §6.5 "+ Add task" row per column | `AddTaskForm` exists in `plan-board-task-card.tsx:500-584`, wired to `useAddPlanTask` | Reuse it. Move it to its own file (`plan-board-add-task.tsx`) so the card file shrinks below its current 584 lines. |
| C29 | §9.1 attention items, "or derive client-side (N calls)" | No backend endpoint exists. Client derivation is aggregation in the client, against Constraint 1 | Build the backend endpoint (Phase 8). No client-side derivation. Decided (D3): build it. |
| C30 | §9.2 `spent_usd` on mission list | `MissionResponse` (`schemas/mission.py:97`) has `budget_ceiling_usd` but no spend; plans carry `total_spent_usd` per plan | Add `spent_usd` to the mission list response from a backend service (Phase 8). |
| C31 | §5.2 search / ⌘K trigger, "otherwise a TODO stub" | No command palette exists | Omit the search box (Constraint 3). Decided (D4). |
| C32 | §5.2 optional `NAV_STYLE = 'sidebar' \| 'tabs'` | Not required by any screen | Do not build it (no extra features). Decided (D5). |

### 2.4 Existing code to reuse — do not recreate

The handoff asks for several things the tree already has. The implementing agent promotes or
reuses these; it does not write a second version. "Promote" means move the existing code to
the shared location, update every caller, and delete the original.

| Need in the handoff | Already exists | Action |
|---|---|---|
| Task status icon in columns, cards, timelines | `StatusIcon` in `plan-board-task-card.tsx:78` | Promote to `components/ui/status-icon.tsx`, driven by `lib/status-tone.ts` (status → tone + lucide icon). Runs table, Run live timeline and plan columns all use it. No per-screen icon switch. |
| Icon buttons (Reject `X`, History, Trash) | `IconButton` in `plan-board-task-card.tsx` (palette-coloured `tone` prop) and a second private `IconButton` in `workflows-panel.tsx:585` | Delete both. Use `Button` `size="icon"` / `"icon-sm"` (task card in Phase 5.2, workflows panel in Phase 7). |
| Filter chips (Runs filters, Knowledge filters, Narrative) | `FilterChip` in `knowledge-tab.tsx:329` | Promote to `components/ui/filter-chip.tsx`, restyled per handoff §6.6, with optional `count`. |
| `Segmented` control | Hand-rolled segment groups: console category tabs (`console.tsx:124` `FilterBar`), Costs timeframe buttons (`costs-tab.tsx:50`), plan gate `<select>` (`plan-board-top-bar.tsx:113`) | Create `components/ui/segmented.tsx` once and replace all three in their phases. |
| Confirmation before Archive / Delete | `ConfirmDialog` in `pages/dashboard.tsx:23`, private; the only confirm dialog in the frontend | Promote to `components/ui/confirm-dialog.tsx` in Phase 3.3, where the settings-drawer Archive becomes its second caller. |
| Hover `⋯` menus (dashboard cards, plan cards) | Inline menu with click-outside in `plan-board-task-card.tsx:154-167` | Promote to `components/ui/menu.tsx`. |
| Click-outside handling | Duplicated in `notification-dropdown.tsx`, `plan-board-task-card.tsx` and `variable-autocomplete.tsx` (`slash-command-popover.tsx` only matched on its `onMouseDown` prop; it has no click-outside code) | Extract `hooks/use-click-outside.ts` when `menu.tsx` is created (third+ use, P14). Migrate each file in the phase that touches it. |
| Cost formatting | `toFixed(4)` inlined 40 times for per-call and per-task costs (`$0.0412`), `toFixed(2)` for totals and budgets (`$212.40`) | `fmtCost` (4 decimals) and `fmtUsd` (2 decimals) in `lib/format.ts` (added in 2.2); replace inline formatting in every file a phase restyles. |
| Durations and elapsed time | `formatDuration` (`workflow-run-history.tsx`), `formatElapsed` (`live-footer.tsx`) | Moved to `lib/format-date.ts` in Phase 2.2. `runs-panel.tsx:204` still computes a duration inline; use `formatDuration` when Phase 6 restyles it. |
| Relative time ("2h ago") | None; `date-fns` is already a dependency but unused | Added `formatRelative` to `lib/format-date.ts` in Phase 9 with its first callers. It does not use `date-fns`: `formatDistanceToNow` returns "about 4 months ago", and the handoff's rows are `4mo ago`. `date-fns` is still unused. |
| Cron in words (§6.8) | `describeCronExpression` in `lib/cron.ts:150` | Use it. |
| User avatar initials (sidebar footer) | `components/ui/avatar.tsx` | Restyle and use it. |
| Plan Stop/Resume (§5.3, §6.5) | `handlePlanPauseToggle` in `plan-board-top-bar.tsx:70`; a duplicate in `layout.tsx:128-136` | Keep the toolbar one, restyle it, delete the `layout.tsx` copy (Phase 3.3). |
| Live agent state (§9.3) | `useWorkspaceStore` `agentStatuses` (C25) | Use it. |
| Error reporting from client code | `reportError` in `components/error-boundary.tsx:13` (posts to `/client-errors`), private | Export it; the theme store uses it on storage failure. |
| Polling while work is active | `refetchInterval` callback pattern in `use-executions.ts:38` | Follow the same pattern in `use-attention.ts`. |
| Mission spend aggregate (§9.2) | `TokenEconomicsService.get_summary(mission_id=…)` sums `llm_calls.cost_usd` through `_scope_filters`; it is the figure the Costs tab shows | Add one grouped method to the same service (§3.1). No new repository query path. |
| Pending gates / human input (§9.1) | `MissionPlanService.list_pending_gate_requests(mission_id)` (`services/mission_plan.py:237`), `WorkflowRunService.list_pending_human_input(mission_id)` (`services/workflow_run.py:721`); each has exactly one caller (`missions_gates.py:122`, `missions_workflows.py:870`) | Change each signature to `mission_ids: list[str]` and update its one caller to pass `[mission_id]`. No single-mission wrapper (P3: no shims). |
| Tasks by status (§9.1) | `TaskRepository.get_by_mission_id(mission_id, status=…)` (`repositories/task.py:65`) is single-mission and cross-plan, so it would return failed tasks from archived plans | Add one repository method, `list_by_status_for_missions(mission_ids, statuses)`, joined to `mission_plans` and limited to plans in `active` or `paused` status. `get_by_mission_id` stays as is for its existing callers. |
| Progress bars | Inline bars in `plan-board-top-bar.tsx:166` (budget) and `context-panel.tsx:52-61` (context size) | `components/ui/progress.tsx` replaces both in the phases that restyle those files. |
| Enable toggles | Button-style toggles in `workflows-panel.tsx:377` (workflow enabled) and `pages/admin/catalog.tsx:76` (catalog agent enabled) | `components/ui/switch.tsx` is created in Phase 7 with its first caller (`workflows-panel.tsx`) and reused by Team (10.1) and Admin catalog (11.2). One toggle style. |
| Shared attention data | Dashboard list and sidebar badges both need it | One `use-attention` query key; TanStack Query deduplicates, so the two consumers make one request. |

---

## 3. Backend Data (only backend scope in this plan)

Two read-only additions (§3.1, §3.2) and one write endpoint (§3.3). All follow Constraint 10
and reuse existing services (§2.4).

**3.1 Mission spend.** `MissionResponse` gains `spent_usd: float` (never null; 0.0 means no
calls recorded). Add `TokenEconomicsService.get_cost_by_mission(mission_ids: list[str])`, built
on the existing `_scope_filters` with an all-time scope, returning `{mission_id: total}` from one
grouped query. `MissionResponse` is returned by four endpoints in `api/v1/endpoints/missions.py`
(create, list, get, update: lines 77, 112, 136, 206). Add one `MissionService` method that
takes missions and returns their responses with `spent_usd` attached, calling
`get_cost_by_mission` once; all four endpoints use it, so no path returns a response without
the field. The list endpoint therefore issues one cost query per page. Do not use
`ExecutionPersistenceService.get_cross_mission_cost_breakdown()`: it sums
`execution_records.total_cost_usd`, a different source from the Costs tab, so the two screens
would disagree. Decided (D7): `spent_usd` is the `llm_calls` total.

**3.2 Attention items.** New `GET /api/v1/attention` returns, for missions the current user can
access:

```
{ mission_id, mission_name, kind: 'task_approval' | 'gate' | 'human_input' | 'retry',
  title, detail, created_at, href }[]
```

- `task_approval`: tasks in `proposed`, in an active or paused plan whose gate mode needs a
  human to approve (via `list_by_status_for_missions`, §2.4).
- `gate`: pending `GateRequest` rows, via the generalised `list_pending_gate_requests`.
- `human_input`: pending `HumanInputRequest` rows, via the generalised
  `list_pending_human_input`.
- `retry`: tasks in `failed`, in an active or paused plan. Failed tasks in completed or archived
  plans are not attention items.

`href` is built by the backend so the client renders it without logic. The response also returns
per-mission pending counts for the sidebar badge. Every list is fetched for all accessible
missions in one query per kind, never per mission.

Which gate modes need a human is defined today only as a private tuple,
`_AUTO_APPROVE_GATE_MODES = ("ai_assisted", "autonomous")`, in
`agents/mission/director/tools/approve_plan_tasks.py:26`. A service must not import a private
constant from an agent tool. Move it to `models/mission_plan.py` as `AUTO_APPROVE_GATE_MODES`
next to `VALID_GATE_MODES`, import it in `approve_plan_tasks.py` and in the attention service,
and delete the private tuple. Note for the owner, not part of this plan:
`api/v1/endpoints/missions_workflows.py:306` uses a different grouping
(`("manual", "interactive", "ai_assisted")`) for workflow dispatch.

**3.3 Team member enable/disable (D6).** New
`PATCH /api/v1/missions/{mission_id}/team/{member_id}/enabled` with a typed request schema
`TeamMemberEnabledUpdate { enabled: bool }` in `schemas/mission_team.py` (not `data: dict`).
The endpoint calls `require_mission_access`, then `MissionTeamService.get_member` and rejects
with `NotFoundError` if the member's `mission_id` is not the path's `mission_id`, then calls the
existing `toggle_enabled`. It returns `MissionTeamMemberResponse` in `ApiResponse`. No new
service method. Note for the owner, not part of this plan: the existing
`PATCH …/team/{member_id}/constraints` (`missions_team.py:236`) and `PUT …/prompt` do not check
that the member belongs to the mission in the path.

---

## 4. Phases

Each sub-phase is one commit. Each commit passes every gate in §6 before it is made.

### Phase 0 — Green baseline

**0.1 Fix the three lint warnings.**
- `components/workspace/plan-board-task-card.tsx:54` — `react-refresh/only-export-components`:
  move the non-component export to `plan-board-types.ts`.
- `pages/mission/tabs/chat-conversation.tsx:57` — `agentTools` is rebuilt every render and
  breaks the dependency arrays of the `useMemo` (line 65) and `useCallback` (line 191).
  Wrap its initialisation in `useMemo`.
- Done when `npm run lint` exits 0 and `npm run build` succeeds.

### Phase 1 — Tokens, fonts, theme (handoff §2, §3)

**1.1 Tokens and Tailwind.**
- Replace `src/index.css` token blocks with handoff §2.1 values, keeping the shadcn variable
  names. Apply C6 (no font `@import` in CSS; drop the `body` font-family override).
- Replace `tailwind.config.js` `theme.extend` with handoff §2.2, applying C9 (no class used in
  §6 may be missing from this config).
- Install `@fontsource/geist-mono`; import 400 and 500 in `src/main.tsx`.
- Decided (D8): install `eslint-plugin-tailwindcss` (a release whose peer range covers
  Tailwind 3.4 and ESLint 8; confirm at install) and enable `tailwindcss/no-custom-classname`
  as an error in `.eslintrc.cjs`, pointed at `tailwind.config.js`, with no whitelist entries.
  Do not enable the plugin's other rules (class ordering would reformat every file). Fix any
  existing violations it reports in this commit; if the count is large, list them in the
  commit message and fix them all before committing — `npm run lint` must exit 0.
- Done when every existing screen renders in both themes with no unreadable text. Because of C10,
  check every route.

**1.2 Theme switching.**
- `index.html` boot script is the single place the initial theme is validated and applied
  (it must run before first paint). A stored value that is not a known theme is removed. When
  nothing valid is stored the default applies. Per D1 as re-timed below, the default is `dark`
  until Phase 12, which replaces it with the `prefers-color-scheme` result (`dark` OS → `dark`,
  otherwise `warm-white`). If `localStorage` is unreadable it sets `window.__mcThemeStorageError`.
- `src/stores/theme.ts` (new): `Theme = 'dark' | 'warm-white'`, `THEMES`, storage key
  `mc.theme`. It reads the applied class from `<html>` instead of resolving the theme a second
  time, and throws at start-up if no theme class is present (boot script missing or out of
  sync). `setTheme` applies the class, persists, and reports a write failure through
  `reportError`, exported from `components/error-boundary.tsx` (§2.4). Reads the boot error
  once and reports it.
- `App.tsx` Toaster: handoff §3.4 classes.
- The toggle button itself ships with the sidebar footer (Phase 3.2) and Login (Phase 9.1).
  Until then the store has no importer by design.
- Done when reload keeps the chosen theme and an invalid stored value is replaced. Verified by
  a 12-case browser test run against the dev server (default, persisted theme, invalid value
  removed, class set before DOMContentLoaded, toggle/setTheme, storage unreadable reported once,
  store fails fast without the boot script).

### Phase 2 — UI primitives (handoff §4)

**2.1 Tone maps (done).** `lib/status-tone.ts` defines the one `Tone` type
(`success | warning | danger | info | brand | violet | neutral`) and, per C15–C17, `missionTone`,
`taskTone`, `runTone` and `consoleCategoryTone` (`execution`, `chat`, `system` — the categories
`layout.tsx:87-103` produces), each mapping a status to `{ tone, icon }`. Primitives import
`Tone` from here; `lib` never imports from `components`. `lib/agent-tone.ts` per C14. In this
sub-phase the new modules replace `getAgentIcon` and `AGENT_ICONS`; the plan-board functions
are replaced in Phase 5.2, where their callers are restyled.

**2.2 New primitives and promotions (done).** Built now, each with a caller in this phase:
`status-pill.tsx` (first caller: 2.4), and the promotions from §2.4 — `status-icon.tsx`,
`filter-chip.tsx`, `menu.tsx` with `hooks/use-click-outside.ts` — plus the `fmtCost` / `fmtUsd`
helpers in `lib/format.ts` and `formatDuration` / `formatElapsed` in `lib/format-date.ts`. Each
promotion updated its original callers in the same commit and deleted the original. Every other
primitive is built with its first caller, so nothing lands unused and unverified: `icon-tile.tsx`
and `kbd.tsx` in Phase 4, `progress.tsx` and `segmented.tsx` in Phase 5.1, `switch.tsx` in
Phase 7, `formatRelative` in Phase 9.2. Each new primitive has typed props (interfaces named
`<Component>Props`, doc 23) and `aria-label` support where icon-only. `IconTile` takes
`{ icon, tone }`, exactly what `agent-tone` returns, so callers pass the result through without
mapping.

**2.3 Restyle existing primitives (done).** One name per concept, no aliases (P3: no shims, no legacy
aliases). The handoff's `Card = Panel` aliases and its `outline` alias of `secondary` are not
built:
- `button.tsx` per handoff §4.1: `default`, `secondary`, `ghost`, `destructive` (tinted), `link`;
  sizes `sm`, `default`, `lg`, `icon`. `outline` is deleted. `variant="outline"` exists on both
  `Button` and `Badge`; only the 26 `Button` uses changed (an AST codemod, not a text replace —
  the other 40 are `Badge`, which keeps `outline`; the "63 call sites" in earlier versions of
  this plan wrongly counted both). The handoff's `pill` and `xl` variants and `icon-sm` size are
  added with their first callers (Phases 4, 9.1, 5.2).
- `card.tsx` became `panel.tsx` exporting `Panel`, `PanelHeader` (title / meta / actions, §4.3)
  and `PanelContent`. 15 files migrated (37 cards) by one agent per file, each checked by a second
  reader; `StatCard` was rewritten by hand; `card.tsx` is deleted and no `ui/card` import remains.
- Restyled `input.tsx`, `textarea.tsx`, `stat-card.tsx`, `empty-state.tsx`, `spinner.tsx`,
  `avatar.tsx`. `EmptyState` keeps a plain icon wrapper until `IconTile` exists (Phase 4).
Remove `mr-1.5` from icons inside `Button` at call sites only when the file is otherwise touched.

**2.4 Badge migration (done).** `badge.tsx` is restyled and accepts only `default` and `outline`, so
the type checker fails on any site using a removed variant. 103 `Badge` sites in 41 files became 99
elements: 32 `StatusPill` (states) and 67 `Badge` (labels); the totals differ because some sites
were merged when their conditionals were rewritten (not itemised). Rules applied: a state (status, health, severity, live, enabled, revoked, success/error
outcome) is a pill, tone-mapped success→success, warning→warning, destructive→danger,
secondary→neutral; a label (type, version, count, tag, model, engine, artifact type, event type
name) is a `Badge`. Colour-coded labels (blue model, green engine, purple thinking budget) lost
their colour rather than become pills with no state. Run and mission statuses use the shared
`runTone` / `missionTone` maps, with `styleFor` throwing on an unknown value.

Findings from the verifier pass that changed the code: task executions end as
completed/failed/skipped (`TaskExecutionStatus`), a different set from a run's own status, so the
runs panel uses `taskTone` for them (`runTone` has no `skipped` and would have crashed the detail
panel); only `success` / `error` events are states in the run-detail event log, while `start` /
`decision` are event-type labels; only the `run_failed` and `gate_approval` notifications carry
severity, the other notification types are labels.

Known consequence: `styleFor` throws at render on a status it does not know. The only error
boundary is the one around the whole app (`main.tsx`), so an unexpected status from the API shows
the app-level error screen rather than failing one panel. Today every status the backend can emit
is covered. Follow-up for the owner, not in this plan: a per-panel error boundary.
Also left for later phases: `live-footer.tsx` keeps its own status map (deleted in Phase 6), and the
label badges in the warm-white console are faint on its fixed dark scrim (Phase 10.6).

### Phase 3 — Shell (handoff §5)

**3.1 AppShell (done).** Handoff §5.1 layout, keeping `RightDrawer` (C5): it renders as a right
Panel inside the gutter (`rounded-panel bg-panel border border-panel-border`, 400px, 8px inset),
not a full-height `border-l` strip. `main` stays a scrolling column on the `bg-well` surface until
every page has its own top bar and scroll container (the shell's `overflow-y-auto` is removed in
Phase 12 once the last page is migrated; `TopBar` is `sticky` so it works either way).
`StatusBar` stays in this commit and is deleted in 3.2, in the commit that moves its run indicator
into the sidebar footer, so the indicator is never missing.
Known transitional effect (reviewed, accepted): in warm-white the well is darker than the old page
surface, so elements not yet rebuilt as panels read as sunk — the mission header and tab bar (replaced
in 3.3), dashed empty-state and template boxes (Phase 7), and unselected filter chips and the intent
callout (Phase 10.4). Text stays legible throughout.

**3.2 Sidebar (done).** Rewrite per handoff §5.2 with C31 (no search box) and C32 (no tab option).
Split to stay under 300 lines: `sidebar.tsx` (frame, primary nav, missions list) and
`sidebar-footer.tsx` (run indicator from `useExecutions({ status: 'running' })`, which today
feeds `StatusBar`; user row with `Avatar`; `NotificationDropdown`, restyled and migrated to
`use-click-outside`; theme toggle; log-out). Delete `StatusBar` here. The sidebar is the same 236px
everywhere (the 48px rail is removed); inside a mission it shows the missions list, and the
mission tab bar stays in the mission layout until 3.3. The per-mission pending badge waits for
Phase 8 and is added in Phase 8.3.
Built: the run indicator links to the longest-running run and shows its elapsed time; `parseUtc` was
extracted into `lib/format-date.ts` (it replaced the same UTC-suffix fix copied into `formatUtc` and
`formatUtcTime`). The notification popover is anchored `left-0` so it cannot clip off the screen
edge in the narrower footer, and shows an unread dot instead of a count (handoff §5.2).
Known effect, reviewed: inside a mission the sidebar is 236px (was a 48px rail), so the conversation
column in Chat is narrower; Phase 4 must wrap long unbroken strings (URLs) in message bubbles
(`overflow-wrap: anywhere`), which the narrower width exposed.

**3.3 Top bar and mission layout (done).** `components/layout/sidebar-mission-nav.tsx` (grouped sub-nav
for the active mission, from `lib/constants.ts`) arrives in this commit, together with the removal
of the tab bar, so there is never both or neither. `components/layout/top-bar.tsx` (new) per
handoff §5.3.
It is generic: props are `segments: { label, to? }[]`, an optional `status` node and an
`actions` node. It contains no mission logic, so Dashboard, Catalog, Admin and mission pages
all use it. In `pages/mission/layout.tsx`: remove the header and tab bar, render `TopBar`, keep
the SSE fan-out, `MissionSettingsDrawer` and `RunModal` unchanged in behaviour. The plan pill
uses `plan.status`, `plan.gate_mode` and task counts already loaded by `useMissionPlan`.
`missions/:id` must still redirect to the last tab (`App.tsx:42-52`).

Every action the old header held must have its new home **in this same commit**, so nothing is
unreachable between commits:
- Pause / Resume mission and Run: in `TopBar` actions.
- Archive: `MissionSettingsDrawer` has no archive or status control today; add an Archive
  action to it, calling the existing `useUpdateMission` with `{ status: 'archived' }` after
  the same confirmation the Dashboard asks for. Promote `ConfirmDialog` (§2.4) in this commit
  and point `dashboard.tsx` at the shared copy.
- Stop / Resume plan: delete the header copy (`layout.tsx:128-136`, `350-363`); the Plan
  toolbar's `handlePlanPauseToggle` already does this.
- Brief: `InlineBrief` is deleted (C8, D9). The brief stays on Overview and is edited through
  Overview's Settings modal.
- Background-task indicator: fold into the plan pill tooltip (handoff §5.3).

Done when every mission route renders with the new shell and every former header action is
reachable.

Built: `TopBar` (generic, `sticky`), `MissionTopBar` (status and tier pills, plan/background-task pill,
owner-only Pause/Resume, settings, Run), `SidebarMissionNav`, `MISSION_NAV_GROUPS` and three new
`ROUTES` entries in `lib/constants.ts`, `lib/plan-progress.ts` (tasks completed out of tasks not
cancelled), the shared `ConfirmDialog` (now token-styled and Escape-aware; its palette-coloured
buttons became `Button` variants) and `ArchiveMissionButton`. `layout.tsx` went from 511 to 232 lines;
the settings drawer did not grow (394 lines, was 395). Browser-tested with 25 checks; no write
request was sent during the test.

Found by the before/after review and fixed: the old header showed "Resume Plan" on every tab while a
plan was paused, so a paused plan became invisible outside the Plan tab. The control stays on the Plan
toolbar by design; `MissionTopBar` now shows a quiet "Plan paused" pill on every tab that links to the
Plan tab, so the state is never hidden.

### Phase 4 — Chat (handoff §6.4) (done)

Restyled `chat-tab.tsx`, `chat-conversation.tsx`, `chat-artifacts-panel.tsx` and the slash-command
popover as three floating panels (roster, conversation, outputs). Live agent state in the roster comes
from `useWorkspaceStore` `agentStatuses` (C25): the second line shows the current tool in mono
(running), `thinking…`, `Done`, `Failed`, `Mission lead`, `Idle` or `Task agent`, and the tile gets a
live dot while an agent is working. Sessions, `chat/:threadId`, slash commands and ⌘↵ send are
unchanged. Built here with their first callers: `components/ui/icon-tile.tsx`,
`components/ui/kbd.tsx` and the Button `pill` variant ("New thread").

Refactor that made the file shrink instead of grow: the 17 near-identical event rows in
`chat-conversation.tsx` became a table-driven `chat-events.tsx` (`EventLine`, `EventBox`,
`InlineNarrativeRow`), and `MessageBubble` moved to `chat-message.tsx` with a shared `AgentMessage`
layout used by sent and streaming messages. `chat-conversation.tsx` went from 674 to 324 lines;
`chat-tab.tsx` from 390 to 342. A new `lib/tone-class.ts` holds the tone → class maps (text, dot,
tinted box) so the sidebar, `StatusIcon`, `IconTile` and the event rows share one copy.
Long unbroken strings (URLs, tokens) wrap with `overflow-wrap: anywhere`, which fixes the exposed
case from Phase 3.2; verified with a 200+ character URL measured on the message scroller. (A first
measurement selected the outer page wrapper, which always fits, and proved nothing; it was redone on the
real scroller.)

Two corrections to the plan's earlier text: `slash-command-popover.tsx` has no click-outside code (it
only uses `onMouseDown` on its items), so there was nothing to migrate there; and `Conversation` is
also rendered inside the workflow editor's Architect panel (380px), so it must keep working in a
narrow container (verified; the Architect chat creates a session when opened, which the test answered
with a fake so nothing was written).

Browser-tested with 26 + 7 + 6 checks (header, roster, agent switching, slash popover, ⌘↵ send against
a faked stream, outputs collapse and resize, breakpoints at 1100 and 900 px, every event type, live roster
state, overflow, Architect panel). Not exercised because it writes: creating a thread, sending to a real
model.

### Phase 5 — Plan board (handoff §6.5) (done)

Built as one commit: `progress.tsx`, `segmented.tsx` and the Button `icon-sm` size
(first callers: the toolbar and the cards), the toolbar, the columns and cards, the detail panel, and
`plan-board-add-task.tsx` (the add-task row, split out of the card file). `plan-board-task-card.tsx`
went from 498 to 324 lines and `plan-board-top-bar.tsx` from 391 to 331; `AGENT_DOMAIN_COLORS`,
`getBorderClass`, `getAgentDomainClass`, `getAgentBadgeClass` and the card's private `IconButton` are
deleted, and `edgeColor` returns `hsl(var(--token) / alpha)` strings. The Plan tag pill that clipped its
last letter (§5) is gone with the old card.

Deviations from the handoff:

- "+ Add task" appears only in the Proposed column. New tasks are always created as proposed, so a row
  in the other columns would put the task somewhere else.
- The button reads "Refine plan", not "Refine with Director": it calls the Planning Agent, not the
  Director.
- A card shows a status icon only for failed, skipped and cancelled. The column already says the rest.
- Dependency curves are drawn above the column panels (they would be hidden by the opaque panels
  otherwise) and below the cards (`z-30`; `z-40` on hover or focus so an open menu stays on top), so
  they show in the gaps and never cross card text. The handoff draws no curves.
- Card buttons stop propagation, so Retry no longer also opens the detail panel (it did before).
- The toolbar fits one row at 1440 px; below that it wraps rather than clipping.

Browser-tested with 32 checks, every write intercepted: toolbar, gate selector, progress and budget,
four columns, 1,160 curve paths on theme tokens, pause/resume, refine, add task, retry, detail panel
open and close, fabricated proposed, approved-with-veto and running cards (Approve, Reject, Veto, Stop),
the Run approved dialog, no overflow at 1100 px. Not exercised because they write: approve, reject,
retry, run and add against real data.

**5.1 Toolbar.** `plan-board-top-bar.tsx`: create `components/ui/progress.tsx` and use it for
the budget bar at line 166; replace the `<select>` with a four-segment
`Segmented` (C16). Restyle the existing `handlePlanPauseToggle` button as Stop plan
(destructive tinted) / Resume plan. Replace the inline `toFixed(4)` with `fmtCost`.

**5.2 Columns and cards.** `plan-board.tsx`, `plan-board-task-card.tsx` per handoff §6.5 with
C18 and C28. Inline Approve/Reject on proposed cards and Retry on failed cards call the same
mutations the detail panel uses — find them in `hooks/use-mission-plan.ts` and reuse; add none.
Veto countdown uses the existing `VetoState`. The board has no drag-and-drop: `@hello-pangea/dnd` is
installed but imported nowhere, now or at the original baseline, so task status changes only through
the card buttons (C38). Replace
`getAgentDomainClass`, `getAgentBadgeClass` and the task-border function with
`agent-tone` / `status-tone`, and `edgeColor`'s `rgb()` literals with
`hsl(var(--token) / alpha)` strings; then delete the old functions and `AGENT_DOMAIN_COLORS`.

**5.3 Detail panel.** `plan-board-detail-panel.tsx` as a right Panel inside the gutter.

### Phase 6 — Runs and Run live (handoff §6.6, §6.7) (done)

**Runs.** `runs-panel.tsx` is now filter chips (`FilterChip`: All, Running, Completed, Failed, with counts) above one `Panel`
table (Status, Run, Objective, Started, Duration, Cost; C40). A row opens on click, Enter or Space and expands to
`run-row-detail.tsx` (metrics, objective, tasks, decisions, artifacts, and the Events/Output/Cost buttons, which now show which
view is open; before, both branches of that ternary were `secondary`). An in-flight row shows a ticking duration, a Live link
to the run page and a Cancel button; its Live link stays reachable because the row itself toggles. Counts are of the 50 rows
the page loads, so a note says "Showing the latest 50 of 59 runs." when there are more (the 50-row limit is pre-existing).
`run-detail-panel.tsx` is a floating, resizable `Panel` that appears only when a view is opened; before, an empty
"Details" column was always there. `runs-tab.tsx` lays the page out as a document column plus that panel.

**Run live.** `live-summary.tsx` replaces the header bar and `live-footer.tsx` (deleted): objective, short id, Elapsed, Cost,
Steps, tokens when the run's recorded outcome has them (C21; input and output as recorded, never estimated), the Live or status pill, the two panel toggles and Cancel run (C41). The
activity panel is a vertical timeline (planning, every event, the agents working now), the results panel one block per
finished task. The back arrow is gone; the breadcrumb already links to Runs. `research-live-view.tsx` now lays its header
and three columns out as panels. The four palette colours in `source-panel.tsx` and `sub-question-tree.tsx`, the amber box
in `gate-approval.tsx` and two icons in `output-preview-panel.tsx` moved to tokens, because they render on these screens.

**Deviations.** There is no pending-steps list in the timeline (the stream does not announce steps ahead of time, and the
store would need a new field); the results panel lists finished tasks rather than one streaming document, because that is
what the store holds.

**Built with their first callers** (reuse, not new patterns): `hooks/use-now.ts` (the one ticking clock; `sidebar-footer` was
switched to it, and `use-veto-countdown` keeps its own because it derives a deadline), `components/layout/document-page.tsx`
(the §5.1 document column, for the other document screens), `components/ui/metric-tile.tsx` and
`components/ui/detail-section.tsx` (extracted from the Plan detail panel, which now imports them). `event-utils.ts` keeps its
exports; its icons are a `{icon, tone}` table, which also removes 26 palette classes from the Console, chat and activity icons.
`statusLabel` moved to `lib/format.ts`.

Browser-tested with 27 + 23 checks, every write intercepted (filters and counts, header, rows, keyboard, the three detail views,
New run modal, a fabricated in-flight run with ticking duration, Live link and Cancel, then a faked stream with a failed step,
panel toggles, Cancel run, a finished run, 1100 px). Not exercised: cancelling a real run.

**Original plan text:**


`runs-panel.tsx`, `run-detail-panel.tsx`, `run-live.tsx`, `components/live/*`. Apply C21. Fold
`live-footer.tsx` stats into the summary Panel (its `formatElapsed` has already moved to
`lib/format-date.ts` in Phase 2.2), then delete `live-footer.tsx`. Status icons use
`StatusIcon` with `runTone`. Filter chips use `FilterChip`. `runTone` is typed against `RunStatus`
(`types/execution.ts`, added in Phase 2.1 from the two backend enums); the API returns plain
strings, so use `styleFor(runTone, status, 'run')`, which throws on an unknown value.

### Phase 7 — Workflows list and editor (handoff §6.8, §6.9) (done)

Two commits: first `human-input-panel.tsx` was moved out of `workflow-editor.tsx` as a pure move (914 → 792 lines) to make
room, then the restyle (editor 787, `step-detail.tsx` 812 → 800, `workflow-editor-node.tsx` 562 → 364, `workflows-panel.tsx`
615 → 508; none grew).

**One description of a step type.** The icon, label, description and tone of each step type were written four times (node
palette, toolbar, node, inspector header) with 46 palette colours in `workflow-editor-types.ts` (C11). They are now
`STEP_TYPES` in that file (`StepType` comes from `WorkflowStep.node_type`), read by the palette, the toolbar, the nodes and
the inspector; the old domain colour maps are deleted and an agent step takes its tone from `agentStyle` (the same
domain tones as the plan board). Tones: condition `info`, notification `success`, human input `warning`, LLM call `brand`,
sub-workflow and decision `violet`, the rest `neutral`.

**Editor.** Floating panels on the well: a toolbar panel (name, "N steps", unsaved dot, Architect, Auto-layout, History,
Save, Run workflow), a left 220 px `StepPalette` (hidden below 1100 px, where a toolbar "Add step" button opens the command
search instead), the canvas as a panel (dotted `canvas-dot` background; React Flow's own controls and minimap themed by one
block of CSS variables in `index.css`), and a 300 px inspector or run-history panel on the right (inspector hidden below
960 px, as in the handoff). Nodes are one `NodeFrame` (rounded row, `IconTile`, title, mono sub-line, `shadow-node`) with a
thin body per type, replacing ten near-copies; run state uses the shared `StatusIcon`. Selected is `border-brand` plus a
brand ring; running, completed, failed and awaiting input colour the border. The two copies of the edge-colour logic are
one `edgeAppearance` helper on theme tokens. `NODE_HEIGHT` (dagre spacing) went from 80 to 56 because nodes are shorter,
which only changes auto-layout. `Switch` (`components/ui/switch.tsx`) is used for the sub-workflow "pass parent context"
option, schedule on/off and the run dialog's boolean parameters. The architect's collapsed side strip is gone; the toolbar
button already opens and closes it. `variable-autocomplete.tsx` uses `use-click-outside`; the schedule and run dialogs
match `ConfirmDialog`.

**Deviations.** No drag from the palette (C42). No last-run pill, cron text or workflow switch on cards (C43). No "edited 2m
ago" in the toolbar (the workflow detail has no `updated_at`). Cards keep their actions visible (C44). The two dialogs do not
close on a backdrop click or Escape, because they are forms.

Browser-tested with 31 + 10 + 17 + 12 + 4 checks, writes intercepted: toolbar, palette, node frame, widths, theme edges,
adding steps, inspector, History, Architect, command search, a faked running run with a human-input request answered,
narrow widths, the list, schedule switches, both dialogs, run history, drag, connect, undo, redo, delete. Not exercised:
saving, scheduling and running for real.

**Original plan text:**


`workflows-panel.tsx`, `workflow-editor.tsx`, `workflow-editor-node.tsx`,
`workflow-editor-toolbar.tsx`, `node-palette.tsx`, `step-detail.tsx`, `workflow-editor-types.ts`.
Create `components/ui/switch.tsx` (handoff §4.6, `role="switch"`, `aria-checked`) and use it
for the workflow enable toggle in `workflows-panel.tsx:377`, and for the inspector toggles in
`step-detail.tsx`. Apply C11. React Flow `Background`, `Controls`, `MiniMap` use tokens (`workflow-editor.tsx:842`
already uses one). Trigger summaries use `describeCronExpression`; `variable-autocomplete.tsx`
migrates to `use-click-outside`. `workflow-editor.tsx` (914) and `step-detail.tsx` (812) must not grow; if the
restyle cannot fit, split by responsibility before restyling, in its own commit.

### Phase 8 — Backend data (§3) and client hooks (done)

Built in this order, one commit each: the team authorisation fix (D10), the configured default model (D11), then 8.1,
8.4 and 8.2 with 8.3.

**8.1 Mission spend.** `MissionResponse.spent_usd` (never null) from `TokenEconomicsService.get_cost_by_mission`, one
grouped query on the shared scope filter (which now also takes a list of missions); `MissionService.to_responses` is the
only way an endpoint returns missions, so create, list, get and update all carry it; `MissionResponse.from_mission` builds
it because spend is not a column. Verified against a real database session: the sum, `0.0`, other missions' calls ignored,
the four endpoints, and exactly one `llm_calls` statement for a list.

**8.4 Team member enable.** `PATCH /missions/{id}/team/{member_id}/enabled` with `TeamMemberEnabledUpdate`, calling the
existing `toggle_enabled`, behind the scoped member lookup. The Team page's switch, and the `enabled_only=false` its list
needs (C26), are Phase 10.1.

**8.2 Attention.** `GET /attention` returns `{ items, pending_counts }` (`AttentionService`, `schemas/attention.py`).
Deviations from §3.2:

- Tasks are aggregated (D12): `TaskRepository.summarise_for_missions` is one grouped query joined to ACTIVE or PAUSED plans,
  replacing the planned `list_by_status_for_missions`; proposed tasks only count where the plan's gate mode needs a person
  (`AUTO_APPROVE_GATE_MODES`, now in `models/mission_plan.py`; a plan with no gate mode counts, as it defaults to
  interactive). Each item carries `count`.
- Agent code may not import models (rule 011.1), so the Director's approve tool asks `gate_mode_auto_approves` in
  `services/mission_plan.py` instead of importing the constant as §3.2 said.
- Visible missions are the ones the user owns or belongs to (what `require_mission_access` allows), never platform ones
  unless admin, never archived: `MissionRepository.list_open_for_user`.
- `list_pending_gate_requests` and `list_pending_human_input` take lists of missions; their one caller each passes
  `[mission_id]`.
- Links built by the backend: tasks to the Plan board, a gate to the mission's Overview (the active run card answers it),
  human input to its workflows page. Items are ordered gates, human input, approvals, then failures.
- `hooks/use-attention.ts` (24 lines) is a query with `refetchInterval: ATTENTION_POLL_MS` (`lib/constants.ts`); the
  mission layout also invalidates it on `mission_plan.*`, `gate.*` and `workflow.human_input.*` events and on reconnect.

**8.3 Sidebar badge.** A `CountBadge` on each mission row (items for the mission) and a count on the Plan item (items whose
link is the Plan page), from the same query as the Dashboard will use: one request.

Verified: 2208 backend tests (unit and integration) pass; with the service's user scope, or its auto-approve exclusion,
removed, the attention tests fail. The sidebar was browser-tested with the endpoint answered by the test, because the
running dev API predates it.

**Original plan text:**


Decided (D3): build both additions.

**8.1 Mission spend.** Repository aggregate, service method, `spent_usd` on `MissionResponse`,
`types/mission.ts` updated. Integration test against real Postgres: a mission with recorded LLM
calls returns their sum; a mission with none returns 0.0; the list endpoint issues one aggregate
query.

**8.2 Attention endpoint.** Move `AUTO_APPROVE_GATE_MODES` (§3.2). Change
`list_pending_gate_requests` and `list_pending_human_input` to take mission-id lists and update
their one caller each (§2.4). Add `TaskRepository.list_by_status_for_missions`. Then schema,
service, endpoint,
router registration, `ApiResponse` envelope, auth scoped to accessible missions. Integration
tests: each `kind`; access scoping; and the existing per-mission gate and human-input endpoints
still return what they did. `hooks/use-attention.ts` (new, ≤ 150 lines) is a TanStack Query
passthrough. Inside a mission it is invalidated by the SSE events that already invalidate
`planKeys.plan` and `['executions']` in `layout.tsx`. The Dashboard has no mission SSE stream,
so the hook also polls, using the `refetchInterval` pattern from `use-executions.ts:38`, with
the interval as a named constant in `lib/constants.ts` (no inline number).

**8.3 Sidebar badge.** Add the per-mission pending count to `sidebar.tsx`.

**8.4 Team member enable endpoint (§3.3).** Endpoint and schema. Integration tests against real
Postgres: toggling off removes the member from `list_team(enabled_only=True)` (the roster
input); toggling on restores it; a member id from another mission returns 404; a user without
mission access is refused.

Gates for this phase include `pytest tests/unit tests/integration` and
`python scripts/code_rules_fast.py --all`.

### Phase 9 — Login, Dashboard, New mission, Overview (handoff §6.0–§6.3) (done)

**Shared pieces added:** `ui/field.tsx` (label, hint, error), `ui/input-group.tsx` (prefix and suffix adornments),
`ui/theme-toggle.tsx` (extracted from the sidebar footer, which now uses it), `Button` size `xl`, `formatRelative`
(C45, §2.4) and `attentionTone` in `lib/status-tone.ts`.

**9.1 Login.** Centred 360px column, heading, labelled fields, one `signIn(email, password)` for the form and for the
quick-login buttons (the old `setTimeout` plus `requestSubmit` is gone), theme toggle top right. Quick login is a
development-build feature (D13, C48).
**9.2 Dashboard.** Greeting and summary counts, "Needs your attention" (hidden when empty), a Segmented status filter, mission
cards, a dashed New mission tile and the empty state. `AttentionPanel` and `MissionCard` are their own files. Cards are
`role="link"` and open on Enter; the admin-only `⋯` menu (Archive, Delete) keeps the existing confirmation dialogs and its
clicks do not open the card. Spend and the progress bar show only when a ceiling is set. Age is `created {relative}` (C45).
**9.3 New mission.** Single step (C27), breadcrumb, `Field`s, `missions/` prefix and `$`/`USD` adornments; validation, payload
and the redirect to Team are unchanged.
**9.4 Overview.** `overview.tsx` went from 659 to 280 lines by splitting out `mission-edit-modal.tsx`, `setup-checklist.tsx`,
`environment-status-card.tsx`, `recent-errors.tsx` and `team-panel.tsx`. The brief row carries Edit and Delete (D9); the facts
strip is one `Panel` with clipped inner cell dividers (the one `border-l` the layout gate reports is a cell divider inside an
`overflow-hidden` panel, not a panel side stripe); Recent runs per C46; the Team panel shows live agent state from the workspace
store. The active-run card keeps its gate approval, event link, Live pill and click-through, and shows no step count (C41).
The Edit modal now closes on Escape, like `ConfirmDialog`.

Verified (2026-10-21): `tsc`, lint and build; colour, template-class and layout gates; production bundle free of the dev
credentials. Browser tests in both themes: login (error path, single POST per submit, quick login, theme toggle, real sign-in),
dashboard (attention against real data, filter, keyboard open, menu does not navigate, Archive sends one PATCH, Cancel sends
none), new mission (validation, exact POST body, redirect, Cancel), overview (setup checklist with a faked empty mission,
Edit modal and Escape, Delete confirm, faked running run with its clock and click-through). Earlier sidebar-badge, fixes,
editor, runs, live, plan, workflows and modals tests pass unchanged; the route sweep reports no failed request, console error
or page error. Before/after screenshot review of all 26 routes against Phase 7 found no regression: the five flags the reviewers
raised were each refuted against the code.

### Phase 10 — Mission secondary screens (handoff §6.10–§6.16) (done)

Seven writers worked on separate files in parallel, each with its own browser test; an independent reviewer then read each
diff, re-ran the gates and the test and compared the screenshots, and a fixer applied what held up. One commit per screen.

**10.1 Team (C26).** `useTeam(missionId, enabledOnly = true)` sends `?enabled_only=` and puts the flag in the query key, so the
default key (chat roster, Overview, console, plan board, settings drawer) is unchanged; the Team page asks for
`enabledOnly=false`. `useToggleTeamMember` PATCHes `.../enabled` and invalidates `teamKeys.all`. Cards carry the `Switch` and
dim at `opacity-60` when off. `team.tsx` 532 → 102 lines, with the card, configuration block, constraints editor and model
label in `components/team/`. The empty state is `EmptyState`, which gained an optional `secondaryAction`. The mission-brief
callout, the Configuration expander and the constraints editor stay (they are existing features the handoff omits).
**10.2 Narrative (C33).** The hidden-types filter keeps its storage key and becomes `FilterChip`s with counts. Events are now
grouped into one `Panel` per session, with the header read from event payloads only (objective, status, cost, duration);
the dispatcher's `run_status` `success` and `partial` are mapped, and any other status shows as a neutral pill. 492 → 164 lines.
**10.3 Context (C22, C51).** `context-panel.tsx` 338 → 115 lines; sections, dynamic values, a 300px history panel, and a
collapsed "Recent changes" section below 960px so the change list stays reachable. The change-type colours now apply: the old
map was keyed by uppercase and the API returns lowercase.
**10.4 Knowledge (C49, C50).** `knowledge-tab.tsx` 322 → 46 lines; intent, learnings and recent-failures panels; kind chips.
`IntentStrip` (also on Overview) was moved off the amber palette and its source labels now live in one place.
**10.5 Artifacts (C23, C52).** Six groups, viewer header and actions in their own files, streaming card with the shimmer bar.
**10.6 Console (C53).** `console.tsx` 672 → 137 lines; a `Segmented` category control with counts replaces the tabs;
`isErrorEvent` is one function in `lib/console-event.ts`, used by the rows, the toolbar pill and the store's Errors filter (the
Errors filter now also catches `step === 'error'`, which the row tint already did). `consoleCategoryTone` already existed.
**10.7 Costs (C19, C20, C54).** `costs-tab.tsx` 205 → 72 lines. `StatCard` gained an optional `hint` line.

Verified (2026-10-22): `tsc`, lint, build; colour, template-class and layout gates over all 44 touched files; every touched
screen has a browser test (Team 43, Narrative 64, Context 44, Knowledge 43, Artifacts 51, Console 56, Costs 42 checks) in both
themes at 1440 and 1000px with every write intercepted; the Phase 9, sidebar, editor, runs, live, plan, workflows and modals
tests pass unchanged and the route sweep is clean.

### Phase 11 — Catalog, Admin, Profile, Not found (handoff §6.17–§6.20) (done)

Run like Phase 10: parallel writers on separate files, each with a browser test, an independent reviewer and a fixer.
The Team card also gained the remove confirmation agreed after Phase 10 (a `ConfirmDialog`, outside the dimmed card).

**11.1 Catalog (C55).** `catalog.tsx` 197 → 110 lines; `components/catalog/agent-card.tsx`. The page-local `modelLabel`, which hard-coded
versions, is gone: the card uses the shared team helper.
**11.2 Admin (C57, C58).** One layout with the sanctioned underline tab row (`components/admin/admin-tabs.tsx`, the only
`border-b`) inside a `DocumentPage`; the pages render bare content. Metrics, Config, Health, Token economics (the `Segmented` range
control and the Costs-page panels), Users (role and status pills, a create form and API-key rows as components; a failed load now
says so rather than "No users yet") and the catalog (677 → 230 lines, `Switch` for the enable toggle).
**11.3 Profile (C56).** 296 → 30 lines; `components/profile/`; the theme `Segmented` follows `useTheme`.
**11.4 Not found.** `EmptyState` with the `Compass` icon; its action is the secondary button, not the primary one the
handoff shows.

Verified (2026-11-01): `tsc`, lint, build and the colour, template-class and layout gates over 39 files; browser tests per screen
(Catalog 32, Admin shell 77, Admin data 101, Admin catalog 45, Profile 39, Team confirmation and Not found 10 checks), both themes,
1440 and 1000px, writes intercepted; the route sweep reports nothing. The before/after review of 26 routes found one regression
(Profile had no top bar), fixed. Earlier browser suites were not re-run: the machine restarted between phases and the scratch
tests were lost; their routes are covered by the sweep and the screenshot review.

**Incident (2026-11-01).** A Profile test copied from the shared test template reached the real API: the template let every
`/auth/` path through, so the display name of `admin@missioncontrol.dev` became "AdminAdmin Two" and an API key "my-key" was
created. The template now lets only login, refresh and logout through. Restored the same day with the owner's agreement: the display name is "Admin" again and the key is revoked (the API revokes; the revoked record stays listed).

### Phase 12 — QA sweep (done)

Run every gate in §6 across the whole of `src/`, not just touched files. Fix every finding.
Walk the behaviour-parity list in §6.4 in both themes. Update `docs/01-overview/` only where a
screen description is now wrong. Rename this file with the `-[X]` suffix and set Status.

**12.1 (`ed39d2d6`).** The theme default follows `prefers-color-scheme` when nothing valid is stored (D1, C12); it is read once at
boot, not tracked. The whole-`src/` colour gate found two files no phase had restyled. `MarkdownRenderer` imported the dark-only
`github-dark` highlight stylesheet, which painted dark code blocks in warm-white; `index.css` now colours highlight.js output from the
theme tokens, and the blockquote side stripe became a tinted surface. The Architect panel lost its emerald palette classes and its
`border-b` strip.
**12.2 (`eba2d7b9`).** Fixes from the screenshot review: inactive filter chips use `border-border-strong` (`panel-border` is invisible in dark
by design, so they read as bare text); the Overview facts strip fits five cells at 1024px (`minmax(130px, 1fr)`, was 150); the Runs row hides
the task and artifact counts below `xl` so the objective keeps its width; Task Results cards truncate the task id instead of wrapping it
over four lines; the Architect close button has an accessible name. `runs-panel.tsx` is one line longer (the comment).

**Whole-`src/` gates (2026-11-01).** Lint (`--max-warnings 0`) and build pass. The colour gate is empty outside `index.css`. The layout
gate reports four hits, all specified by the handoff: the sidebar edge, the sidebar sub-nav guide line, the settings drawer's left edge and
the Overview facts-strip cell divider, plus the Admin underline row sanctioned in 11.2.

**Responsive sweep.** 26 routes, both themes, at 1024, 1280, 1440 and 1920px (208 screenshots): no horizontal page overflow, failed
request or console error. Five readers reviewed the images; every finding they raised was checked by two skeptics. Eight were confirmed;
four were fixed in 12.2 (chips, facts strip, Runs objective, Task Results ids). Four were left: see §5 (two on the Plan board, the Team
grid, the Admin catalog at 1024). Three more were refuted as design or capture artefacts. The Architect label came from the parity suites.

**Behaviour parity (§6.4, both themes).** Four areas, each with a rebuilt suite and every write answered locally: shell and modals
(258 checks), chat and plan board (137, 0 failed), runs and workflows (198), dashboard and mission tabs (237). Of the 42 failures
across them, none is a redesign regression. The causes: suite faults (selectors, a title compared before CSS capitalisation, fixed delays
that were too short, an assertion that counted the health check, which is a POST, as a write), a harness that answers the read-only health POST
with `{}` and so crashes the Admin health page, saving the Overview Edit modal with the harness's `{}` reply (the page then renders
a mission with no fields), and real data that is older than 30 days (Costs "30 days" has nothing to show). Each suspect was re-run on
its own: "Run not found" 12 of 12, the Knowledge kind filter 8 of 8, Artifacts select, Download (correct file name) and group collapse,
the Copy handler (it hands the stored content, 3306 characters, to the clipboard API; headless Chrome refuses the clipboard itself, so the
real clipboard was not exercised) and the Costs empty range ("No calls in this time range", no page error). The remaining failures are
pre-existing behaviour, recorded in §5.

Not exercised, because they write, need a live stream or a state the data lacks: any real write; the streamed reply to a sent message;
live roster, Console and Narrative appends; Run approved, Resume and the escalation banner on real state (the real plan is paused and
all 230 cards are finished, so card states came from a faked plan); the human-input answer in the editor; Delete workflow and the
post-create redirects; the notification list (empty); the Admin health page against a real reply (the harness stub breaks it).

`docs/01-overview/` describes API actions, not screens, and no description in it is wrong, so it is unchanged.

---

## 5. Out of Scope

**Pre-existing defects found while verifying (confirmed present before this plan's changes by
baseline screenshots; not fixed here — each needs its own decision):**

| Where | Defect |
|---|---|
| `/admin/metrics` (fixed 2026-10-20) | The page crashed: its types did not match the API. Overview counts are nested (`counts.missions`, `sessions`, `execution_records`, `workflow_runs`, `agents`), costs per agent are `runs` and `total_cost_usd`, agent stats use `total_runs` and a nullable `avg_duration_seconds`. Types and page now read the real fields. The "Users" card is gone: the API sends no user count. |
| `/admin/users` (fixed 2026-10-20) | Blank page: the router's collection routes are `/`, so `GET /admin/users` answered `307` with an absolute redirect to port 8100. The list and create calls now use `/admin/users/`. |
| `/missions/:id/context` (fixed 2026-10-20, live after the 2026-10-21 restart) | Size read `3.2KB / NaNKB`: the page expects `max_characters` and the response never carried it. `get_context_size` now returns it from the same config as `pct_of_max`. |
| Plan board (fixed in Phase 5) | Agent tag pill clipped its last letter (`RESEARCH.SYNTHESIZE`); the card was rebuilt. |
| Console (warm-white) (scrim fixed 2026-10-20) | The log pane was a fixed `bg-zinc-950/50` scrim, dark in the light theme; it is `bg-well/50` now. The rest of the console is restyled in Phase 10.6. |
| Right drawer (fixed 2026-10-20) | `event-log`, `output-preview` and `cost-breakdown` had no caller. The panels, their drawer cases and the unused `agent-events` and `architect-chat` type entries are deleted; `OutputPreviewContent` stays (the Runs detail panel uses it). |
| Dependencies (fixed 2026-10-20) | `@hello-pangea/dnd` was imported nowhere; removed from `package.json` and the lockfile. |
| Run live (fixed 2026-10-22) | A run id the API does not know left the page blank after its retry: the data load had no error state. It shows "Run not found" with a way back to Runs. |
| Workflow cards (fixed 2026-10-22) | The Phase 7 footer squeezed "designed by …" to a few characters beside the pills and actions. The attribution is its own line above the footer. |
| Workflow editor (fixed 2026-10-20) | Clicking Run workflow toasted "Workflow started" before anything started. `handleRun` now clears the overlay and opens the dialog, which reports the result; the always-false `isRunning` state is removed. |
| Workflow editor (fixed 2026-10-20) | A wide graph opened at about 0.2 zoom. Fit-to-view now stops at 0.5 (`FIT_MIN_ZOOM`); pan or zoom out to see the rest. |
| Step inspector (fixed 2026-10-20, 2026-10-21) | The decision Model field showed an invented `anthropic:claude-haiku-4-5` when the step had none, while the backend raises if a decision has no model; it now shows the step's own value. The editor also created new LLM-call and decision steps with a hard-coded `copilot:claude-haiku-4.5`. New steps now start with the `models.yaml` alias named by `workflows.yaml` `default_step_model` (`quick`), served by `GET /workflows/editor-defaults`; the key has no code default, a name that is not an alias fails the config load, and if the editor cannot load it the new step is created with an empty model and says so. The backend resolves aliases at run time, so changing the alias in `models.yaml` changes every step that uses it. |
| Workflows (fixed 2026-10-20) | `dag-graph.tsx` was imported nowhere; deleted. |
| Run live (fixed 2026-10-20) | A run opened after it finished showed no activity or results. It now renders from its record: the timeline lists the recorded task executions and the results panel the recorded outcome (`OutputPreviewContent`); the summary shows recorded tokens (input and output) when the outcome has them. Live events are still not kept, and the page says so. |
| Run live | The store reads a `tasks` list from `plan.created`, but the event is typed with `step_count` and nothing in `modules/` emits it, so the step total may never be known. |
| Admin health (fixed 2026-10-20) | The page called `GET /admin/system/health`, which answers 405: the endpoint is `POST`. |
| Missions API | `GET /missions` returns only the missions a non-admin owns, while access (and the attention list) also covers missions they belong to; a member sees a mission's page by link but not in the sidebar or dashboard list. |
| Knowledge | `CollapsibleSection` put its header filter chips (buttons) inside its toggle button, which React flags as nested buttons and which breaks keyboard and screen-reader use. The toggle is now the title area only (fixed 2026-10-20). |
| Chat history | Old Director prompts stored in session messages still quote the `__META__` tail from before the supervisor fix (visible in the ai-deep-research chat thread). It is recorded conversation, so it was left as it is. |
| Dev stack | `temporal server start-dev` runs without `--db-filename`, so its state is in memory, and it had been failing since 17 October (`ListNamespaces ... interrupted (9)`, about 5 million log lines, the log file at 1.2 GB), so no worker could validate its namespace. A restart brought it back (a new, empty store; nothing was running). Open: the start command in `services.py` and `dev_runner.py` has no persistent store and nothing bounds the log. `services.py stop` also kills every process connected to the backend port, which took the Vite dev server down with the API. |
| Runs / API (closed 2026-10-21) | The API had run since 16 October without `--reload`, so it served stored supervisor reasoning with its metadata tail, no `max_characters` and none of the Phase 8 endpoints. Restarted with `services.py`; the decisions, the Context page and `/attention` now return the new data. |
| Chat (fixed 2026-10-19) | Intermittently the thread stopped hundreds of pixels short of the bottom on load (830-884px measured). The auto-scroll effect in `chat-conversation.tsx` did not depend on `historicalEvents` (the separate narrative query), so events arriving after the first scroll left the thread short. Reproduced deterministically by delaying the narrative response, and confirmed at the original baseline. The effect now depends on the timeline; measured 0px from the bottom at every sample with the narrative delayed 1.5s, delayed 3s, and not delayed. |
| Dev stack / API (fixed 2026-11-02) | Cause settled. (1) The SSE endpoints and `SseUser` took the request-scoped `DbSession`, which FastAPI 0.135 keeps open until a streaming response ends, so every open stream held one of the 30 pooled connections. They now use a short `get_async_session()` scope for the auth and access checks and hold none while streaming (45 concurrent streams answer in 4 to 5 ms for other requests; before, 12 of 20 answered and `/health/ready` timed out). (2) The Vite dev proxy kept a stream open on the API when the client left before the API's headers arrived (http-proxy aborts only on `aborted`, which Node 24 does not emit for a fully read GET): a client dropping within about 2 ms of the request orphaned 20 of 20 streams, and an orphan outlived every browser until Vite was restarted. A `proxyReq` hook in `vite.config.ts` now aborts the upstream request; 50 early aborts leave none. Still open: Chrome keeps a frozen page's streams (back-forward cache) after a full navigation away until the tab closes or the entry is evicted; these now cost a socket and a Redis connection, not a database connection. |
| Missions API (fixed 2026-11-02) | A mission member who is not the owner got a 500 (`MissingGreenlet`) from every endpoint that calls `require_mission_access` (67 call sites) and from the mission, costs, artifacts and stream access checks: they read `mission.members`, a lazy relationship, on an async session. Reproduced against the test database with a fresh session; `MissionRepository.get_by_id` now loads members (`selectinload`), and `tests/integration/backend/api/test_mission_member_access.py` covers a member and a stranger through both access helpers. Not run against the dev database (it needs a second user and a membership row). `streams._require_mission_access` duplicates `core.dependencies.require_mission_access`. |
| Workflow editor (fixed 2026-11-02) | `handleNodeDragStop` autosaves node positions only, then cleared the unsaved flag. A step or edge added before the drag existed only in memory; the flag went out, Save was disabled, and a reload lost the change. Reproduced in the parity suite on the unfixed code (flag cleared, Save disabled, Cmd+S sent nothing). The editor now tracks unsaved positions and unsaved structure apart; the autosave clears only the first. The line dated from the original editor commit. |
| Login (fixed 2026-11-02) | Three causes. (1) `login()` flipped `isAuthenticated`, so the page's own redirect to the Dashboard rendered before `navigate(from)` ran and always won; the page now has one exit, a `<Navigate>` to the route `AuthGuard` recorded, including its query string and hash. (2) On session expiry `ApiClient` set `window.location.href` to `/login`, a full load that discarded the route; it now only clears the session and `AuthGuard` redirects with the route recorded. (3) A full load of `/login` while signed in showed the form, because only protected routes ran the refresh; the restore moved into `useSessionRestore` (`hooks/use-session-restore.ts`), used by `AuthGuard` and the login page. The form now maps the failure: 401 is "Invalid email or password", a network failure names the connection, and other statuses show the server's message (`ApiError` in `lib/api.ts` carries the status). Browser test `p14-login-test.mjs`, 23 checks, fails 10 on the unfixed code: deep link, expiry without a reload, stale refresh token, signed-in `/login`, each error class, log out then sign in (lands on the Dashboard), quick login. Seeded password: `bootstrap.py` seeds `admin123`, the local database holds `admin`, so quick login fails locally; the test rewrites the password in flight. |
| Log out (fixed 2026-11-03) | `logout()` cleared client state only, so a refresh token copied before sign-out stayed valid until it expired. Login now mints a session id (`sid`) carried by every access and refresh token of that login; `POST /auth/logout` stores it in `revoked_sessions` (migration `plan87_001`) and commits before answering. Verification refuses a revoked `sid` ("Session ended") and a token with no `sid`, so every token of the session dies, including earlier refresh tokens, while the user's other sessions are unaffected. `daily_cleanup` deletes rows after one refresh lifetime. SSE tokens record the `sid` and are refused at connect once it is revoked. The client (`useSignOut`) calls the endpoint first, aborts after 5 seconds, and signs out locally with a toast if the server fails. Tests: unit, real-database integration (service and endpoints, including a check that logout commits), real-Redis SSE tests, and `p14-login-test.mjs` (34 checks, real `/auth/logout`). An independent review raised 9 findings, 6 confirmed and fixed or recorded: in-flight refresh undoing a sign-out, 401 path recording the page left, commit untested, docs gap, SSE token not bound to the session. Retention (fixed 2026-11-03): tokens carry `iat`, and verification refuses a refresh token whose lifetime exceeds the configured `refresh_token_expire_days`, so the revocation row (kept one configured lifetime from logout) always outlives every token of its session; lowering the setting signs out holders of older, longer-lived tokens. Ending all sessions of a user (2026-11-03): `users.token_version` (migration `plan87_002`) is carried by every token as `tv`; a password change, an admin reset and a deactivation increment it, so every existing session of that user ends, and a reactivated user does not get old sessions back. After a password change the client signs out locally and returns to the profile page after sign-in. Deploy impact: tokens issued before this change have no `sid`, `iat` or `tv` and are refused, so everyone signs in once. Not covered: streams already open at logout keep running. Doc 05 still says the refresh token is rotated and held in an HttpOnly cookie; the code does neither. |
| Escape key (fixed 2026-11-02) | `RunModal`, `MissionSettingsDrawer` and the right drawer did not close on Escape. All five overlays (those three, the Overview Edit modal and `ConfirmDialog`) now use one `useEscapeKey` hook (`hooks/use-escape-key.ts`): only the topmost overlay closes, so Escape on a confirmation over the settings drawer closes the dialog first, and a control that has used Escape itself (`preventDefault`) keeps the overlay open. Escape in a text field closes the overlay, as in the Edit modal, so an unsaved edit in a form is discarded. Open: `RunModal` still uses `bg-black/50` and `bg-card` (it was never restyled), and the inline Escape handlers in `variable-autocomplete.tsx` and `menu.tsx` do not call `preventDefault`; neither sits inside these overlays today. |
| Plan board (width fixed 2026-11-03; curves kept by decision) | The board was `min-w-[1040px]` with four equal columns, so below about 1290px it scrolled sideways and the Done column, often the only populated one, sat out of sight with no cue. A column with no cards now collapses to a 44px rail (icon, count, vertical name, `role="group"` labelled "Approved, no tasks") and the populated columns share the width, each at least 250px (`COLUMN_MIN_WIDTH`, `RAIL_WIDTH` in `plan-board.tsx`). Proposed never collapses, because the add-task row lives there. With all four populated the minimum is the width it always was, so a narrow window still scrolls. Dependency curves between cards in one column are unchanged: the owner chose to keep them. Browser test `p15-plan-board-test.mjs`, 30 checks on fabricated plans (Done only at 1100, 1280 and 1440; all four populated at 1440 and 1100; Running only; a plan where Running is populated), fails 13 on the unfixed board; curves start and end on card edges with the new widths. |
| Team grid, Admin catalog (left as is) | Team cards use `items-start`, so rows have ragged heights (a card grows when its prompt is edited). At 1024px the Admin catalog truncates agent names with an ellipsis. Reviewers split on both. |

- ⌘K command palette and the sidebar search trigger (C31).
- Tab-bar navigation option (C32).
- `light-neutral` theme; server-side theme persistence.
- Layouts below 768px.
- Splitting existing files that exceed doc 23 limits, except where a phase says so.
- Frontend test framework and frontend CI job (D2: decided against).

---

## 6. Verification Gates

### 6.1 Every commit

1. `cd modules/frontend && npm run build` succeeds.
2. `cd modules/frontend && npm run lint` exits 0 (no warnings).
3. Colour gate, run on the files the commit restyles, excluding `src/index.css` (the token
   file, where colour literals live by design, C35) — no output. A commit that only fixes a
   lint warning or renames a class (Phases 0 and 1) is gated on the lines it changes, not on
   the whole file; whole-file clean is required once a phase restyles the file:
   `grep -nE "(slate|zinc|gray|red|green|blue|yellow|amber|emerald|orange|purple|violet|rose|sky|cyan)-[0-9]{2,3}|#[0-9a-fA-F]{3,8}\b|rgba?\(" <files>`
4. Undefined-class gate: enforced by `tailwindcss/no-custom-classname` inside gate 2 (D8).
   Classes built dynamically (template strings) or held in plain string constants are invisible
   to the rule, so token classes are written as whole literals or selected from maps of whole
   literals (as `status-tone` does) — never assembled from fragments such as
   `` `bg-${tone}/10` ``. For any commit that changes `tailwind.config.js` or `index.css`,
   also diff emitted selectors: build the CSS with the previous config and with the new one
   over the same `src/` (`npx tailwindcss -c <config> -i <css> -o <out>`), extract the class
   selectors from both, and confirm no selector present in the old build is absent from the
   new one.
5. Layout gate on touched workspace files: no full-height `border-l`/`border-r` (sidebar edge
   excepted) and no `border-b` header strips.
6. Size gate: new files within doc 23 limits; touched files not larger than before.

### 6.2 Visual check

Method (no test framework is added, D2): start the stack with
`python services.py start --daemon --no-migrate --no-seed`, log in with the documented dev user,
and screenshot each route in both themes with headless Chrome driven by a throwaway
`puppeteer-core` script kept outside the repo. Setting `document.documentElement.className` to
`dark` or `warm-white` switches theme before the theme store exists. Pages must load without
writing to the database; session creation in Chat is click-only. Reviewers read the PNGs; each
flagged issue is checked by a second reader before it is acted on.

For each screen the commit touches: compare against the matching `data-screen-label` in the
reference, in **both** themes, at 1024, 1280, 1440 and 1920 px widths. Responsive rules from
handoff §10 Layout apply (roster hides < 960, outputs < 1200, palette < 1100, inspector < 960,
history < 960, Runs table scrolls horizontally, plan pill shortens < 1100).

### 6.3 Backend commits (Phase 8)

`pytest tests/unit -q` and `pytest tests/integration -q` pass;
`python scripts/code_rules_fast.py --all` reports no new error or warning.

### 6.4 Behaviour parity (run at the end of Phases 3, 5, 7 and 12)

Phase 3 pass (2026-10-19, read-only, no write requests sent): every route resolves; `missions/:id`
redirects; RunModal, MissionSettingsDrawer, NotificationDropdown open; the three reachable drawer
panels (`agent-detail` from Catalog and Team, `prompt-history` from Team, `run-events` from the active
run card) open from their real entry points; the chat slash-command popover opens on `/`; the Plan board
renders its four columns. Not exercised because they would write: approve/reject/retry, send message,
run, save and schedule.

Phase 5 pass (2026-10-19, every write intercepted): approve, reject, veto, stop and retry on the cards
reach `useApproveTask`, `useRejectTask` and `useRetryTask` (POST `/approve`, `/reject`, `/retry`); gate
mode, pause and resume reach PATCH `/plan`; Run approved opens the confirm dialog and Cancel dispatches
nothing; the refine and add-task forms open; the detail panel opens from a completed or failed card
and closes. Drag-and-drop does not exist (C38). Real-data writes were not exercised.

Phase 6 pass (2026-10-19, every write intercepted): the Runs filters, row expand and collapse by click and keyboard, the Events,
Output and Cost views and New run reach the same hooks as before; Cancel on a running row and Cancel run on the live page
POST `/executions/{id}/cancel`; the Live link opens the run page. The live page's data logic (starting a pending run once the stream connects, the hand-off to the
research view, the gate approval prompt) was left as it was and not exercised: no run was pending, researching or gated. Cancelling
a real run was not exercised.

Phase 7 pass (2026-10-19, every write intercepted; this is the mid-point pass of §6.4): in the editor, select, add (palette, command
search, narrow-width button), drag (and its autosave `PUT .../graph`), connect, undo, redo, delete, History, Architect, the run
dialog, the schedule dialog and answering a human-input request all work; schedule on/off reaches the same mutation; Edit opens
the editor. Not exercised because they write: Save (Cmd+S), creating a schedule, starting a run for real, deleting a workflow.
Earlier passes still hold: the Plan, Runs and Run live tests were re-run after this phase and pass unchanged.

Phase 9 pass (2026-10-21, every write intercepted): sign-in posts the typed credentials once and a failure shows the error; the
Dashboard menu, Archive and Delete confirmations send nothing on Cancel and one PATCH on Archive; New mission posts the same
body and lands on Team; Overview Edit, Delete, the setup checklist actions and the running-run click-through work. Not exercised
because they write: saving the Edit modal and deleting a real mission. Earlier passes still hold (tests re-run, all pass).

Phase 10 pass (2026-10-22, every write intercepted): the Team switch sends PATCH `.../enabled` with the new value and a disabled
member stays listed; the chat roster and Overview still ask for enabled members only; prompt edit, history, remove, configuration
and constraints still reach their hooks; Narrative filter chips keep their storage key; Context sections collapse and the change
list opens; the Knowledge kind filter, Artifacts selection, Console filters, Clear and Auto, and the Costs range work. Not
exercised because they write or need a live stream: removing a real member, saving constraints, live Console appends.

Phase 11 pass (2026-11-01, every write intercepted): Catalog search, type filter and Details reach the same hooks and drawer; the
Admin tabs, the enable Switch, catalog create, edit and prompt save, user create, role change and key revoke, token range, Profile
display name, password, theme and API key flows, Team remove (now with confirmation) and the Not found link work. Not exercised
because they write: saving a real agent, creating a real user, the password reset prompt.

Phase 12 pass (2026-11-01, every write intercepted, both themes): see Phase 12 in §4 for the results, the failures that were not
regressions and what was not exercised. Earlier passes hold: the rebuilt shell, chat and plan, runs and workflows, and dashboard and tabs
suites cover the Phase 3, 5, 6, 7, 9 and 10 lists; the six Phase 11 suites were re-run after 12.2 and pass with the same counts (10, 32, 77, 101, 45, 39), and the theme-default suite is new (31 checks).

All routes in `App.tsx` resolve; `missions/:id` redirects to the last tab; plan approve/reject
from card and panel hit the same mutations; chat threads, slash commands and
⌘↵ work; RunModal, MissionSettingsDrawer, NotificationDropdown and every RightDrawer panel open;
workflow editor drag, connect, select, save, run and schedule work.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| Global font-size and radius change (C10) breaks layouts on screens restyled late | Phase 1 checks every route; any breakage is fixed in Phase 1, not deferred. |
| Renames ripple widely: `Card` → `Panel` (16 files), button `outline` → `secondary` (26 `Button` call sites; 40 `Badge` uses keep `outline`), Badge states → `StatusPill` (41 files) | Phases 2.3 and 2.4 each migrate in one commit; `tsc` fails on any missed import or variant, and a grep confirms no `outline` variant or `ui/card` import remains. |
| Large files grow during restyle | Size gate 6.1.6 on every commit. |
| No automated frontend tests, so regressions rely on manual checks | §6.4 parity list at fixed points. D2 decided against frontend CI, so local build and lint are the only automated checks. |
| Removing `layout.tsx` header loses actions | Phase 3.3 done criteria: every former header action is reachable. |

---

## 8. Decisions Needed (ask the owner one at a time before the phase that needs it)

| # | Decision | Needed before | Recommendation |
|---|---|---|---|
| D1 | Theme default when nothing is stored: system preference (doc 23) or always dark (handoff) | Phase 1.2 | **Decided 2026-10-16:** system preference. **Re-timed 2026-10-18:** the default stays `dark` until every screen is migrated, because several screens still use dark-designed colour classes that are unreadable in warm-white (confirmed by the Phase 1.1 visual review); Phase 12 switches it to system preference. The stored choice, validation and toggle work from the start. **Done in 12.1 (2026-11-01).** |
| D2 | Add a frontend CI job (`npm ci`, `npm run build`, `npm run lint`) and a Playwright screenshot pass per screen in both themes (doc 22 names Playwright) | Phase 1 | **Decided 2026-10-16:** no CI change. Build and lint run locally before every commit (§6.1); nothing server-side checks the frontend. |
| D3 | Build the two backend endpoints (§3) or drop the attention panel and spend bars | Phase 8 | **Decided 2026-10-16:** build both. |
| D4 | Omit the ⌘K search trigger until a palette exists | Phase 3.2 | **Decided 2026-10-16:** omit. |
| D5 | Drop the optional tab-bar navigation style | Phase 3.2 | **Decided 2026-10-16:** drop. |
| D6 | Team enable/disable: read-only now, or add a backend `PATCH` and a `Switch` | Phase 10.1 | **Decided 2026-10-16:** build the switch (§3.3, Phases 8.4 and 10.1). |
| D7 | Definition of "spent" against the mission budget: `llm_calls` total (what the Costs tab shows) or `execution_records` total (what the Platform Director's cost tool uses). Budget enforcement itself is per plan (`MissionPlan` budget ceiling seeded from the mission ceiling in `services/mission_plan.py:137`), so neither figure is the enforced one | Phase 8.1 | **Decided 2026-10-16:** `llm_calls`, so Dashboard, Overview and Costs show one number. |
| D8 | Add `eslint-plugin-tailwindcss` with `no-custom-classname`, so undefined classes fail `npm run lint` instead of needing gate 6.1.4 by hand | Phase 1.1 | **Decided 2026-10-16:** add it (Phase 1.1). |
| D9 | What happens to the header's inline brief editor (`InlineBrief`) when the header is removed | Phase 3.3 | **Decided 2026-10-19:** drop it; the brief stays on Overview and is edited in its Settings modal. |
| D10 | Team member endpoints that take a member id (remove, prompt, constraints, prompt history) checked access to the mission in the URL, not that the member is on it | Before 8.4 | **Decided 2026-10-20:** fix first, in its own commit (`get_member_in_mission`, 404 for another mission's member, integration tests per endpoint). The new enable endpoint uses it too. |
| D11 | What new LLM-call and decision steps start with (a model string was hard-coded in the editor) | Before 8.2 | **Decided 2026-10-20:** a configured default: `workflows.yaml` `default_step_model`, a `models.yaml` alias, no code default, read through `GET /workflows/editor-defaults`. |
| D12 | The attention list as specified returns every failed and proposed task (586 failed tasks on the dev data, 177 in one mission) | Phase 8.2 | **Decided 2026-10-20:** one item per mission per kind with a count for tasks; a gate request and a human-input request stay one item each; the sidebar badge counts items. |
| D13 | The Login quick-login buttons hold seeded passwords | Phase 9.1 | **Decided 2026-10-21:** dev build only (`import.meta.env.DEV`); a production bundle contains no credentials. |
