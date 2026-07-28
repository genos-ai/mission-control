# Plan 85 — Multi-Instance Deployment on a Universal Core

**Version:** 1.0.0
**Date:** 2026-07-29
**Author:** Herman + Opus 5 design session (`/prompt-get-context` → ideation → `/prompt-make-plan`)
**Status:** Not started
**Depends on:** None (all changes are to existing config resolution and seeding)
**Unlocks:** Running N differentiated Mission Control instances (security / business / laptop-coworker)
from one code checkout, each with its own database, catalog subset, and identity
**Workflow:** Commit directly to `main`, one commit per sub-phase, working code only (no PRs)

---

## 0. Problem Statement

We want several Mission Control instances — one security-focused, one business-focused, one running
locally as a personal coworker — sharing **one universal core codebase** while each has its own
missions, agents, tools and workflows.

A central AI Ops team builds and tests every agent and tool. That is the decisive constraint: because
one team owns all the code, we do **not** need a plugin architecture, entry points, a host SDK, or
independently versioned extension packages. Every instance deploys the same tree and differentiates
itself entirely through **data and configuration**.

Most of this already exists:

| Requirement | Already in the tree |
|---|---|
| A mission's agents | `mission_team_members` × `agent_catalog`, joined by `agents/mission_control/roster.py` |
| A mission's tools | `agent_catalog.tools` (JSON column, per agent) |
| The brief | `mission.brief` + the `mission_intent` model with revision history |
| Agent prompts | `agent_catalog.system_prompt` + `prompt_version` table — DB authoritative, YAML seed-only |
| Workflows | `workflow_definitions`, `mission_id = NULL` meaning global |
| Per-instance enable/disable | `agent_catalog.enabled` + `admin.py admin toggle-agent` |

**Mission = agents + tools + brief is the current schema, not a proposal.** What blocks multi-instance
deployment is narrower than it first appears — four concrete defects:

1. **Config location is derived from the code checkout.** `find_project_root()`
   (`modules/backend/core/config.py`) walks up from `Path.cwd()` looking for `.project_root`, and every
   config path is `<that root>/config/...`. Two instances sharing one clone would share one `.env`, one
   `models.yaml`, one `prompts/organization/`, and one `var/logs/`.

2. **`find_project_root()` is cwd-dependent, so it is non-deterministic.** Running
   `python /path/to/mc-core/mc.py` from `~/instances/laptop` raises `RuntimeError: Project root not
   found`. Worse, `var/worktrees/*/workspace/.project_root` files exist, so a process whose cwd lands
   inside a worktree silently resolves the *worktree* as project root.

3. **Seeding is all-or-nothing.** `seed_catalog()` (`services/catalog_seeder.py`) rglobs every
   `config/agents/**/agent.yaml`; `seed_workflows()` (`services/workflow_seeder.py`) globs every
   template. There is no way to seed the subset an instance should have.

4. **Catalog/code drift fails silently.** `AgentRegistry._load_from_db()` catches per-row failures,
   logs an error, and continues. An enabled catalog row whose Python module is absent from the
   deployment produces an agent that silently does not exist — the only symptom is a mission that never
   dispatches. Tolerable when code and catalog always ship together; a live failure mode once instances
   hold independent catalog state.

This plan fixes exactly those four things and adds a `full` / `solo` profile so the laptop instance can
run without Temporal or containers.

### Out of scope

- **Plugin/extension architecture.** No entry points, no host SDK, no separate distributions, no
  conformance suite. Explicitly rejected for this org model. Revisit only if a second team owns a
  domain, an instance needs a different release cadence than core, or someone outside the AI Ops team
  must ship an agent.
- **Making the repo pip-installable.** Not required — `sys.path.insert(PROJECT_ROOT)` in the four entry
  files continues to work, and `PROJECT_ROOT` there is already `Path(__file__).parent`.
- **Generalising capability-based tool resolution** out of `agents/security/tool_registry.py`. Valuable
  and cheap, but independent of this plan. Follow-up.
- **Row-level tenancy.** Each instance gets its own PostgreSQL database. No `instance_id` columns
  anywhere. If instances ever must share one database, that is a different plan.
- **Anything in Plan 84.** The hardening backlog (error visibility, god-file decomposition, API-key
  scopes, rate limiter wiring, dependency-manifest split) is unaffected and proceeds independently.
- **New product features.** This plan changes where configuration lives and what gets seeded. Nothing
  else.

---

## Global constraints for the implementing agent

These override any instinct to improvise.

1. **Fail fast, fail loud.** No silent fallbacks, no hardcoded defaults. This plan *removes* a silent
   fallback (Phase 3); never add one. Where a value is genuinely optional, absence must be
   representable and must break loudly downstream, not be papered over.
2. **P3 applies — breaking changes are free.** No shims, no `_legacy` aliases, no deprecation wrappers.
   Delete replaced code in the same commit.
3. **Backwards compatibility for the *existing checkout* is required, and is achieved by one
   deliberate default, not by shims:** when no instance root is specified, `instance_root()` returns
   `<code_root>/config`. The current single-instance dev flow keeps working with zero file moves and
   zero env vars. Phase 1 must not relocate any file in this repo.
4. **Line numbers in this document are hints only.** The tree moves. **Re-locate every target by symbol
   name** (`find_project_root`, `get_settings`, `seed_catalog`, `_load_from_db`, …).
5. **Verify before every commit:**
   ```bash
   python scripts/code_rules_fast.py --all   # must exit 0
   pytest tests/unit -x -q                   # must pass
   ```
   Run `pytest tests/integration -x -q` when the phase touches services, API, or config loading
   (requires local Postgres + Redis; `python services.py check` verifies they are up).
6. **Never commit broken code.** One commit per sub-phase, message prefix `Plan 85 Phase N:`.
7. **House rules that recur here:** absolute imports only; `utc_now()` for all timestamps; centralised
   logging via `get_logger()`; config schemas use `extra="forbid"`; every YAML config file opens with a
   commented options header (rule 003.3); no `os.getenv()` with a hardcoded fallback in module code
   (rule 003.5); files target ~500 lines, hard max 1000.
8. **New config files must have a commented options header.** `config/profiles/*/README.md` is not a
   substitute — the header goes in each YAML.
9. **When a phase says "enumerate via grep", the authoritative list is the live grep output**, not the
   counts in this document.

---

## 1. Phase 0 — The instance-root primitive

Everything else depends on this. Two new functions and one behaviour fix, all in
`modules/backend/core/config.py`. No files move in this phase.

### 0.1 Make `find_project_root()` deterministic

**Problem:** it walks up from `Path.cwd()`. This makes the resolved root depend on the caller's working
directory, breaks any invocation from outside the repo, and can silently resolve to
`var/worktrees/<id>/workspace` (those directories contain `.project_root` — verified 2026-07-29).

**Change:** resolve from the module's own location instead of the process cwd.

```python
def find_project_root() -> Path:
    """Find the code root by walking up from this module toward .project_root.

    Deterministic — independent of the process working directory. Agent
    worktree redirection is explicit (deps.project_root override in
    agents/mission_control/helpers/agent_executor.py), never implicit
    via cwd, so this must not consult cwd.
    """
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".project_root").exists():
            return current
        current = current.parent
    raise RuntimeError(
        "Project root not found: no .project_root marker above "
        f"{Path(__file__).resolve().parent}"
    )
```

**Safety check the implementer must perform before committing:** confirm nothing relies on cwd-based
resolution to reach a worktree. The known worktree path overrides `deps.project_root` explicitly —
verify by reading `agents/mission_control/helpers/agent_executor.py` (the tier guard and
`project_root` override) and `scripts/verify_isolation.py`. If any caller *does* rely on cwd
resolution, it must be changed to pass an explicit root, not to keep the cwd behaviour.

**Tests to update:** `tests/unit/backend/core/test_config.py` has `find_project_root` cases that
`monkeypatch` cwd (see the class around line 45) and a case asserting `RuntimeError` when the marker is
missing. Rewrite them against the new contract: the function is cwd-independent, and the
marker-missing case now requires patching `__file__` resolution rather than cwd.
`tests/unit/backend/core/test_logging.py` patches
`modules.backend.core.logging.find_project_root` — unaffected.

### 0.2 Add `instance_root()`

**New function in `modules/backend/core/config.py`:**

```python
def instance_root() -> Path:
    """Resolve the instance root — where per-instance config, secrets and state live.

    Resolution order:
      1. MC_INSTANCE_ROOT environment variable (set by the --instance CLI flag)
      2. <code_root>/config   (the single-instance default — today's layout)

    The directory must exist. A configured-but-missing instance root is a
    hard error, never a silent fall back to the default.
    """
```

Requirements:

- Not `@lru_cache`d on its own — cache it the same way `get_settings()` is cached, i.e. downstream
  accessors cache, so tests can clear caches. Confirm: `get_settings`, `get_app_config`, and
  `get_mission_control_config` are all `@lru_cache`. Any test that changes `MC_INSTANCE_ROOT` must
  clear those caches; add a fixture in `tests/conftest.py` that does so.
- If `MC_INSTANCE_ROOT` is set and the path does not exist → raise, with the resolved path in the
  message. Do **not** fall back.
- `MC_INSTANCE_ROOT` is read with plain `os.environ.get()` and *no* default value inside module code —
  the default lives in this function's documented resolution order, which rule 003.5 permits because
  the fallback is a computed path, not a literal. Keep it that way: no `os.getenv("X", "literal")`.

**New `--instance` option on all four entry files** (`mc.py`, `admin.py`, `services.py`, `tui.py`):

- `--instance PATH` — sets `MC_INSTANCE_ROOT` in `os.environ` **before** any `modules.backend.core.config`
  import resolves configuration. In the Click entry files this means setting it in the group callback
  before the lazy handler import; in `services.py` (argparse) before `sys.path` work triggers config
  loading.
- Rule 010.1: the `tree` output of every entry file must list the new option. `admin.py tree` and
  `services.py tree` introspect the real parser, so this is automatic; verify.
- Rule 002.1 already requires `--verbose` and `--debug` on entry scripts — do not disturb them.

### 0.3 Three-layer settings resolution

**Current:** `load_yaml_config(filename)` reads exactly `<code_root>/config/settings/<filename>` and
raises `FileNotFoundError` if absent. `AppConfig.__init__` calls it 18 times through
`_load_validated` / `_load_validated_optional`.

**New:** resolve each settings file through three layers, lowest to highest precedence:

1. `<code_root>/config/settings/<file>` — core defaults (always present; missing here is still an error
   for the `_load_validated` set)
2. `<code_root>/config/profiles/<profile>/<file>` — profile overlay (optional; profile from
   `instance.yaml`, default `full`)
3. `<instance_root>/settings/<file>` — instance overlay (optional)

**Merge semantics — state these in the docstring and test them:**

- Mappings merge **recursively**, key by key.
- Scalars and **lists replace wholesale** (a list is a value, not a set to union). This matters for
  `application.cors.origins` and `models.aliases`.
- Merge raw dicts first, validate the **merged** result once against the Pydantic schema. Do not
  validate layers individually — a partial overlay will not satisfy `extra="forbid"` schemas with
  required fields.

**Skip rule:** when `instance_root()` resolves to `<code_root>/config`, layer 3 is the same directory as
layer 1. Skip layer 3 in that case rather than merging a file with itself. Make this explicit in code
with a comment, not incidental.

**Signature change:** `load_yaml_config(filename: str) -> dict[str, Any]` keeps its signature and
gains the layering internally, so `AppConfig` needs no change. Confirm no other caller of
`load_yaml_config` expects single-file semantics (`grep -rn "load_yaml_config" --include='*.py'`).

### Verification (Phase 0)

```bash
python scripts/code_rules_fast.py --all          # exit 0
pytest tests/unit -x -q                          # green
pytest tests/integration -x -q                   # green

# Determinism: same root regardless of cwd
python -c "from modules.backend.core.config import find_project_root; print(find_project_root())"
(cd /tmp && python -c "import sys; sys.path.insert(0,'$PWD'); from modules.backend.core.config import find_project_root; print(find_project_root())")

# Default instance root == today's config dir
python -c "from modules.backend.core.config import instance_root; print(instance_root())"

# Missing instance root is a hard error, not a fallback
MC_INSTANCE_ROOT=/nonexistent python -c "from modules.backend.core.config import instance_root; instance_root()"  # must raise

# tree lists --instance
python mc.py tree | head -5
python admin.py tree | head -5
python services.py tree
python tui.py tree
```

**New tests required (`tests/unit/backend/core/test_config.py`):**
- `find_project_root()` returns the same path from three different cwds
- `instance_root()` returns `<code_root>/config` with `MC_INSTANCE_ROOT` unset
- `instance_root()` raises when `MC_INSTANCE_ROOT` points at a missing directory
- three-layer merge: instance overlay wins over profile, profile wins over core default
- recursive mapping merge (nested key preserved from a lower layer)
- list replacement (not union)
- layer 3 skipped when it equals layer 1

---

## 2. Phase 1 — Move instance-owned config to the instance root

**No file in this repo moves.** Every path below gains instance-root resolution while the default keeps
today's behaviour. The proof this works is Phase 5, where a second instance directory is created.

### 1.1 Classify every config call site

`find_project_root()` and `PROJECT_ROOT` have ~90 call sites across `modules/`, `scripts/`, the four
entry files, and `tests/`. Most are **code paths** and must not change. Enumerate the live list:

```bash
grep -rn "find_project_root\|validate_project_root\|PROJECT_ROOT" --include='*.py' \
  modules/ scripts/ tests/ mc.py admin.py services.py tui.py | grep -v __pycache__
```

**Convert to `instance_root()` — instance-owned config and state:**

| Site (re-locate by symbol) | What it resolves | Notes |
|---|---|---|
| `core/config.py` → `get_settings()` | `config/.env` | secrets are per-instance |
| `core/config.py` → `load_yaml_config()` | `config/settings/*` | via Phase 0.3 layering |
| `core/logging.py` → the log-path helper taking `configured_path` | log file path | logs are per-instance state |
| `agents/mission_control/helpers/prompt_builder.py` | `config/prompts/organization/` **only** | see 1.3 |
| `api/v1/endpoints/admin.py` → the `models.yaml` path constant | read **and write** target | see 1.4 |
| `admin.py` → `catalog aliases set` handler | `config/settings/models.yaml` write | see 1.4 |
| `clients/cli/api_client.py` → `_find_project_root()` usage for `application.yaml` | server host/port | CLI must read the instance's server config; also make this helper delegate to `core.config` rather than duplicating the walk |
| `services.py` → `PROJECT_ROOT / "config" / "settings" / "application.yaml"` | server host/port | |
| `services.py` → `SERVICE_LOG_DIR` | `var/logs` | per-instance state |

**Leave on `find_project_root()` — code paths:**

`clients/cli/migrate.py` (alembic.ini, subprocess cwd); `services.py` process `cwd` and
`modules/frontend` dir; `agents/mission_control/mission_dispatch.py` (CodeMapLoader root, repo_root
default); `agents/mission_control/helpers/cli_executor.py` (subprocess cwd);
`agents/mission_control/helpers/agent_setup.py` (`project_root` dep, `tool_registry_path`);
`agents/mission_control/helpers/agent_executor.py` (planning `project_root`);
`agents/mission_control/chat_cli_handler.py` (`working_dir`); `services/execution_environment.py`
(`working_dir`); `core/agent_registry.py` (YAML seed fallback dir); `services/catalog_seeder.py`
(seed source); `services/workflow_seeder.py` (template source); `services/workflow.py`
(`_project_root`); `services/compliance.py` (scan targets); `core/config.py` →
`get_mission_control_config()` (dispatch config ships with code); everything in `scripts/`; everything
in `tests/`.

**Rule for ambiguous cases:** if the file ships in git and is the same for every instance, it is a code
path. If it holds secrets, per-instance identity, per-instance tuning, or runtime state, it is instance
config.

### 1.2 `var/` becomes instance state

`SERVICE_LOG_DIR`, worktree base directory, and cache directories resolve under
`instance_root()/var/`. With the default instance root that is `<code_root>/config/var/` — which is
**wrong**, because today logs land in `<code_root>/var/logs/`.

**Resolution:** add a third accessor rather than nesting state under `config/`:

```python
def instance_var_root() -> Path:
    """Runtime state root (logs, worktrees, cache).

    MC_INSTANCE_VAR_ROOT, else <instance_root>/var, except when instance_root()
    is the single-instance default (<code_root>/config) — then <code_root>/var,
    preserving today's layout.
    """
```

Create the directory if missing (this is state, not config — creating it is correct; a *missing config
file* is still an error). Document the exception in the docstring so the special case is visible rather
than surprising.

### 1.3 Split the prompt layers

`prompt_builder.py` assembles three layers (verified in `_assemble_from_disk`):

1. `config/prompts/organization/*.md` → **instance root**. This is the instance's identity —
   `communication_style.md`, `principles.md`, `security_posture.md`. A security instance and a laptop
   coworker should not share these.
2. `config/prompts/categories/{category}.md` → **code root**. Ships with the agents.
3. `config/prompts/agents/{path}/system.md` → **code root**. Ships with the agents.

Both `_assemble_from_disk` (used by the seeder, reads disk) and the runtime path around the second
`find_project_root()` call in that module must be updated. `services/catalog_seeder.py` calls
`_assemble_from_disk` — so seeding an instance picks up that instance's organization layer, which is
the behaviour we want. Say so in the seeder docstring.

**Existing test to check:** `tests/unit/backend/agents/test_instruction_assembly.py` patches
`modules.backend.agents.mission_control.helpers.prompt_builder.find_project_root` in five places. Those
patches must be updated to patch `instance_root` for the organization layer and `find_project_root` for
the other two, and the test should assert the split explicitly.

### 1.4 Writable config: `models.yaml`

`models.yaml` is the only settings file the application **writes** — via
`PATCH /admin/catalog/...` alias handling in `api/v1/endpoints/admin.py` and via
`admin.py catalog aliases set`.

With layering, a write must target the **instance overlay**, not the core default:

- Write path: `instance_root()/settings/models.yaml`
- Create the file (and `settings/` directory) on first write, containing only the keys being set
- The `registry:` block (provider → models) stays a **core default** and is not written by either path.
  If a write handler currently rewrites the whole file, change it to write only the `aliases:` mapping.
- After writing, invalidate the `get_app_config` cache so the change takes effect without a restart.
  Check whether the current handlers already do this; if they rely on a process restart, keep that
  behaviour but state it in the response/CLI output rather than leaving it implicit.

**When `instance_root()` is the default (`<code_root>/config`)**, the write target is
`config/settings/models.yaml` — exactly today's behaviour. Verify this explicitly; it is the case the
existing tests cover.

### Verification (Phase 1)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit -x -q
pytest tests/integration -x -q

# Nothing moved, nothing broke: default instance behaves exactly as before
python services.py check
python admin.py config                    # loads all settings
python admin.py catalog aliases list      # reads models.yaml
python mc.py status                       # CLI resolves server host/port

# Log path unchanged for the default instance
python -c "from modules.backend.core.config import instance_var_root; print(instance_var_root())"
# expect: <repo>/var
```

**New tests required:**
- `instance_var_root()` returns `<code_root>/var` for the default instance and
  `<instance_root>/var` for an explicit one
- organization prompts resolve from instance root; category and agent prompts from code root
- alias write targets the instance overlay and leaves the core default untouched (use `tmp_path` as
  `MC_INSTANCE_ROOT`)

---

## 3. Phase 2 — Instance manifest and seed filters

### 2.1 `instance.yaml` schema

New file, read from `instance_root()/instance.yaml`. **Optional** — absent means "everything, `full`
profile", which is today's behaviour and keeps the existing checkout working.

```yaml
# =============================================================================
# Instance Manifest
# =============================================================================
# Identifies this deployment and declares which catalog content it seeds.
# Absent file = all agents, all workflows, profile "full" (single-instance default).
#
# Available options:
#   name        - Instance label, used in logs and platform metrics (string, required)
#   profile     - Runtime profile (string: full|solo, default: full)
#                 full - Temporal, containers, plan daemon all available
#                 solo - single-process, no Temporal, no containers, no daemon
#   agents      - fnmatch patterns against agent_catalog.agent_name (list of strings,
#                 default: ["*"]). Controls what `seed-catalog` inserts and enables.
#   workflows   - fnmatch patterns against workflow_name (list of strings,
#                 default: ["*"]). Controls what `seed-workflows` inserts.
# =============================================================================

name: security-prod
profile: full
agents:
  - "mission.*"
  - "system.*"
  - "platform.*"
  - "security.*"
  - "software.*"
workflows:
  - "general.*"
  - "system.*"
  - "security.*"
  - "code.*"
```

Implementation requirements:

- New Pydantic schema in `modules/backend/core/config_schema.py` — **not** `modules/backend/schemas/`.
  Config schemas all live in `core/config_schema.py` (it holds `ApplicationSchema`, `FeaturesSchema`,
  `TemporalSchema` and ~50 others); `modules/backend/schemas/` holds domain and API schemas. Subclass
  the existing `_StrictBase` (which already sets `extra="forbid"`), and type `profile` as
  `Literal["full", "solo"]`.
- Accessor `get_instance_config()` in `core/config.py`, `@lru_cache`d like its siblings, returning the
  validated schema. Absent file → return the schema's defaults with `name` derived from
  `instance_root().name`. A **present but invalid** file → raise with the validation error. Absent is
  fine; malformed is not.
- Pattern matching uses `fnmatch.fnmatch` against the full `agent_name` / `workflow_name`. Say so in the
  header comment so `security.*` semantics are unambiguous (`security.webapp.scanner.agent` matches).

### 2.2 Filter `seed_catalog()`

`services/catalog_seeder.py` → `seed_catalog(service, *, force=False, reset_prompts=False)`.

- Add an explicit keyword parameter — **not** `**kwargs` (rule 002.9):
  `agent_patterns: list[str] | None = None`. `None` means "read from `get_instance_config().agents`".
  Passing an explicit list is what tests use.
- After discovering `agent.yaml` files, filter by `agent_name` against the patterns **before** any DB
  write.
- Return counts must distinguish filtered-out from errored. Extend the return dict with a
  `"filtered"` count; update every caller that reads the dict:
  `api/v1/endpoints/admin.py` → `admin_seed_catalog`, `admin.py` → `admin_seed_catalog`,
  `clients/cli/catalog_cmds.py` → `_action_seed_catalog`.
- **A pattern that matches nothing is an error.** If `instance.yaml` lists `security.*` and no
  security agent YAML exists in the deployment, that is a misconfigured instance — raise, listing the
  unmatched patterns. Silently seeding fewer agents than declared is exactly the failure this plan
  exists to prevent.
- `force=True` currently clears and reloads. With filtering, `force` must clear only rows the patterns
  match, or the semantics become "delete agents this instance was told to ignore". Decide explicitly,
  document the choice in the docstring, and test it: **recommended** — `force` clears only matching
  rows.

### 2.3 Filter `seed_workflows()`

Same shape in `services/workflow_seeder.py` → `seed_workflows(service, *, force=False)`.

- Add `workflow_patterns: list[str] | None = None`.
- Filter on `workflow_name` from the parsed YAML (not the filename) — the two can differ.
- Same unmatched-pattern error rule.
- Same `force` scoping decision, documented and tested.
- Callers to update: `modules/backend/main.py` lifespan, `admin.py` → `admin_seed_workflows`.
- Note the existing guard: `seed_workflows` skips when any system template exists unless `force`. With
  filtering, "any template exists" is too coarse — an instance that added `security.*` later would be
  skipped. Change the guard to "any template **matching the patterns** exists".

### 2.4 Instance CLI surface

Add to `admin.py` (Click group, `--options` not positional args, per house rules), with handlers in
`modules/clients/cli/` — no logic in the entry file:

- `admin.py instance show` — resolved instance root, name, profile, code root, database URL (sanitised),
  pattern lists, and the counts of catalog rows and workflow definitions currently in the DB.
- `admin.py instance validate` — runs the Phase 3 reconciliation and the unmatched-pattern check
  without mutating anything. Exit 1 on any problem. This is the command an operator runs after editing
  `instance.yaml`.
- `admin.py instance init --path PATH --name NAME --profile full|solo` — creates the directory
  skeleton (`settings/`, `prompts/organization/`, `var/`), writes an `instance.yaml` with the given
  values, and copies `config/.env.example` to `<path>/.env`. It must **not** write secrets and must
  print the remaining manual steps (fill `.env`, create the database, run migrations, seed).

Update `admin.py tree` output (automatic via introspection — verify) and `USAGE.md`.

### Verification (Phase 2)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit -x -q
pytest tests/integration -x -q

# Default instance: no manifest, everything seeds, behaviour unchanged
python admin.py admin seed-catalog --force
python admin.py admin seed-workflows --force
python admin.py catalog list | wc -l

python admin.py instance show
python admin.py instance validate     # exit 0
```

**New tests required:**
- `tests/unit/backend/services/test_catalog_seeder.py` — pattern filtering seeds only matches;
  unmatched pattern raises; `force` clears only matching rows; `"filtered"` count is correct
- `tests/unit/backend/services/test_workflow_seeder.py` — same four cases, plus the reworked
  already-seeded guard
- `tests/unit/backend/core/test_config.py` — `get_instance_config()` defaults when the file is absent;
  raises when the file is present and invalid; `Literal` rejects an unknown profile

---

## 4. Phase 3 — Fail fast on catalog/code drift

### 3.1 Reconcile enabled catalog rows against deployed modules

**Current behaviour** (`core/agent_registry.py` → `_load_from_db`): each row is converted inside a
`try`, and on failure it logs `"Failed to load agent from DB"` and continues. Note also the
`except (ValidationError, Exception)` clause — `Exception` subsumes `ValidationError`, so the tuple is
misleading; fix it while you are here.

**New:** a reconciliation function that checks every enabled row resolves to an importable module, and
raises **once** with the complete list.

```python
def verify_catalog_against_code() -> None:
    """Raise if any enabled catalog row has no importable agent module.

    Uses importlib.util.find_spec — checks importability without executing
    module code or paying import cost. Collects every failure and raises a
    single error listing all of them; never raises on the first.
    """
```

Requirements:

- Use `importlib.util.find_spec(AgentRegistry.resolve_module_path(name))`. Do **not** import.
  `find_spec` raises `ModuleNotFoundError` for a missing *parent* package — catch that and treat it as
  a failure for this row, not as a crash.
- Error message lists each `agent_name` with its expected module path, and names the fix: either
  disable the row (`admin.py admin toggle-agent`) or narrow `instance.yaml.agents` and re-seed.
- Call it from **both** process entry points, not just the API:
  - `modules/backend/main.py` lifespan — after seeding, before the app accepts requests
  - the Temporal worker startup path (`modules/backend/temporal/worker.py`)
  - `AgentRegistry.reload()` — so an admin catalog change that breaks resolution fails immediately
    rather than at next dispatch
- `admin.py instance validate` calls it (Phase 2.4).

### 3.2 Stop swallowing per-row load failures

In `_load_from_db`, a row that fails `_db_row_to_config` conversion (bad `model_config_json`, invalid
schema) must not be logged-and-skipped. Collect failures and raise after the loop, with the same
all-at-once shape as 3.1. A malformed catalog row is a deployment defect, not a runtime condition.

Keep the **YAML fallback** in `_ensure_loaded()` as-is — it exists for bootstrap and tests where the DB
is genuinely unavailable, which is a different condition from "the DB has bad rows". Do not widen it to
cover 3.1/3.2 failures: a reachable DB with a broken row must raise, not silently fall back to YAML.
Make that distinction explicit in a comment, because it is exactly the kind of thing a later change
would erode.

### Verification (Phase 3)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit -x -q
pytest tests/integration -x -q

# Healthy tree: reconciliation passes
python admin.py instance validate            # exit 0
python -c "from modules.backend.core.agent_registry import verify_catalog_against_code; verify_catalog_against_code(); print('ok')"

# Manual negative check, documented in the commit message:
#   enable a catalog row whose module does not exist (SQL or admin API),
#   restart the backend, confirm it aborts at boot naming that agent,
#   then revert.
```

**New tests required (`tests/unit/backend/core/test_agent_registry.py`, integration if it needs real
rows):**
- all rows resolvable → no raise
- one unresolvable row → raises, message contains the agent name and module path
- three unresolvable rows → single raise listing all three
- a row with malformed `model_config_json` → raises rather than being skipped
- DB unavailable → still falls back to YAML (the existing behaviour must be preserved and pinned by a
  test, so a future change cannot erode it)

---

## 5. Phase 4 — Profiles (`full` / `solo`)

The laptop coworker must run without Temporal, containers, or the plan daemon. Every switch already
exists in config; the profile bundles them so "solo" is defined once in core rather than copy-pasted
into each laptop instance.

### 4.1 Profile overlay directories

Create `config/profiles/full/` and `config/profiles/solo/`. Each contains **partial** settings YAML
merged by the Phase 0.3 layering. Every file needs a commented options header (rule 003.3) explaining
that it is an overlay, which keys it overrides, and what the core default is.

`config/profiles/full/` may be empty (a `.gitkeep` and a `README.md` explaining that `full` is the
core default with no overrides). Do not create empty YAML files just to have them.

`config/profiles/solo/` overrides. **Verified against the tree on 2026-07-29:**

| File | Key | Solo value | Reason |
|---|---|---|---|
| `temporal.yaml` | `enabled` | `false` | top-level key, already exists and is already honoured — see 4.2 |
| `features.yaml` | `experimental_mission_plan_daemon_enabled` | `false` | daemon spends budget unattended |
| `features.yaml` | `channel_telegram_enabled` | `false` | no bot on a laptop |
| `features.yaml` | **new flag** `execution_container_enabled` | `false` | see 4.1b — no such gate exists today |

Every key above is defined in `modules/backend/core/config_schema.py` (`TemporalSchema`,
`FeaturesSchema`). Read those classes before writing the overlay files. Do **not** reference
`config/settings/environments.yaml` — see 4.1a.

### 4.1a Delete the orphaned `environments.yaml`

`config/settings/environments.yaml` declares `default_mode`, `container.enabled` and a `worktree` block.
**Nothing reads it.** There is no `EnvironmentsSchema` in `core/config_schema.py`, `AppConfig` never
loads it, and no code references `default_mode` or `container.enabled`. It was added by Plan 37 Phase 3
(`25811b3`) and never wired.

Delete the file (P3 — no dead config). Container mode is in fact selected per-mission via
`mission.execution_environment` and per-agent via `execution.mode` in `agent.yaml`, then passed as the
`mode` argument to `ExecutionEnvironmentService.get_or_create_for_mission()`. That is the real
mechanism; the YAML was a decoy.

Verify before deleting:
```bash
grep -rn "environments.yaml\|EnvironmentsSchema\|default_mode" --include='*.py' modules/ scripts/ tests/ | grep -v __pycache__
```
Must return nothing. If it returns anything, wire the file properly instead of deleting it and say so in
the commit message.

### 4.1b Add a real container gate

Because 4.1a removes the only (dead) global container switch, `solo` needs a live one. Add
`execution_container_enabled: bool` to `FeaturesSchema` and `config/settings/features.yaml`
(default `true`, under the existing "Agent Infrastructure" section with a comment explaining it).

Honour it at the single choke point — `ExecutionEnvironmentService.get_or_create_for_mission()` and any
sibling entry point that accepts a `mode` argument (`grep -n 'mode: str\|mode=' modules/backend/services/execution_environment.py`).
When the flag is `false` and a caller requests `mode="container"` or `mode="worktree"`, **raise with a
clear message** naming the flag and the profile — do not silently downgrade to `local`. A silent
downgrade would run an agent unisolated when the mission asked for isolation, which is worse than
failing.

### 4.2 Honour the profile where Temporal is assumed

`temporal.enabled` **already exists and is already honoured in several places** — verified:

- `modules/backend/temporal/client.py` raises `RuntimeError` when disabled
- `modules/backend/api/v1/endpoints/executions.py` branches on it in three places
- `modules/backend/agents/mission_control/approval.py` branches on it
- `modules/backend/agents/platform/director/agent.py` reports it

So this sub-phase is an **audit for gaps, not a new feature**. Enumerate every Temporal touchpoint and
confirm each is either behind the flag or unreachable when it is false:

```bash
grep -rn "temporal" --include='*.py' modules/backend/main.py modules/backend/services/ \
  modules/backend/api/ modules/backend/tasks/ modules/backend/temporal/ | grep -v __pycache__
grep -rn "temporal.enabled" --include='*.py' modules/ | grep -v __pycache__   # the covered set
```

Known gaps to close (confirm each against the tree before changing it):

- `main.py` lifespan — must not start the Temporal client or create the scheduled-check schedule when
  disabled
- `ScheduledMissionCheckWorkflow` schedule creation — skipped when disabled
- `services.py start` — skip the Temporal dev server and the worker when the resolved profile disables
  Temporal; reflect that in `status` and `check` output
- Any dispatch path reaching Temporal that is **not** already flag-guarded must fail with a message
  naming the profile, and must **emit a mission event** (rule 014.1), not just log. A raised
  `RuntimeError` that only reaches a log file is invisible in the Console — that is the exact class of
  defect Plan 84 Phase 4 exists to remove, so do not add a new instance of it here.

Read `docs/03-principles/01-project-principles.md` P9 before touching this: the platform works without
Temporal for Tiers 1–3, and autonomous multi-wave dispatch is Tier 4 and genuinely unavailable under
`solo`. The error must say that.

### 4.3 Surface the profile

- `admin.py instance show` prints it (Phase 2.4).
- `admin.py health` and the platform metrics output include instance name and profile, so an operator
  looking at output can tell which instance produced it.
- Log the resolved instance name and profile once at startup, at INFO, from `main.py`.

### Verification (Phase 4)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit -x -q
pytest tests/integration -x -q

# Default (full) unchanged
python services.py check
python services.py status

# Solo resolves the overlay
MC_INSTANCE_ROOT=$(mktemp -d) python -c "
import os,pathlib,textwrap
p=pathlib.Path(os.environ['MC_INSTANCE_ROOT'])
(p/'instance.yaml').write_text('name: t\nprofile: solo\n')
from modules.backend.core.config import get_app_config, get_instance_config
print(get_instance_config().profile)
print(get_app_config().features.experimental_mission_plan_daemon_enabled)  # expect False
"
```

**New tests required:**
- `solo` profile overlay sets `temporal.enabled=false`, `experimental_mission_plan_daemon_enabled=false`
  and `execution_container_enabled=false`; `full` leaves core defaults intact
- `get_or_create_for_mission(mode="container")` raises when `execution_container_enabled` is false, and
  the message names the flag — assert it does **not** fall back to `mode="local"`
- a Tier-4 dispatch attempt under `solo` raises with the profile named **and** emits a mission event
- profile appears in `instance show` output

---

## 6. Phase 5 — Prove it with a second instance

This phase is the acceptance test for the whole plan. It creates a real second instance and runs a
mission through it.

### 5.1 Create the laptop instance

```bash
python admin.py instance init --path ~/instances/laptop --name laptop --profile solo
# fill ~/instances/laptop/.env (own DB_PASSWORD, JWT_SECRET, API_KEY_SALT, provider key)
# create its own database
```

`~/instances/laptop/instance.yaml`:

```yaml
name: laptop
profile: solo
agents:
  - "mission.*"
  - "system.*"
  - "software.*"
workflows:
  - "general.*"
  - "code.*"
```

`~/instances/laptop/settings/models.yaml` binds the aliases to cheaper models.
`~/instances/laptop/prompts/organization/communication_style.md` gives it the coworker voice.

### 5.2 End-to-end smoke

```bash
export MC_INSTANCE_ROOT=~/instances/laptop
python admin.py instance show                     # laptop / solo
python admin.py migrate upgrade head              # against the laptop DB
python admin.py admin seed-catalog --force        # only the declared subset
python admin.py admin seed-workflows --force
python admin.py catalog list                      # no security.* or deliberation.* rows
python admin.py instance validate                 # exit 0
python admin.py admin bootstrap-user --email you@example.com --name "You"
python services.py start --backend-only           # no Temporal dev server, no worker
python mc.py login --email you@example.com
python mc.py mission create --name "Laptop smoke" --description "Prove the instance works"
python mc.py run --objective "run a system health check" --budget 1.00
python mc.py status
```

**Then switch back and confirm isolation:**

```bash
unset MC_INSTANCE_ROOT
python admin.py instance show      # default instance, full profile
python admin.py catalog list       # full catalog, unaffected
python mc.py mission list          # laptop's mission is NOT here
```

Both must hold. If the laptop mission appears in the default instance, the database separation is not
actually in effect and the phase is not complete.

### 5.3 Documentation

- **`README.md`** — new "Running multiple instances" section: what an instance directory holds, the
  `--instance` / `MC_INSTANCE_ROOT` mechanism, the `instance init` → fill `.env` → create DB →
  migrate → seed → bootstrap-user sequence, and the `full` vs `solo` distinction. The existing
  Quick Start must remain correct for the default single-instance flow.
- **`USAGE.md`** — the `admin.py instance` command group.
- **`docs/02-architecture/`** — a new document (next free number) recording the decision: instances are
  differentiated by database and configuration, not by code; a plugin architecture was considered and
  rejected because one team owns all agents and tools; and the named triggers for revisiting that
  (second team owning a domain, divergent release cadence, external contribution).
- **`config/.env.example`** — note that this file is the template for `<instance_root>/.env`.

### Verification (Phase 5)

The 5.2 sequence is the verification. Record the commands run and their outcomes in the commit message.

---

## 7. Phase 6 — Cleanups this work exposes

Small, bounded, and each independently committable. Do these last so they do not obscure the phases
above.

### 6.1 Delete the dead tier-roster path

`services/workflow_run_waves.py` builds a path to
`config/mission_control/rosters/{roster}-{tier}.yaml` and guards it with `os.path.exists`. That
directory does not exist anywhere in the tree, so the branch is permanently dead and the guard hides
it. Delete the branch and the surrounding dead logic (P3 — no commented-out code). If tier-specific
rosters are wanted later they belong in the DB, not on disk.

### 6.2 De-duplicate the project-root walk in the CLI

`modules/clients/cli/api_client.py` defines its own `_find_project_root()` duplicating
`core.config.find_project_root`. Delete it and import the shared one (P14 — write once, use
everywhere). Verify the CLI still resolves the server host/port from the instance overlay.

### 6.3 Tests that hardcode config paths

Several tests construct config paths directly rather than through the accessors, e.g.
`tests/unit/backend/agents/test_code_qa.py` and `tests/unit/backend/services/test_compliance.py` both
use `Path(__file__).resolve().parents[4] / "config" / "agents" / ...`. These are code-root paths so they
still work, but they bypass the resolution under test. Route them through `find_project_root()` so a
future change to root resolution is caught by the suite rather than passing silently.

### 6.4 Fix the misleading exception tuple

`core/agent_registry.py` has `except (ValidationError, Exception)`. `Exception` subsumes
`ValidationError`, so the tuple documents an intent the code does not have. Phase 3.2 replaces this
block; make sure the replacement catches the specific exceptions it means to handle.

### Verification (Phase 6)

```bash
python scripts/code_rules_fast.py --all
pytest tests/unit -x -q
pytest tests/integration -x -q
grep -rn "mission_control/rosters" --include='*.py' modules/   # must return nothing
grep -rn "_find_project_root" --include='*.py' modules/        # must return nothing
```

---

## 8. Completion checklist

- [ ] `find_project_root()` is cwd-independent and resolves from `__file__`
- [ ] `instance_root()`, `instance_var_root()`, `get_instance_config()` exist, are cached consistently
      with their siblings, and raise on a configured-but-missing path
- [ ] `--instance` on all four entry files, listed in each `tree` output
- [ ] Three-layer settings resolution (core default → profile → instance) with documented and tested
      merge semantics; layer 3 skipped when it equals layer 1
- [ ] `.env`, settings overlay, `prompts/organization/`, and `var/` resolve from the instance root
- [ ] `models.yaml` writes target the instance overlay
- [ ] Code paths still resolve from the code root — no config/code confusion in the converted list
- [ ] `instance.yaml` schema with `extra="forbid"`; absent is fine, malformed raises
- [ ] `seed_catalog()` and `seed_workflows()` filter by pattern via explicit keyword params (no
      `**kwargs`); unmatched patterns raise; `force` scoping decided, documented and tested
- [ ] `verify_catalog_against_code()` runs at API boot, worker boot, and on `registry.reload()`, and
      raises once with every failure listed
- [ ] Malformed catalog rows raise instead of being logged and skipped; the DB-unavailable YAML
      fallback is preserved and pinned by a test
- [ ] `config/profiles/{full,solo}/` exist with commented options headers and verified key names
- [ ] Orphaned `config/settings/environments.yaml` deleted (nothing read it)
- [ ] `execution_container_enabled` added to `FeaturesSchema` and honoured at the
      `ExecutionEnvironmentService` choke point, raising rather than downgrading to `local`
- [ ] `solo` disables Temporal, containers and the daemon; a Tier-4 dispatch under `solo` fails with a
      clear message and a mission event
- [ ] Instance name and profile logged at startup and shown in `instance show` and health output
- [ ] A second instance runs a mission end-to-end, and neither instance sees the other's data
- [ ] `README.md`, `USAGE.md`, and a new `docs/02-architecture/` decision record are updated
- [ ] Phase 6 cleanups done: dead roster path, duplicated root walk, hardcoded test paths, exception
      tuple
- [ ] `python scripts/code_rules_fast.py --all` exits 0
- [ ] `pytest tests/unit -q` and `pytest tests/integration -q` both green
- [ ] No new rule warnings introduced (compare warning count against the pre-plan baseline of 148)

---

## 9. Explicitly deferred

Recorded so these are conscious deferrals rather than oversights.

| Item | Why deferred | Revisit when |
|---|---|---|
| Plugin architecture (entry points, host SDK, separate distributions) | One team owns all agents and tools, so there is no independent-shipping problem to solve | A second team owns a domain; an instance needs a release cadence different from core; someone outside the AI Ops team must ship an agent |
| Making the repo pip-installable | `sys.path.insert` in the entry files is sufficient without entry points | A plugin architecture is adopted, or core needs to be a dependency of something else |
| Generalising capability-based tool resolution out of `agents/security/tool_registry.py` | Independent of multi-instance; valuable on its own merits | Any second domain needs swappable tool implementations |
| Row-level tenancy (`instance_id` columns) | Separate database per instance makes it unnecessary | Instances must share one database or one API endpoint |
| Per-instance capability overrides in `instance.yaml` | Depends on the capability generalisation above | That work lands |
| Unused domain code shipping to every instance (~55 agent files) | Never imported, unreachable without a catalog row, zero runtime cost | Deployment size or attack surface becomes a measured problem, not a theoretical one |
