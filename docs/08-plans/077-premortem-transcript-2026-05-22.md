# Premortem Transcript — Plan 77 (UK Client Onboarding Demo)

**Date run:** 2026-05-22
**Plan target:** [77-plan-demo-uk-onboarding.md](077-plan-demo-uk-onboarding.md)
**Method:** Klein-style premortem (8 parallel deep-dives)

---

## Context

**What it is:** A demo-grade vertical (six agents, Plan 75 composable workflow, five mock tools, three synthetic fixtures) that walks executives through how the platform decomposes a UK client onboarding case across makers + QA + human gates.

**Who it's for:** Executive stakeholders. Live walkthrough. NOT real customers, NOT regulated, NOT production.

**Success:** Presenter clicks "Start Onboarding", runs the three fixtures end-to-end (straight-through / single gate / four-eyes), lands on an evidence artifact + cost summary. Zero regressions to the rest of the platform.

**Frame set:** It is 2026-11-22. The demo is dead. We are looking back to understand why.

---

## Raw premortem — 8 failure reasons identified

1. Plan 75 convergence semantics at `assemble_case` / `record_rejection` are not as assumed; the workflow won't run.
2. Chat trigger via `match_patterns` cannot supply the applicant context the agents require.
3. GAPS.md's radical honesty backfires when read by hostile / external audiences.
4. Live demo breaks on stage due to SSE reconnect / JWT race condition.
5. Four-eyes "same person clicks twice" approximation is called out live by a compliance-aware audience member.
6. Operator forgets the `admin seed-catalog --force` first-time setup; demo dies at dispatch.
7. The `mission.supervisor.agent` "REUSE-WITH-CONFIG" claim is wrong; deeper coupling than the audit found.
8. Demo gets built but never lands — no exec sponsor, no committed date, opportunity cost wasted.

---

## Deep-dives

### #1 — Plan 75 convergence assumption is wrong

**Story.** Day 3 of implementation. Engineer wires `assemble_case` as a plain `agent_step` with three decision-routed predecessors. Local smoke test against the clean path: `route_qa` returns the `pass` branch, the other two get marked `_skipped` by wave routing. `assemble_case` never runs. Status: SKIPPED. Engineer opens `workflow_run_waves.py:1208` and reads the docstring: *"ANY of its dependencies was itself skipped (propagation). Exception: merge nodes never propagate skips."* §13 Q7 was supposed to catch this — but the deep-research template doesn't actually have multi-decision convergence on a non-merge node, so the "reference precedent" was a phantom.

Three panic options surface. (a) Convert convergence nodes to `node_type: merge` — but merge is join-only, can't execute the assembly logic, so you need merge + downstream agent step, blowing up the clean three-path diagram. (b) Patch `_should_skip` four days before a live demo — touches shared wave engine, risks regressing deep-research + architecture-review. (c) Collapse to linear path with inline `condition` guards — loses the parallel-branch visual that was the whole reason for choosing Plan 75. Team picks (a) under pressure. Demo runs, but architect spends the first five minutes explaining why there are six rectangles where the slide shows three.

**Underlying assumption:** That decision-node skip propagation is graph-aware (a skipped branch satisfies its successor), when in fact `_should_skip` propagates skips through any non-merge dependency unconditionally.

**Early warning signs:**
- First dry-run convergence step shows `SKIPPED` despite a predecessor branch completing.
- Grep of `config/workflow_templates/*.yaml` for steps with `depends_on` listing 2+ decision/condition nodes returns zero hits on non-`merge` node types.

---

### #2 — Chat trigger broken (context-loading gap)

**Story.** Demo shipped on time. UI worked beautifully — fixture loaded, applicant injected, agents produced KYC verdicts that read like real compliance write-ups. Two weeks later a senior PM tried the "other path" during a stakeholder walkthrough: typed "demo onboard uk" in chat. Director matched `match_patterns`, called `run_workflow("demo.uk-onboarding")` with `context_overrides=None`. The workflow launched with the template's default `context: {applicant: {}, fixture_name: "", jurisdiction: ""}`. First agent ran KYC against an empty applicant dict and confidently produced a verdict for "John Doe, address unknown, DOB unknown" — hallucinated end-to-end. The stakeholder noticed. The PM didn't.

Three weeks later, retrofit options were proposed: (a) resurrect `fixture_loader` as a tool — undoing the §quality-review fix, and chat still can't specify which fixture. (b) Parameterise `match_patterns` — Director-side change touching `run_workflow`'s `dict[str, str]` signature (fixture is nested object, not flat string), plus conversation-state parameter prompting. Neither cheap. Team quietly removed `match_patterns`. "UI + chat" became "UI only" in a README diff nobody read.

**Underlying assumption:** That `match_patterns` is equivalent to the UI trigger, when it's actually a context-free pattern match — can launch a workflow but cannot supply the structured parameters a templated workflow needs.

**Early warning signs:**
- `run_workflow`'s signature is `context_overrides: dict[str, str] | None` — flat string dict, can't carry nested `applicant`.
- Template defines `parameters:` but `match_patterns:` has no parameter-binding mechanism.

---

### #3 — GAPS.md becomes the vendor's kill-shot

**Story.** November 2026. Team was invited to present Mission Control to the CRO's office at a UK challenger bank — warm intro from a board member, the kind of meeting that turns into a paid pilot. Two days before, an analyst on the bank's vendor risk team did her pre-read: GitHub repo (shared for transparency), docs folder, plan artefacts. She found `77-gaps-demo-uk-onboarding.md`. She didn't read the plan. She didn't watch the demo video. She copy-pasted §17 into a one-page memo titled "Vendor Self-Disclosure: Mission Control" and sent it with one line: "Their own document calls two of six agents 'LLM theatre' and the audit trail 'not immutable'. Recommend we decline."

The CRO never took the meeting. The board member who'd made the intro got a polite note back referencing "material concerns raised in the vendor's own documentation" and stopped returning calls. Internally, a skeptical exec lobbying for buy-vs-build forwarded the same §17 to the steering committee under "Per the team's own assessment". The phrase "LLM theatre" — written by us, about us — became the meme that defined the project in three rooms we weren't in.

**Underlying assumption:** That the audience for "radical honesty" would always be the original team and a charitable executive in the same room — never a hostile reader, a procurement gatekeeper, or a screenshot taken out of context.

**Early warning signs:**
- GAPS.md uses rhetorical flourishes ("roast", "theatre", "illustrative only") rather than neutral engineering language ("demo-scope", "stub", "representative").
- No one asks "who else might read this, and what would they screenshot?" before committing it to a repo shared outside the core team.

---

### #4 — Live demo SSE reconnect loses gate event

**Story.** Twelve minutes into the `adverse_media` walkthrough, the JWT minted at presenter login crosses its expiry while the SSE stream is mid-flight. Next heartbeat triggers backend to close. `useFetchSse` exits its loop, sets `connected = false`, enters reconnect path. Reconnect hits a 401, calls `refreshTokens()`, then `setTimeout(r, backoff)` before retrying — minimum 1s, doubling.

During the reconnect gap, the workflow keeps emitting events the browser is no longer subscribed to. SSE has no replay on this codepath — new connection picks up *future* events only. The `GateApprovalRequested` event for the second approver has already been emitted and lost. `GateApproval` component never mounts. The Approve button never appears. Workflow sits in `WAITING_FOR_APPROVAL` with nothing to click. Presenter says "give it a moment" three times, then refreshes — forty seconds of dead air in front of execs.

**Underlying assumption:** SSE event delivery is reliable enough that the frontend has no replay-from-cursor mechanism — reconnect resumes from "now," not from the last seen event ID.

**Early warning signs:**
- Backend SSE endpoint does not accept `Last-Event-ID` header or `?since=` cursor; frontend never sends one.
- JWT TTL is short enough that any demo run longer than the access-token lifetime will hit the 401-refresh branch at least once.

---

### #5 — Four-eyes credibility collapse

**Story.** 34 minutes into the adverse_media walkthrough. Presenter clicks "Approve" on the first gate, then — without changing user, without moving the mouse to a different window — clicks "Approve" on the second gate. Both approvals attributed to the same session. Sarah Whitfield, a former PRA supervisor now on the prospect's risk committee, leans forward. Doesn't interrupt. Waits for the presenter to finish the disclaimer, then asks evenly: "So what I just watched isn't four-eyes. It's one person clicking twice and the system letting them. Is the dual-control enforcement a roadmap item, or does the platform genuinely not model identity separation?" Presenter says *both* — the worst possible answer.

Two weeks later the screen recording surfaces in the prospect's compliance Slack with the timestamp pinned to the double-click. Verbal disclaimer is not in the recording. A second-line compliance officer who wasn't in the room writes: "they're calling this four-eyes." Deal stalls in legal review for SMCR attestability questions the platform was never designed to answer. Three other prospects in the same vertical hear the story through the London fintech grapevine within a month. The demo's signature feature becomes the reason the platform is filed under "not regulated-ready."

**Underlying assumption:** That a verbal disclaimer can neutralise a visual demonstration of a regulatory control being violated, in front of an audience trained to trust what they see over what they're told.

**Early warning signs:**
- During dry-run, a non-compliance reviewer says "wait, you just clicked it yourself twice?" — and the team rationalises rather than redesigns.
- The GAPS.md entry for four-eyes is written defensively (long justification paragraph) rather than crisply.

---

### #6 — The two-step seed trap

**Story.** Flag flipped at 13:47. Cara, the platform owner, had been told this was the "one-line enablement". She set `DEMO_UK_ONBOARDING_ENABLED=true`, restarted, clicked the tile. Tile rendered. "Start Onboarding" form posted cleanly. Temporal workflow ID came back. Four seconds later: `AgentNotFoundError: demo.uk.onboarding.supervisor.agent`. She refreshed. Same. Checked the flag — true. Checked the YAMLs — present. Checked `agent_catalog` — empty for `demo.uk.*`. The toggle-only seeder had run successfully, logged "0 entries updated", and exited 0. No alarm, no warning. The RUNBOOK mentioned `admin seed-catalog --force` on page 2 in a paragraph titled "First-time setup" she'd skimmed because the email said "just a flag flip."

Exec walkthrough was at 14:00. She paged the demo author at 13:54. He was on a flight. Tried `admin seed-catalog --force` at 13:57 but didn't have the prod admin token cached; IAM round-trip took six minutes. Execs saw a spinning loader and a broken tile.

**Underlying assumption:** That a two-step enablement procedure (seed-then-toggle) will be reliably executed in the correct order by an operator who treats "enable the demo" as a single atomic action.

**Early warning signs:**
- Toggle-only seeder logs "0 entries updated" on success — indistinguishable from "rows already correct" vs "rows don't exist."
- Flag-to-tile path has no startup validation that the referenced catalog rows exist; failure surfaces only at dispatch time.

---

### #7 — Supervisor reskin breaks on semantics, not surface

**Story.** Audit looked at `agent.yaml` and saw "supervisor — Haiku, three tools, structured output" and concluded the demo could swap the prompt and tool list. Six months in, implementer discovered the truth: `mission.supervisor.agent` is not a *shape*, it is a hardwired *post-run autonomy classifier*. Its `create_event_agent` factory returns `SupervisorDecision` — a closed enum of `wait | advance | refine | propose-complete | escalate` — meaningless for a UK onboarding triage step. All three "reusable" tools (`get_plan`, `get_recent_run_outcomes`, `get_past_decisions`) hardcode-import `plan_introspection` and `supervisor_introspection` adapters that key off `mission_id` and assume a `MissionPlan` row exists. The demo's workflow-template runs have no `MissionPlan` — every tool call returned `{"error": "..."}` and the agent hallucinated around empty introspection.

Implementer hit the predicted fork: option (b). Rather than admit the audit was wrong, retrofitted by stubbing the three tools with demo-specific shims, subclassing `MissionSupervisorDeps` to inject a fake plan_id, and forcing `SupervisorDecision` to be interpreted as a triage routing decision (`advance` ≈ "route to KYC"). Frankenstein result: YAML still claimed REUSE, but at runtime the demo had its own copy of every adapter, a parallel deps class, and a brittle mapping layer.

**Underlying assumption:** That "same agent shape" (LLM + tools + prompt) is equivalent to "same agent semantics," ignoring that `SupervisorDecision`'s closed output enum and `mission_id`-keyed introspection adapters are load-bearing for the autonomy loop.

**Early warning signs:**
- Plan does not specify which of the two factories (`create_event_agent` vs `create_agent`) it reuses.
- Plan never addresses what `SupervisorDecision`'s five-action enum means in a UK onboarding context.

---

### #8 — The demo nobody asked for

**Story.** November 2026. Plan 77 branch shipped clean in early June — thirteen commits, green CI, polished RUNBOOK, GAPS.md. Walkthrough tentatively scheduled for late June with two execs and a business sponsor. Slipped to mid-July (quarter-end). Then August (one exec on leave). Then "let's roll it into the September strategy offsite." At the offsite it got 8 minutes after lunch, in a graveyard slot, to an audience of the COO's chief of staff, two engineering leads, and a PM who already used the real tool. COO joined for the last 3 minutes, said "neat, send me the recording," and pivoted to the regulatory roadmap discussion that ate the next 90 minutes. No recording was ever requested. No follow-up.

Meanwhile the team that built it moved on. Plan 75 shipped a real customer-facing capability in August and consumed all the oxygen. By October, when a new BD lead asked "do we have anything that shows the onboarding story?", nobody could drive the demo cleanly — catalog_seeder had been refactored twice, gate.yaml shape had drifted, fixtures referenced a feature flag that had been renamed. Reviving it would take three days. It didn't happen. Q4 retro flagged "the two weeks on Plan 77" as an example of why we should require a signed exec commitment *before* demo builds.

**Underlying assumption:** That executive attention is a resource you can earn by building something impressive, rather than a calendar slot you must secure in writing *before* you write a line of code.

**Early warning signs:**
- No exec name on the plan as the requesting sponsor — only "executives" (plural, abstract).
- Walkthrough date is "TBD" or floating, not a fixed calendar invite predating commit 1.

---

## Synthesis

### Most likely failure
**#1 — Plan 75 convergence.** Verified against actual code. `_should_skip` propagates skips through any non-merge dependency. The workflow as designed cannot run. This kills the plan at the first integration test in commit 6 unless caught and redesigned with explicit `merge` nodes — which themselves break the clean three-path diagram that motivated choosing Plan 75 over a script.

### Most dangerous failure
**#5 — Four-eyes credibility collapse.** Happens in the demo's most distinctive moment, in front of the audience most equipped to weaponise it. Recording outlives the room. Word spreads through the London fintech grapevine. Becomes the platform's defining label — "fakes regulated controls" — in markets where this matters most. #3 (GAPS.md) is a close second; both share the same underlying flaw: the team optimised for in-room candour, ignoring the asymmetric downside of out-of-room interpretation.

### Hidden assumption
**Reuse is free.** The audit, the §quality-review, and this very plan are full of "REUSE-WITH-CONFIG" claims that turned out to be semantic mismatches at runtime: the supervisor (wrong output schema), `match_patterns` (wrong context-passing semantics), `_should_skip` (wrong convergence semantics), SSE reconnect (wrong replay semantics), `GateApproval` (assumed but not verified to fit the decision-node payload shape). Five of eight failures trace to "we looked at the function signature but not the behaviour around it."

### Revised plan — concrete amendments

1. **§10 workflow template** — Replace `assemble_case` and `record_rejection` predecessors with explicit `node_type: merge` join nodes, then chain the agent_step/tool_call after the merge. Update §13 Q7 from "verify in commit 1" to "redesigned to use merge nodes — verification still required to confirm merge node behaviour matches assumption."

2. **§10 trigger surface** — Remove `match_patterns` from the workflow template. UI-only trigger. Update §3 / §17 to drop the "chat trigger" promise. Document why in §13.

3. **§17 / GAPS.md tone-shift** — Replace "theatre", "roast", "illustrative only" with neutral language ("demo-scope", "stub", "representative"). Add `**Distribution: Internal team only.**` header. Decide explicitly whether GAPS.md ships to the repo or stays in a private wiki/Notion.

4. **§12.5 / SSE robustness** — Verify in commit 1 whether the SSE endpoint accepts a cursor. If not, either (a) extend JWT TTL to comfortably exceed longest demo run (e.g. 30 minutes), (b) add an `?after_event_id=` query param + cursor wiring in the demo page only, or (c) add a "Refresh / Resume" button to the demo page so the presenter has graceful recovery. Choose one before commit 1.

5. **§3 / §10 four-eyes** — Drop the four-eyes path entirely OR commit to real identity separation (two distinct test users with distinct sessions). Do not ship the one-person-clicks-twice version. The `adverse_media.json` fixture either simplifies to a single approval or requires the second approver to log in as a different user. **Recommendation: drop the four-eyes path; rename `adverse_media.json` to demonstrate something the platform can honestly do.**

6. **§6 / §11.3 seeder + §11.1 API** — Make failure modes loud:
   - Demo seeder logs `WARNING` when flag is on but zero demo agents found in catalog (not silent success).
   - API `POST /start` endpoint pre-flights: confirm all 6 demo agents exist in `agent_catalog` with `enabled=true` before launching. If not, return `503 Demo Not Seeded` with a clear instruction string. UI shows this instead of a generic spinner.

7. **§7.2 supervisor** — Drop the REUSE-WITH-CONFIG claim. Build the demo supervisor fresh, with its own output schema (no `SupervisorDecision` enum), its own deps (no `MissionSupervisorDeps`), and its own tools. Treat it as the sixth from-scratch agent. Saves the Frankenstein retrofit.

8. **§18 status checklist** — Add at top, **before** "User-approved plan":
   - `[ ]` Named exec sponsor committed in writing (sponsor: ________).
   - `[ ]` Fixed walkthrough date on calendar (date: ________).
   - `[ ]` If either above is empty, plan does not proceed to implementation.

### Pre-launch checklist (concrete, do before demo day)

1. **Before commit 1.** Get sponsor + date in writing. Read `_should_skip` and redesign convergence with `merge` nodes. Decide four-eyes outcome (drop vs. real separation).
2. **Before commit 5 (workflow template).** Build a one-off test workflow that exercises multi-decision-branch convergence in isolation. Confirm assumed behaviour. If the assumption fails again, redesign.
3. **Before commit 9 (frontend stream view).** Run a 20-minute demo in a browser tab and confirm the SSE stream survives a JWT refresh without losing a gate event. If it doesn't, fix before commit 10.
4. **Before demo day, T-24h.** Pre-flight script that verifies: all 6 demo agents present + enabled in agent_catalog, Redis up, no concurrent demo run in flight, presenter has admin token cached locally.
5. **Before demo day, T-1h.** Run all three fixtures end-to-end on the same backend the demo will use. If any path fails, do not present.
6. **Before GAPS.md is committed anywhere.** Second pair of eyes reviews tone. Strip rhetorical flourishes. Decide explicitly: repo, wiki, or burn.
