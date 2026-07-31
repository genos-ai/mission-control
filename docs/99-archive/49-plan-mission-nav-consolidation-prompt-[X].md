# Task: Plan 49 — Mission Navigation Consolidation (investigate, refactor, verify)

You are being dispatched into an existing codebase (Mission Control) to consolidate
two parallel navigation systems that have converged on showing overlapping content.
Work in the repository at `/Users/herman.young/development/mission-control`.

**This is a standalone brief.** The person handing you this prompt has full conversation
context; you do not. Read the referenced files first, then the referenced plan docs,
then build your own mental model before touching any code.

This is **pure structural refactoring**. It does not ship new features, does not
change any API, does not touch any backend code, and does not resolve the parallel
Plan 41 narrative-feed reconciliation or Plan 45 Phase 4 workflow-editor work. Any
temptation to "fix while you're here" is explicitly out of scope — see §6.

---

## 1  Why this matters

Mission Control today has two mission UIs running in parallel:

1. **Legacy tab-bar routes.** `/missions/:id/{overview,team,chat,workflows,runs,console,workshop,context}` — eight URL routes, each rendering a standalone page component (`OverviewPage`, `TeamPage`, `ChatPage`, etc.) with its own tab bar chrome at the top. Wired in `modules/frontend/src/App.tsx:62-71`.
2. **New 3-panel workspace.** `/missions/:id` (no sub-path) renders `pages/mission/workspace.tsx` — a 1269-line god component with a 3-panel layout (left agent sidebar + center content + collapsible right artifacts drawer) and an in-page Zustand-driven feed-mode toggle: `chat / plan / narrative / stream / context / runs / workflows`.

A user on `/missions/abc123/runs` sees the legacy tab bar rendering `RunsPage`. A user on `/missions/abc123` sees the new workspace with the Runs feed-mode button highlighted. Both show "the runs for this mission" in different layouts, via different URL patterns, implemented in different files, styled differently. The two views have converged on showing the same data.

The product owner noticed this on 2026-04-11 while browsing `/missions/.../runs` and decided the two navigations should be merged into one. Their exact framing:

> "I think we should merge the new tabs/menus into this view (consolidate it). Where we currently have chat, we use the new chat with agents in the left sidebar and artifacts on the right (collapsible), where we Console we look at how stream does it and if it's the same, narrative seems to be missing so merge that in or figure out if it's redundant... Workshop can be removed, I never understood its purpose."

The direction is: **keep the legacy tab-bar URL-route pattern as the outer navigation shell, move the new 3-panel workspace layout OUTWARD so every tab renders inside the same shell, delete Workshop entirely, and close the parallel-nav paper-cut.**

This is NOT scheduled for immediate work — it sits in the deferred tracker of [Plan 46 — Autonomous Mission Roadmap](../08-plans/046-plan-autonomous-mission-roadmap.md) §5, slated for Phase 4 (kanban UX polish) or as a dedicated interstitial between Phase 3 and Phase 4. The reason it has its own handoff brief is that the product owner wants it implementable by a different agent in parallel, same pattern [Plan 47](47-plan-agent-execution-isolation-[X].md) followed.

**Outcome when you are done:** every mission URL (`/missions/:id/chat`, `/missions/:id/plan`, `/missions/:id/runs`, ...) renders the same outer shell (3-panel layout with left agent sidebar + top bar + tab bar + center content + collapsible right artifacts drawer), with tab-specific content in the center panel. The Zustand `feedMode` state is deleted. Workshop is gone. Each tab is a real URL route with browser-history support. A user bookmarking `/missions/abc/runs` gets taken straight to the Runs tab inside the new shell.

---

## 2  Current state — read these first

### 2.1  Plan docs to read in this order

1. [docs/97-plans/46-plan-autonomous-mission-roadmap.md](../08-plans/046-plan-autonomous-mission-roadmap.md) — standing roadmap; read §5 (anti-drift rules) and the §5 Deferred-from-phase tracker entry that points at this task. Understand that Phase 1 is closed, Phase 2 is "durable output", and this consolidation is scheduled for Phase 4 not now. You are the agent that gets handed the Phase 4 prep work early.
2. [docs/97-plans/41-plan-mission-workspace-redesign.md](41-plan-mission-workspace-redesign-[X].md) — the original workspace redesign spec. Read §3 (layout), §4 (routing), §3.5a (plan board spec, already implemented). This is where the 3-panel layout came from in the first place. Honour that design intent when moving the shell outward.
3. `TODO.md` entry at the end: **"Consolidate mission navigation: legacy tab routes + new workspace feed modes"**. This is the canonical design you are implementing; do NOT re-litigate it. It encodes all four user-confirmed decisions listed in §3 below.
4. Plan 47 ([docs/97-plans/47-plan-agent-execution-isolation-[X].md](47-plan-agent-execution-isolation-[X].md)) and its Plan 47 prompt brief for reference — shows the pattern you're following for handoff + verification script discipline.

### 2.2  Legacy pages to read (each tab's current source of truth)

Read these in full so you know what each legacy page actually does before you rewrap it. They vary in size from 300 to 1200 lines and several of them already exceed AGENTS.md's 1000-line limit (flagged separately as code-review P2):

- [modules/frontend/src/pages/mission/overview.tsx](../../modules/frontend/src/pages/mission/overview.tsx) — mission dashboard: brief, status, delete, workflows list, executions list, team summary. **Keep** as a tab.
- [modules/frontend/src/pages/mission/team.tsx](../../modules/frontend/src/pages/mission/team.tsx) — team roster management: add/remove members, update agent prompts, seed team, per-member config with drawers. **Keep** as a tab.
- [modules/frontend/src/pages/mission/chat.tsx](../../modules/frontend/src/pages/mission/chat.tsx) — current chat implementation. **Replace** with the chat feed-mode renderer from `workspace.tsx` (the new chat with agent sidebar + artifacts).
- [modules/frontend/src/pages/mission/workflows.tsx](../../modules/frontend/src/pages/mission/workflows.tsx) — legacy workflows DAG viz. **Keep as the drill-in fallback** (per [Plan 45 candidate TODO](../../TODO.md)); the root `workflows` tab becomes the new `WorkflowsPanel` placeholder (list view with template clone).
- [modules/frontend/src/pages/mission/runs.tsx](../../modules/frontend/src/pages/mission/runs.tsx) — legacy runs list page. **Reconcile** with the workspace's runs feed-mode renderer (see §4 decision-point question).
- [modules/frontend/src/pages/mission/console.tsx](../../modules/frontend/src/pages/mission/console.tsx) — legacy console/event-stream page. **Reconcile** with the workspace's `stream` feed-mode renderer — verify they render the same component; if yes, delete one; if no, merge into one named `stream` and pick the fuller behaviour.
- [modules/frontend/src/pages/mission/workshop.tsx](../../modules/frontend/src/pages/mission/workshop.tsx) — **DELETE this file and its route.** Product owner has confirmed they never understood its purpose. Also delete any associated tests, imports, and constants.
- [modules/frontend/src/pages/mission/context.tsx](../../modules/frontend/src/pages/mission/context.tsx) — legacy context viewer. **Reconcile** with the workspace's `context` feed-mode renderer (same question as runs/stream — see §4).

### 2.3  New workspace + its pieces

- [modules/frontend/src/pages/mission/workspace.tsx](../../modules/frontend/src/pages/mission/workspace.tsx) — **1269 lines**, the god component. Contains:
  - The top bar (mission name, status, pause/archive/delete, gate-mode selector).
  - The left agent sidebar (Director pinned + team roster + click-to-chat).
  - The center panel with `FEED_MODES` array (line ~522) and a switch statement rendering the right feed component.
  - The right collapsible artifacts drawer.
  - The SSE subscription and event fan-out into `workspaceStore` + `consoleStore`.
  - The run modal.
  - Hardcoded `DEFAULT_CHAT_AGENT = 'mission.director.agent'` + `AGENT_ICONS` mapping (the code itself flags as future debt).
- [modules/frontend/src/stores/workspace.ts](../../modules/frontend/src/stores/workspace.ts) — owns the `feedMode` slice you are **removing**, plus other slices (`agentStatuses`, `artifacts`, `streamingArtifact`, `liveTaskOverlay`) that you are **keeping**.
- [modules/frontend/src/components/workspace/plan-board.tsx](../../modules/frontend/src/components/workspace/plan-board.tsx) — the Plan 42 kanban board. Already a clean, self-contained component — just needs to be mounted at `/missions/:id/plan` as a page-level wrapper.
- [modules/frontend/src/components/workspace/workflows-panel.tsx](../../modules/frontend/src/components/workspace/workflows-panel.tsx) — Plan 45 Phase 1 placeholder; mount at `/missions/:id/workflows`.
- [modules/frontend/src/components/workspace/mission-settings-drawer.tsx](../../modules/frontend/src/components/workspace/mission-settings-drawer.tsx) — **uncommitted on disk as of 2026-04-11**. Run `git status` to find it. Finish and wire as the deep-config drawer opened from the outer shell's top bar.
- [modules/frontend/src/components/workspace/context-drawer.tsx](../../modules/frontend/src/components/workspace/context-drawer.tsx) — **uncommitted**. Check `git status`. Decide how this fits (context tab OR a drawer — you pick).
- [modules/frontend/src/components/workspace/run-history-drawer.tsx](../../modules/frontend/src/components/workspace/run-history-drawer.tsx) — **uncommitted**. Check `git status`. Already planned as part of Phase 2 by the roadmap, but may be relevant to how the Runs tab looks post-consolidation.

### 2.4  Routing, SSE, and store

- [modules/frontend/src/App.tsx](../../modules/frontend/src/App.tsx) lines 57-76 — the mission route block you are rewriting. Note the pattern already used for `/admin/*` (nested parent route with `<Outlet />`); mirror it for `/missions/:id`.
- [modules/frontend/src/context/mission-stream.tsx](../../modules/frontend/src/context/mission-stream.tsx) — `MissionStreamContext` provider. Currently created inside `workspace.tsx`; must move to the new outer layout so all tabs share ONE SSE connection. Do NOT open a second connection per tab.
- [modules/frontend/src/hooks/use-sse.ts](../../modules/frontend/src/hooks/use-sse.ts) — the `useMissionStream` hook. Pay attention to the SSE wire format fix from commit `0dceeeb` — events are wrapped in `{event_id, event_type, category, timestamp, source, data}` now (not flat). Any consumer still reading `parsed.some_field` instead of `parsed.data.some_field` is buggy and was papering over it with a fallback.
- [modules/frontend/src/lib/constants.ts](../../modules/frontend/src/lib/constants.ts) — the `ROUTES` object. Update it so nothing hardcodes `/missions/:id/workshop` or stale sub-paths after this refactor.

### 2.5  Commits worth reading

- `00a38e2` — Plan 42 Plan tab: horizontal kanban. Shows how a feed-mode renderer is already structured as a self-contained component — `PlanBoard` is the easiest tab to migrate.
- `0dceeeb` — SSE wire format fix. Understand the wrapped shape; consumers should read `data.X`, not `X`.
- `39507f4` — Plan 45 Phase 1 Workflows feed-mode placeholder. Shows how a simple tab looks as a standalone component.
- `60ae31a` — Plan 46 Phase 1 CLOSED. Roadmap context for where you fit.

---

## 3  User-confirmed design decisions (do NOT re-litigate)

The product owner approved these decisions on 2026-04-11. Implement accordingly and resist the urge to redesign:

1. **Outer shell = legacy-style URL routes.** Every tab is a real route under `/missions/:id/{tab}`. The active tab is derived from `useLocation().pathname`, not from a Zustand state variable. This gives: deep-link support, browser back/forward, bookmarkable tabs, native middle-click-to-new-tab.
2. **The new 3-panel workspace layout moves OUTWARD** and becomes the outer shell wrapping an `<Outlet />`. The 3 panels (left agent sidebar + center content + collapsible right artifacts drawer) are now rendered once per mission route, not once per tab. The center panel's `<Outlet />` swaps the tab-specific content on URL change.
3. **Keep Overview and Team** as their own tabs with their **existing page components** unchanged except for the outer page chrome removal. They do things the workspace top bar cannot express (mission delete, agent prompt editing, team seeding, per-member config), so they stay as full-width experiences inside the shell.
4. **Keep both Narrative and Stream** as separate tabs. They are different lenses on the same event data — Narrative is an opinionated curated view (tool rows grouped under narrative headers, per Plan 41 §3–4), Stream is a raw firehose (what legacy Console shows). There is a separate TODO item at the top of `TODO.md` for reconciling Plan 41 Narrative spec drift — **do not do that work here**. Just make Narrative a tab with whatever the current `workspace.tsx` feed-mode renderer for Narrative does; the spec drift is someone else's problem.
5. **Workshop is deleted entirely.** Route, file, component, imports, tests, constants, docs references. The product owner confirmed they never understood its purpose. Grep the repo for `workshop` and clean up every mission-scoped reference. (There may be unrelated uses of the word "workshop" elsewhere — only touch mission-scoped ones.)

**Final tab bar order (9 tabs):** Overview / Team / Chat / Plan / Narrative / Stream / Context / Runs / Workflows.

---

## 4  Open decisions you still need to make

Three decision points that couldn't be resolved without reading the actual code. Investigate and decide, then document your decision in a PR comment or commit message so it's visible on review:

### 4.1  Stream vs Console — same or different?

The legacy `/console` route renders `ConsolePage`. The new workspace's `stream` feed-mode renders something too. Verify empirically:
- `grep -n "stream" modules/frontend/src/pages/mission/workspace.tsx` and see what `StreamFeedPanel` (or equivalent) actually is.
- If it's literally `<ConsolePage />` or renders `ConsolePage`'s internal components, **delete the `/console` route** and reuse `ConsolePage` verbatim at `/stream`. One component, one source of truth.
- If they're different components that happened to converge on the same UI, pick the fuller one (probably `ConsolePage` given it's the older, more-polished legacy page), delete the other, and mount the survivor at `/stream`.
- Either way, there is no more `/console` route after this work — only `/stream`.

### 4.2  Runs — legacy RunsPage or workspace Runs renderer?

Same question pattern. Investigate:
- What does the workspace's `runs` feed-mode currently render? Is it a separate component or does it import `RunsPage` already?
- What does `pages/mission/runs.tsx` do that the workspace version doesn't (or vice versa)?
- Pick the fuller one, delete the other, mount the survivor at `/missions/:id/runs`.

Note: there's also a `/missions/:id/runs/:runId` route for individual run detail (`RunLivePage`). **Keep it.** The Runs tab shows a list; clicking an item navigates to `/runs/:runId` for the detail view. Do not consolidate the detail view into the outer shell — it's a drill-in page.

### 4.3  Context — legacy ContextPage or workspace context renderer?

Same question. Investigate both, pick the fuller one, delete the other. Note: there's an uncommitted `context-drawer.tsx` that might be relevant — check `git status` and decide whether it's intended as a drawer (opened from a button in the shell top bar) or as an inline tab renderer. Ask the product owner if unclear — leave a note in the PR.

---

## 5  Concrete work plan

Work in small, focused commits with clear messages. Each commit should be independently buildable (frontend typecheck + vite build still pass) and independently revertable. Order matters — do them in this sequence.

### Commit 1: Delete Workshop

- `git rm modules/frontend/src/pages/mission/workshop.tsx`
- Remove the `/missions/:id/workshop` route from `App.tsx`.
- Grep for any `ROUTES.WORKSHOP` or `'workshop'` references in `lib/constants.ts`, `hooks/`, `components/`, and delete them.
- Grep for `WorkshopPage` imports and delete them.
- Run `npx tsc --noEmit` and confirm clean (or only the three pre-existing unrelated warnings remain).
- Commit message footer: `Phase 4 — nav consolidation: delete Workshop`.

### Commit 2: Extract the outer layout from workspace.tsx

This is the biggest mechanical step. Produce a new file:

- `modules/frontend/src/pages/mission/mission-layout.tsx` — the new outer layout component. Contains:
  - The top bar (extracted from `workspace.tsx`).
  - The left agent sidebar (extracted).
  - The right collapsible artifacts drawer (extracted).
  - The tab bar (NEW — reads active tab from `useLocation().pathname`, renders 9 tab buttons, clicking navigates via `useNavigate`).
  - The `MissionStreamContext` provider (moved from `workspace.tsx`).
  - The SSE subscription and store fan-out (moved from `workspace.tsx`).
  - The run modal trigger + modal component (moved).
  - The `mission-settings-drawer.tsx` wiring (finished and mounted here).
  - `<Outlet />` in the center panel slot where feed-mode content used to render.

The center panel's dynamic content (the current `FEED_MODES` switch statement) goes away entirely — tab-specific content is now rendered by child routes via `<Outlet />`.

Delete from `mission-layout.tsx` (things that belonged in `workspace.tsx` but aren't layout concerns):
- `DEFAULT_CHAT_AGENT` constant — moves to `components/workspace/chat-tab-page.tsx` (created in Commit 3).
- `AGENT_ICONS` mapping — move to a shared `lib/agent-icons.ts` (or better: flagged for removal in favour of a catalog column — leave the inline version for now but note the debt).
- Feed-mode specific renderers — those become the per-tab pages in Commit 3.

Update `stores/workspace.ts`:
- **Remove** the `feedMode` field, `setFeedMode` action, and the `FeedMode` type.
- **Keep** all other slices (`agentStatuses`, `artifacts`, `streamingArtifact`, `liveTaskOverlay`) — they are used by multiple components and stay session-wide.
- Grep for every reference to `feedMode` / `setFeedMode` in the codebase before deleting, and replace with `useLocation()` or direct navigation as appropriate.

Update `App.tsx`:

```tsx
<Route path="missions/:id" element={<MissionLayout />}>
  <Route index element={<Navigate to="chat" replace />} />
  <Route path="overview" element={<OverviewPage />} />
  <Route path="team" element={<TeamPage />} />
  <Route path="chat" element={<ChatTabPage />} />
  <Route path="chat/:threadId" element={<ChatTabPage />} />
  <Route path="plan" element={<PlanTabPage />} />
  <Route path="narrative" element={<NarrativeTabPage />} />
  <Route path="stream" element={<StreamTabPage />} />
  <Route path="context" element={<ContextTabPage />} />
  <Route path="runs" element={<RunsTabPage />} />
  <Route path="runs/:runId" element={<RunLivePage />} />
  <Route path="workflows" element={<WorkflowsTabPage />} />
</Route>
```

At this commit, the per-tab page components don't exist yet — the app will not build. That's OK because Commit 3 creates them. You can stage Commit 2 and 3 together as a single logical step if you prefer (mention it in the commit message).

Footer: `Phase 4 — nav consolidation: extract mission-layout outer shell`.

### Commit 3: Create the per-tab page components

Create `modules/frontend/src/pages/mission/tabs/` (new directory) and add:

- `chat-tab-page.tsx` — the chat feed-mode renderer extracted from `workspace.tsx`. Includes the agent-pinned chat with `DEFAULT_CHAT_AGENT`, streaming assistant message handling, artifacts wiring.
- `plan-tab-page.tsx` — wraps `<PlanBoard missionId={id} />` from `components/workspace/plan-board.tsx`. Very thin — probably <20 lines.
- `narrative-tab-page.tsx` — extracts the narrative feed-mode renderer. Leave the Plan 41 spec drift alone; copy the current behaviour verbatim.
- `stream-tab-page.tsx` — reuses whichever component won the §4.1 decision (likely `ConsolePage` at the page level).
- `context-tab-page.tsx` — wraps whichever component won the §4.3 decision.
- `runs-tab-page.tsx` — wraps whichever component won the §4.2 decision.
- `workflows-tab-page.tsx` — wraps `<WorkflowsPanel missionId={id} />` from `components/workspace/workflows-panel.tsx`. Thin.

Each tab page component is a **page wrapper**, not a new component. Its job is to grab `missionId` from `useParams`, grab `id` from `useParams` if needed, and render the underlying feature component. Avoid adding new state, new hooks, or new styling at this layer.

Delete the old feed-mode switch statement from `workspace.tsx` if you haven't already.

**Crucial:** the legacy page components (`OverviewPage`, `TeamPage`, `ConsolePage` etc.) must **stop rendering their own page chrome**. Most of them have a top-level wrapper with padding, back button, etc. They're about to be rendered inside the new outer shell which already provides that chrome. Delete the outer wrapper from each legacy page component — leave only the inner content. This is where the risk of visual regression is highest, so eyeball each page in a browser before moving on.

Footer: `Phase 4 — nav consolidation: per-tab page wrappers`.

### Commit 4: Legacy page chrome cleanup

For each legacy page that stays (Overview, Team, Workflows legacy DAG drill-in):
- Remove the imported top bar / mission header — that's the outer shell's job now.
- Remove the back button — the tab bar replaces it.
- Remove any duplicate SSE subscription — the outer shell owns the single SSE connection.
- Remove any `useMission` call that's redundant with the outer layout's — OR, if the legacy page needs mission data, it can still call `useMission(id)` (react-query will de-dupe the fetch). Either is fine.

Footer: `Phase 4 — nav consolidation: strip legacy page chrome`.

### Commit 5: Delete deprecated files and constants

Anything that's now unreachable:
- The old `workspace.tsx` (if you renamed to `mission-layout.tsx`) or the old center-panel renderers if they lived in sibling files.
- Dead imports.
- Dead `FeedMode` type exports.
- Dead `ROUTES.WORKSHOP` / dead `ROUTES.FEED_MODE` constants.
- Unused `AGENT_ICONS` if it moved to a shared location.

Run `npm run build` and confirm the production build succeeds. Run `npx tsc --noEmit` and confirm only the three pre-existing unrelated warnings remain.

Footer: `Phase 4 — nav consolidation: delete dead code`.

### Commit 6: Deep-link compatibility + last-visited tab

- Add a `localStorage` read in `MissionLayout` that remembers the last-visited tab per mission. On root `/missions/:id` the `<Navigate>` element uses that value as the target (falling back to `chat` if nothing stored).
- On every tab switch, write the current tab id to `localStorage[`missions.lastTab.${id}`]`.
- Bookmark test: visit `/missions/abc/plan`, close tab, reopen — should land back on Plan.

Footer: `Phase 4 — nav consolidation: last-visited tab memory`.

---

## 6  Explicitly out of scope

The product owner was specific: this work ships structural consolidation, not new features. Do NOT do any of the following in this task:

1. **No backend changes.** No new API endpoints, no schema changes, no event type changes, no backend service edits. Every tab already has everything it needs from the backend.
2. **No Plan 45 Phase 4 workflow editor.** The Workflows tab stays on the placeholder `WorkflowsPanel` list view. The real React Flow editor is Plan 45 Phase 4 work and is not in this task. Legacy `WorkflowsPage` DAG viz remains the drill-in destination from the Edit button in `WorkflowsPanel`.
3. **No Plan 41 narrative feed reconciliation.** The Narrative tab renders whatever the current `workspace.tsx` narrative feed-mode renders. Tool-row grouping, tiered transparency, spec-drift resolution — all of that is a separate TODO.md item and not your problem. Copy the current behaviour verbatim.
4. **No redesign of Overview or Team internals.** The product owner said "keep them as-is". Strip their outer chrome per Commit 4 but do not touch the dashboard layout, card structure, or data flow.
5. **No new drawer patterns.** If `mission-settings-drawer.tsx`, `context-drawer.tsx`, `run-history-drawer.tsx` are uncommitted, finish the one that fits naturally (mission-settings is the obvious one to land as part of the outer shell's top bar). Leave the others alone — if they're destined to become tabs, they already are; if they're destined to be drawers, that can be a follow-up.
6. **No hook extraction beyond what's needed to move code between files.** Code-review item P10 proposes extracting hooks like `useStreamedAssistantMessage`, `useMissionEventRouter`, `useAgentChatSelection` from `workspace.tsx`. You MAY do that if it makes the layout extraction cleaner, but DO NOT do it gratuitously — this task is about structure, not hook-level refactoring. If you do extract hooks, mention in the commit message that P10 is partly folded in.
7. **No styling changes.** The 3-panel shell should look exactly the same after the refactor — same colors, same spacing, same collapsible behaviour. If you find styling bugs while refactoring, fix them in a separate commit with a clear "drive-by fix" note.
8. **No Workshop escape hatch.** Do not leave a redirect from `/missions/:id/workshop` to any other tab. Delete it entirely. If someone has an old bookmark it hits 404 — that's fine, the product owner confirmed.
9. **No SSE subscription changes.** The outer shell owns exactly one SSE connection per mission, same as today. Do not refactor the SSE fan-out to stores or change the `MissionStreamContext` shape. Just move it from `workspace.tsx` to `mission-layout.tsx` verbatim.
10. **No TypeScript version bump, no dependency bumps, no build config changes.** Anything that drags in a tooling change.
11. **No CI changes.** If the existing CI doesn't already catch something you're worried about, note it in the PR description but do not add new CI in this task.
12. **No tests written from scratch.** If the legacy pages had tests, keep them working (re-point imports after file moves). Do not add new tests for the new layout — the whole task is structural, and existing tests + manual smoke testing are the acceptance bar. Testing library coverage for the outer layout is a follow-up.

---

## 7  Verification — acceptance test (manual, no script this time)

Unlike Plan 47 (which had `scripts/verify_isolation.py`), this task cannot be automated with a script because the deliverable is a visual/navigation refactor. Do the following **manual smoke test** with the backend running (`python admin.py server start` or `uvicorn ...`) and the frontend in dev mode (`cd modules/frontend && npm run dev`):

1. **Open `/missions/:id`** with an existing mission ID. Expect: redirects to `/missions/:id/chat`, shows the outer shell (agent sidebar, chat in center, artifacts drawer collapsed on right, tab bar with 9 tabs, `Chat` tab highlighted).
2. **Click every tab in order.** Overview → Team → Chat → Plan → Narrative → Stream → Context → Runs → Workflows. For each:
   - URL updates to `/missions/:id/{tab}`.
   - Active tab highlight moves.
   - Center content changes to the tab-specific component.
   - Outer shell (agent sidebar, top bar, artifacts drawer) is visually unchanged.
   - No console errors, no failed requests.
   - Browser back button returns to the previous tab.
   - Browser forward button re-advances.
3. **Bookmark `/missions/:id/runs`**, close the tab, open the bookmark. Expect: lands on the Runs tab inside the new shell. The last-visited tab memory should not override a direct URL visit.
4. **Visit `/missions/:id` fresh** (no sub-path). Expect: redirects to the last visited tab (if any in localStorage) or `chat` (if nothing stored).
5. **Visit `/missions/:id/workshop`.** Expect: 404 or "Not found" page. Do not redirect to another tab — the workshop route is gone.
6. **Switch tabs while streaming is active.** Kick off a chat message or a plan dispatch in one tab, switch to another tab mid-stream, switch back. Expect: the stream state is preserved (artifacts still populate, no duplicate SSE connection opened — check network panel).
7. **Open the run detail page** at `/missions/:id/runs/:runId`. Expect: renders the existing `RunLivePage` either inside the outer shell (if you decided to keep it there) or standalone (if you decided drill-ins escape the shell). Either is acceptable — document the choice.
8. **Open mission-settings-drawer** from the top bar (if finished). Expect: drawer slides in from the right, shows mission-level config (gate mode, budget, autonomy), can be dismissed without nav change.
9. **Test on a mission with zero runs** to confirm empty states still render.
10. **Test on a mission with active autonomous run** to confirm the roster panel, streaming artifacts, and plan kanban all still update live across tab switches.

If any of 1–10 fails, do NOT land the refactor — iterate until all pass.

Also run these **automated checks** before committing:

- `cd modules/frontend && npx tsc --noEmit` — zero new errors.
- `cd modules/frontend && npm run build` — production build succeeds.
- `cd modules/frontend && npm run lint` — zero new warnings (preserves the `--max-warnings 0` ratchet).
- `grep -rn "feedMode\|setFeedMode\|FEED_MODES\|FeedMode" modules/frontend/src/` — returns zero matches after the consolidation. If any remain, either finish the removal or add a `// TODO: reach this in the next pass` comment explaining why.
- `grep -rn "workshop" modules/frontend/src/ --include='*.ts' --include='*.tsx'` — returns zero mission-scoped matches (unrelated uses of the word are fine).

---

## 8  Anti-goals — things you must NOT do

(In addition to the scope cuts in §6, which are about what this task doesn't include. These are patterns/behaviours to avoid while doing the task.)

- **Do NOT** start "improvements" in adjacent files while you're touching them. If you spot tech debt, file it in `TODO.md` with a brief note; don't fix it here.
- **Do NOT** rename the route paths. They must be literally `/overview`, `/team`, `/chat`, `/plan`, `/narrative`, `/stream`, `/context`, `/runs`, `/workflows`. No `/dashboard`, no `/board`, no `/feed`. Bookmarks and muscle memory matter.
- **Do NOT** change the tab bar visual design. Copy the exact styling from the existing legacy tab bar in `workspace.tsx` or the legacy page chrome, whichever is more polished. A visual redesign is separate work.
- **Do NOT** replace React Router primitives with custom navigation. Use `<Outlet />`, `<Navigate>`, `useLocation`, `useNavigate`, `useParams` — standard library primitives only.
- **Do NOT** move `stores/workspace.ts` slices around except removing `feedMode`. The other slices stay where they are.
- **Do NOT** touch `stores/console.ts`. It's used by the Stream tab (and likely the Console legacy page that you're merging). Leave it alone.
- **Do NOT** add a fancy transition animation on tab change. Plain swap. Animations are Phase 4 polish work.
- **Do NOT** reach into the backend to "fix" anything you notice. Frontend-only refactor.
- **Do NOT** skip the visual regression smoke test (§7 steps 1–10). The whole risk of this task is "everything still works, just in a slightly different shape", and the only way to catch regressions is to actually click through every tab.

---

## 9  Deliverables

When you hand control back, produce:

1. **A sequence of commits on a feature branch** (`feat/mission-nav-consolidation` or similar). Each commit follows the §5 plan and has a `Phase 4 — nav consolidation: <description>` footer. The footer is important for `git log --grep "Phase 4 — nav consolidation"` discoverability.
2. **An updated `TODO.md` entry** — find the "Consolidate mission navigation" item and mark it as `[x]` DONE (or remove it and add a one-line close-out in the existing code-review P10 entry explaining that this refactor subsumed P10).
3. **An updated Plan 46** — find the `§5 Deferred-from-phase tracker` entry for this task and mark it DONE with a dated close-out note citing the commit range.
4. **A short handoff note** in the final commit body or in `/tmp/mission-nav-consolidation-handoff.md` covering:
   - What you actually shipped vs what the plan said.
   - Decisions you made on §4.1 (Stream vs Console), §4.2 (Runs), §4.3 (Context).
   - Any visual regressions you spotted and fixed.
   - Any that you intentionally left for later, and where they're tracked.
   - Confidence level that every tab still works (honest assessment — did you actually click through all 9 tabs on a real mission with data, or just check the happy path).
   - Whether you folded any of P10's hook extraction into this work.
5. **PR description** summarising the refactor, linking to this prompt, and including:
   - A screenshot of the before state (legacy tab bar + new workspace in parallel).
   - A screenshot of the after state (outer shell + tab bar + center content).
   - A bullet list of the 9 tabs with "works ✓" next to each.
   - The list of files deleted (workshop + anything else made redundant).

The person you're handing this back to will be looking for: **(a) zero behavioural regressions** — every tab works exactly as it used to, just inside the new shell; **(b) the tab bar actually replacing the Zustand feed-mode toggle** — no dead `feedMode` code left behind; **(c) a clean deletion of Workshop** — no stubs, no dead imports, no 500-line leftover file; **(d) one SSE connection per mission, not nine** — verified in the browser network panel.

Good luck. The scope is tight and the design is already settled — your job is to execute the refactor cleanly without drifting into the adjacent rabbit holes that this codebase has plenty of.
