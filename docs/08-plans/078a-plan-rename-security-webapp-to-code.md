# Plan 78a: Rename WASA Phase 1 — `security.webapp.*` → `security.code.*`

## Status: Draft (2026-05-22)

**Priority:** Medium (mechanical, but blocks Plan 78)
**Branch:** TBD — `feature/78a-rename-security-webapp-to-code`
**Dependencies:** None
**Blocks:** Plan 78 (Code Security Review Mission)

---

## Summary

Rename the WASA Phase 1 agents, prompts, configs, and workflow from `security.webapp.*` to `security.code.*`. **No behavioural changes.** Reserves the `security.web.*` namespace for genuinely-web (DAST / HTTP / browser) agents from WASA Phase 2+ per Plan 66.

Pure mechanical rename:
- 7 directory moves (agent dirs + prompt dirs + config dirs)
- 1 workflow YAML rename
- ~21 files containing `security.webapp.*` strings → `security.code.*`
- 1 catalog re-seed
- Updates to ~4 test fixtures

---

## Why

WASA Phase 1 ships scanner/triage/reporter agents that run SAST tools on a code directory. They never touch HTTP, browsers, or web traffic. The `webapp` label was inherited aspirationally from Plan 66 (which has DAST in Phase 2+) but is factually wrong for the shipped code:

- `security.webapp.scanner` runs OpenGrep / Bandit / Trivy / pip-audit / Roslyn on a directory — no web semantics.
- `security.webapp.triage` is an LLM filter over SARIF findings — no web semantics.
- `security.webapp.reporter` synthesises a `SecurityAssessmentReport` from findings — no web semantics.

The misnomer is about to propagate. Plan 78 (Code Security Review Mission) was originally going to add `security.webapp.holistic` and `security.webapp.config_review` — entrenching the wrong namespace. Fix it now while it's cheap.

P3 (Breaking Changes Are Free During Dev) applies — no backward-compatibility shims, no aliases. Delete the old name.

---

## Scope

### What renames

| From | To |
|---|---|
| `modules/backend/agents/security/webapp/` | `modules/backend/agents/security/code/` |
| `config/agents/security/webapp/` | `config/agents/security/code/` |
| `config/prompts/agents/security/webapp/` | `config/prompts/agents/security/code/` |
| `config/workflow_templates/security.webapp-assessment.workflow.yaml` | `config/workflow_templates/security.code-assessment.workflow.yaml` |
| Capability `security.webapp.scanner` | `security.code.scanner` |
| Capability `security.webapp.triage` | `security.code.triage` |
| Capability `security.webapp.reporter` | `security.code.reporter` |
| Workflow name `security.webapp-assessment.workflow` | `security.code-assessment.workflow` |
| Agent module path `modules.backend.agents.security.webapp.{scanner,triage,reporter}.agent` | `modules.backend.agents.security.code.{scanner,triage,reporter}.agent` |

### What stays the same

- All Python code inside agent files (only import paths change).
- All prompt content.
- All workflow logic.
- All Pydantic models in `agents/security/models.py`.
- `agents/security/{tool_runner,sarif,roe,evidence,errors,tool_registry,deps,config}.py` — unchanged (these live at `agents/security/` root, not under `webapp/`).
- Container image name `security-assessment-worker:latest` — unchanged. The image is generic SAST infrastructure; renaming it would create a separate ops migration. Defer to a follow-up if desired.
- Plan 66 spec document — keep "WASA" as the program name; it's a brand, not a capability namespace. The spec already acknowledges (§0.1) that other security families (network, cloud, mobile) get sibling specs.

### What's reserved going forward

| Namespace | Reserved for |
|---|---|
| `security.code.*` | Static analysis of source code (this rename's target) |
| `security.web.*` | Genuinely-web work: DAST, HTTP fuzzing, browser automation, Burp integration (WASA Phase 2+) |
| `security.cloud.*` | Future — cloud infrastructure scanning |
| `security.network.*` | Future — network recon, port scanning |
| `security.mobile.*` | Future — mobile binary analysis |
| `security.<other>.*` | Future families per Plan 66 §0.1 |

`security.webapp.*` is deleted, not reserved. The next user of a webapp surface should pick `security.web.*`.

---

## Rename surface (enumerated)

Exhaustive list, verified by grep. **21 files** carry `security.webapp.*` or `webapp-assessment` references.

### Agent code (4 files — moved by `git mv`)

| File | Action |
|---|---|
| `modules/backend/agents/security/webapp/__init__.py` | Move to `modules/backend/agents/security/code/__init__.py` |
| `modules/backend/agents/security/webapp/scanner/agent.py` | Move to `code/scanner/agent.py`; update internal references (see below) |
| `modules/backend/agents/security/webapp/triage/agent.py` | Move to `code/triage/agent.py`; update internal references (see below) |
| `modules/backend/agents/security/webapp/reporter/agent.py` | Move to `code/reporter/agent.py`; update internal references (see below) |
| `modules/backend/agents/security/webapp/{scanner,triage,reporter}/__init__.py` | Move with parent |

**Load-bearing internal references inside the moved agent files** (verified by grep) — these MUST update or agents fail to load at runtime:

| File | Line | What |
|---|---|---|
| `webapp/scanner/agent.py` | 1 | Docstring: `"""WASA Scanner Agent (security.webapp.scanner.agent)."""` → update both substrings |
| `webapp/scanner/agent.py` | 57 | `instructions=assemble_instructions("security.webapp.scanner")` → `"security.code.scanner"`. **This is load-bearing** — `assemble_instructions()` resolves prompt files by this string. After the prompt-directory rename, this MUST match or the agent fails to find its system.md. |
| `webapp/triage/agent.py` | 1 | Docstring: `"""WASA Triage Agent (security.webapp.triage.agent)."""` → update |
| `webapp/triage/agent.py` | 26 | `assemble_instructions("security.webapp.triage")` → `"security.code.triage"` |
| `webapp/reporter/agent.py` | 1 | Docstring: `"""WASA Reporter Agent (security.webapp.reporter.agent)."""` → update |
| `webapp/reporter/agent.py` | 27 | `assemble_instructions("security.webapp.reporter")` → `"security.code.reporter"` |

These six edits are the highest-risk diffs in the PR. A project-wide `sed 's/security\.webapp/security.code/g'` over `.py` files catches all six. Verify with `grep -rn "security\.webapp" modules/` after the sed (should return zero).

### Agent YAML configs (3 files — moved)

| File | Action |
|---|---|
| `config/agents/security/webapp/scanner/agent.yaml` | Move to `code/scanner/agent.yaml`; update `name:` field (`security.webapp.scanner.agent` → `security.code.scanner.agent`) |
| `config/agents/security/webapp/triage/agent.yaml` | Same |
| `config/agents/security/webapp/reporter/agent.yaml` | Same |

### Prompt files (3 files — moved)

| File | Action |
|---|---|
| `config/prompts/agents/security/webapp/scanner/system.md` | Move to `code/scanner/system.md` |
| `config/prompts/agents/security/webapp/triage/system.md` | Move to `code/triage/system.md` |
| `config/prompts/agents/security/webapp/reporter/system.md` | Move to `code/reporter/system.md` |

### Workflow YAML (1 file — moved + content edit)

| File | Action |
|---|---|
| `config/workflow_templates/security.webapp-assessment.workflow.yaml` | Move to `security.code-assessment.workflow.yaml`; update `workflow_name:` field, all `capability:` fields, all `source_task:` fields |

### Cross-references in non-security code (4 files — string replace)

| File | Lines | Note |
|---|---|---|
| `modules/backend/core/agent_registry.py` | 250-251 | Docstring mentioning `security.webapp.scanner` as an example — update to `security.code.scanner` |
| `modules/backend/agents/mission_control/helpers/agent_setup.py` | 90 | **`if "security.webapp.scanner" in agent_name:` — hardcoded substring check.** Must update to `security.code.scanner`. **Risk point.** |
| `modules/backend/agents/mission_control/helpers/prompt_builder.py` | 37-38 | Docstring examples — update |
| `modules/backend/agents/mission/director/agent.py` | 455 | Docstring referencing `security.webapp-assessment` workflow name — update to `security.code-assessment` |
| `modules/backend/agents/mission/planning/tools.py` | (grep hit) | Verify and update |

### Tests (2 files — fixture update)

| File | Note |
|---|---|
| `tests/unit/backend/agents/mission/planning/test_build_session.py` | Fixture or assertion referencing webapp namespace — update |
| `tests/unit/backend/agents/mission/planning/test_planning_tools.py` | Same |

**No `tests/.../webapp/` test directory exists** (verified by `find tests -type d -name webapp`). The only test changes are string updates inside the two files above.

### Catalog seeding

| File | Action |
|---|---|
| `modules/backend/services/catalog_seeder.py` | Re-seeds the catalog from YAML at startup. After this rename, on next startup the seeder will create new catalog rows under `security.code.*` and orphan the old `security.webapp.*` rows. Need a one-shot migration (see "Catalog migration" below). |

### Documentation (5 files — content edit)

| File | Note |
|---|---|
| `docs/97-plans/66-spec-webapp-security-assessment.md` | Spec for WASA — keep "WASA" as program name, update capability strings in §6.2 (workflow definition) |
| `docs/97-plans/67-plan-wasa-phase-1-implementation.md` | Update capability strings; note rename completion |
| `docs/97-plans/68-plan-agent-decision-audit-trail.md` | Update any references |
| `docs/97-plans/69-plan-incremental-plan-building-[X].md` | Closed plan — update only if referenced strings are misleading |
| `docs/97-plans/78-plan-code-security-review-mission.md` | This plan's sibling — already uses `security.code.*` in v3 |

### Settings

| File | Note |
|---|---|
| `.claude/settings.json` | Check if any allowlist / permission rule references the webapp namespace |

### Stays unchanged (verified)

| File | Why |
|---|---|
| `modules/backend/agents/security/{tool_runner,sarif,roe,evidence,errors,tool_registry,deps,config,models}.py` | Live at `agents/security/` root — not under `webapp/`. Generic to all security families. |

---

## Catalog migration

The agent catalog is DB-backed (per `pattern_agent_catalog` memory: "DB is authoritative for the agent catalog; YAML is seed-only"). After this rename, the seeder will register new `security.code.*` rows on next startup, but the old `security.webapp.*` rows will remain unless explicitly removed.

Two options:

### Option A — DB migration (recommended)

Alembic migration that:
1. `UPDATE agent_catalog SET capability = REPLACE(capability, 'security.webapp.', 'security.code.') WHERE capability LIKE 'security.webapp.%';`
2. `UPDATE agent_catalog SET name = REPLACE(name, 'security.webapp.', 'security.code.') WHERE name LIKE 'security.webapp.%';`
3. Same for any `agent_path` / `module_path` columns.
4. Migration is reversible (down() does the reverse REPLACE).

This preserves any operator-side catalog edits (PATCH overrides from Plan 65) — the row identity is the same, only the capability string changes.

### Option B — Re-seed (simpler but lossy)

`DELETE FROM agent_catalog WHERE capability LIKE 'security.webapp.%'`, then let the seeder re-create under `security.code.*`. Loses any operator PATCH overrides.

**Recommendation: Option A.** Migration is straightforward; preserves DB-authoritative edits per the catalog pattern.

### Migration ordering (must be deterministic)

The Alembic migration **must run before** the catalog seeder on the first post-rename startup. Otherwise:
- Seeder runs first → creates new `security.code.*` rows alongside orphaned `security.webapp.*` rows.
- Migration's `UPDATE … REPLACE` then collides on the now-existing new rows (unique-name constraint).

Standard Alembic migrations execute during `alembic upgrade head` which is part of deploy / startup ordering ahead of FastAPI `lifespan` (where the seeder runs from `services.catalog_seeder`). Verify this ordering in the deploy pipeline before merge; if `lifespan` runs Alembic, the order is automatic. If migrations are hand-applied, document the required order in the PR description.

**Acceptance:** Boot from a fresh DB (no rows) → seeder creates `security.code.*` only. Boot from a populated DB (old `security.webapp.*` rows) → migration updates them in place; seeder finds matching rows and is idempotent.

---

## In-flight mission impact

Most cross-table references use foreign keys by ID, not name. The migration's reach is narrower than first appears.

| Table | Reference style | Impact of rename |
|---|---|---|
| `workflow_definition` | Stores `name` as a string field | **Update required** — the `name` column carries `security.webapp-assessment.workflow`; migration UPDATEs it to `security.code-assessment.workflow`. |
| `workflow_run` | `workflow_definition_id` FK (UUID) to `workflow_definition.id` | **No update needed** — FK by ID, not name. Renaming the definition's name field preserves all run references. |
| `mission` | Carries no direct workflow-name string (verify) | No update needed if true. |
| `mission_team` | References agents by capability string (e.g., `security.webapp.scanner.agent`) | **Update required** — capability strings must be migrated alongside `agent_catalog`. |
| `agent_catalog` | Carries `name` and `capability` strings | **Update required** — Option A migration above. |

**Pre-merge SQL audit:** target only tables that store *name strings*. Specifically:
```sql
SELECT 'agent_catalog' AS tbl, name, capability FROM agent_catalog WHERE name LIKE 'security.webapp.%' OR capability LIKE 'security.webapp.%';
SELECT 'workflow_definition' AS tbl, name FROM workflow_definition WHERE name LIKE 'security.webapp%';
SELECT 'mission_team' AS tbl, mission_id, agent_capability FROM mission_team WHERE agent_capability LIKE 'security.webapp.%';
```

Migration handles all three with consistent `UPDATE … REPLACE` operations. No `workflow_run` table edit needed.

---

## Build order

Single PR, no phases. Mechanical changes only.

1. Run `git mv` for the directory moves.
2. Run a project-wide `sed` (or scripted refactor) for the string replacements. Verify the count drops to zero with `grep -r "security.webapp"`.
3. Update the hardcoded `if "security.webapp.scanner" in agent_name:` branch in `agent_setup.py:90`.
4. Update workflow YAML internals (`capability:`, `source_task:`, `workflow_name:`).
5. Write Alembic migration (Option A above).
6. Run the unit + integration test suite. Update any test fixtures that reference the old namespace.
7. Manual smoke: create a `security.code-assessment.workflow` run, verify scan → triage → report executes end-to-end.

---

## Acceptance criteria

1. `grep -r "security\.webapp" modules/ config/ tests/` returns zero results.
2. `grep -r "webapp-assessment" modules/ config/ tests/` returns zero results.
3. Existing WASA Phase 1 integration tests pass under the new namespace.
4. A fresh database boot seeds `security.code.{scanner,triage,reporter}` capability rows; no `security.webapp.*` rows exist.
5. An existing database with `security.webapp.*` rows is migrated cleanly by the Alembic up() migration; the down() migration restores the old state for rollback.
6. A workflow run with the new `security.code-assessment.workflow` name executes scan → triage → report end-to-end against a fixture target.
7. No `.claude/settings.json` permission breakage.
8. Docs in `97-plans/` are consistent — no plan refers to `security.webapp.*` as a current state (historical references in Plan 66/67 are fine if marked).

---

## Failure modes

| Failure | Response |
|---|---|
| `agent_setup.py:90` substring check missed → scanner instantiation breaks | Pre-merge: explicit grep for `security.webapp` in all `.py` files; the substring check is the only place this matters because it's a runtime branch, not an import. |
| Alembic migration fails on prod-like data | Migration is wrapped in a transaction; failure rolls back. Test against a snapshot before merge. |
| Catalog seeder creates duplicate rows (one set old, one set new) | Pre-condition: run the migration *before* the seeder runs on next startup. Verify migration ordering. |
| Existing TUI / frontend has hardcoded references to `security.webapp.*` | Grep both `modules/clients/` and `modules/frontend/` — current grep shows no client references; verify before merge. |

---

## Out of scope

- Renaming the `security-assessment-worker:latest` Docker image. The image name is generic SAST infrastructure; renaming it requires a separate ops migration (registry tag, CI build, references in container_image fields). Defer.
- Renaming Plan 66/67 file names. The `wasa-phase-1` framing is the program name, not the capability namespace. The plan content gets updated for capability strings; filenames stay.
- Renaming any Pydantic model that contains `Webapp` in its name (verify none exist — Plan 67 models.py uses generic names like `Finding`, `SecurityAssessmentReport`).
- Renaming the existing test directory structure under `tests/unit/backend/agents/security/`. If tests live at `tests/unit/backend/agents/security/webapp/`, they should also be moved — verify and include if so.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Hardcoded substring check in `agent_setup.py:90` missed | High | Explicit grep audit; pin this as the highest-attention diff in code review. |
| Alembic migration data loss on existing rows | Medium | Migration is reversible (Option A); test against DB snapshot before merge. |
| In-flight workflow runs orphaned | Low (assuming P1 is still in dev) | Pre-merge SQL audit; include in migration if found. |
| Client / frontend hardcoded references | Low | Grep both client trees; current scan shows none. |
| Cascading rename to image / config keys creates merge friction | Low | Explicitly out of scope; deferred. |

---

## Done definition

- [ ] All 21 webapp references replaced with code equivalents
- [ ] Alembic migration written and reversible
- [ ] All existing tests pass under new namespace
- [ ] Smoke run of `security.code-assessment.workflow` succeeds end-to-end
- [ ] No `security.webapp.*` strings remaining in `modules/`, `config/`, `tests/`
- [ ] Docs updated for current state (Plan 66 / 67 capability strings refreshed)
- [ ] Plan 78 unblocked
