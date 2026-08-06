# Plan 86 — Hypothesis-Driven Code Security Review

**Version:** 1.4.0
**Date:** 2026-08-04 (v1.0) · revised same day after `/prompt-adversarial-review` (v1.1) and two
`/prompt-check-plan-quality` passes (v1.2, v1.3) an `output_reference` verification (v1.3.1) and `/prompt-premortem` (v1.4)
**Author:** Herman + Opus 5 design session
**Status:** Not started
**Depends on:** **Plan 78a (rename `security.webapp.*` → `security.code.*`) must merge first.** Nothing else.
**Supersedes:** Plan 78 (Code Security Review Mission) — its DAG and tool-driven premise.
**Unlocks:** A repeatable code security review where a senior analyst owns the threat model up front and the
finding verdicts at the end, and the platform does the work in between.
**Workflow:** Commit directly to `main`, one commit per phase, working code only (no PRs).

---

## 0. Problem Statement

A senior security analyst wants to run a whitebox (SAST) security review as a mission, with two
non-negotiable properties:

1. **An agent drafts a threat model first, and the analyst can rewrite it before any testing starts.**
2. **Every hypothesis in the approved model gets tested**, and the analyst verifies the findings at the end.

The analyst's time should concentrate at those two ends — shaping the model, and judging the results — not in
the middle.

### 0.1 Why Plan 78's premise does not serve this

Plan 78's DAG is `acquire → scan → mode-gate → triage → holistic/config-review → merge-findings → report →
baseline-diff → human-gate`. It is **tool-driven**: run the scanners, then triage whatever they emitted. Its
only human gate sits at the end, conditional on new URGENT findings. There is no threat model, no
pre-execution analyst influence, and no way to assert coverage of anything the scanners do not happen to flag.

A review whose scope is defined by tool output can only ever find what the tools find. This plan makes the
*threat model* define scope, and reduces the scanners to evidence-gathering instruments invoked in service of
a hypothesis.

Plan 78 is a draft and unbuilt. P3 applies: do not build the tool-driven spine and then invert it.

### 0.2 What already exists and is reused

Everything in this table was verified by reading the code. The right-hand column is the whole point of the
table — this plan's delta is small because most of it already exists.

| Requirement | Already in the tree | Reused |
|---|---|---|
| **Unified finding model** | `Finding` ([models.py:163](modules/backend/agents/security/models.py#L163)) — severity, OWASP category, CWE, file/line, evidence, PoC, `poc_validated`, `source_phase`, `source_tool`, remediation, CVSS/EPSS/KEV, `dedup_hash` | **Yes — +1 field.** See §0.3(g) |
| ~~Report synthesis~~ | `security.code.reporter` — **`output_type=str`; `SecurityAssessmentReport` never constructed in production** | **No — reversed in v1.4, constraint (n). New `hypothesis_reporter` with a validated schema, §6a** |
| **P17 incremental accumulator pattern** | `PlanBuildingSession` ([build_session.py:133](modules/backend/agents/mission/planning/build_session.py#L133)) + `register_planning_tools(agent)` | **Yes — pattern copied.** See §0.3(h) |
| ~~MCD as the threat-model store~~ | `MissionContext` — **20 KB hard cap, no pruning, atomic silent rejection** | **No — reversed in v1.4, constraint (k). Dedicated tables instead, §1.3** |
| Single-wave dispatch, no supervisor loop | `dispatch_approved(..., skip_post_run_supervisor=True)` ([mission_plan_dispatch.py:127](modules/backend/services/mission_plan_dispatch.py#L127)) | Yes — via a **fix** to the existing endpoint, §0.3(i) |
| SAST / SCA / secrets / container scanning | `security.code.scanner` + 9 capabilities | Yes |
| Tech-stack inventory | `detect_surface()` ([tool_registry.py:180](modules/backend/agents/security/tool_registry.py#L180)) | Yes, **as an agent tool only**, §0.3(d) |
| Container isolation + ROE + evidence hashing | [roe.py](modules/backend/agents/security/roe.py), [evidence.py](modules/backend/agents/security/evidence.py), `security-assessment-worker:latest` | Yes, via `agent_step` `environment: container` |
| Dynamic N-task execution in waves | Mission plan + `Task` DAG | Yes |
| Append a task without reconciliation | `MissionPlanService.add_task` ([mission_plan.py:491](modules/backend/services/mission_plan.py#L491)) | Yes, +2 params |
| Merge N upstream outputs into one input | `TaskInputs.from_upstream` accepts a list of refs | Yes |
| Per-task 3-tier verification, retry, cost ceiling | Existing dispatch pipeline | Yes |
| Versioned document + audit trail | Pattern copied from `MissionContext` + `ContextChange` into dedicated tables (§1.3) | Pattern only |
| Live workflow canvas with run status | `WorkflowEditor` + `useWorkflowRunStatus` | Yes |

**Deliberately not reused, with reasons:** `AssessmentState` ([models.py:85](modules/backend/agents/security/models.py#L85))
tracks pipeline run-state (phase, counts, cost) — this design does not duplicate run-state anywhere, because
`Task.status` is the single source of truth (P3 of the reference architecture). `CoverageMatrix`
([models.py:351](modules/backend/agents/security/models.py#L351)) models tested-vs-untested and already ships
inside `SecurityAssessmentReport` — the reporter continues to populate it; the live coverage strip (§7.2) is a
separate, cheaper view derived from task status, not a second model of the same data.

### 0.3 Seventeen engine constraints that shape this plan

Each was found by reading the code, and each killed a more obvious design. An implementer who does not know
them will reintroduce the broken version.

**(a) A workflow run cannot hand dispatch over to the plan mid-run.**
[`_persist_workflow_as_plan`](modules/backend/services/workflow_run.py#L442) mirrors workflow steps into
`Task` rows for Kanban visibility and sets `gate_mode = "workflow_managed"` so `find_ready_plans` skips the
plan. During a workflow run the plan is a **view**, not an executor.

**(b) The workflow engine has no loops.**
[`should_skip`](modules/backend/services/workflow_run_steps/helpers.py#L227) is forward-only skip propagation
over `depends_on`-derived waves. A `decision` node routes by *skipping* downstream steps whose edge label does
not match; a back-edge to a completed step does nothing. So the analyst's iteration loop cannot live inside
the workflow.

**(c) `POST /plan/dispatch` runs the full supervisor loop, which auto-approves everything.**
The handler is named `dispatch_approved` but calls `orchestrator.dispatch_autonomous()`
([missions_plan.py:297](modules/backend/api/v1/endpoints/missions_plan.py#L297)), starting a
`MissionRunWorkflow`. On `advance_approved` that workflow calls `approve_proposed_tasks(mission_id)` —
**mission-wide and unconditional** ([mission_run_workflow.py:196](modules/backend/temporal/mission_run_workflow.py#L196)).
Dispatching one boundary would approve and run every remaining hypothesis. See (i) for the fix.

**(d) `tool_call` nodes resolve names from `modules/backend/tools/` only, and have no container support.**
[`execute_tool_call_step`](modules/backend/services/workflow_run_steps/io.py#L83) resolves via
`get_tool_registry()`, which discovers only `modules/backend/tools/*.py` modules exporting `TOOL_DEF`, then
calls `impl(**resolved_args)` **in-process**. `security.detect_surface` lives in the *agent adapter* registry,
so a `tool_call` referencing it fails at runtime. Consequence: `detect_surface` is an agent tool, and there is
no `acquire`/`clone_repo` step at all (§0.6).

**(e) `reconcile_tasks` cancels any non-terminal task absent from the candidate plan.**
[task.py:171-216](modules/backend/repositories/task.py#L171). Since `_persist_workflow_as_plan` reconciles at
workflow *start*, running any workflow on a mission whose plan holds pending tasks **silently cancels them**.
A **pre-existing platform defect**; Phase 1.3 fixes it.

**(f) `resolve_upstream_inputs` raises `KeyError` when an upstream task has no output.**
[dag.py:58-70](modules/backend/agents/mission_control/dispatch/dag.py#L58). A report task depending on N
hypothesis tasks hard-fails if one failed. Combined with `approve_task` approving all transitive dependencies
([mission_plan.py:322](modules/backend/services/mission_plan.py#L322)) — one click on the report task would
approve every hypothesis and destroy boundary control — the report task must not be seeded upfront.

**(g) `Finding` is the unified finding model and the reporter already consumes it.**
Do **not** invent a hypothesis-specific finding schema. The hypothesis tester emits `Finding` with
`source_phase="hypothesis"` and `source_tool="security.code.hypothesis_tester"`. `source_phase` is a free
string, so this needs no schema change. The **only** schema delta is one optional field —
`hypothesis_id: str | None` — carrying the join key (D6). `Finding` reuse still holds; what did **not** hold is reusing the reporter that consumes it (constraint (n)). There is no reporter prompt revision in
this plan: the reporter's existing contract is already satisfied, including its `validated` requirement via
`poc_validated`.

**(h) `apply_updates` fails soft.** "Errors are logged and skipped — they do not fail the operation", returning
`(new_version, errors)`. Any writer built on it **must inspect `errors` and raise**, or a malformed threat
model persists silently under a fail-fast contract. Note the existing
[tools/update_context.py](modules/backend/tools/update_context.py) only logs a warning — do not copy that
behaviour here.

**(i) All three `/plan/dispatch` callers want single-wave semantics, and none of them get it.**
[use-mission-plan.ts:236](modules/frontend/src/hooks/use-mission-plan.ts#L236),
[mc_plan.py:285](modules/clients/cli/mc_plan.py#L285) (help text: "Dispatch all currently APPROVED tasks"),
and [mc_run.py:103](modules/clients/cli/mc_run.py#L103) — which reads `outcome_status` and `total_cost_usd`
off the response and prints "Retry complete", despite `dispatch_autonomous` returning immediately with a
workflow ID. It prints an outcome that has not happened. The autonomous path does not use HTTP at all
(`find_ready_plans` → `MissionRunWorkflow`). So the endpoint is simply wrong, and the fix is to correct it
rather than add a parallel one. Phase 3.4.

**(j) A refuted hypothesis fails verification unless the criteria are written to allow it — and the retry
loop then pressures the agent to fabricate a vulnerability.** This is the plan's most dangerous failure mode,
so the chain is documented in full:

1. Tester returns `verdict="refuted"`, `finding=None`.
2. **Tier 1** checks `field_name not in output` ([verification_tiers.py:67](modules/backend/agents/mission_control/verification_tiers.py#L67))
   — a *presence* check, so `finding: null` passes. But `model_dump(exclude_none=True)` would drop the key
   entirely and Tier 1 would FAIL.
3. **Tier 2** `validate_field_exists` uses the same presence semantics
   ([builtin.py:96](modules/backend/agents/mission_control/checks/builtin.py#L96)) — also safe.
4. **Tier 3** scores the output against `evaluation_criteria` and fails on
   `overall_score < min_score or blocking_issues` ([verification_tiers.py:291](modules/backend/agents/mission_control/verification_tiers.py#L291)).
   A criterion phrased as *"the vulnerability is confirmed with evidence"* scores a refuted result at 0.0 →
   **FAIL**.
5. A tier FAIL routes into `execute_with_retry`, which **retries with the failure text as feedback**
   ([retry_handler.py:61](modules/backend/agents/mission_control/dispatch/retry_handler.py#L61)). The agent is
   now told its output failed quality evaluation for not confirming the vulnerability — so its next attempt
   tries harder to find one. **This manufactures false positives.** In a security tool that is worse than a
   wrong status.
6. Retry budget exhausts → `TaskStatus.FAILED`.
7. The supervisor counts `TaskStatus.FAILED` ([supervisor_activities.py:144](modules/backend/temporal/supervisor_activities.py#L144))
   and may escalate or refine.
8. `create_report_task` (§3.5) only references COMPLETED tasks, so the hypothesis silently vanishes from the
   report — and the coverage strip shows `failed` instead of `clean`.

Every link is fixable, and none of the fixes require new platform capability — see §1.5, §3.3, §6 and §9.
Two existing properties work in our favour: Tiers 1 and 2 are presence-based, and the verification agent's
prompt rule 8 forbids inventing criteria beyond those supplied
([verification/system.md](config/prompts/agents/system/verification/system.md)), so Tier 3's behaviour is
fully determined by strings this plan writes in deterministic Python.

**(k) The MCD is a 20 KB hard-capped store with no pruning, and oversized writes are rejected atomically and
silently.** `pcd_max_size_bytes: 20480` ([missions.yaml:17](config/settings/missions.yaml#L17)). At
[mission_context.py:316](modules/backend/services/mission_context.py#L316), if the serialised document would
exceed the cap, `apply_updates` discards **the entire batch**, returns
`(current_version, ["MCD would exceed size cap…"])`, writes no `ContextChange` rows, and raises nothing. The
error message advises pruning; `ChangeType.PRUNE`/`ARCHIVE` are emitted nowhere in production code and
`_get_target_size()` has exactly one occurrence — its own definition. Both are dead.

A realistic 40-hypothesis threat model (8 boundaries, 15 assets, prose claim + test strategy per hypothesis,
task UUIDs) serialises to roughly 40 KB — about **2× the cap** — so only ~10 hypotheses would fit alongside a
modest seed MCD. This is why D5 was reversed in v1.4 and the model lives in its own table (§1.3). Note the
second-order hazard: any mission whose MCD sits near the cap has *every other* context writer failing soft —
`ContextCurator` logs a warning, the `update_context` tool reports "completed with errors", and
`summarization.py` discards the return value entirely.

**(l) `gate_mode: interactive` freezes the whole worker, and is one-way.** `MissionPlan.mission_id` is
`unique=True` ([mission_plan.py:68](modules/backend/models/mission_plan.py#L68)) — one plan per mission — so
`gate_mode` is mission-global mutable state. `dispatch_approved` builds the gate from it via
`create_gate(mode_override=plan.gate_mode)`, and `interactive` routes to `CliGateReviewer`, whose `_prompt`
calls bare synchronous **`input("\n> ")`** ([gate.py:323](modules/clients/cli/gate.py#L323)) with no TTY
check, no timeout and no cancellation. `gate.review()` fires at every `post_layer`, `post_task` and
`verification_failed`. Inside the headless backend or Temporal worker that blocks the entire asyncio event
loop — every mission, not just this one. It is also irreversible: `VALID_GATE_MODES`
([mission_plan.py:48](modules/backend/models/mission_plan.py#L48)) excludes `workflow_managed`, and the only
writer of that value is guarded to *preserve* `interactive`.

Therefore **this plan never writes `gate_mode`.** Boundary approval is task-status-driven (§3.3). Fixing
`CliGateReviewer` to check for a TTY and time out is correct platform hygiene and worth doing — but it is a
change to shared gate code every mission depends on, so it belongs in its own commit, not here.

**(m) `inconclusive` is not `clean`, and the tester's tools cannot decide many real hypotheses.** The seven
registered engines ([config/security/tools.yaml](config/security/tools.yaml)) are all static pattern matchers;
the only capabilities carrying `finding_confirmed` are Phase 2/3 and unregistered, so `get_primary` raises
`KeyError`. `list_files` rglobs **`*.py` only** ([list_files.py:34](modules/backend/tools/list_files.py#L34)),
`search_codebase` stops silently at 20 results, and `read_file` returns the *string*
`"Error: file not found"` rather than raising ([read_file.py:31](modules/backend/tools/read_file.py#L31)).
Authz, cross-tenant and race-condition claims are not decidable this way. Worse, constraint (j)'s cure makes
`inconclusive` the *cheapest passing verdict* — the criteria reward a well-argued one and the prompt forbids
revising under pressure. So this plan must treat `inconclusive` as a first-class outcome everywhere (§3.5,
§7.2, §7.3), gate hypotheses on testability before seeding, and cap the acceptable inconclusive ratio.

**(n) The existing reporter has no output contract.** `output_type=str`, and `SecurityAssessmentReport` is
never constructed in production code. Its required fields are unsuppliable here and its `CoverageMatrix` is
DAST-shaped. See §6a — this plan ships its own validated report schema rather than pretending the reuse works.

**(o) Tier 3 fails 100% of the time in current platform code.** `execute_agent` returns
`{"output": {...}, "_meta": {...}}` ([agent_executor.py:288](modules/backend/agents/mission_control/helpers/agent_executor.py#L288)),
but `_run_tier_3` reads `evaluation.get("overall_score", 0.0)` off that envelope without unwrapping
([verification_tiers.py:287](modules/backend/agents/mission_control/verification_tiers.py#L287)). So
`overall_score` is always `0.0` and `passed = 0.0 >= min_score` is always False — every task with
`requires_ai_evaluation=True` fails with `Score: 0.00`, and `cost_usd = evaluation.get("_cost_usd", 0.0)`
misses `_meta`, so verification spend is unbilled. The unit test mocks the flat shape production never emits,
so CI is green. **This must be fixed in platform code before any Plan 86 task enables Tier 3** — otherwise the
failure text becomes retry feedback and fires constraint (j)'s fabrication loop on every hypothesis at
`retry_budget=2` (three attempts each). Also: `min_evaluation_score` has conflicting defaults — `0.8` at
[verification_tiers.py:205](modules/backend/agents/mission_control/verification_tiers.py#L205) and `0.7` at
[task_plan.py:212](modules/backend/schemas/task_plan.py#L212) — and appears nowhere in `config/settings/`.

**(p) Container mode is disabled, and the container is a per-mission singleton.**
`container.enabled: false` ([environments.yaml:19](config/settings/environments.yaml#L19)), so no step of this
plan runs containerised today. When enabled, `get_or_create_for_mission` provisions **one** environment handle
per mission and hands it to every task, at `cpu_limit: 2.0` / `memory_limit_mb: 2048`. `_execute_layer` uses
`asyncio.gather` with **no semaphore**, so 30 hypothesis testers would `docker exec` into one 2 GB container,
each invoking semgrep, and all writing the same `/workspace/evidence/sarif`. Wave width must be bounded and
per-task evidence paths namespaced before this runs at scale.

**(q) A NULL `budget_usd_ceiling` turns a recoverable stop into batch corruption.**
`default_budget_ceiling_usd: null` ([missions.yaml:15](config/settings/missions.yaml#L15)), and the clean abort
— the one whose message says "Increase budget_usd_ceiling to continue" — is guarded by
`if plan.budget_usd_ceiling is not None` ([mission_plan_dispatch.py:185](modules/backend/services/mission_plan_dispatch.py#L185)),
so it never fires. The failure instead surfaces downstream *after* tasks flip to RUNNING, marking the whole
batch FAILED with a message blaming a "dispatcher bug", incrementing `retry_count`. The effective ceiling is
the single-workflow default of $10.00 ([workflows.yaml:21](config/settings/workflows.yaml#L21)) against a
realistic $39–60 for 30 tasks. `approve_and_seed` must therefore set an explicit ceiling (§3.3).

### 0.4 The resulting shape

```
PHASE A — workflow: security.code-threat-model.workflow   (ONE containerised agent_step)
┌────────────────────────────────────────────┐
│  threat_model  (agent_step, container)     │
│  reads target → ThreatModelBuildingSession │
│  → finalise() → ONE threat_models write    │
└─────────────────────┬──────────────────────┘
                      │ draft persisted, run COMPLETES
                      ▼
PHASE B — analyst owns the model. No workflow running, no timeout pressure.
   Threat Model tab: edit / add / remove hypotheses, discuss with the modeller
   (unbounded iteration — this is where the analyst spends their time)
                      │
   "Approve & seed"  ─┴─► POST /{mission_id}/threat-model/approve
                            N hypothesis tasks, PROPOSED, grouped by boundary
                            gate_mode UNTOUCHED (constraint l)
                      │
   approve a boundary ┴─► POST /{mission_id}/plan/dispatch   (FIXED, Phase 3.4)
                            single run, no supervisor loop
                            each task: hypothesis_tester → 3-tier verify → retry
                            confirmed ⇒ emits a `Finding`
                      ▼
PHASE C — Findings tab: analyst confirms / rejects each verdict
   "Generate report" ──► POST /{mission_id}/threat-model/report
                            ONE report task referencing only COMPLETED tasks
                            → existing reporter → security_report artifact
```

Phase A is a single node because constraints (b) and (d) removed the rest: no `decision` signoff (no loops),
no `recon` `tool_call` (wrong registry), no containerised `acquire` (no container support). `target_path` is a
workflow parameter, exactly as the shipped
[security.webapp-assessment.workflow.yaml](config/workflow_templates/security.webapp-assessment.workflow.yaml#L52)
does it.

**Residual risk, stated rather than hidden:** the initial draft runs containerised, but Phase B refinement chat
runs in-process (ADR-004: user-initiated chat is in-process), so the modeller re-reads target files outside
the container. It reads, never executes — the exposure is prompt injection via source comments, not RCE.
Acceptable for v1; revisit if targets become genuinely hostile.

### 0.5 Decisions taken during design (do not relitigate)

| # | Decision | Rationale |
|---|---|---|
| D1 | Recon is **surface inventory only** — `detect_surface` as a modeller tool, no vulnerability scan before the model. | Prevents tool-anchoring, where the "threat model" degenerates into scanner triage. |
| D2 | Plan 86 **supersedes Plan 78's spine**. | P3. Do not build a DAG you are about to invert. |
| D3 | **Whitebox only.** Blackbox/DAST is a follow-up plan. | Scanner/triage/reporter already run. Blackbox needs unbuilt WASA Phase 2 agents, egress allowlisting, live-target ROE. |
| D4 | Approval is **per trust boundary** via task approval status only — this plan never writes `gate_mode` (constraint (l)) — with individual approval for `intrusive` hypotheses. | 40 hypotheses at per-task approval means 40 clicks; the analyst switches to autonomous by hypothesis six and the control is lost. |
| D5 | **The threat model lives in dedicated `threat_models` / `threat_model_revisions` tables — NOT in the MCD.** Revised in v1.4 after the premortem. | The MCD is a 20 KB hard-capped store that rejects oversized writes atomically and fails soft (constraint (k)); a realistic 40-hypothesis model is ~2× the cap. And MCD injection into every agent's context was a token tax, not a benefit — the tester gets its own hypothesis via `inputs_json`. §1.3. |
| D6 | Hypothesis ID is the **join key** across model → task → finding, via `inputs_json.hypothesis_id` and `Finding.hypothesis_id`. | Without it you cannot distinguish tested-and-clean from never-tested, which is what signing off an assessment requires. |
| D7 | Approval and iteration happen **outside the workflow**, behind endpoints. Phase A is one-shot. | Constraint (b). Also avoids a durable pause timing out an analyst who wants to think for days, and gives `approved_by` a real authenticated user. |
| D8 | Seeding and report creation are **service methods behind endpoints**, not agents and not workflow `tool_call`s. | P2 — deterministic transforms needing `CurrentUser`, analyst-triggered. |
| D9 | Three distinct agents: modeller, tester, existing Tier-3 `system.verification.agent`. | P13 — the modeller must not mark its own hypotheses confirmed. |
| D10 | **No plan-DAG visualiser.** A coverage strip instead. | Hypothesis tests are independent by construction, so `depends_on` is empty for nearly all: the "DAG" is an edgeless fan. Revisit only if the modeller emits inter-hypothesis `depends_on`. |
| D11 | The report task is created **on demand after verification**, referencing only COMPLETED tasks. | Constraint (f). |
| D12 | Delete `dag-graph.tsx`. | Zero importers; superseded by `WorkflowEditor`. P3. |
| D13 | **Reuse `Finding`; do not invent a finding schema.** Drafting uses a `ThreatModelBuildingSession` copying `PlanBuildingSession`; it does **not** use `modules/backend/tools/` registry modules. | Constraints (g) and §0.3(h). Eliminates a duplicate schema, a reporter prompt change, and 40 redundant MCD writes per draft. |

### 0.6 Out of scope

- Blackbox / DAST / HTTP / browser testing. `security.web.*` stays reserved (D3).
- **Repository acquisition.** No `acquire` step, no `clone_repo` tool. `target_path` must already exist on
  disk. Cloning an arbitrary URL from inside the backend process with unrestricted egress is unacceptable in a
  security tool, and constraint (d) means a containerised `tool_call` is unavailable. If cloning is needed it
  is a separate plan that first builds container support for `tool_call` nodes.
- Plan 78's run-over-run **baseline diff** and fingerprint FP suppression. `Finding.dedup_hash` already exists
  to support it — a follow-up on this spine.
- Plan 78's `holistic` (26-CWE) and `config_review` agents. The hypothesis tester subsumes their role.
- A CWE registry. `Hypothesis.cwe` is a free string in v1.
- Editing a task's `instructions` before approval (no `PATCH /plan/tasks/{id}` exists). The analyst edits the
  *hypothesis* instead.
- Adding new hypotheses **after** approval. See §11.

### 0.7 Revision deltas

**v1.1** — from `/prompt-adversarial-review`, all verified against code:

| # | Finding | Change |
|---|---|---|
| 1 | `POST /plan/dispatch` runs the supervisor loop and auto-approves mission-wide — the trap v1.0 documented then walked into. | Constraint (c); resolved in v1.2 by fixing the endpoint. |
| 2 | `security.detect_surface` is not in the `tools/` registry; the `recon` node would fail at runtime. | `recon` deleted; `detect_surface` becomes a modeller tool. |
| 3 | Re-running Phase A silently cancels every seeded hypothesis. | Platform fix, Phase 1.3. |
| 4 | `source_field="finding"` named a nonexistent field. | Resolved in v1.2 by reusing `Finding`. |
| 5 | "Reuse the reporter unchanged" was false. | Resolved in v1.2 — reusing `Finding` makes it true. |
| 6 | Seeding the report task with N dependencies broke boundary control and hard-failed on one failure. | Report created on demand, D11. |
| 7 | `acquire` was a containerised `tool_call`, unsupported by the engine. | Acquisition removed from scope. |

**v1.2** — from `/prompt-check-plan-quality`, duplication and design-quality pass:

| # | Finding | Change |
|---|---|---|
| 8 | `Finding` already exists and the reporter already consumes it; `HypothesisFinding` + `EvidenceRef` duplicated it. | Both deleted. Reuse `Finding` + one `hypothesis_id` field. **The entire reporter-prompt phase is deleted** — v1.1's finding 5 was self-inflicted. |
| 9 | Five `modules/backend/tools/` registry modules reimplemented the accumulator pattern badly — 40+ MCD writes and version bumps per draft, no `finalise()` validation, registry pollution for single-agent tools. | Replaced by `ThreatModelBuildingSession` copying `PlanBuildingSession`. One MCD write per draft. |
| 10 | Adding `/plan/dispatch-wave` beside a broken `/plan/dispatch` left two endpoints where one correct one belongs. All three existing callers want single-wave and none get it — `mc run` prints an outcome that has not happened. | Fix the existing endpoint. New endpoint deleted from the plan. |
| 11 | Phase 1.2 speculated that MCD optimistic concurrency might need building. It already exists — but `apply_updates` **fails soft**. | Speculative work deleted; explicit raise-on-`errors` requirement added, constraint (h). |
| 12 | The plan appeared unaware of `CoverageMatrix` and `AssessmentState`. | Both acknowledged in §0.2 with reasons for not reusing them. |

**v1.3** — second quality pass, reviewing v1.2's own additions:

| # | Finding | Change |
|---|---|---|
| 13 | The `validate_hypothesis_verdict` Tier 2 check added in v1.2 **duplicated** the `HypothesisTestResult` `model_validator`. `output_reference` is the agent's own output dict ([convergence.py:435](modules/backend/agents/mission_control/dispatch/convergence.py#L435)), so `output_type=HypothesisTestResult` means PydanticAI already enforced every assertion before Tier 2 sees it — one invariant defined twice, in two enforcement languages. | Custom check deleted. Tier 2 uses the existing generic `validate_field_exists`; the invariant lives once, on the model (§1.5, §6). **No new check code.** |
| 14 | A security-domain check in generic `checks/builtin.py` would couple the platform check registry to a security schema. `register_check` is an open decorator, so domain checks belong in the domain package. | Recorded in §1.5 so nobody re-adds it there. Moot given 13. |
| 15 | `schemas/threat_model.py` would import `SeverityLevel` and `Finding` from `agents/security/` — **no file in `schemas/` imports from `agents/` today.** First layering inversion in the tree. | Types moved to `agents/security/threat_model.py`, a sibling of `models.py` (431 lines, so both stay near the ~500 target). `services/` → `agents/` is established precedent. |
| 16 | `TriageVerdict` is semantically parallel to the verdict enum and was not obviously considered. | Decision and reasoning recorded in §6: not reused, because triage judges a scanner *finding* while this judges a *claim*, and `Finding.triage_verdict` already carries the former. |

**v1.4** — `/prompt-premortem`. Eight parallel deep-dives, **all eight CONFIRMED IN CODE**:

| # | Finding | Change |
|---|---|---|
| 17 | The MCD is a 20 KB hard-capped store with no pruning that rejects oversized writes atomically and silently; a 40-hypothesis model is ~2×. D5 was unworkable. | Threat model moved to dedicated `threat_models` / `threat_model_revisions` tables (§1.3). Constraint (k). |
| 18 | `gate_mode: interactive` routes to a bare synchronous `input()` in the headless worker, freezing the event loop for every mission — and is one-way. | This plan never writes `gate_mode`; boundary control is task-approval-status only (§3.3). Constraint (l). |
| 19 | Tier 3 fails 100% of the time — `_run_tier_3` reads the score off an unwrapped executor envelope. Its unit test mocks the shape production never emits. | Platform fix promoted to HALT gate §0.2, with the test rewritten. Constraint (o). |
| 20 | The reporter has `output_type=str` and `SecurityAssessmentReport` is never constructed; its required fields are unsuppliable and `CoverageMatrix` is DAST-shaped. The v1.2/v1.3 reuse claim was hollow. | New `security.code.hypothesis_reporter` with a validated `HypothesisAssessmentReport` (§6a). Existing reporter untouched. Constraint (n). |
| 21 | `inconclusive` was folded into `clean`, hiding the most likely quality failure behind a green indicator — while the tester's seven static engines cannot decide authz or race claims. | `inconclusive` is first-class in §3.5/§7.2/§7.3/§6a; testability gate added at approve time (§3.3 step 7); Phase 8 caps the ratio. Constraint (m). |
| 22 | `default_budget_ceiling_usd: null` makes the recoverable budget abort unreachable, so an overrun marks a whole batch FAILED blaming a "dispatcher bug". Effective ceiling was $10 against a realistic $39–60. | `approve_and_seed` sets an explicit ceiling (§3.3 step 6). Constraint (q). |
| 23 | Container mode is `enabled: false`; when enabled, one 2 GB container is shared by all tasks behind an unbounded `asyncio.gather`. | Phase 0.4 enables it, caps wave concurrency, namespaces evidence paths. Constraint (p). |
| 24 | The Phase 8 canary used a nonexistent file, but `read_file` returns a soft error *string* — so the canary always passed while proving nothing. | Canary rewritten to assert something false about a file that exists. |

---

## Global constraints for the implementing agent

- **Read `AGENTS.md` and `docs/04-rules/*.jsonl` first.** `python scripts/code_rules_fast.py --all` must pass
  with zero new violations at every phase boundary.
- Absolute imports only. `get_logger` from `modules.backend.core.logging`, never `import logging`.
- `utc_now()` from `modules.backend.core.utils`. No `datetime.now()`, no `astimezone`.
- No hardcoded values — timeouts, ceilings, thresholds in `config/settings/*.yaml` via `get_app_config()`.
  **Fail fast if a required key is missing; never fall back to a literal.**
- No untyped `**kwargs` in public functions (rule 002.9).
- Files under 1000 lines, target ~500 (rule 002.2).
- Rule 014.1/014.2: an `except` block that logs error/warning where `mission_id` is in scope must also emit a
  mission event, and `logger.error`/`warning` must carry `mission_id`.
- API responses wrapped in `ApiResponse`; the frontend `unwrap()` reads `json.data`.
- Tests use real PostgreSQL and real Redis (P12). Mock only the LLM, via `TestModel` (P11).
- **Before writing any new function, check `.codemap/map.md` for an existing one.** This plan lost a duplicate
  schema, a duplicate endpoint and a wrongly-patterned tool layer to that check; assume more remain.
- **Resolve the uncommitted Plan 84 Phase 5.2 split first** — `mission_plan_orchestrator.py` is mid-split with
  unverified tests, and Phases 1 and 3 touch all three new modules.

---

## 1. Phase 0 — Prerequisite gates (platform fixes, before any Plan 86 code)

**0.1 — [Plan 78a](docs/08-plans/078a-plan-rename-security-webapp-to-code.md) must be merged:**
`security.webapp.*` → `security.code.*`.

**0.2 — Fix the Tier-3 envelope unwrap (constraint (o)). This is a HALT gate.** In `_run_tier_3`
([verification_tiers.py:287](modules/backend/agents/mission_control/verification_tiers.py#L287)), unwrap the
executor envelope before reading the evaluation, exactly as `retry_handler.py:353` does for task output:

```python
raw = await execute_agent_fn(...)
evaluation = raw.get("output", raw)          # was: read straight off `raw`
meta = raw.get("_meta", {})
overall_score = evaluation.get("overall_score", 0.0)
blocking_issues = evaluation.get("blocking_issues", [])
cost_usd = meta.get("cost_usd", 0.0)        # was: raw.get("_cost_usd", 0.0)
```

Then **rewrite the unit test**, which currently mocks the flat shape production never emits
(`tests/unit/.../test_verification.py`) — that fixture is why this has been green while broken. Add a test
asserting a realistic envelope yields a non-zero score and a PASS.

Until this lands, **no Plan 86 task may set `requires_ai_evaluation=True`**: Tier 3 fails unconditionally, and
its failure text becomes retry feedback that fires constraint (j)'s fabrication loop on every hypothesis.

**0.3 — Reconcile `min_evaluation_score`.** Two conflicting defaults (`0.8` in `verification_tiers.py`, `0.7`
in `task_plan.py`) and no key in `config/settings/`. Add the key, read it in one place, delete the literals
(rule 002.5).

**0.4 — Enable container execution** (`container.enabled: true`,
[environments.yaml:19](config/settings/environments.yaml#L19)) and **bound wave width** — `_execute_layer` uses
`asyncio.gather` with no semaphore, and the container is a per-mission singleton at 2 GB (constraint (p)). Add
a dispatch concurrency cap from config, and namespace evidence paths per task so 30 testers do not write the
same `/workspace/evidence/sarif`.

```bash
rg "security\.webapp" modules/ config/ tests/          # expect zero results
pytest tests/unit/backend/agents/mission_control/test_verification.py -v   # must fail before 0.2, pass after
python admin.py catalog detail security.code.scanner
```

---

## 2. Phase 1 — Schema, state access, and the reconciliation fix

### 1.1 `ThreatModel` schema

**New file:** `modules/backend/agents/security/threat_model.py` — **not** `modules/backend/schemas/`.

No file in `modules/backend/schemas/` imports from `modules.backend.agents` today, and these types need
`SeverityLevel` and `Finding` from
[agents/security/models.py](modules/backend/agents/security/models.py) — putting them in `schemas/` would
invert the dependency and be the first such violation in the tree. The security domain already lives in
`agents/security/` (`models.py`, `roe.py`, `evidence.py`, `config.py`), so these belong there. A sibling file
rather than an addition to `models.py` keeps both near the ~500-line target (`models.py` is at 431).

`services/` → `agents/` imports are established precedent (`session_memory.py`,
`mission_plan_orchestrator.py`, `workshop.py`, `catalog_seeder.py` and others), so the service and API layers
can import this freely.

Reuse `SeverityLevel` from [models.py:24](modules/backend/agents/security/models.py#L24). All models
`extra="forbid"`.

```python
class TrustBoundary(BaseModel):
    id: str                      # slug: ^[a-z][a-z0-9-]*$
    name: str
    description: str
    entry_points: list[str]      # "path/to/file.py:120" or a route pattern

class Asset(BaseModel):
    id: str
    name: str
    description: str
    sensitivity: Literal["public", "internal", "confidential", "regulated"]
    boundary_id: str             # → TrustBoundary.id

class Hypothesis(BaseModel):
    id: str                      # "h-001", stable, analyst-visible, the join key (D6)
    claim: str                   # falsifiable and specific
    boundary_id: str
    asset_ids: list[str]
    cwe: str | None
    test_strategy: str
    severity_if_true: SeverityLevel
    intrusive: bool = False      # true → individual approval required (D4)
    origin: Literal["agent", "analyst"]
    task_id: str | None = None   # set by approve_and_seed; None ⇒ not yet seeded

class ThreatModel(BaseModel):
    schema_version: int = 1
    model_version: int = 1
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    target_path: str             # persisted here; the workflow run context is gone by Phase 3
    boundaries: list[TrustBoundary]
    assets: list[Asset]
    hypotheses: list[Hypothesis]
```

**There is no `Hypothesis.status` and no hypothesis-specific finding model.** Seeded state derives from
`task_id`; test state derives from the task's status; findings are `Finding` (constraint (g)). One source of
truth for each fact.

**Referential integrity in a `model_validator`, not left to callers** (P14): every `Asset.boundary_id` and
`Hypothesis.boundary_id` resolves to a declared boundary; every `Hypothesis.asset_ids` entry resolves to a
declared asset; boundary, asset and hypothesis IDs are each unique. Raise on violation.

### 1.2 Add `hypothesis_id` to `Finding`

One field on [models.py:163](modules/backend/agents/security/models.py#L163):

```python
hypothesis_id: str | None = Field(
    default=None,
    description="Hypothesis this finding confirms (Plan 86). None for scanner-driven findings.",
)
```

Optional and defaulted, so every existing producer and `SecurityAssessmentReport` keeps working unchanged.
**This is the only change to the security models.** Do not add a parallel finding type.

### 1.3 Persistence — a dedicated table, not the MCD

Constraint (k). The MCD cannot hold this document, and injecting it into every agent's context was never a
benefit. Two new tables plus a repository and an Alembic migration.

**New file:** `modules/backend/models/threat_model.py`

```python
class ThreatModelRecord(UUIDMixin, TimestampMixin, Base):
    """One threat model per mission. The JSON payload is a validated ThreatModel dump."""
    __tablename__ = "threat_models"

    mission_id:   FK missions.id, ondelete CASCADE, unique=True, index=True
    model_json:   JSON, nullable=False        # ThreatModel.model_dump()
    model_version: Integer, nullable=False, default=1   # optimistic concurrency
    approved_by:  FK users.id, nullable=True
    approved_at:  DateTime(timezone=True), nullable=True   # rule 004.4

class ThreatModelRevision(UUIDMixin, TimestampMixin, Base):
    """Append-only edit audit trail — the ContextChange equivalent."""
    __tablename__ = "threat_model_revisions"

    threat_model_id: FK threat_models.id, ondelete CASCADE, index=True
    model_version:   Integer, nullable=False
    change_type:     Enum(ThreatModelChangeType, native_enum=False)   # ADD | REPLACE | REMOVE
    path:            String(200)              # e.g. "hypotheses.h-004.claim"
    old_value:       JSON, nullable=True
    new_value:       JSON, nullable=True
    reason:          Text
    actor:           String(200)              # agent name or user id
```

`Enum(native_enum=False)` stores by NAME — write uppercase members, never lowercase strings.

**New file:** `modules/backend/repositories/threat_model.py` — `ThreatModelRepository` with `get_by_mission_id`,
`create`, `update_with_version_check(mission_id, model, expected_version)` (raises on mismatch), and
`append_revisions`. Receives `AsyncSession` by injection (rule 005.2); no engine creation.

**New file:** `modules/backend/services/threat_model_state.py` — `ThreatModelStore`:

- `read(mission_id) -> ThreatModel | None` — `None` when no row exists (first run). **Raises if the row exists
  but `model_json` fails `ThreatModel` validation** — never treat corruption as absence.
- `write(mission_id, model, *, expected_version, actor, revisions) -> int` — validates the Pydantic model,
  writes the row and its revision rows in **one transaction**, bumps `model_version`, returns the new version.
  Raises on version mismatch.

**What this deliberately gives up, and why that is correct:** the MCD's automatic injection into every
downstream agent's context. Each hypothesis task already receives its claim, test strategy, boundary and
target path through `inputs_json` (§3.3 step 5), so the tester needs *its own hypothesis*, not the whole
model. MCD injection would have put the entire document into every agent's context window on every call for
the life of the mission — a permanent token tax masquerading as a feature.

**Alembic migration required** (rule 005.4): `python admin.py migrate autogenerate -m "Plan 86 threat models"`,
then review the generated script and write the downgrade.

### 1.4 Fix `_persist_workflow_as_plan` reconciliation scope (platform defect)

Constraint (e). `_persist_workflow_as_plan` generates fresh step UUIDs every run, so its `reconcile_tasks`
call exists only to clear the *previous run's* mirror rows — but reconciliation cancels every non-terminal
task in the plan, including tasks no workflow created.

**Failure this prevents:** an analyst approves a 40-hypothesis model, then runs any workflow on that mission.
All 40 PROPOSED tasks are cancelled silently, no error, no event.

**Fix:** tag mirrored tasks (`domain_tags` including `"workflow_mirror"`) and scope cancellation to tasks
carrying that tag. Non-mirror tasks are untouched. This is a pre-existing defect affecting every mission that
mixes workflow runs with a plan — fix it properly, not just for this plan's path.

`ThreatModelService` (Phase 3) additionally refuses to start Phase A when the plan holds tasks tagged
`hypothesis`, producing a clear error rather than a confusing re-draft.

### 1.5 Where the verdict invariant lives — one definition, not two

Constraint (j) needs the `HypothesisTestResult` shape guaranteed: verdict in the allowed set,
`confirmed ⇒ finding` present, `not confirmed ⇒ finding` null, join key matching, reasoning non-empty.

**That guarantee belongs on the Pydantic model and nowhere else** (§6). `output_reference` is
`raw_result.get("output", {})` ([convergence.py:435](modules/backend/agents/mission_control/dispatch/convergence.py#L435))
— the agent's own output dict. With `output_type=HypothesisTestResult`, PydanticAI validates it *including the
`model_validator`* before the dispatch pipeline ever sees it, so an output violating any of those assertions
cannot reach Tier 2. A custom Tier 2 check re-asserting them would be the same invariant defined twice, in two
enforcement languages — a P14 violation, and the Pydantic definition wins because it sits closest to the data
and fails earliest.

**Tier 2 therefore uses the existing generic check, with no new code:**

```python
DeterministicCheck(
    check="validate_field_exists",                    # already registered, builtin.py:74
    params={"fields": ["hypothesis_id", "verdict", "confidence", "reasoning"]},
)
```

That asserts something genuinely different from the model validator — that the *persisted projection* retained
the keys — and is exactly the presence semantics constraint (j) step 3 depends on.

**Two notes for whoever revisits this.** A security-domain check does not belong in
[checks/builtin.py](modules/backend/agents/mission_control/checks/builtin.py) even if one were needed:
`register_check` is an open decorator writing to a module-level `_REGISTRY` triggered by import
([checks/__init__.py:7](modules/backend/agents/mission_control/checks/__init__.py#L7)), and builtin.py holds
only generic primitives (`validate_json_schema`, `validate_field_exists`, `validate_field_type`,
`validate_field_range`). A domain check would live in `agents/security/`. And the refutation fix does not
depend on any of this — the load-bearing part is the verdict-neutral Tier 3 criteria in §3.3.

### Verification (Phase 1)

```bash
pytest tests/unit/backend/agents/security/test_threat_model.py -v
pytest tests/integration/backend/services/test_threat_model_state.py -v
pytest tests/integration/backend/services/test_workflow_plan_mirror.py -v
pytest tests/unit/backend/agents/security/test_models.py -v            # Finding back-compat
python scripts/code_rules_fast.py --all                                # 001.x: no schemas/ → agents/ import
```

Must cover: dangling `boundary_id` / `asset_ids` rejected; duplicate IDs rejected; reader returns `None` on
absent key and **raises** on malformed; writer **raises when `apply_updates` returns errors**; existing
`Finding` producers and `SecurityAssessmentReport` still validate with the new optional field. For 1.4: seed N
non-mirror tasks, run a workflow on that mission, **assert all N survive**, and assert the prior run's mirror
rows are still cleared.

The verdict invariant is tested with `HypothesisTestResult` in Phase 5, where the model lives — **all three
verdicts construct successfully**; `confirmed` with null `finding` raises; `refuted` with a non-null `finding`
raises; mismatched `hypothesis_id` raises; empty `reasoning` raises. The first of those is the unit-level
regression for constraint (j) and must exist before any tester code is written.

---

## 3. Phase 2 — `ThreatModelBuildingSession` and modeller tools

P17, following the pattern this codebase already established rather than inventing a second one (D13).

**New file:** `modules/backend/agents/security/code/threat_modeller/build_session.py`, copying the structure
of [build_session.py](modules/backend/agents/mission/planning/build_session.py):

```python
class ThreatModelBuildingSession:
    """In-memory ThreatModel assembly via incremental mutations.

    Mirrors PlanBuildingSession (Plan 69). Each mutation is validated
    eagerly; finalise() validates the assembled ThreatModel once and is
    the ONLY thing that writes to the MCD.
    """
    def add_trust_boundary(...) -> str
    def add_asset(...) -> str
    def add_hypothesis(...) -> str          # assigns h-NNN, origin="agent"
    def revise_hypothesis(...) -> str       # rejects if task_id is set
    def remove_hypothesis(...) -> str       # rejects if task_id is set
    def finalise() -> ThreatModel           # full validation, then one write
```

**New file:** `threat_modeller/tools.py` with `register_threat_model_tools(agent: Agent) -> None`, mirroring
`register_planning_tools`. Tools are `@agent.tool` closures reading the session off `RunContext` deps.

**Not** `modules/backend/tools/*.py` registry modules. That was v1.0's design and it was wrong on four counts:
40 hypotheses would mean 40+ table writes and 40 `model_version` bumps and 40 revision rows; there would
be no `finalise()` gate, so a half-built model with dangling references would persist; the registry is for
cross-agent reuse and these tools serve exactly one agent (P14 — extract on second use, not before); and the
"how does `mission_id` reach the tool" question disappears entirely because the session lives on deps.

Each mutation returns a short confirmation including the current hypothesis count, so the dynamic prompt can
show accumulated state (P17). Validation errors return **inline as tool result strings** so the LLM
self-corrects; genuine faults raise.

For Phase B refinement the same session is used, seeded from `ThreatModelStore.read(...)` instead of empty,
so the modeller sees the analyst's edits (verified in §10 step 4).

### Verification (Phase 2)

```bash
pytest tests/unit/backend/agents/security/test_threat_model_session.py -v
pytest tests/integration/backend/agents/security/test_threat_modeller_tools.py -v
```

Must cover: `finalise()` rejects dangling refs; `revise_hypothesis` / `remove_hypothesis` reject a seeded
hypothesis; **a drafting run producing 20 hypotheses results in exactly one `model_version` bump**; a session
seeded from an existing model round-trips analyst edits.

---

## 4. Phase 3 — Service, endpoints, and the dispatch fix

### 3.1 Extend `MissionPlanService.add_task`

[mission_plan.py:491](modules/backend/services/mission_plan.py#L491) already appends a PROPOSED task without
reconciliation. Add two explicit keyword params (no `**kwargs`, rule 002.9):

```python
domain_tags: list[str] | None = None,
verification: TaskVerification | None = None,
```

passed through as `domain_tags=` and `verification_json=verification.model_dump()`.
[`TaskRepository.create_task`](modules/backend/repositories/task.py#L83) already accepts both. That is the
whole delta — **do not add a new append primitive** (P14).

### 3.2 `ThreatModelService`

**New file:** `modules/backend/services/threat_model.py`, extending `services/base.py`.

### 3.3 `POST /{mission_id}/threat-model/approve`

**New file:** `modules/backend/api/v1/endpoints/missions_threat_model.py`. Also hosts the hypothesis
CRUD the Threat Model tab needs (§7.1) — those go through `ThreatModelBuildingSession` seeded from the current
model, so analyst edits get the same validation as agent edits.

`_require_mission_access` first. Declares `idempotency: Idempotency` — not because rule 009.1 strictly applies
(this creates rows, it does not dispatch) but because a double-submit produces an unrecoverable double-seed.
Body carries the `model_version` being approved.

`approve_and_seed(mission_id, *, model_version, approved_by)` — **one transaction**, fail loud at every guard:

1. Read the model. Raise if absent. Raise if `model_version` mismatches (the analyst cannot approve a model
   that changed under them).
2. Raise if zero hypotheses — seeding nothing is a silent no-op, not a success.
3. Raise if any hypothesis already has a non-null `task_id`.
4. Set `approved_by` and `approved_at = utc_now()`.
5. For each hypothesis, `add_task(...)`:
   - `agent="security.code.hypothesis_tester.agent"`
   - `description=h.claim`
   - `instructions` = a rendered brief: claim, test strategy, boundary, assets, CWE, and the explicit
     instruction that **refuted is a first-class outcome**, not silence.
   - `inputs={"hypothesis_id": h.id, "target_path": model.target_path, "boundary_id": h.boundary_id}`
   - `domain_tags=[h.boundary_id, "security", "hypothesis"]` — the boundary tag drives approval grouping (D4)
   - `dependencies=[]` — hypotheses are independent (D10)
   - `verification` = the **verdict-neutral** `TaskVerification` below
6. **Set `plan.budget_usd_ceiling` explicitly** — `N × per-task ceiling × (retry_budget + 1)`, with a floor
   from config. Constraint (q): leaving it NULL makes the *recoverable* budget abort unreachable, so a
   mid-assessment overrun instead marks the whole batch FAILED with a message blaming a "dispatcher bug". An
   explicit ceiling also makes the plan-board burn-down bar render, which is the analyst's only warning.
7. **Add a testability gate** (constraint (m)): reject any hypothesis whose `test_strategy` does not name a
   capability the tester actually has, at approve time rather than discovering it as an inconclusive verdict
   30 tasks later. Return the rejected list so the analyst can rewrite or drop them.

**The verification config is the single most important thing this method writes** (constraint (j)). It is
written here, in deterministic Python — not chosen by an LLM — which is exactly why the refutation risk is
controllable:

```python
TaskVerification(
    tier_1=Tier1Verification(
        schema_validation=True,
        # NOTE: 'finding' is deliberately absent. Tier 1 is a presence check, so a null
        # finding would pass — but omitting it means even a serialisation change to
        # exclude_none=True cannot fail a refuted result here.
        required_output_fields=["hypothesis_id", "verdict", "confidence", "reasoning"],
    ),
    tier_2=Tier2Verification(
        deterministic_checks=[
            # Existing generic check — no new code. The verdict/finding invariant is
            # enforced once, on the HypothesisTestResult model_validator (§1.5, §6).
            DeterministicCheck(
                check="validate_field_exists",
                params={"fields": ["hypothesis_id", "verdict", "confidence", "reasoning"]},
            ),
        ],
    ),
    tier_3=Tier3Verification(
        requires_ai_evaluation=True,
        evaluator_agent="system.verification.agent",       # never the tester (P13)
        min_evaluation_score=<from config>,
        evaluation_criteria=[
            "The verdict is one of confirmed, refuted, or inconclusive.",
            "The reasoning cites specific files and line numbers in the target that were actually examined.",
            "If the verdict is confirmed, the finding includes evidence, severity and remediation.",
            "If the verdict is refuted, the reasoning explains what was checked and why the claim does not hold.",
            "If the verdict is inconclusive, the reasoning states precisely what could not be determined and why.",
        ],
    ),
)
```

**Every criterion evaluates investigation quality; none evaluates outcome.** A criterion such as "a
vulnerability is confirmed with evidence" or "findings are present" would score a correct refutation at 0.0
and trigger the fabrication loop in constraint (j) step 5. The verification agent's prompt rule 8 forbids it
from inventing criteria beyond these, so this list fully determines Tier 3's behaviour.

These strings are a **hardcoded correctness invariant, not configuration** — do not move them to YAML where
they can be edited without a test run. `min_evaluation_score` is config; the criteria are code, and the
Phase 5 test suite is what protects them.

6. Write `task_id` back onto each hypothesis and persist in **one** `threat_models` write (§1.3).

**Do not touch `plan.gate_mode`.** Earlier drafts set it to `interactive` here; the premortem showed that is a
platform outage (constraint (l)). Boundary control comes entirely from **task approval status** plus the fixed
dispatch endpoint: the analyst approves a boundary's tasks, dispatches, and only APPROVED tasks run.
`dispatch_approved(..., skip_post_run_supervisor=True)` (§3.4) already prevents the supervisor from
auto-approving the rest, so **no gate is needed on the hypothesis path at all** — leave `ConfigurableGate` out
of it. That also means the mission is never wedged in a one-way mode and no mission-global state changes.

**No report task is created here** (D11).

Leaving `gate_mode` alone also resolves the ordering issue in constraint (a) for free: whatever
`_persist_workflow_as_plan` set at Phase A's start stays put, and `find_ready_plans` picks up only
`autonomous`/NULL, so no autonomous dispatch is triggered either way.

One transaction is load-bearing: a partial seed (tasks created, `task_id` not written back) makes step 3 raise
forever and wedges the mission.

### 3.4 Fix `POST /{mission_id}/plan/dispatch`

Constraint (i). **Change the existing endpoint; do not add a parallel one.**

```python
result = await orchestrator.dispatch_approved(
    plan.id,
    str(current_user.id),
    session_id=str(request_id),
    skip_post_run_supervisor=True,
)
```

The handler is already *named* `dispatch_approved` and its docstring already claims to dispatch approved
tasks; it just calls the wrong orchestrator method. `DispatchApprovedResponse` is unchanged, so all three
callers keep working — and two of them start working *correctly*: `mc plan dispatch` stops silently launching
the autonomous loop, and `mc run --retry` starts printing an outcome that actually happened.

Add `idempotency: Idempotency` — rule 009.1 genuinely applies; this fires agent execution.

**Verify each caller's intent before merging.** If `mc run` genuinely wants the looping behaviour, add an
explicit `?mode=autonomous` rather than reverting the default — the default must match the documented
contract. Leave a comment recording why `dispatch_autonomous` is not the default, because the method names
invite the mistake.

### 3.5 `POST /{mission_id}/threat-model/report`

Constraint (f), D11. `create_report_task(mission_id, *, requested_by)`:

1. Read the model. Raise if `approved_at` is None.
2. Partition the hypothesis tasks **four** ways by reading each task's `result_summary`:
   - **`confirmed`** — COMPLETED, `verdict == "confirmed"`. The only ones carrying a `Finding`.
   - **`refuted`** — COMPLETED, `verdict == "refuted"`. Tested and clean.
   - **`inconclusive`** — COMPLETED, `verdict == "inconclusive"`. **Tested but undecided — not the same as
     clean** (constraint (m)). Earlier drafts folded this into `clean`; that hid the plan's most likely quality
     failure behind a green indicator.
   - **`not tested`** — FAILED, CANCELLED, or still PROPOSED.
3. **Raise if all four are empty.** A run with zero confirmed but many refuted is a *valid and useful* report
   ("we tested 30 hypotheses and confirmed none"), so do **not** raise on empty `confirmed` alone.
4. Create one task: `agent="security.code.hypothesis_reporter.agent"` (§6a), `dependencies=[]`, and
   `inputs.from_upstream={"findings": [FromUpstreamRef(source_task=tid, source_field="finding") for tid in confirmed]}`
   — **`confirmed` only**, never all COMPLETED (see the note below).
5. Pass all four ID lists as `inputs.static` so the report's coverage table is computed from data rather than
   narrated, and return them to the caller so the analyst sees coverage before reading the report.

`dependencies=[]` is deliberate: all referenced tasks are already COMPLETED, so there is nothing to wait for,
and an empty dependency list means approving this task cannot transitively approve anything (constraint (f)).

**Why `confirmed` only, not all COMPLETED.** This was a defect in an earlier draft. A refuted hypothesis is
COMPLETED *by design* (constraint (j)) and its `finding` is `null`. Referencing every COMPLETED task would
resolve `findings` to a list like `[{...}, None, None, {...}]` — `resolve_upstream_inputs` returns whatever the
key holds, including `None`, so no error is raised. Filtering on verdict is what keeps the refutation design
and the report contract compatible.

**`source_field="finding"` is verified correct.** Traced end to end:
`agent_output = output.get("output", output)` unwraps the executor envelope at
[retry_handler.py:353](modules/backend/agents/mission_control/dispatch/retry_handler.py#L353); every
`output_reference=output` site is inside `_handle_verification_failure` / `_handle_post_task_gate`, whose
`output` parameter is bound to `agent_output` at the call sites (lines 374 and 397) — so `output_reference` is
the **unwrapped** `HypothesisTestResult` dict with `finding` at the top level. `write_back_task_results` stores
`json.dumps(output_reference)` in `result_summary`
([mission_plan_taskio.py:213](modules/backend/services/mission_plan_taskio.py#L213)); `load_prior_outputs`
reads it back with `json.loads` for tasks completed in earlier waves
([mission_plan_taskio.py:145](modules/backend/services/mission_plan_taskio.py#L145)); and
`resolve_upstream_inputs` then reads `source_output["finding"]`
([dag.py:66](modules/backend/agents/mission_control/dispatch/dag.py#L66)). `convergence.py:435` stores the same
unwrapped shape, so the two dispatch paths agree.

The same fact makes §7.2 and §7.3 correct as written: the coverage strip and Findings tab read
`json.loads(result_summary)["verdict"]` and `["finding"]` directly, with **no `["output"]` hop**.

### Verification (Phase 3)

```bash
pytest tests/integration/backend/services/test_threat_model_service.py -v
pytest tests/integration/backend/api/test_threat_model_endpoints.py -v
pytest tests/integration/backend/api/test_plan_dispatch.py -v
pytest tests/unit/clients/test_mc_run_retry.py -v          # the outcome-reporting regression
python scripts/code_rules_fast.py --all
```

Must cover: absent model raises; stale `model_version` rejected; empty model raises; N hypotheses → exactly N
tasks (**not** N+1); correct `hypothesis_id` and boundary `domain_tags`; `approved_by` is the authenticated
user; **`gate_mode` is unchanged from its pre-call value**; approve twice raises; mid-method failure rolls back completely; no
pre-existing task cancelled.

For 3.4, the single most important assertion in this plan: **approve two boundaries, dispatch, and confirm
every other boundary's tasks are still PROPOSED after the run completes.** Plus: the response carries a real
`outcome_status` and `total_cost_usd`, and no `MissionRunWorkflow` was started.

For 3.5: `source_field` resolves against real `output_reference`; failed hypotheses excluded and reported.

---

## 5. Phase 4 — `security.code.threat_modeller` agent

4-file contract per [003-agent-blueprint.md](docs/02-architecture/003-agent-blueprint.md).

| File | Content |
|---|---|
| `config/agents/security/code/threat_modeller/agent.yaml` | `security.code.threat_modeller.agent`, `agent_type: vertical`, `chat_enabled: true`, `model: copilot:claude-sonnet-4.6`, `temperature: 0.0`, `execution.mode: container`, `template: security-assessment-worker:latest` |
| `config/prompts/agents/security/code/threat_modeller/system.md` | System prompt |
| `modules/backend/agents/security/code/threat_modeller/agent.py` | `create_agent` / `run_agent`; calls `register_threat_model_tools(agent)`; thin wrappers only (P7) |
| Roster entry | Per the blueprint |

**Tools:** the session tools from Phase 2, plus `list_files`, `read_file`, `search_codebase`, and
`security.detect_surface` (constraint (d)).

`produces_artifact: false` — the model lives in the MCD (D5). `max_budget_usd` and `max_tokens` from config.

**Prompt requirements** — the main quality lever:

- Hypotheses must be **falsifiable and specific**, grounded in a real file path or route the modeller has
  actually read. "The app might have SQL injection" is worthless; "`GET /reports?tenant={id}` interpolates
  `tenant` into the query at `reports/dao.py:88` without parameterisation" is testable.
- **No speculative hypotheses about code the modeller has not read.**
- Work outward from trust boundaries and assets, not a CWE checklist — checklists produce generic hypotheses
  that waste tester budget.
- Set `intrusive: true` for anything expensive or side-effecting to test.
- State that a human analyst will rewrite this, and that the modeller does **not** test its own hypotheses or
  assess findings (P13, D9).
- `detect_surface` returns a **tech inventory only** — booleans for Python/JS/Dockerfile/Terraform, detected
  frameworks, entry points. It is not an attack-surface map. Say so, and require reading code to build the
  real boundary and asset picture.

### Verification (Phase 4)

```bash
python admin.py admin seed-catalog
python admin.py catalog detail security.code.threat_modeller
pytest tests/unit/backend/agents/security/test_threat_modeller.py -v      # TestModel, P11
python admin.py workshop run security.code.threat_modeller --inputs '{"target_path": "..."}'
```

Asserts tool wiring and that the finalised `ThreatModel` validates — not LLM quality (P11).

---

## 6. Phase 5 — `security.code.hypothesis_tester` agent

Takes **one** hypothesis, attempts to confirm or refute it, returns a structured result.

| File | Content |
|---|---|
| `config/agents/security/code/hypothesis_tester/agent.yaml` | `security.code.hypothesis_tester.agent`, `chat_enabled: false`, `execution.mode: container`, `template: security-assessment-worker:latest` |
| `config/prompts/agents/security/code/hypothesis_tester/system.md` | System prompt |
| `modules/backend/agents/security/code/hypothesis_tester/agent.py` | Agent module |
| Roster entry | Per the blueprint |

**Tools:** `read_file`, `search_codebase`, `list_files`, plus targeted scanner capabilities
(`security.code.scan`, `security.code.lint`, `security.deps.scan`, `security.secrets.detect`,
`security.load_sarif`). The scanners are **evidence instruments in service of a hypothesis**, not a blanket
sweep — the prompt must make that inversion explicit.

**Output schema** in `agents/security/threat_model.py` (§1.1) — reuses `Finding` (D13, constraint (g)) rather
than defining a finding type:

```python
class HypothesisTestResult(BaseModel):        # the agent's output_type
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    verdict: Literal["confirmed", "refuted", "inconclusive"]
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(min_length=1)
    finding: Finding | None = None            # agents.security.models.Finding
```

**This model's `model_validator` is the single authoritative definition of the verdict invariant** (§1.5) —
there is deliberately no second copy in a Tier 2 check. It must enforce all of:

| Assertion | Rationale |
|---|---|
| `verdict == "confirmed"` ⇒ `finding is not None` | A confirmed hypothesis with no finding is useless. |
| `verdict != "confirmed"` ⇒ `finding is None` | Stops a refuted result smuggling in a finding. |
| `finding.hypothesis_id == hypothesis_id` | Enforces the D6 join key. |
| `finding.severity`, `finding.evidence`, `finding.remediation` non-empty when present | `Finding` already requires these; assert the agent did not pass placeholders. |

Because `output_type=HypothesisTestResult`, PydanticAI enforces this at construction — a violating output
fails the agent run rather than reaching verification. The validator's error messages are what the retry
feedback shows the agent, so phrase them as instructions ("a confirmed verdict requires a finding with
evidence"), not as assertions ("finding must not be None").

The agent populates `Finding.source_phase = "hypothesis"` and
`source_tool = "security.code.hypothesis_tester"`.

**`TriageVerdict` was considered and deliberately not reused.** Its values
(`TRUE_POSITIVE`/`FALSE_POSITIVE`/`UNCERTAIN`) map onto this verdict set, but it judges whether a *scanner
finding* is real, whereas this judges whether a *claim about the code* holds. The reporter already keys off
`Finding.triage_verdict` for scanner findings, so overloading the enum would blur two distinct concepts at the
one place they meet.

This makes the `source_field="finding"` reference in §3.5 real, gives refuted hypotheses an explicit `null`,
and means the **existing reporter consumes the output with no prompt change** — the whole reason v1.1's
reporter-revision phase is gone.

**`refuted` and `inconclusive` are first-class successes, not failures.** A task that refutes its hypothesis
`COMPLETED` successfully. This is the mechanism behind D6 — tested-and-clean is a positive result and the
coverage strip depends on it.

Three prompt requirements enforce this, and they exist specifically to close constraint (j) step 5:

- State that **refuting a hypothesis is a complete and successful result**, of equal standing to confirming
  one. The analyst needs to know what was checked and found safe.
- State that a `refuted` verdict **must never be revised to `confirmed` in response to verification feedback
  unless new evidence from the code justifies it.** If verification pushes back, the correct response is
  better reasoning, not a different verdict. This is the direct guard against retry-driven fabrication.
- Require the reasoning to name what was examined — files, lines, call paths — so a refutation is auditable
  rather than a bare assertion. A refutation the analyst cannot check is worthless.

Set the retry budget for hypothesis tasks low in config. Even with correct Tier 3 criteria (§3.3), a low
budget bounds how many times a mis-scored refutation can be pushed back at the agent.

**Serialisation:** the output must **not** be dumped with `exclude_none=True`. Tier 1 and
`validate_field_exists` are presence checks, so dropping a null `finding` key would fail verification on
exactly the refuted results this design depends on (constraint (j) step 2).

`produces_artifact: false`. `scope.read` limited to `@workspace/target/` and the SARIF evidence dir;
`scope.write: []`.

### Verification (Phase 5)

```bash
python admin.py admin seed-catalog
pytest tests/unit/backend/agents/security/test_hypothesis_tester.py -v
python admin.py workshop run security.code.hypothesis_tester \
  --inputs '{"hypothesis_id":"h-001","claim":"...","test_strategy":"...","target_path":"..."}'
```

Must assert: all three verdicts validate; `confirmed` without `finding` rejected; `refuted` **with** a finding
rejected; mismatched `hypothesis_id` rejected; a `refuted` task reaches COMPLETED, not FAILED; the emitted
`Finding` validates against the **unmodified** `SecurityAssessmentReport` schema.

---

## 6a. Phase 5b — `security.code.hypothesis_reporter` agent and its schema

Constraint (n). The existing reporter cannot be reused: `output_type=str`
([reporter/agent.py:26](modules/backend/agents/security/webapp/reporter/agent.py#L26)) so nothing validates
its output, and `SecurityAssessmentReport` is **never constructed anywhere in production code** — its required
`roe_sha256`, `evidence_manifest_sha256`, `scanners_run`, `exploit_stage_reached` and `duration_hours` are not
supplied by this design, `AttackPath.source_findings` requires ≥2 linked findings that independent hypotheses
cannot produce, and `CoverageCell` requires `endpoint` + `auth_zone`, which are DAST concepts.

**New schema** in `agents/security/threat_model.py` — only fields this design can honestly fill:

```python
class HypothesisCoverage(BaseModel):
    hypothesis_id: str
    claim: str
    boundary_id: str
    outcome: Literal["confirmed", "refuted", "inconclusive", "not_tested"]
    finding_id: str | None = None       # set iff confirmed

class HypothesisAssessmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    target_name: str
    target_path: str
    assessment_date: str
    threat_model_version: int                    # exactly which model was assessed
    approved_by: UUID

    executive_summary: str = Field(min_length=200)
    confirmed_findings: list[Finding]             # reuses Finding (D13)
    coverage: list[HypothesisCoverage]            # one row per hypothesis, no exceptions
    boundaries_assessed: list[str]
    counts: dict                                  # {confirmed, refuted, inconclusive, not_tested}
    total_cost_usd: float
    known_limitations: list[str] = Field(min_length=1)
```

`coverage` must contain **exactly one row per hypothesis in the approved model** — a `model_validator`
enforces that against `counts`. This is the deliverable: it is the only artefact that can answer "did we test
what I asked for", and computing it from the four ID lists (§3.5 step 5) rather than letting the LLM narrate it
is what makes it trustworthy.

**New agent** `security.code.hypothesis_reporter` (4-file contract), with
`output_type=HypothesisAssessmentReport`, `produces_artifact: true`,
`artifact_type: security_report`. Its prompt must state that an inconclusive verdict is reported as
inconclusive and **never** as clean or as a finding, and that it may not populate `Finding` fields the tester
did not supply — no invented CVSS scores.

Verification for the report task: Tier 1 with `required_output_fields` covering the top-level keys; Tier 3
**off** (`requires_ai_evaluation=False`) — the schema is the gate, and constraint (o) means Tier 3 would fail
it unconditionally anyway.

The existing `security.code.reporter` is left untouched for the scanner-driven
`security.code-assessment` workflow. Two reporters, two honest contracts, no shared prompt to regress.

### Verification (Phase 5b)

```bash
python admin.py admin seed-catalog
pytest tests/unit/backend/agents/security/test_hypothesis_reporter.py -v
```

Must assert: `coverage` length equals the hypothesis count; a report whose `counts` disagree with `coverage` is
rejected; an all-refuted run produces a valid report with `confirmed_findings == []`; and
`HypothesisAssessmentReport.model_validate(artifact_content)` passes on the artifact actually persisted.

---

## 7. Phase 6 — The Phase A workflow

**New file:** `config/workflow_templates/security.code-threat-model.workflow.yaml`,
`workflow_name: security.code_threat_model.workflow`.

Parameters: `target_path` (string, **required** — the repo must already be on disk, §0.6), `target_name`
(string), `scope_notes` (text).

**One step:**

| id | node_type | detail |
|---|---|---|
| `threat_model` | `agent_step` | `capability: security.code.threat_modeller`, `environment: container`, `container_image: security-assessment-worker:latest`. Input: `target_path`, `scope_notes`. `condition: "@context.target_path != null"`. Drafts via the Phase 2 session, `finalise()` writes once. |

The step persists `target_path` into `ThreatModel.target_path` — Phase 3.3 needs it and the workflow run
context is gone by then.

The run **completes at the draft**. `approved_by` / `approved_at` are set by §3.3, which is why that endpoint
can supply a real authenticated user (D7).

A one-step workflow is still the right container: it yields a `WorkflowRun` record, event streaming, cost
ceiling enforcement, and containerised execution for the bulk read of untrusted code — none of which
in-process chat provides.

**No seeder registration needed** — [workflow_seeder.py:77](modules/backend/services/workflow_seeder.py#L77)
is `rglob("*.yaml")` over the templates dir.

### Verification (Phase 6)

```bash
python admin.py admin seed-workflows
python admin.py workflow detail security.code_threat_model.workflow
# Break a @node ref deliberately: WorkflowSchema.validate_steps must fail seed-workflows, not fail mid-run.
```

Then a real Phase A run: the step completes; the MCD carries a `threat_model` with boundaries, assets,
hypotheses and `target_path`; the run reaches COMPLETED without waiting on a human; **exactly one `model_version`
bump**.

---

## 8. Phase 7 — Frontend

### 7.1 Threat Model tab

New tab in `modules/frontend/src/pages/mission/tabs/`, following the thin-re-export pattern
([plan-tab.tsx](modules/frontend/src/pages/mission/tabs/plan-tab.tsx)).

- Left: trust boundary → asset tree.
- Right: hypothesis table — claim, CWE, boundary, `severity_if_true`, `intrusive`. Inline edit / add / remove
  via the §3.3 CRUD endpoints. Rows with a `task_id` are read-only.
- Version badge with a diff against the previous version, from `threat_model_revisions`.
- Chat panel bound to the modeller (`chat_enabled: true`). **This is the iteration loop** — the analyst stays
  here as long as they want, no workflow running, nothing timing out (D7).
- **"Approve & seed version N"** → `POST /{mission_id}/threat-model/approve` with the displayed version and an
  `Idempotency-Key`. Disabled once `approved_at` is set.

### 7.2 Coverage strip (D10)

Per hypothesis, one of `untested | testing | refuted | inconclusive | finding | failed` — **`inconclusive` is its own state, never folded into clean** (constraint (m)). Derived from the hypothesis's `task_id` status
joined with the verdict. The data is already on the wire:
[`TaskResponse`](modules/backend/schemas/mission_plan.py#L71) carries `inputs_json`, `status` and
`result_summary`, and `result_summary` holds the JSON `output_reference` containing `verdict` and `finding`.

This is a **live progress view**, distinct from the `CoverageMatrix` the reporter puts in the report artifact
(§0.2). Deriving it from task status keeps it free and current; do not invoke an agent to compute it.

### 7.3 Findings tab

Findings grouped by hypothesis, read from each task's `result_summary` JSON: verdict, confidence, reasoning,
and the `Finding` fields, with confirm / reject / needs-more-work controls. **Must also list hypotheses with
no finding**, distinguishing tested-and-clean from never-tested from failed.

**"Generate report"** → `POST /{mission_id}/threat-model/report`, then dispatch the created task. Surface the
excluded-hypothesis list so the analyst sees coverage before reading the report.

### 7.4 Boundary-level approval (D4)

In the Plan board's `proposed` column, group hypothesis tasks by their boundary `domain_tag` with an "Approve
boundary" action per group. `intrusive` hypotheses render outside the group action and need individual
approval. Then a **Dispatch** action calling the now-fixed `POST /{mission_id}/plan/dispatch` (§3.4).

### 7.5 Delete dead code (D12)

Delete `modules/frontend/src/components/workflow/dag-graph.tsx` — zero importers, superseded by
`WorkflowEditor`.

### Verification (Phase 7)

```bash
cd modules/frontend && npm run build && npx tsc --noEmit
rg "dag-graph" modules/frontend/src/     # expect zero results
```

---

## 9. Phase 8 — End-to-end verification

Against a real repository with known issues, already checked out on disk.

1. `mc mission create` → run `security.code_threat_model.workflow` with `target_path`.
2. Confirm the run COMPLETES, the tab renders boundaries/assets/hypotheses, and **only one `model_version` bump
   occurred** for the whole draft.
3. Edit one hypothesis, add one by hand (`origin: "analyst"`), remove one. Confirm `model_version` increments
   and `threat_model_revisions` records each edit.
4. Chat with the modeller about the edited model. Confirm it sees the analyst's edits in its session state —
   if it cannot, the iteration loop is broken and nothing downstream matters.
5. "Approve & seed". Confirm exactly N tasks, correct `hypothesis_id`, boundary `domain_tags`, `approved_by` =
   the logged-in user, `gate_mode` unchanged, nothing cancelled.
6. Re-submit approve with the same `Idempotency-Key`. Confirm exactly one seeding.
7. **The refutation canary — constraint (j). Run this before any real boundary.** Add one hypothesis by hand
   that is *guaranteed false but requires real investigation*: pick a file that **does exist** and assert something
   false about it, e.g. "`<a real module>` builds its SQL by string interpolation" where it demonstrably uses
   parameterised queries. **Do not use a nonexistent file** — `read_file` returns the string
   `"Error: file not found"` rather than raising ([read_file.py:31](modules/backend/tools/read_file.py#L31)), so
   the tester would refute it without reading any code and the canary would pass while proving nothing.
   Approve and dispatch that one alone, then assert **all** of:
   - the task reaches `COMPLETED`, not `FAILED` or `TIMEOUT`;
   - `verdict == "refuted"` and `finding is None`;
   - `retry_count == 0` — a retry means Tier 3 mis-scored the refutation and the fabrication loop is live,
     even if the final status happens to look right;
   - the supervisor's `failed` count for the plan is `0`;
   - the coverage strip shows `clean`, not `failed`;
   - no `Finding` and no artifact was produced for it.

   This is the acceptance test for the plan's highest-risk behaviour. **If it does not pass, stop — do not
   proceed to the real assessment**, because every clean result in that assessment would be unreliable.
8. Approve **one** real boundary, dispatch. Confirm only that boundary's tasks ran and **every other
   boundary's tasks are still PROPOSED after the run completes** — the constraint (c)/(i) regression.
9. Confirm at least one `confirmed` and one genuine `refuted` verdict among the real hypotheses, and that the
   confirmed `Finding` carries `hypothesis_id` and `source_phase="hypothesis"`.
10. Confirm the coverage strip distinguishes clean from untested from failed.
11. Approve and dispatch the remaining boundaries. Deliberately fail one hypothesis task (kill its container)
    and confirm the report still generates, excluding it and saying so.
12. "Generate report". Confirm the new `hypothesis_reporter` produces an artifact that satisfies
    `HypothesisAssessmentReport.model_validate(...)` — the acceptance criterion is the schema, not a visual
    check. Assert `coverage` has exactly one row per hypothesis in the approved model, that `counts` agrees
    with it, and that **`inconclusive` rows are reported as `inconclusive`, never as clean**. Assert the
    `findings` input contains no `None` entries (§3.5). Then run it on a plan where *every* hypothesis was
    refuted: that must produce a valid report with `confirmed_findings == []`, not an error.
13. Run the existing `security.code-assessment` workflow on another mission — regression proof that the
    `Finding` field addition and the dispatch fix broke nothing.
14. `python scripts/trace_execution.py --mission <name> --last` — clean timeline, no silent errors.
15. Re-run Phase A on the same mission. Confirm the §1.4 fix holds: **no hypothesis task is cancelled.**

### Final gate

```bash
python scripts/code_rules_fast.py --all      # zero violations
pytest tests/unit -v
pytest tests/integration -v
python mc.py tree && python admin.py tree && python services.py tree && python tui.py tree   # rule 010.1
```

---

## 10. Delta summary

| Kind | Item | New / Changed |
|---|---|---|
| Schema | `agents/security/threat_model.py` — `ThreatModel`, `TrustBoundary`, `Asset`, `Hypothesis`, `HypothesisTestResult`, `HypothesisAssessmentReport`, `HypothesisCoverage` | New |
| Model | `models/threat_model.py` — `ThreatModelRecord`, `ThreatModelRevision` + Alembic migration | New |
| Repository | `repositories/threat_model.py` — `ThreatModelRepository` | New |
| Platform fix | **`_run_tier_3` envelope unwrap + rewritten unit test** (constraint (o), HALT gate §0.2) | Changed |
| Platform fix | Wave concurrency cap, `container.enabled: true`, per-task evidence paths (constraint (p)) | Changed |
| Config | `min_evaluation_score` key; reconcile 0.8/0.7 literals | Changed |
| Agent | `security.code.hypothesis_reporter` + `HypothesisAssessmentReport` (§6a) | New (4 files) |
| Schema | `Finding.hypothesis_id` — one optional field | Changed (1 field) |
| Agent infra | `threat_modeller/build_session.py` + `tools.py` (copies `PlanBuildingSession`) | New |
| Service | `services/threat_model_state.py` — `ThreatModelStore` (read/write against the tables) | New |
| Service | `services/threat_model.py` — `approve_and_seed`, `create_report_task`, hypothesis CRUD | New |
| Service | **`_persist_workflow_as_plan` reconciliation scoped to mirror tasks** (platform defect) | Changed |
| Service | `MissionPlanService.add_task` — `domain_tags`, `verification` | Changed (2 params) |
| API | `endpoints/missions_threat_model.py` — approve, report, CRUD | New |
| API | **`POST /plan/dispatch` → `dispatch_approved(skip_post_run_supervisor=True)`** (fixes 3 callers) | Changed |
| Agents | `security.code.threat_modeller`, `security.code.hypothesis_tester` | New (2 × 4 files) |
| Workflow | `security.code-threat-model.workflow.yaml` (1 step) | New |
| Frontend | Threat Model tab, coverage strip, Findings tab, boundary approval | New |
| Frontend | `dag-graph.tsx` | Deleted |
| Docs | Plan 78 marked superseded | Changed |

Reused **unchanged**: `Finding` (+1 optional field), scanner and triage agents, all 9 scanner capabilities,
container image, ROE, evidence manifest, plan/task DAG and wave dispatch, `add_task` append path,
`dispatch_approved` single-run path, `from_upstream` list-merge, 3-tier verification *after* the §0.2 fix,
retry, cost ceilings, `Idempotency`, `WorkflowEditor`, and the `PlanBuildingSession` pattern.

**No longer claimed as reuse** (each was verified non-functional or unsuitable): the MCD as a store
(constraint (k)), `SecurityAssessmentReport` / the existing reporter (n), `CoverageMatrix` for hypothesis
coverage (n), and `gate_mode` for boundary approval (l).

**What the three review passes removed rather than added:** the `decision` signoff node, the `human_input`
durable pause, the explicit `edges` block, the `recon` node, the `acquire` node, the `clone_repo` tool, five
registry tool modules, a duplicate finding schema, a duplicate evidence schema, a duplicate dispatch endpoint,
a whole reporter-prompt phase, `Hypothesis.status`, and speculative concurrency work. Phase A went from five
nodes to one.

**And what v1.4 added back, honestly:** two tables and a migration, a repository, a second reporter agent with
its own schema, and four platform fixes. v1.2 and v1.3 shrank the plan by finding things to reuse; v1.4 grew it
by finding that four of those things do not work. The delta is now larger than v1.0's — because v1.0's was
fiction. Two of the four platform fixes (§0.2 Tier 3, §0.4 wave concurrency) benefit every mission on the
platform, not just this feature, and would have to be paid by whoever hit them first.

---

## 11. Known risks

| Risk | Mitigation |
|---|---|
| The modeller emits generic checklist hypotheses and the analyst rewrites everything — no time saved. | The prompt requirement that every hypothesis cite a real file path actually read (§5). Measure on the Phase 8 run: if more than half are rewritten, the prompt is wrong, not the architecture. |
| A refuted hypothesis fails verification, and the retry loop then pressures the tester into fabricating a vulnerability. | **Was the plan's top risk; now traced end to end and closed at four layers** (constraint (j)). The `HypothesisTestResult` `model_validator` (§6) is the single definition of the verdict invariant, enforced by PydanticAI at construction; Tier 1 omits `finding` from `required_output_fields`; Tier 2 uses the existing generic `validate_field_exists` for the presence contract (§1.5); Tier 3 criteria (§3.3) are verdict-neutral strings written in Python, protected by the verification agent's own no-invented-criteria rule; the tester prompt (§6) forbids revising a verdict under verification pressure, with a low retry budget bounding the exposure. Phase 8 step 7 is a falsifiable canary that halts the build if any layer leaks. Residual risk is now "a future edit weakens a criterion string", which the Phase 5 test suite catches. |
| Fixing `/plan/dispatch` changes behaviour for the frontend Run button and two CLI paths. | §3.4 requires verifying each caller's intent before merging, with `?mode=autonomous` as the escape hatch. Two of the three callers are currently broken, so the change is a net fix — but it is a behaviour change and must be verified, not assumed. |
| The inconclusive rate makes the assessment undecidable rather than clean. | **New top risk (v1.4, constraint (m)).** The tester has seven static pattern matchers and no runtime capability, so authz/cross-tenant/race claims cannot be settled — and constraint (j)'s cure makes `inconclusive` the cheapest passing verdict. Mitigations: testability gate at approve time (§3.3 step 7), `inconclusive` as a first-class state in §3.5/§7.2/§7.3/§6a, and a Phase 8 ceiling on the inconclusive ratio. If the first real boundary exceeds ~30% inconclusive, the tool-reach problem is real and blackbox/runtime capability (D3, deferred) becomes a prerequisite rather than a follow-up. |
| Tier 3 fails unconditionally, firing the fabrication loop on every hypothesis. | **Pre-existing platform bug, constraint (o).** Fixed as HALT gate §0.2 before any Plan 86 code, with the mocking unit test rewritten. Plan 86 must not enable Tier 3 until that lands. |
| A mid-assessment budget overrun corrupts a whole batch instead of stopping cleanly. | Constraint (q). `approve_and_seed` now sets an explicit ceiling (§3.3 step 6) so the recoverable abort path is reachable and the burn-down bar renders. |
| 30 testers share one 2 GB container behind an unbounded `gather`. | Constraint (p). Phase 0.4 enables containers, adds a concurrency cap from config, and namespaces per-task evidence paths. |
| ~~`output_reference` does not expose `finding` at the top level.~~ | **Closed by verification (v1.3.1).** Traced through `retry_handler.py:353` → `_handle_post_task_gate(output=agent_output)` → `output_reference` → `result_summary` → `load_prior_outputs` → `resolve_upstream_inputs`. The shape is the unwrapped `HypothesisTestResult` with `finding` at the top level; both dispatch paths agree. Evidence in §3.5. |
| A `null` finding from a refuted hypothesis reaches the reporter, which expects `list[Finding]`. | Found while verifying the above. §3.5 now filters the `from_upstream` refs on `verdict == "confirmed"` rather than on task status, because refuted tasks are COMPLETED by design. `resolve_upstream_inputs` returns `None` without erroring, so this would have been a silent malformed-input bug, not a crash. Phase 8 step 11 asserts it. |
| Hypothesis testing costs more than a blanket scan. | Per-task `cost_ceiling_usd`, `intrusive` gating. Compare against a plain `security.code-assessment` run in Phase 8 step 12. |
| 40 hypotheses is still too many approvals even grouped by boundary. | If boundary grouping proves too fine, the next step is approve-all-with-veto using the existing `veto_window_sec` / `veto_expires_at` mechanism — not per-hypothesis clicking. |
| Seeding is one-shot, so the analyst cannot add hypotheses after approval. | Deliberate in v1. The fix is an incremental seed appending only hypotheses with a null `task_id` — a small extension of §3.3, but it needs its own idempotency story. Do not bolt it on mid-build. |
| Nothing forces the analyst to actually review the draft — they can approve version 1 blindly. | Not solvable in software and deliberately not attempted. The coverage strip and `origin` field make blind approval *visible* after the fact (zero `origin: "analyst"` hypotheses), the honest limit of tooling here. |
| Refinement chat reads target files in-process, outside the container. | §0.4. Reads, never executes — exposure is prompt injection via source comments, not RCE. Revisit if targets become hostile. |
