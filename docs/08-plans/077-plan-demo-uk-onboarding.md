# Plan 77: Demo Vertical — UK Client Onboarding

## Status: Draft (awaiting approval)

**Priority:** Demo
**Branch:** `demo/uk-onboarding`
**Dependencies:** Plan 75 (composable workflows + decision nodes — shipped 2026-05-21)
**Owner:** Herman

---

## 1. Purpose

A demo-grade vertical that approximates the "Client Onboarding (UK)" reference
team from the Agentic Workforce Platform BRD/TRD. The audience is an executive
walkthrough of how the platform decomposes a regulated-looking case across
makers + QA + human gates and emits an evidence pack at completion.

**This is theatre with real moving parts.** No real KYC, no jurisdictional
residency, no MRM register, no immutable audit, no Entra SSO. Every adverse
finding, screening hit, and document extract is canned. See `GAPS.md` (produced
during implementation) for the brutally-honest scope statement.

---

## 2. Scope guarantees

These restate the brief's hard constraints in concrete terms:

| Constraint | How this plan honours it |
|---|---|
| Additive only | All new files live under `demo_uk_onboarding/` subfolders. Section 4 lists the **six unavoidable shared-file edits** — each one a single additive line. No behaviour change to anything outside the demo. |
| Namespaced | Every file path, agent name, tool name, fixture, route, DB column (none added), and config key carries `demo` as the top segment plus an `uk` / `onboarding` qualifier. Agents use dotted form `demo.uk.onboarding.*` (matching repo convention — single-word lowercase segments). Tools, fixtures, route, and config keys use snake/kebab `demo_uk_onboarding_*` / `demo-uk-onboarding-*`. Folder layouts use `demo/uk/onboarding/`. Cleanup grep takes a two-pattern alternation; see §15.5. |
| Flag-gated at load | `DEMO_UK_ONBOARDING_ENABLED=false` (default) → agents disabled, route 404s, dashboard tile hidden, tools not registered. The mechanism for enforcing this on agent loading is an **open question** flagged in §13. |
| Mock tools only | Five mock tools under `modules/backend/tools/demo_uk_onboarding/`. Deterministic-from-seed payloads. 100–300 ms randomised latency. No outbound HTTP. |
| No shared schema migrations | No Alembic migration needed. Evidence persists as a `MissionArtifact` row (`content_type=json`) via the existing `store_artifact` tool. No new file-system persistence pattern is introduced. |
| No changes to gate, Temporal worker, or auth | Reuses `mission_run_workflow`, `ConfigurableGate`, and the existing JWT/admin auth. Four-eyes is approximated using two sequential `decision` nodes with `resolver: human` (Plan 75). |
| No new pyproject deps | Plan uses only stdlib + already-installed packages (PydanticAI, SQLAlchemy, FastAPI, structlog, React Query, react-router). |
| All new code typed and tested | Pydantic schemas on all I/O. pytest coverage per §11. |

---

## 3. Architecture choice

The brief describes "Supervisor decomposes the case and dispatches Makers". Two
implementation shapes fit the platform:

**Design A (recommended) — Composable workflow.** The orchestrator is a static
`workflow_template` YAML. Each maker is an `agent_step`. Routing between
straight-through, single-gate, and additional-docs paths is expressed as
`decision` nodes that landed in Plan 75. The "supervisor" is a thin triage
agent at step 0 that emits a dispatch summary event (for the demo narrative)
but does not LLM-decompose.

**Design B — Planning-Agent driven.** The Director invokes Planning Agent to
decompose the case dynamically, then mission control dispatches via
`mission_plan_orchestrator`. Equivalent capability, ~10× the cost, lower
predictability, and harder to script for a stakeholder walkthrough.

**This plan uses Design A.** Rationale:

1. Aligns with P2 (Deterministic Over Non-Deterministic) — the only LLM
   reasoning needed is the per-maker work + the QA judgement, not the
   orchestration.
2. Reuses the just-shipped Plan 75 decision-node mechanism end-to-end,
   demonstrating composable workflows on a realistic-looking case.
3. Predictable timings and event sequence for a live walkthrough.
4. Same six agents the brief specifies, but the "supervisor" is honest about
   what it does (triage + narrative) rather than pretending to decompose
   something the workflow has already decomposed statically.

If a demo viewer asks "would Production use LLM decomposition?", the honest
answer is "Production would use Planning Agent (Design B) for novel cases and
Workflows (Design A) for repeatable cases — Onboarding is repeatable, so
Workflow is correct". This is documented in `GAPS.md`.

---

## 4. Shared-file edits (seven unavoidable additions)

Each one is a single additive line/block. No existing behaviour changes. This
list is the entire intersection with constraint #1 ("Additive only — no edits
to shared code"). Approved.

| # | File | Edit |
|---|---|---|
| 1 | `config/settings/features.yaml` | Add `demo_uk_onboarding_enabled: false` |
| 2 | `modules/backend/core/config_schema.py` (`FeaturesSchema`) | Add `demo_uk_onboarding_enabled: bool = False` |
| 3 | `modules/backend/api/v1/__init__.py` (router registry) | `from .endpoints import demo_uk_onboarding; router.include_router(demo_uk_onboarding.router, prefix="/demo/uk-onboarding", tags=["demo"])` (one line) |
| 4 | `modules/backend/api/health.py` (`/health/detailed`) | Append `features.demo_uk_onboarding_enabled` to the response dict |
| 5 | `modules/backend/main.py` (FastAPI lifespan) | One line: `await seed_demo_uk_onboarding(session)` after the existing Temporal schedule registrations. Reconciles demo agents' `enabled` state in the DB against the feature flag at startup (per §13 Q1, resolved). |
| 6 | `modules/frontend/src/App.tsx` (router) | One `<Route path="demo/uk-onboarding" element={<DemoUkOnboardingPage />} />` |
| 7 | `modules/frontend/src/pages/dashboard.tsx` | One conditional tile composed from the existing `Card` primitive, rendered only when `features.demo_uk_onboarding_enabled` is true (§12.3) |

Frontend route stays as kebab `/demo/uk-onboarding`. Feature-flag env var stays
`DEMO_UK_ONBOARDING_ENABLED`. Tool names stay snake_case
`demo_uk_onboarding_*`. Agent names use dotted `demo.uk.onboarding.*` per
repo convention (§7.1).

Schemas: per-agent Pydantic output schemas will live in
`modules/backend/agents/demo_uk_onboarding/schemas.py` (a NEW file, not the
shared `modules/backend/agents/schemas.py`). Verified by Explore: research
agents have local schemas in their own modules — convention permits this.

---

## 5. File layout

Agent folders use the dotted convention (`demo/uk/onboarding/`); tools, fixtures,
services, and endpoints use snake_case `demo_uk_onboarding_*` because that is
the existing convention for every non-agent artefact in the repo
(`store_artifact.py`, `read_file.py`, etc.).

```
config/
├── agents/
│   └── demo/uk/onboarding/
│       ├── supervisor/agent.yaml
│       ├── maker/
│       │   ├── identity/agent.yaml
│       │   ├── screening/agent.yaml
│       │   ├── risk_rating/agent.yaml
│       │   └── data_capture/agent.yaml
│       └── qa/agent.yaml
├── prompts/agents/demo/uk/onboarding/   (mirrors the agents tree, system.md per agent)
├── fixtures/demo_uk_onboarding/
│   ├── clean.json
│   ├── sanctions_hit.json
│   └── adverse_media.json
├── workflow_templates/
│   └── demo.uk-onboarding.intake.workflow.yaml
└── settings/features.yaml                (1-line edit per §4)

modules/backend/
├── agents/demo/uk/onboarding/
│   ├── __init__.py                       (minimal — re-exports only)
│   ├── deps.py                           (DemoOnboardingDeps dataclass)
│   ├── schemas.py                        (Pydantic output models)
│   ├── supervisor/agent.py
│   ├── maker/
│   │   ├── identity/agent.py
│   │   ├── screening/agent.py
│   │   ├── risk_rating/agent.py
│   │   └── data_capture/agent.py
│   └── qa/agent.py
├── tools/demo_uk_onboarding/         # NOTE: flat layout, see §5 note below
│   ├── __init__.py                       (minimal)
│   ├── identity_verify.py                (TOOL_DEF + register)
│   ├── screening_search.py
│   ├── document_ocr.py
│   ├── crm_create_case.py
│   ├── playbook_fetch.py
│   ├── request_docs.py                   (returns a "request additional documentation"
│                                          outcome — drives adverse_media's third path)
│   ├── fixture_loader.py                 (returns the applicant dict for a given
│                                          fixture_name — restored per Premortem-2 #3
│                                          because resolve_template stringifies dicts)
│   └── evidence_writer.py                (assembles the evidence JSON server-side
│                                          from scalar args, then calls store_artifact —
│                                          restored per Premortem-2 #2 because the YAML
│                                          template engine has no Jinja filters)
# Tool registry uses pkgutil.iter_modules which only walks TOP-LEVEL
# tools/. See P1 #6 — these files must live at modules/backend/tools/
# demo_uk_onboarding_<name>.py (flat), not under a subdirectory.
├── services/demo_uk_onboarding_service.py (start_mission, list_fixtures, status)
├── services/demo_uk_onboarding_seeder.py  (idempotent team-binding + flag toggle)
├── api/v1/endpoints/demo_uk_onboarding.py (FastAPI router)
└── core/config_schema.py                  (1-line edit per §4)

modules/frontend/src/
├── pages/demo/uk-onboarding/
│   ├── index.tsx                         (DemoUkOnboardingPage)
│   ├── fixture-selector.tsx
│   ├── stream-view.tsx                   (composes useMissionStream + log)
│   └── evidence-panel.tsx
├── hooks/use-demo-uk-onboarding.ts       (React Query hooks)
└── App.tsx                                (1 route line per §4)
└── pages/dashboard.tsx                    (1 conditional tile per §4)

docs/97-plans/
├── 77-plan-demo-uk-onboarding.md         (this file)
├── 77-runbook-demo-uk-onboarding.md      (deliverable 3 — produced post-impl)
└── 77-gaps-demo-uk-onboarding.md         (deliverable 4 — produced post-impl)

tests/
├── unit/backend/demo_uk_onboarding/
│   ├── test_tools.py                     (deterministic-by-seed assertions)
│   ├── test_seeder.py
│   └── test_load_fixture.py            (tests _load_fixture helper inside demo_uk_onboarding_service.py)
└── integration/demo_uk_onboarding/
    ├── test_flag_off_smoke.py
    ├── test_clean_path.py
    ├── test_sanctions_hit_gate.py
    └── test_adverse_media_request_docs.py
```

**No new Alembic migration.** Evidence persistence uses the existing
`mission_artifacts` table via `store_artifact` with `content_type=json`. No
new file-system persistence pattern is introduced. See §10.

---

## 6. Feature flag mechanism

### 6.1 Declaration

Edit `config/settings/features.yaml`:
```yaml
# (existing flags unchanged)
demo_uk_onboarding_enabled: false   # Toggles the UK Onboarding demo vertical.
```

Edit `modules/backend/core/config_schema.py` → `FeaturesSchema`:
```python
demo_uk_onboarding_enabled: bool = Field(
    default=False,
    description="Toggles the UK Client Onboarding demo vertical (Plan 77).",
)
```

Runtime read: `get_app_config().features.demo_uk_onboarding_enabled`.

`.env` override: `DEMO_UK_ONBOARDING_ENABLED=true` (pydantic_settings already
maps env → config fields via the established convention; verify during impl
that `FeaturesSchema` participates in this — flagged in §13).

### 6.2 Enforcement points

| Point | Behaviour when flag = false |
|---|---|
| FastAPI router (`/api/v1/demo/uk-onboarding/*`) | Router-level dependency raises 404. |
| Dashboard tile | `useHealthCheck()` returns `features.demo_uk_onboarding_enabled = false` → tile not rendered. |
| Frontend route `/demo/uk-onboarding` | Guard component reads feature flag from health endpoint, redirects to dashboard with toast. |
| Agent registry / catalog | A new `demo_uk_onboarding_seeder.py` runs on startup as a post-step after the main `catalog_seeder`. When flag is on it ensures the six demo agents exist and `enabled=true`; when off it sets them to `enabled=false`. Avoids editing `catalog_seeder.py`. Hooked into `main.py` lifespan per §4 edit #5. |
| Tool registry | Tools auto-discover via `TOOL_DEF` import, so they're effectively dormant until an enabled agent references them. No edit needed. |
| Workflow template seeder | `workflow_seeder.py` seeds all templates in `config/workflow_templates/`. Demo template is seeded regardless of flag (cheap, idempotent), but the template's agent steps cannot resolve unless agents are enabled, so the flag is enforced one layer up. |

### 6.3 Frontend flag exposure

Minimal change: append `features` block to `/health/detailed` response.
```jsonc
{
  "status": "healthy",
  "app": { ... },
  "features": {
    "demo_uk_onboarding_enabled": true
  }
}
```

Frontend hook `useFeatures()` (NEW, in `hooks/use-features.ts`) wraps this and
is consumed by the route guard, dashboard tile, and demo page.

---

## 7. Agent YAMLs

All six agents follow the existing 4-file contract
(`docs/02-architecture/003-agent-blueprint.md`). Agent-name format
`{category}.{name}.agent` is honoured by treating `demo_uk_onboarding` as the
category. Multi-segment names like `mission.workflow.architect.agent` show
deeper nesting is already supported.

**Invocation tier:** All six agents use `invocation.tier: user`. With the flag
on, the demo agents are visible to any signed-in user in the standard
catalog — matching the brief's "live walkthrough from the React dashboard"
intent. (Confirmed 2026-05-21.)

### 7.1 Naming reconciliation

The brief used `demo_uk_onboarding_`-prefixed dotted identifiers throughout.
Repo convention is stricter: agent names are dot-separated, single-word
lowercase segments, ending in `.agent`. No existing category uses
underscores. We follow the repo convention for agents and the existing
snake_case convention for tools:

| Brief asked for | This plan uses | Reason |
|---|---|---|
| `demo_uk_onboarding.supervisor` (agent) | `demo.uk.onboarding.supervisor.agent` | Dot-separated, single-word segments, `.agent` suffix. Mirrors `mission.workflow.architect.agent`. |
| `demo_uk_onboarding.maker.identity` | `demo.uk.onboarding.maker.identity.agent` | Same |
| `demo_uk_onboarding.maker.screening` | `demo.uk.onboarding.maker.screening.agent` | Same |
| `demo_uk_onboarding.maker.risk_rating` | `demo.uk.onboarding.maker.risk_rating.agent` | `risk_rating` keeps its underscore because (a) it's a leaf segment, not a category, and (b) it mirrors agent leaf names in the existing tree (e.g. `system.knowledge.officer.agent` → segment `officer`; `data_capture` and `risk_rating` are equivalent leaf identifiers). |
| `demo_uk_onboarding.maker.data_capture` | `demo.uk.onboarding.maker.data_capture.agent` | Same |
| `demo_uk_onboarding.qa` | `demo.uk.onboarding.qa.agent` | Same |
| `demo_uk_onboarding.identity.verify` (tool) | `demo_uk_onboarding_identity_verify` | Existing tools (`store_artifact`, `read_file`) are flat snake_case. |
| `demo_uk_onboarding.screening.search` | `demo_uk_onboarding_screening_search` | Same |
| `demo_uk_onboarding.document.ocr` | `demo_uk_onboarding_document_ocr` | Same |
| `demo_uk_onboarding.crm.create_case` | `demo_uk_onboarding_crm_create_case` | Same |
| `demo_uk_onboarding.playbook.fetch` | `demo_uk_onboarding_playbook_fetch` | Same |

**Implication for grep cleanup:** the single prefix `demo_uk_onboarding`
no longer catches everything — agent folders live at `config/agents/demo/uk/onboarding/`
and agent names use dot-separated segments. The §15.5 cleanup grep is updated to
use an alternation pattern: `'demo_uk_onboarding|demo\.uk\.onboarding|demo/uk/onboarding'`.

### 7.2 Skeleton YAML — supervisor

**Built from scratch — the REUSE-WITH-CONFIG claim was dropped.** Premortem #7
(2026-05-22) confirmed via code inspection that `mission.supervisor.agent` is
not a generic triage shape — it is a hardwired post-run autonomy classifier.
Its `create_event_agent` factory returns `SupervisorDecision` (a closed enum
of `wait | advance | refine | propose_complete | escalate`), and all three of
its tools (`get_plan`, `get_recent_run_outcomes`, `get_past_decisions`) are
keyed off `mission_id` and assume a `MissionPlan` row exists. The demo's
workflow-template runs have no `MissionPlan`, so those tools would return
`{"error": "..."}` and the agent would hallucinate around empty introspection.

The demo supervisor is the **sixth from-scratch agent** with:
- Its own output schema (no `SupervisorDecision` enum)
- Its own deps dataclass (no `MissionSupervisorDeps`)
- Its own tools (no `get_plan` / introspection adapters)

Agent count is back to **6 new agents**, not 5 + 1 reskin.

`config/agents/demo/uk/onboarding/supervisor/agent.yaml`:

```yaml
agent_name: demo.uk.onboarding.supervisor.agent
agent_type: vertical
description: >
  Triage agent for the UK Onboarding demo. Loads the playbook, summarises the
  applicant, and emits a dispatch narrative event for the demo walkthrough.
enabled: true
chat_enabled: false

model:
  name: anthropic:claude-haiku-4-5
  temperature: 0.0
  max_tokens: 1500

max_input_length: 10000
max_budget_usd: 0.02

execution:
  mode: local

invocation:
  tier: user

tools:
  - demo_uk_onboarding_playbook_fetch

keywords:
  - onboarding
  - kyc
  - demo

interface:
  input:
    fixture_name: str    # from @context.fixture_name (scalar — not the dict)
    jurisdiction: str
  output:
    applicant_summary: str
    playbook_id: str
    dispatched_makers: list[str]
```

### 7.3 Skeleton YAML — maker.identity

`config/agents/demo/uk/onboarding/maker/identity/agent.yaml`:

```yaml
agent_name: demo.uk.onboarding.maker.identity.agent
agent_type: vertical
description: Verifies identity documents (demo — calls mock identity.verify tool).
enabled: true
model:
  name: anthropic:claude-haiku-4-5
  temperature: 0.0
  max_tokens: 1500
max_input_length: 10000
max_budget_usd: 0.02
execution: { mode: local }
invocation: { tier: user }
tools:
  - demo_uk_onboarding_identity_verify
  - demo_uk_onboarding_fixture_loader   # agent calls this to get the applicant dict
interface:
  input:
    fixture_name: str    # from @context.fixture_name (scalar)
  output:
    match_score: float
    doc_authenticity: float
    issues: list[str]
```

Maker.screening, maker.risk_rating, maker.data_capture, and qa follow the same
shape. Each declares the minimum tool allow-list and a typed `interface`
contract so the workflow template can wire outputs to downstream inputs without
LLM glue.

**Agents that need applicant data declare `demo_uk_onboarding_fixture_loader`
in `tools:`** (data_capture, identity, screening at minimum). They call it as
`fixture_loader(fixture_name=...)` to get the applicant dict — the workflow
context only carries scalar values like `fixture_name`, never the dict
itself (Premortem-2 #D: `resolve_template` stringifies dicts).

**The qa agent's output schema MUST include a `route` field**:

```python
class QaResult(BaseModel):
    route: Literal["straight_through", "needs_approval", "needs_more_docs"]
    summary: str
    requires_approval: bool
    findings: list[QaFinding]
```

The workflow's `route_qa` decision node reads `@node.qa.output.route` and
matches it literally against one of the option keys (Premortem-2 #A — the
rule resolver does string equality, not boolean coercion).

### 7.4 System prompts

One `system.md` per agent under `config/prompts/agents/demo/uk/onboarding/`.
Each prompt is short (≤60 lines), enforces the I/O contract, and includes the
explicit instruction:

> This is a demo agent. All inputs are synthetic. Do not warn users about
> regulatory compliance, real-world impact, or data accuracy — those concerns
> are documented in the demo's GAPS.md.

This avoids the LLM editorialising during the walkthrough.

---

## 8. Mock tools

Each tool file follows `modules/backend/tools/store_artifact.py` pattern:
`TOOL_DEF` dict + `register(agent: Agent)` function + pure async impl.

Deterministic-by-seed pattern:
```python
def _seed_rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
```

Same `(name, dob, document_ref)` always returns the same payload across runs.

### 8.1 Tool signatures

| Tool name | Signature | Notes |
|---|---|---|
| `demo_uk_onboarding_identity_verify` | `(ctx, *, name: str, dob: str, document_ref: str) -> IdentityVerifyResult` | Returns `match_score`, `doc_authenticity`, `issues`. |
| `demo_uk_onboarding_screening_search` | `(ctx, *, name: str, dob: str, country: str) -> ScreeningResult` | Returns `sanctions_hits`, `pep_hits`, `adverse_media`. Sanctions-hit applicants seed `sanctions_hits=[{...}]`; adverse-media seeds `adverse_media=[{...confidence: 0.4...}]`. |
| `demo_uk_onboarding_document_ocr` | `(ctx, *, document_ref: str) -> OcrResult` | Returns `extracted_fields`, `confidence`. |
| `demo_uk_onboarding_crm_create_case` | `(ctx, *, applicant_name: str, dob: str, country: str, risk_rating: str) -> CaseRef` | Returns `case_id` (UUID seeded from name+dob hash), `status="draft"`. **Takes scalars, not a dict** — the YAML template engine cannot pass dict values (Premortem-2 #D). |
| `demo_uk_onboarding_playbook_fetch` | `(ctx, *, jurisdiction: str = "UK") -> Playbook` | Returns `steps[]`, `thresholds`, `escalation_rules`. UK is the only seeded jurisdiction. |
| `demo_uk_onboarding_request_docs` | `(ctx, *, applicant_name: str, reason: str) -> DocsRequestResult` | Deterministic. Returns `requested_documents[]`, `request_id`, `due_date`. Drives `adverse_media`'s `needs_more_docs` path. Scalar args only. |
| `demo_uk_onboarding_fixture_loader` | `(ctx, *, fixture_name: str) -> Applicant` | Loads `config/fixtures/demo_uk_onboarding/{name}.json`, validates against `ApplicantFixture`, caches in-process. **Restored** per Premortem-2 #D — `resolve_template` does `str()` coercion on dict values, so the original "load once at API edge, pass via `@context.applicant`" pattern silently malformed the data. Each agent that needs applicant data declares this in its `tools:` allow-list and calls `fixture_loader(fixture_name=...)`. The API still does a lightweight existence check at start, but agents get the real dict via this tool. |
| `demo_uk_onboarding_evidence_writer` | `(ctx, *, mission_id: str, fixture_name: str, outcome: str, case_id: str \| None, risk_rating: str, qa_summary: str, screening_summary: str, identity_summary: str, human_decision: str \| None, additional_docs: str \| None) -> str` | Assembles the evidence JSON server-side from scalar args, then calls `store_artifact(content_type=json, artifact_type=data)`. **Restored** per Premortem-2 #C — the YAML template engine has no `\| tojson` filter; inline JSON assembly in `tool_args` produces silent garbage. All args are strings/scalars, all assembly happens in Python. Returns the artifact id. |

### 8.2 Latency, logging, and event emission

Every tool:
- Sleeps `random.uniform(0.1, 0.3)` (seeded) before returning.
- Logs entry + exit via `logger.info(..., extra={"correlation_id": ctx.deps.correlation_id, ...})`.
- The wrapper at the agent level emits a `ToolInvokedEvent` to the session event bus so the SSE stream surfaces each call.

### 8.3 Boundaries

- No `httpx`, `aiohttp`, or `requests` calls anywhere in this folder. CI
  rule check in `code_rules_fast.py` already blocks this (rule 008.2).
- Tools never import models or repositories.
- Tools never touch `os.environ` other than to read the demo's evidence path
  base (which itself comes from config, not env).

---

## 9. Fixtures

Three synthetic applicants. All identities are obviously fake.

### 9.1 Shape (`ApplicantFixture` Pydantic model)

```python
class ApplicantFixture(BaseModel):
    fixture_name: str
    application: ApplicationForm
    documents: list[DocumentRef]   # exactly 2: passport + utility bill
    source_of_funds_note: str
    expected_outcome: ExpectedOutcome   # for assertions in tests
```

### 9.2 `clean.json`

```jsonc
{
  "fixture_name": "clean",
  "application": {
    "full_name": "Synthia Mockworth",
    "dob": "1990-01-01",
    "country_of_residence": "GB",
    "address": "12 Test Lane, Mocktown, MK1 9TT",
    "occupation": "Software Engineer",
    "annual_income_gbp": 65000
  },
  "documents": [
    { "type": "passport", "document_ref": "DEMO-PASS-001" },
    { "type": "utility_bill", "document_ref": "DEMO-UTIL-001" }
  ],
  "source_of_funds_note": "PAYE salary",
  "expected_outcome": {
    "screening_clean": true,
    "risk_rating": "low",
    "gates": 0
  }
}
```

### 9.3 `sanctions_hit.json`

Same shape. Triggers a seeded `sanctions_hits` payload in
`demo_uk_onboarding_screening_search` keyed on `name+dob`.
`expected_outcome.gates = 1`.

### 9.4 `adverse_media.json`

Same shape. Triggers a low-confidence (`0.40`) adverse-media payload.
`expected_outcome.gates = 0, requires_additional_docs = true`.

**No four-eyes path.** The original brief approximated four-eyes via two
sequential human gates clicked by the same presenter. Premortem #5 (2026-05-22)
identified this as the most dangerous failure mode — a compliance-aware
audience reads "same person clicks twice" as evidence the platform fakes
regulated controls. The path is dropped entirely.

**What `adverse_media` now demonstrates instead:** low-confidence findings
route to a deterministic `tool_call` step (`demo_uk_onboarding_request_docs`)
that produces a "request additional documentation" outcome. The workflow
completes without a human gate. This preserves a third distinct demo path
(straight-through / single-gate / additional-docs) without simulating a
regulatory control the platform cannot honestly enforce.

---

## 10. Workflow template

`config/workflow_templates/demo.uk-onboarding.intake.workflow.yaml`:

```yaml
workflow_name: demo.uk-onboarding.intake.workflow
objective:
  statement: "Onboard a UK retail client (DEMO — synthetic data only)."
  category: demo
  priority: high

trigger:
  type: on_demand
  # UI-only trigger. The original plan retained `match_patterns` so Director
  # could launch the workflow from chat, but Premortem #2 (2026-05-22)
  # confirmed via code inspection that `match_patterns` cannot supply the
  # nested `applicant` context the agents require — `run_workflow`'s
  # signature is `context_overrides: dict[str, str] | None`. Chat trigger
  # is dropped; UI is the only entry point.

budget:
  max_cost_usd: 0.50
  max_tokens: 200000

parameters:
  - key: fixture_name
    type: enum
    options: ["clean", "sanctions_hit", "adverse_media"]
    required: true
  # NOTE: no `applicant` parameter. Premortem-2 #D — the YAML template
  # engine `str()`-coerces dict values, so passing the applicant via
  # context is broken. Agents call the `fixture_loader` tool inline to
  # get the dict.

context:
  jurisdiction: "UK"
  fixture_name: ""

steps:
  - id: triage
    node_type: agent_step
    capability: demo.uk.onboarding.supervisor
    depends_on: []

  - id: data_capture
    node_type: agent_step
    capability: demo.uk.onboarding.maker.data_capture
    depends_on: [triage]

  - id: identity
    node_type: agent_step
    capability: demo.uk.onboarding.maker.identity
    depends_on: [data_capture]

  - id: screening
    node_type: agent_step
    capability: demo.uk.onboarding.maker.screening
    depends_on: [data_capture]

  - id: risk_rating
    node_type: agent_step
    capability: demo.uk.onboarding.maker.risk_rating
    depends_on: [identity, screening]

  - id: qa
    node_type: agent_step
    capability: demo.uk.onboarding.qa
    depends_on: [risk_rating]

  - id: route_qa
    node_type: decision
    decision_config:
      resolver: rule
      expression: "@node.qa.output.route"   # qa agent emits a string equal to one option key.
      options:
        - { key: straight_through,  label: "Auto-complete — no adverse findings" }
        - { key: needs_approval,    label: "Adverse finding — escalate to human" }
        - { key: needs_more_docs,   label: "Low-confidence finding — request more documentation" }
    depends_on: [qa]
    # Premortem-2 #A fix: the `qa` agent's output schema includes
    #   route: Literal["straight_through", "needs_approval", "needs_more_docs"]
    # so the rule evaluator gets a literal string match against one of the
    # option keys, mirroring `general.decision-routing.workflow.yaml`.
    # Previously used `rule:` (rejected by DecisionConfig extra="forbid")
    # and Jinja `{{...}}` (rejected by condition_evaluator.tokenize).

  - id: human_approval
    node_type: decision
    decision_config:
      resolver: human
      prompt_message: "QA flagged a screening hit. Approve to proceed or reject the case."
      channel: sse
      options:
        - { key: approve, label: "Approve" }
        - { key: reject,  label: "Reject" }
      timeout_hours: 24
    depends_on: [route_qa]
    # Only runs when route_qa branch = needs_approval (sanctions_hit fixture).

  - id: request_more_docs
    node_type: tool_call
    tool_call_config:
      tool_name: demo_uk_onboarding_request_docs
      tool_args:
        applicant_name: "{{@node.data_capture.output.full_name}}"
        reason: "low-confidence adverse-media finding"
    depends_on: [route_qa]
    # Only runs when route_qa branch = needs_more_docs (adverse_media fixture).
    # Scalar args only — dict-passing via template is broken (Premortem-2 #D).

  - id: merge_outcomes
    node_type: merge
    merge_config:
      strategy: wait_all   # `wait_any` is accepted by the schema but ignored
                           # by the wave engine (Premortem-2 #B). Use wait_all
                           # — which is what actually happens in any case.
    depends_on: [human_approval, request_more_docs]
    # Premortem-2 #B: `route_qa` is removed from `depends_on` because it's
    # the transitive parent of the two children — listing all three adds no
    # value. Skipped predecessors count as "done" for wave progression, so
    # merge fires after both children are in terminal state. Downstream
    # refs to skipped nodes (e.g. @node.human_approval.output when the
    # `needs_more_docs` branch fired) resolve to empty string silently
    # (_resolve_ref returns None). evidence_writer treats "" as None for
    # optional fields.

  - id: assemble_case
    node_type: tool_call
    tool_call_config:
      tool_name: demo_uk_onboarding_crm_create_case
      tool_args:
        applicant_name: "{{@node.data_capture.output.full_name}}"
        dob: "{{@node.data_capture.output.dob}}"
        country: "{{@node.data_capture.output.country_of_residence}}"
        risk_rating: "{{@node.risk_rating.output.rating}}"
    depends_on: [merge_outcomes]
    # Scalar args only — Premortem-2 #D.

  - id: write_evidence
    node_type: tool_call
    tool_call_config:
      tool_name: demo_uk_onboarding_evidence_writer
      tool_args:
        mission_id: "{{@context.mission_id}}"
        fixture_name: "{{@context.fixture_name}}"
        outcome: "completed"
        case_id: "{{@node.assemble_case.output.case_id}}"
        risk_rating: "{{@node.risk_rating.output.rating}}"
        qa_summary: "{{@node.qa.output.summary}}"
        screening_summary: "{{@node.screening.output.summary}}"
        identity_summary: "{{@node.identity.output.summary}}"
        human_decision: "{{@node.human_approval.output.choice}}"
        additional_docs: "{{@node.request_more_docs.output.request_id}}"
    depends_on: [assemble_case]
    # evidence_writer is a Python tool that assembles JSON server-side and
    # calls store_artifact. All tool_args are scalar strings — the YAML
    # template engine cannot handle Jinja filters or dict interpolation
    # (Premortem-2 #C and #D). Skipped-node refs resolve to empty string;
    # evidence_writer treats "" as None for the optional fields.

edges:
  - { from: route_qa,         to: merge_outcomes,    label: straight_through }
  - { from: route_qa,         to: human_approval,    label: needs_approval }
  - { from: route_qa,         to: request_more_docs, label: needs_more_docs }
  - { from: human_approval,   to: merge_outcomes,    label: approve }
  # On `reject`, the workflow ends at human_approval with no downstream
  # edge — wave engine marks remaining steps SKIPPED and the mission
  # concludes with the rejection captured in human_approval's output.
  # write_evidence still fires because it sits after the merge.
```

**Three demo paths:**

| Fixture | route_qa branch | Demonstrated capability |
|---|---|---|
| `clean.json` | `straight_through` | No human in the loop, fully automated |
| `sanctions_hit.json` | `needs_approval` → human_approval | Single human gate, approve or reject |
| `adverse_media.json` | `needs_more_docs` → request_more_docs | Deterministic routing to a "request more docs" branch |

**No four-eyes simulation.** Premortem #5 (2026-05-22) confirmed the
single-user double-click approximation is unsafe to demonstrate in
financial-services audiences. The capability is dropped from the demo
entirely. If real two-identity enforcement is later required, it becomes a
genuine product capability (distinct `approved_by_user_id` per gate, second
approver UI), not a demo trick.

**Convergence semantics.** Both `assemble_case` and `write_evidence` depend
on a single `merge_outcomes` node rather than multiple decision-routed
predecessors directly. Premortem #1 confirmed via
`services/workflow_run_waves.py:_should_skip` that only `node_type: merge`
is skip-exempt — any other node downstream of multiple decision branches
would be SKIPPED on every run. The merge is mandatory, not aesthetic.

**Verification of edge semantics:** Confirmed by re-reading Plan 75 §3.2
("How Decisions Route via Edges") and `services/workflow_validator.py:158`
(`_check_decision_edges`). The `_should_skip()` extension at
`workflow_run_waves.py:1038` makes decision edges behave identically to
condition edges — non-matching downstream nodes are skipped.

**Four-eyes mechanism:** Single sequential gates per Plan 75. The demo does
not pretend the two approvals come from different users — that would require
auth-aware gate code we have explicitly excluded. The RUNBOOK will instruct
the presenter to perform both approvals personally and explain "in production,
this would be enforced as two distinct identities". Documented honestly in
`GAPS.md`.

---

## 11. Backend wiring

### 11.1 API endpoint

`modules/backend/api/v1/endpoints/demo_uk_onboarding.py`:

```python
router = APIRouter()

@router.get("/fixtures", response_model=ApiResponse[list[FixtureSummary]])
async def list_fixtures(...): ...

@router.post("/start", response_model=ApiResponse[StartResult])
async def start_mission(
    body: StartRequest,
    db: DbSession,
    user: AuthenticatedUser,
    idempotency: Idempotency,
):
    # Pre-flight: classify each of the 6 demo agents into three states and
    # respond accordingly. Premortem-2 #E: the original "if any missing,
    # return 503 — run seed-catalog --force" conflated two distinct
    # failure modes with different remedies.
    #
    #   present + enabled=true  → OK, proceed
    #   present + enabled=false → 503 DEMO_FLAG_OUT_OF_SYNC
    #                             "Demo agents exist but are disabled.
    #                              Restart the backend so the lifespan
    #                              seeder reruns and applies the current
    #                              flag state. (Did you toggle .env
    #                              without restarting?)"
    #   missing                 → 503 DEMO_NOT_SEEDED
    #                             "Demo agents are missing from the
    #                              catalog. Run `admin seed-catalog
    #                              --force` to bootstrap them, then
    #                              restart so the lifespan seeder enables
    #                              them."
    #
    # Use distinct error codes so the UI can show the right instruction
    # and the operator gets the right remedy first try.
    ...

@router.get("/status/{mission_id}", response_model=ApiResponse[DemoStatus])
async def get_status(...): ...
```

Notes:
- `Idempotency` per P16 / rule 009.1 (background execution dispatch).
- All responses use the `ApiResponse[T]` envelope (memory note
  `feedback_api_envelope`).
- Router-level dependency `require_demo_flag` (in same file) raises 404 if the
  flag is off.

### 11.2 Service

`modules/backend/services/demo_uk_onboarding_service.py`:

```python
class DemoUkOnboardingService(BaseService):
    async def list_fixtures(self) -> list[FixtureSummary]: ...
    async def start(
        self, fixture_name: str, *, owner_id: UUID
    ) -> StartResult:
        # 1. _validate_fixture_exists(fixture_name)  # ~5-line helper:
        #    just checks the file exists and is valid JSON. Raises 404 if
        #    missing. Does NOT load the dict into workflow context —
        #    dict-passing via template is broken (Premortem-2 #D). Agents
        #    that need applicant data call the fixture_loader tool inside
        #    the workflow run.
        # 2. mission = await MissionService(session).create_mission(
        #        name=f"Demo: UK Onboarding ({fixture_name})",
        #        owner_id=owner_id, brief=..., gate_mode="interactive",
        #        tier="user",
        #    )
        # 3. Bind the six demo agents to the mission via
        #    MissionMemberRepository(session).create(...) per agent.
        # 4. workflow_def = await WorkflowDefinitionService(session) \
        #        .import_from_template(mission.id, "demo.uk-onboarding.intake.workflow")
        # 5. run = await WorkflowRunService(session) \
        #        .run_workflow_from_definition(
        #            workflow_def.id, mission.id,
        #            context={"fixture_name": fixture_name,
        #                     "jurisdiction": "UK"},
        #            # NOTE: no `applicant` key. Agents call fixture_loader
        #            # to get the dict; context only carries scalars.
        #        )
        # 6. Return {mission_id: mission.id, workflow_run_id: run.id}
```

**Hard rule for the implementer:** this service MUST NOT re-implement any of
the four reused calls below. It is a ~30-line composition only.

| Reused call | Source |
|---|---|
| `MissionService.create_mission(...)` | [services/mission.py:53](../../modules/backend/services/mission.py#L53) |
| `MissionMemberRepository.create(...)` | existing repository |
| `WorkflowDefinitionService.import_from_template(mission_id, template_name)` | [services/workflow_definition.py:189](../../modules/backend/services/workflow_definition.py#L189) |
| `WorkflowRunService.run_workflow_from_definition(definition_id, mission_id, ...)` | [services/workflow_run.py:174](../../modules/backend/services/workflow_run.py#L174) |

If any of these signatures has changed since this plan was written, update
the plan rather than copy/paste-rewriting the orchestration.

### 11.3 Catalog seeding (flag reconciliation)

`modules/backend/services/demo_uk_onboarding_seeder.py`:

```python
async def seed_demo_uk_onboarding(session: AsyncSession) -> None:
    """Toggle demo agent enablement based on feature flag.

    Runs on startup, AFTER the main catalog_seeder. When flag = true, ensures
    the six demo agents exist (creating from YAML if needed) and enabled=true.
    When flag = false, ensures they are disabled (or deleted, if user prefers
    full removal).
    """
```

Hook point: one new line in `modules/backend/main.py` lifespan, immediately
after the existing schedule registrations (this is §4 edit #5):

```python
await seed_demo_uk_onboarding(session)
```

**Toggle-only seeder.** The demo seeder does NOT load YAML. The existing
`catalog_seeder.py` already walks `config/agents/**/agent.yaml` on first boot
and seeds every YAML it finds — including the demo agents at
`config/agents/demo/uk/onboarding/**/agent.yaml`. The demo seeder's only job
is to toggle the `enabled` column on those rows:

```python
DEMO_AGENT_NAMES = (
    "demo.uk.onboarding.supervisor.agent",
    "demo.uk.onboarding.maker.identity.agent",
    "demo.uk.onboarding.maker.screening.agent",
    "demo.uk.onboarding.maker.risk_rating.agent",
    "demo.uk.onboarding.maker.data_capture.agent",
    "demo.uk.onboarding.qa.agent",
)

async def seed_demo_uk_onboarding(session: AsyncSession) -> None:
    flag_on = get_app_config().features.demo_uk_onboarding_enabled
    svc = AgentCatalogService(session)
    missing: list[str] = []
    for name in DEMO_AGENT_NAMES:
        if await svc.get_by_name_or_none(name):
            await svc.update_entry(name, enabled=flag_on)
        else:
            missing.append(name)
    # Premortem #6 (2026-05-22): make missing agents LOUD when the flag is
    # on. Silent "0 entries updated" on the morning of a demo is the
    # operational failure that kills the walkthrough. Log a WARNING so the
    # operator sees this at startup, not at workflow dispatch.
    if flag_on and missing:
        logger.warning(
            "demo_uk_onboarding flag is ON but agents missing from catalog — "
            "run `admin seed-catalog --force` to bootstrap them",
            extra={"missing_agents": missing},
        )
```

~15 lines. No YAML loading, no upsert logic. The shared catalog services and
the shared catalog seeder do that work.

**RUNBOOK notes (operator-facing — must appear in `77-runbook-demo-uk-onboarding.md`):**

1. **First-time bootstrap on a populated DB.** The toggle-only seeder only
   *updates* existing catalog rows. On a fresh DB the existing
   `catalog_seeder` runs at first boot and picks up the demo YAMLs
   automatically. On an already-populated DB where the demo YAMLs are
   new, run `admin seed-catalog --force` once, then restart the backend
   so the lifespan seeder applies the flag.

2. **Restart REQUIRED after toggling the flag** (Premortem-2 #E).
   `seed_demo_uk_onboarding(session)` only runs inside the FastAPI
   lifespan. Editing `.env` (or `config/settings/features.yaml`) at
   runtime and reloading the dashboard is NOT sufficient — the seeder
   won't rerun, the catalog rows stay at their old `enabled` value, and
   `POST /start` will return `503 DEMO_FLAG_OUT_OF_SYNC`. The operator
   sequence is: edit env → restart backend → confirm seeder log line →
   click tile.

3. **Pre-flight diagnostics.** If the demo tile is visible but
   `POST /start` returns 503, read the error code:
   - `DEMO_NOT_SEEDED` → run `admin seed-catalog --force` and restart.
   - `DEMO_FLAG_OUT_OF_SYNC` → restart only.
   Do NOT run `seed-catalog --force` for `DEMO_FLAG_OUT_OF_SYNC` — it
   re-seeds YAML defaults, which does not toggle the flag and will not
   resolve the 503.

---

## 12. Frontend touchpoint

### 12.1 New page tree

`modules/frontend/src/pages/demo/uk-onboarding/index.tsx`:

Composes three sub-components:
- `FixtureSelector` — native `<select>` with three options; "Start" button posts
  to `/api/v1/demo/uk-onboarding/start`.
- `StreamView` — uses `useMissionStream(missionId)` to render the event log
  with filtering by category (tool calls, agent steps, gates, completions).
- `EvidencePanel` — appears on completion, shows the assembled case package
  JSON and the cost summary, plus a "Download evidence pack" link to the
  artifact endpoint.

### 12.2 Route guard

```tsx
function DemoUkOnboardingPage() {
  const { data: features, isLoading } = useFeatures()
  if (isLoading) return <Spinner />
  if (!features?.demo_uk_onboarding_enabled) return <Navigate to="/" />
  return <DemoLayout>{...}</DemoLayout>
}
```

### 12.3 Dashboard tile

`modules/frontend/src/pages/dashboard.tsx` — single conditional block that
**composes the existing `Card` / `CardHeader` / `CardContent` primitives**
from `modules/frontend/src/components/ui/card.tsx`. No new `DemoTile`
component is introduced.

```tsx
{features?.demo_uk_onboarding_enabled && (
  <Link to="/demo/uk-onboarding">
    <Card className="hover:bg-accent transition">
      <CardHeader>
        <CardTitle>UK Client Onboarding (Demo)</CardTitle>
      </CardHeader>
      <CardContent>
        Synthetic walk-through of the agentic onboarding case.
      </CardContent>
    </Card>
  </Link>
)}
```

### 12.4 API hooks

`modules/frontend/src/hooks/use-demo-uk-onboarding.ts`:

```ts
export function useDemoFixtures() { ... }
export function useStartDemoMission() { ... }   // mutation
export function useDemoMissionStatus(missionId) { ... }
```

All use `api.get/post` from `src/lib/api.ts` — no new client infra.

### 12.5 Gate approval UI

The frontend already has a gate-approval component:
[modules/frontend/src/components/mission/gate-approval.tsx](../../modules/frontend/src/components/mission/gate-approval.tsx)
— takes `{ executionId, gateMessage?, onResolved }` and renders the
approve/reject buttons plus the associated submit hook. The demo page
**composes this existing component** for both the single-gate
(`sanctions_hit`) flow. The `adverse_media` flow now routes deterministically
through `request_more_docs` and does not need the gate UI. No new gate UI is
built.

Two open verifications during impl commit 1 (covered by §13 Q2):

1. Does the SSE stream from `useMissionStream` already include the
   `HumanApprovalRequested`-style event for Plan 75's `human` decision
   resolver? If yes, the demo page hands the event payload (which includes
   the executionId / decision-node id) straight to `GateApproval`.
2. Does the backend already expose a "pending decisions for mission" query
   endpoint? If yes, polling fallback uses it. If not, add a single new
   additive endpoint `GET /api/v1/missions/{mission_id}/pending-decisions`
   in the same demo router file (`endpoints/demo_uk_onboarding.py`) — not in
   shared `missions_workflows.py`, to keep this demo additive.

---

## 13. Open questions to resolve before implementation

**All six questions resolved 2026-05-21.** Items below are kept as historical
context for the audit trail.



1. ~~**Catalog-seeding enforcement.**~~ **Resolved (one-line `main.py` lifespan
   edit, listed as §4 edit #5).**

2. ~~**Gate-approval surfacing.**~~ **Resolved (verify-then-fallback):** first
   implementation commit inspects `workflow_run_waves._execute_decision_step`
   and the human-resolver activity. If SSE already publishes a
   `HumanApprovalRequested`-style event, demo page consumes it via the
   existing `useMissionStream` hook. If not, demo page polls
   `GET /api/v1/missions/{id}/pending-decisions` (existing endpoint per
   Plan 75) at 2s cadence. Either branch keeps the demo page additive — no
   shared-code edit. The fallback path is documented in RUNBOOK.md so the
   presenter knows what to expect.

3. ~~**Pydantic schemas location.**~~ **Resolved:** single NEW file
   `modules/backend/agents/demo/uk/onboarding/schemas.py`, co-located with
   the demo agents. No edit to shared `modules/backend/agents/schemas.py`.

4. ~~**Tool naming.**~~ **Resolved:** flat snake_case `demo_uk_onboarding_*`
   per §7.1. Confirmed.

5. ~~**Evidence path base.**~~ **Superseded twice:**
   - Quality review (2026-05-22): dropped var/ JSON file. Evidence as
     MissionArtifact only.
   - Premortem-2 (2026-05-22): restored `evidence_writer` tool because the
     YAML template engine can't assemble JSON inline. evidence_writer is a
     thin Python tool that takes scalar args, builds the dict in Python,
     and calls `store_artifact(content_type=json)`. Still no file-system
     pattern; still a single `MissionArtifact` row per run.

6. ~~**`.env` → `FeaturesSchema` mapping.**~~ **Resolved (verify-then-alias):**
   first implementation commit inspects `config_schema.py` and the loader for
   how existing flags like `security_startup_checks_enabled` bind to env.
   If `FeaturesSchema` already auto-binds → no extra config. If not → add
   `env="DEMO_UK_ONBOARDING_ENABLED"` alias on the field. Either way the
   outcome is one line and is captured inside §4 edit #2 (no eighth edit).

7. ~~**Plan 75 convergence semantics.**~~ **Resolved by Premortem #1 (2026-05-22):**
   confirmed via code inspection that `_should_skip` propagates skips through
   any non-merge dependency. §10 now uses an explicit `merge_outcomes` node
   (`node_type: merge`, `wait_any`) before `assemble_case`. Still requires
   verification in commit 5 that the merge-node behaviour itself matches the
   assumption (a one-off test workflow with multi-decision-branch convergence
   into a merge node).

8. **SSE durability under JWT refresh.** Premortem #4 (2026-05-22) confirmed
   via `modules/frontend/src/hooks/use-sse.ts` that the SSE endpoint has no
   `Last-Event-ID` cursor and the reconnect path resumes from "now" not
   "last seen". If a JWT refresh happens during a demo run, the gate event
   for `human_approval` can be lost and the approval button never renders.
   First implementation commit must inspect the SSE endpoint and pick one
   mitigation **before commit 9 (frontend stream view)**:
   - (a) Extend access-token TTL via config so longest demo run is comfortably
     within the token lifetime (e.g. ≥30 min).
   - (b) Add `?after_event_id=` cursor support — backend extension to the
     stream endpoint + frontend tracking of last-seen event ID.
   - (c) Add a "Refresh / Resume" button in the demo page only, giving the
     presenter graceful recovery if the stream stalls.
   Option (a) is the smallest change; (b) is the most robust; (c) is the
   demo-scoped workaround. Pick one explicitly, do not defer.

---

## 14. Sequence diagram — clean path

```
User                Frontend                 Backend                Workflow Engine            Mock Tools
 │                     │                        │                          │                       │
 │── click "Start" ───▶│                        │                          │                       │
 │                     │── POST /demo/.../start │                          │                       │
 │                     │   { fixture: clean }   │                          │                       │
 │                     │───────────────────────▶│                          │                       │
 │                     │                        │── Create Mission         │                       │
 │                     │                        │── Bind team (6 members)  │                       │
 │                     │                        │── Start workflow run ───▶│                       │
 │                     │◀───────────────────────│   {mission_id}           │                       │
 │                     │── navigate to stream view                         │                       │
 │                     │── open SSE  ──────────▶│                          │                       │
 │                     │                        │                          │── triage step         │
 │                     │◀──── AgentStepStarted ─│◀─────────────────────────│── invoke playbook_fetch ──▶│
 │                     │                        │                          │                       │ (200ms)
 │                     │◀──── ToolInvoked ──────│                          │◀──────────────────────│
 │                     │                        │                          │── data_capture        │
 │                     │                        │                          │── identity (parallel) │
 │                     │                        │                          │── screening (parallel)│
 │                     │                        │                          │── risk_rating         │
 │                     │                        │                          │── qa                  │
 │                     │                        │                          │── route_qa decision   │
 │                     │                        │                          │    rule eval → straight_through
 │                     │                        │                          │── assemble_case ─────▶│ crm_create_case
 │                     │                        │                          │── write_evidence ────▶│ store_artifact (JSON)
 │                     │◀──── MissionCompleted ─│                          │                       │
 │                     │── show EvidencePanel   │                          │                       │
```

For `sanctions_hit`: an additional `human_approval` decision-node step pauses
the run and emits a `HumanApprovalRequested` SSE event. The demo page renders
Approve/Reject buttons; clicking Approve POSTs to the existing
human-resolver resume endpoint.

For `adverse_media`: the `request_more_docs` tool_call step runs
deterministically (no human gate). The workflow completes by writing an
evidence pack noting the additional-docs request.

---

## 15. Verification

Maps 1:1 to the brief's verification checklist.

### 15.1 Flag-off smoke test

`tests/integration/demo_uk_onboarding/test_flag_off_smoke.py`:

```python
async def test_demo_route_404_when_flag_off(): ...
async def test_demo_agents_disabled_in_catalog_when_flag_off(): ...
async def test_no_demo_template_runnable_when_flag_off(): ...
```

Plus: `pytest` (full suite) before and after, capturing
`pytest --collect-only | tail -1` to confirm test-count parity (one new test
folder added → expected count delta = number of new tests, NOT a regression).

### 15.2 Flag-on golden path

`tests/integration/demo_uk_onboarding/test_clean_path.py` — real Postgres,
real Temporal test server, mocked LLM via PydanticAI's `TestModel`. Asserts:
- Mission completes within budget
- Zero gates fired
- Evidence MissionArtifact row exists for the mission, with
  `content_type="json"` and `artifact_type="data"`
- Parsed JSON contains tool-call timeline + total cost

### 15.3 Flag-on sanctions hit

`test_sanctions_hit_gate.py`. Programmatically resumes the `human_approval`
decision node via the existing resume endpoint with a rationale. Asserts the
rationale is captured in the evidence pack.

### 15.4 Flag-on adverse media

`test_adverse_media_request_docs.py`. Runs the `adverse_media` fixture and
asserts the workflow routes to `request_more_docs` (no human gate fires),
completes cleanly, and the evidence pack records the additional-docs
request. Replaces the original four-eyes test, dropped per Premortem #5.

### 15.5 Cleanup grep

```
grep -rEh 'demo_uk_onboarding|demo\.uk\.onboarding|demo/uk/onboarding|demo-uk-onboarding' \
  modules/ config/ tests/ docs/ | wc -l
```

The alternation covers: snake_case (tools, fixtures, services, env var,
endpoint paths), dotted (agent names, workflow template name, capabilities),
folder path (agent + prompt folders), and kebab (frontend route, workflow
template name segment). `var/` is excluded because no demo files are written
there (evidence persists to the DB). Expected count is recorded in the plan
post-impl. Any unexpected count = constraint violation.

### 15.6 Existing test parity

```
pytest --collect-only -q | tail -1 > /tmp/before.txt   # pre-branch
# ... after impl ...
pytest --collect-only -q | tail -1 > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt    # should show only the added demo tests
pytest -q                                # 100% green
```

---

## 16. Commit plan (post-approval implementation order)

Each commit is self-contained, runnable, and passes `pytest`.

**YAML style requirement (applies to every new YAML file in this plan):** per
the project rules, each new YAML file (agent YAMLs, the workflow template,
the new line in `features.yaml`) must include a leading comment block
listing all valid keys/options for that file's schema. Mirror the
convention used by existing files in `config/agents/` and
`config/workflow_templates/`.

1. **scaffolding**: feature flag declaration (§6) + empty demo router + 404
   guard. Smoke test asserts flag-off 404.
2. **tools**: seven tools + unit tests — five mock domain
   (`identity_verify`, `screening_search`, `document_ocr`, `crm_create_case`,
   `playbook_fetch`), one routing helper (`request_docs`), and two
   internal helpers (`fixture_loader`, `evidence_writer`). Tool files live
   at `modules/backend/tools/demo_uk_onboarding_*.py` (FLAT layout) so the
   `pkgutil.iter_modules` registry walker discovers them (Premortem-2 #F).
3. **fixtures**: three JSON files + Pydantic schema + loader tests.
4. **agents (YAML + prompts)**: six YAMLs + six system.md files. Catalog
   seeder run shows them in DB. Toggle tested via `DemoSeeder`.
5. **agents (Python)**: six `agent.py` modules + `deps.py` + `schemas.py`.
   Each agent unit-tested with `TestModel`.
6. **workflow template**: YAML + workflow_validator pass + seeded into DB.
   Integration test runs `clean.json` end-to-end (no UI yet, drives via
   service layer).
7. **API endpoint**: router + service + idempotency. Integration tests for
   all three fixtures via HTTP.
8. **frontend route + page + hooks**: scaffolding + route guard + fixture
   selector. Manual verification of flag-off → 404.
9. **frontend stream view + evidence panel**: composes existing
   `useMissionStream`. Manual verification of clean path.
10. **frontend gate prompt UI**: surfaces decision-node human-approval events.
    Manual verification of sanctions + adverse-media paths.
11. **dashboard tile**: single conditional tile.
12. **runbook + gaps**: `docs/97-plans/77-runbook-demo-uk-onboarding.md` and
    `docs/97-plans/77-gaps-demo-uk-onboarding.md`.
13. **final regression sweep**: full `pytest`, cleanup grep, mark plan
    "Closed" with date.

---

## 17. Demo-scope limitations (preview for GAPS.md)

**Writing-style requirement.** GAPS.md uses neutral engineering language
throughout. Premortem #3 (2026-05-22) showed that rhetorical flourishes
("theatre", "roast", "illustrative only") become out-of-context kill-shot
quotes if the file is read by procurement, vendor-risk, or a skeptical
internal reader. Standard substitutions:

| Avoid | Prefer |
|---|---|
| "theatre" | "demo-scope simulation" |
| "roast" / "brutally honest" | "known limitations" |
| "illustrative only" | "representative; not production-grade" |
| "fake" / "faked" | "stubbed" |
| "this is not real X" | "this demo does not implement X" |

The information content stays identical; the quotability drops sharply.

### Capabilities this demo does NOT implement

- Real KYC/AML providers (Onfido, ComplyAdvantage, LexisNexis, etc.) — all
  five domain tools return seeded, synthetic payloads.
- Jurisdictional data residency.
- Model Risk Management register / model approval workflow.
- Immutable audit log / WORM storage. Evidence persists as a standard
  `mission_artifacts` row with the same durability guarantees as every
  other workflow's outputs.
- Entra ID SSO or any production IdP integration.
- **Four-eyes (dual-control) enforcement via distinct identities.** The
  original plan included a two-gate approximation; it was dropped (see §9.4
  and §10). The demo does not implement four-eyes in any form. A genuine
  implementation would require distinct `approved_by_user_id` per gate and
  a second-approver UI — a real product capability, out of scope here.
- Environment promotion / change-management gates.
- Cost accounting beyond per-run LLM cost (no infrastructure cost allocation).

### Architectural notes

Two of the six demo agents are LLM-driven where a deterministic
implementation would fit better:

- `maker.data_capture`: extracts structured client data from JSON fixtures
  that are already structured. A production implementation would be a
  `tool_call` step calling `document_ocr` per document.
- `maker.risk_rating`: assembles risk factors into low/medium/high. A
  production implementation would be rule-based scoring (P2: "Deterministic
  Over Non-Deterministic").

The demo retains them as agents so the dispatch narrative matches the
brief's six-agent team composition. This is a demo-scope choice, not a
recommended architecture.

---

## 18. Status checklist

### Pre-implementation reviews

- [x] Plan written (2026-05-21)
- [x] Open questions §13 Q1–Q6 resolved (2026-05-21)
- [x] Plan-quality review applied — 6 amendments (2026-05-21)
- [x] Premortem-1 applied — 8 amendments (2026-05-22)
- [x] Premortem-2 (amendment verification) applied — 6 amendments (2026-05-22)
- [x] All P0 failures resolved in plan
- [ ] User-approved plan for implementation

### Verdict: **PROCEED WITH MITIGATIONS**

All P0 failures from both premortems resolved in the plan. Implementation
may begin once the user gives final approval. Commit 1 still owes the
following verifications (carried over from §13):

- [ ] Commit 1: round-trip §10 YAML through `workflow_validator`; fix any
      schema rejections it reports
- [ ] Commit 1: verify Plan 75 merge-node convergence with an isolated test
      workflow (§13 Q7)
- [ ] Commit 1: pick SSE durability mitigation from the three options in
      §13 Q8 (JWT TTL extension / cursor / refresh button)
- [ ] Commit 1: verify `GateApproval` component's payload shape matches
      what Plan 75's `human` resolver emits

### Implementation

- [ ] Feature flag scaffolding (§6)
- [ ] Mock tools + tests (seven tools per §8.1; flat layout per §16)
- [ ] Fixtures + tests (§9)
- [ ] Agents (YAML + prompts) — six agents per §7
- [ ] Agents (Python + tests) — six from-scratch
- [ ] Workflow template + integration test (clean path) — §10
- [ ] API endpoint + integration tests (all three paths) — §11.1 with
      pre-flight 503 codes per Premortem-2 #E
- [ ] Frontend page + route guard (§12)
- [ ] Frontend stream view + evidence panel
- [ ] Frontend gate prompt UI (reuse existing `GateApproval`)
- [ ] Dashboard tile (reuse existing `Card` primitive — §12.3)
- [ ] RUNBOOK.md — including operator notes from §11.3 (restart-after-flag,
      pre-flight diagnostics)
- [ ] GAPS.md — neutral engineering language per §17 substitution table

### Close-out

- [ ] Full `pytest` green
- [ ] Cleanup grep count recorded (§15.5)
- [ ] Plan marked Closed
