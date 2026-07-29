# Plan 85 — Multi-Instance Deployment on a Universal Core

**Version:** 1.2.0
**Date:** 2026-07-29 (v1.0) · revised same day after `/prompt-adversarial-review` (v1.1) and
`/prompt-check-plan-quality` (v1.2)
**Author:** Herman + Opus 5 design session (`/prompt-get-context` → ideation → `/prompt-make-plan`
→ `/prompt-adversarial-review` → `/prompt-check-plan-quality`)
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

And three **shared-backend collisions** — found by adversarial review of v1.0, which had assumed
isolation was a configuration choice rather than a feature that must be built:

5. **Nothing selects a per-instance database.** `config/settings/database.yaml` holds `host`, `port`,
   **`name: "mission_control"`**, `user`, and the Redis block including **`db: 0`**.
   `get_database_url()` and `get_redis_url()` read them from `AppConfig`. That file is a **core
   default**, so absent an explicit per-instance override every instance resolves the *same* PostgreSQL
   database and the *same* Redis db index — shared missions, shared pub/sub channels, shared SSE tokens,
   shared idempotency keys. Isolation must be declared and validated, not left to the operator
   remembering to shadow a file.

6. **Temporal namespace and task queue are core defaults.** `config/settings/temporal.yaml` sets
   `namespace: "default"` and `task_queue: "agent-missions"`; `temporal/worker.py` and
   `temporal/client.py` read them directly. Two `full` instances on one Temporal server poll the same
   queue and cross-consume each other's activities, which then execute against the wrong database.
   Non-deterministic and load-dependent.

7. **`AgentRegistry.reload()` destroys state before loading.** It calls `self._agents.clear()` then
   `_ensure_loaded()`. Any change that makes loading raise (defect 4's fix) leaves a *running* process
   with zero agents — strictly worse than the silent skip being removed.

This plan fixes those seven things and adds a `full` / `solo` profile so the laptop instance can run
without Temporal or containers.

### v1.1 revision deltas

`/prompt-adversarial-review` on v1.0 returned `REVISE`. What changed, so the implementing agent does not
re-derive it:

1. **Defects 5–7 added above.** Phase 0.2a (instance identity block), Phase 4.0 (Temporal scoping) and
   Phase 3.0 (atomic reload) are new. Isolation is now a built, validated feature.
2. **v1.0's `force` instruction was wrong and is deleted.** It said `force` should clear matching
   catalog rows. `services/catalog_seeder.py` carries an explicit comment —
   `# Never delete — that would cascade to mission team members` — and `mission_team_members` FKs to
   `agent_catalog`. Deleting rows would cascade-break existing mission teams. Replaced by the
   reconcile-and-disable step in Phase 2.2.
3. **`--instance` ordering constraint restated.** v1.0 said "before the lazy handler import", which is
   the wrong landmark. `CliContext.__init__` calls `setup_logging()`, which calls `load_yaml_config()`,
   which populates the `@lru_cache` on `get_app_config()`. The constraint is "before `CliContext` is
   constructed".
4. **`find_spec` claim corrected.** It does not execute the *leaf* module, but it **does** import every
   parent package.
5. **`cache_clear()` claim corrected.** `@lru_cache` is per process, so it cannot make a `models.yaml`
   write take effect "without a restart" under multiple uvicorn workers.
6. **Container gate also validates at mission creation**, not only at dispatch.
7. **v1.0 Phase 6.3 deleted** — rewriting two tests' path construction had no failure mode and was
   scope creep.

### v1.2 revision deltas

`/prompt-check-plan-quality` found the plan structurally sound but not DRY: five "new" helpers already
exist in some form, and one phase targeted the wrong function. No phase added or removed.

1. **Phase 4.1b retargeted.** v1.1 put the container gate in
   `ExecutionEnvironmentService.get_or_create_for_mission()`, which does not validate mode at all.
   `agents/mission_control/dispatch/environment.py` → `resolve_execution_mode()` / `_validate_mode()`
   is the existing feasibility gate, **and it already silently downgrades container/worktree → local**
   with a bare `logger.warning`. The plan forbade exactly that while leaving it in place. 4.1b now fixes
   the existing downgrade rather than adding a second gate beside it.
2. **`reset_config_caches()` is an extraction, not a new function.** `cache_clear()` is hand-rolled in
   two test files (6 calls). It replaces them.
3. **One agent-module-resolution primitive.** `services/workflow_validator.py` already resolves and
   imports agent modules, swallowing every failure. Phase 3.1 now introduces one shared
   `resolve_agent_module()` that both call sites use, with the caller deciding whether absence is fatal.
4. **`instance validate` reuses `validate_config_files()`** logic, which must first move out of the
   agent-adapter layer into a service (a CLI cannot import an agent adapter — rules 001.7 / 008.x).
5. **`instance show` extends `get_sanitized_config_view()`** and reuses
   `PlatformMetricsService.get_overview()` for counts instead of re-deriving both.
6. **One `matches_any()` pattern helper** shared by both seeders — `fnmatch` is already imported locally
   in four places; do not add two more.
7. **Reconcile-and-disable goes through existing service methods** (`AgentCatalogService.update_entry`,
   `WorkflowDefinitionService.update_workflow`), not new queries — a seeder writing raw SQL breaks
   rule 005.5.
8. **Three root-resolution functions collapsed into one `paths()` accessor**, removing
   `instance_var_root()`'s conditional special case.
9. **New rule 001.8** makes the Phase 1.1 call-site classification a machine-checked invariant instead
   of a one-time manual audit.

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
   deliberate default, not by shims:** when no instance root is specified, `paths().instance_root` is
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

### 0.2 Add one `paths()` accessor — not three root functions

v1.1 specified three separate functions (`instance_root()`, `instance_var_root()`, plus the existing
`find_project_root()`), with `instance_var_root()` carrying a conditional exception for the default
instance. Three interdependent functions with a special case is harder to reason about and to keep
correct than one object resolved and validated once.

**One accessor in `modules/backend/core/config.py`:**

```python
@dataclass(frozen=True)
class Paths:
    """Resolved filesystem layout for this process. Built once, validated once.

    code_root      — the checkout. Alembic, migrations, frontend, code map,
                     agent YAML seed data, workflow templates, profiles.
    instance_root  — per-instance config and secrets: .env, settings/,
                     prompts/organization/, instance.yaml.
    var_root       — per-instance runtime state: logs, worktrees, cache.
    """

    code_root: Path
    instance_root: Path
    var_root: Path


@lru_cache(maxsize=1)
def paths() -> Paths:
    """Resolve the layout.

    instance_root:  MC_INSTANCE_ROOT, else <code_root>/config
    var_root:       MC_INSTANCE_VAR_ROOT, else <instance_root>/var,
                    except when instance_root is the single-instance default
                    (<code_root>/config) — then <code_root>/var, preserving
                    today's layout.

    Raises if MC_INSTANCE_ROOT is set and does not exist. var_root is state,
    not config, so it is created if missing.
    """
```

Requirements:

- `find_project_root()` stays as-is (0.1) and becomes `paths().code_root`'s implementation. Do **not**
  delete it — ~90 call sites use it, and Phase 1.1 keeps most of them.
- `paths()` is `@lru_cache(maxsize=1)`, consistent with `get_settings` / `get_app_config` /
  `get_mission_control_config`, and is cleared by `reset_config_caches()` (below).
- If `MC_INSTANCE_ROOT` is set and the path does not exist → raise, with the resolved path in the
  message. Do **not** fall back.
- Both env vars are read with plain `os.environ.get()` and *no* literal default inside module code —
  the defaults are computed paths, which rule 003.5 permits. No `os.getenv("X", "literal")`.
- **The `var_root` exception is the one conditional in this design.** Keep it in `paths()` where it is
  visible in a single docstring, not spread across call sites. The alternative — requiring every
  non-default instance to declare `var` explicitly — was considered and rejected as more ceremony than
  the exception costs.

**`reset_config_caches()` — an extraction, not a new function.** `cache_clear()` is already hand-rolled
in `tests/unit/backend/core/test_config.py` (4 calls) and `tests/unit/backend/events/test_config.py`
(2 calls). Add one helper in `core/config.py` clearing `paths`, `get_settings`, `get_app_config`,
`get_mission_control_config` and `get_instance_config`, and **replace those six inline calls with it**.
Do not leave them alongside the helper — P14 is "write once, use everywhere", and this is the sixth use,
not the second.

**New `--instance` option on all four entry files** (`mc.py`, `admin.py`, `services.py`, `tui.py`):

`--instance PATH` sets `MC_INSTANCE_ROOT` in `os.environ`. **The ordering constraint is exact and
getting it wrong makes the flag silently do nothing:**

- In the Click entry files, set it **before `CliContext` is constructed** — not merely before the lazy
  handler import. `CliContext.__init__` (`modules/clients/cli/cli_context.py`) calls
  `validate_project_root()` and then `setup_logging()`; `setup_logging()` in
  `modules/backend/core/logging.py` calls `find_project_root()` and `load_yaml_config()`, which
  populates the `@lru_cache` on `get_app_config()`. A `CliContext` built before the env var is set
  poisons every cached accessor with the *default* instance's configuration, and the CLI then operates
  on the wrong instance while `instance show` reports the right one.
- In `services.py` (argparse), set it immediately after `parse_args()` and before any
  `modules.backend.core.config` accessor runs — note `services.py` reads `application.yaml` at module
  scope, so that read must move behind a function call.
- **Belt and braces:** immediately after setting the env var, call `reset_config_caches()` (0.2). This
  makes a late set recoverable instead of silently wrong.
- Rule 010.1: the `tree` output of every entry file must list the new option. `admin.py tree` and
  `services.py tree` introspect the real parser, so this is automatic; verify.
- Rule 002.1 already requires `--verbose` and `--debug` on entry scripts — do not disturb them.

### 0.2a Instance identity: database, Redis, and Temporal scoping

**This is the sub-phase that makes isolation real.** Without it every instance resolves the same
PostgreSQL database (`database.yaml` → `name: "mission_control"`), the same Redis db index
(`database.yaml` → `redis.db: 0`), and the same Temporal namespace and task queue
(`temporal.yaml` → `default` / `agent-missions`). All three files are core defaults.

The layering from 0.3 makes overriding them *possible*. It does not make it *required*, and an
isolation guarantee that depends on the operator remembering to shadow a file is not a guarantee.

**Add a required `backend` block to the `instance.yaml` schema** (full schema in Phase 2.1):

```yaml
backend:
  database:
    name: mission_control_security      # required — the isolation boundary
    host: localhost                     # optional, defaults to database.yaml
    port: 5432                          # optional, defaults to database.yaml
    user: mission_control               # optional, defaults to database.yaml
  redis:
    db: 1                               # required — pub/sub, SSE tokens, idempotency keys
  temporal:
    namespace: default                  # optional, defaults to temporal.yaml
    task_queue: agent-missions-security # required when profile is `full`
```

Requirements:

- `get_database_url()` and `get_redis_url()` (`core/config.py`) resolve from `get_instance_config().backend`
  first, falling back to `get_app_config().database` **only for the optional fields**. `database.name`
  and `redis.db` have no fallback — see the default-instance rule below.
- `temporal/client.py` (`namespace`) and `temporal/worker.py` (`task_queue`) resolve from
  `get_instance_config().backend.temporal`, falling back to `temporal.yaml`.
- **Default-instance rule.** When `instance.yaml` is absent (the single-instance default), `backend`
  resolves entirely from `database.yaml` and `temporal.yaml` — today's behaviour, unchanged, no new
  required file. The `backend` block is required only when `instance.yaml` **exists**. State this
  explicitly in the schema docstring; it is what keeps this repo working untouched.
- **Collision detection in `admin.py instance validate`** (Phase 2.4). Given a `--against PATH`
  argument (repeatable) naming other instance roots, `validate` must fail when this instance's
  `(database.host, database.port, database.name)` tuple, its `(redis.host, redis.port, redis.db)`
  tuple, or its `(temporal.namespace, temporal.task_queue)` tuple matches any of them. Without
  `--against`, it must still fail when `instance.yaml` exists and declares a `name` other than the
  default while resolving to the **core-default** database name or Redis db — the single most likely
  operator mistake, and the one that silently merges a new instance into the primary.

**Why the Temporal tuple matters even though it looks like tuning:** `temporal/worker.py` polls
`config.task_queue`. Two `full` instances sharing a queue means instance A's `execute_mission` activity
can be picked up by instance B's worker, which resolves the mission ID against B's database, finds
nothing, and fails — intermittently, under load, in a way that reads like data corruption rather than a
configuration error.

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

**Skip rule:** when `paths().instance_root` resolves to `<code_root>/config`, layer 3 is the same directory as
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
python -c "from modules.backend.core.config import paths; print(paths().instance_root)"

# Missing instance root is a hard error, not a fallback
MC_INSTANCE_ROOT=/nonexistent python -c "from modules.backend.core.config import paths; paths()"  # must raise

# tree lists --instance
python mc.py tree | head -5
python admin.py tree | head -5
python services.py tree
python tui.py tree

# Default instance: backend resolution unchanged
python -c "from modules.backend.core.config import get_database_url, get_redis_url; \
print(get_database_url(async_driver=False)); print(get_redis_url())"
# expect the same host/port/name/db as before this phase

# --instance is honoured, not silently ignored (the finding-6 regression test)
python admin.py --instance "$(pwd)/config" config | head -20
```

**New tests required (`tests/unit/backend/core/test_config.py`):**
- `find_project_root()` returns the same path from three different cwds
- `paths().instance_root` is `<code_root>/config` with `MC_INSTANCE_ROOT` unset
- `paths()` raises when `MC_INSTANCE_ROOT` points at a missing directory
- three-layer merge: instance overlay wins over profile, profile wins over core default
- recursive mapping merge (nested key preserved from a lower layer)
- list replacement (not union)
- layer 3 skipped when it equals layer 1
- `reset_config_caches()` clears all four cached accessors
- **`get_database_url()` / `get_redis_url()` resolve from `instance.yaml.backend` when present, and from
  `database.yaml` when `instance.yaml` is absent** — the isolation boundary, pinned by test
- **Temporal `namespace` / `task_queue` resolve from `instance.yaml.backend.temporal` when present**
- a `CliContext` constructed before `MC_INSTANCE_ROOT` is set, then `reset_config_caches()`, yields the
  new instance's config — proves the belt-and-braces path works

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

**Convert to `paths().instance_root` — instance-owned config:**

| Site (re-locate by symbol) | What it resolves | Notes |
|---|---|---|
| `core/config.py` → `get_settings()` | `config/.env` | secrets are per-instance |
| `core/config.py` → `load_yaml_config()` | `config/settings/*` | via Phase 0.3 layering |
| `agents/mission_control/helpers/prompt_builder.py` | `config/prompts/organization/` **only** | see 1.3 |
| `api/v1/endpoints/admin.py` → the `models.yaml` path constant | read **and write** target | see 1.4 |
| `admin.py` → `catalog aliases set` handler | `config/settings/models.yaml` write | see 1.4 |
| `clients/cli/api_client.py` → `_find_project_root()` usage for `application.yaml` | server host/port | CLI must read the instance's server config; delete the duplicate walk (Phase 6.2) |
| `services.py` → `PROJECT_ROOT / "config" / "settings" / "application.yaml"` | server host/port | must move behind a function call — it currently runs at module scope, before `--instance` is parsed |

**Convert to `paths().var_root` — instance-owned runtime state:**

| Site | What it resolves |
|---|---|
| `core/logging.py` → the log-path helper taking `configured_path` | log file path |
| `services.py` → `SERVICE_LOG_DIR` | `var/logs` |
| `services/container_backend.py` → worktree base directory | `var/worktrees` |

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

### 1.2 Make the classification a machine-checked invariant

The table above is a one-time manual audit over ~90 call sites. Nothing stops a future call site from
picking the wrong accessor, and the failure is silent — an instance quietly reading the wrong `.env`, or
writing logs into the code checkout.

**Add rule 001.8 to both rule engines** (`docs/04-rules/001_module_boundaries.jsonl` **and**
`scripts/code_rules_fast.py` — per the house rule, every rule change goes in both places):

> **001.8 — Path accessors must match what they resolve.** `paths().instance_root` must not build paths
> under `modules/`, `scripts/`, `tests/`, or `docs/`. `paths().code_root` / `find_project_root()` must
> not build paths to `.env`, `settings/`, `prompts/organization/`, or `instance.yaml`.
> `paths().var_root` is the only accessor permitted to build paths under `var/`.

Implement as an AST check in `code_rules_fast.py`: find calls to the accessors, walk the enclosing
expression for `/` operands that are string literals, and flag the forbidden combinations. Severity
`error` — this is the invariant the whole phase rests on, and it is cheap to satisfy.

Adding it in Phase 1 rather than at the end means the rest of Phase 1's conversions are checked as they
land, instead of audited afterwards.

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

- Write path: `paths().instance_root / "settings" / "models.yaml"`
- Create the file (and `settings/` directory) on first write, containing only the keys being set
- The `registry:` block (provider → models) stays a **core default** and is not written by either path.
  If a write handler currently rewrites the whole file, change it to write only the `aliases:` mapping.
- **Cache invalidation is per process, and the plan must not pretend otherwise.** `get_app_config` is
  `@lru_cache`, so `reset_config_caches()` after a write affects only the worker that served the
  request. Under `uvicorn --workers N` the other N-1 workers keep serving the old alias mapping —
  roughly 1/N of subsequent agent runs pick up the change and the rest silently do not, with no error.
  Required behaviour: call `reset_config_caches()` (so single-worker dev is correct) **and** have both
  the API response and the CLI output state that a restart is required to apply the change across all
  workers. Do not describe this as "takes effect without a restart".

**When `paths().instance_root` is the default (`<code_root>/config`)**, the write target is
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
python -c "from modules.backend.core.config import paths; print(paths().var_root)"
# expect: <repo>/var
```

**New tests required:**
- `paths().var_root` is `<code_root>/var` for the default instance and `<instance_root>/var` for an
  explicit one
- organization prompts resolve from instance root; category and agent prompts from code root
- alias write targets the instance overlay and leaves the core default untouched (use `tmp_path` as
  `MC_INSTANCE_ROOT`)

---

## 3. Phase 2 — Instance manifest and seed filters

### 2.1 `instance.yaml` schema

New file, read from `paths().instance_root / "instance.yaml"`. **Optional** — absent means "everything, `full`
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
#   backend     - Backend isolation boundary (object, required when this file exists)
#     database  - PostgreSQL selection (object, required)
#       name    - Database name (string, required) — THE isolation boundary
#       host    - Host (string, optional; defaults to database.yaml)
#       port    - Port (integer, optional; defaults to database.yaml)
#       user    - User (string, optional; defaults to database.yaml)
#     redis     - Redis selection (object, required)
#       db      - Redis database index (integer, required) — pub/sub, SSE
#                 tokens and idempotency keys all live here
#       host    - Host (string, optional; defaults to database.yaml)
#       port    - Port (integer, optional; defaults to database.yaml)
#     temporal  - Temporal scoping (object, required when profile is `full`)
#       task_queue - Worker queue (string, required) — MUST be unique per
#                 instance or workers cross-consume each other's activities
#       namespace  - Namespace (string, optional; defaults to temporal.yaml)
#   agents      - fnmatch patterns against agent_catalog.agent_name (list of strings,
#                 default: ["*"]). Controls what `seed-catalog` inserts and enables.
#   workflows   - fnmatch patterns against workflow_name (list of strings,
#                 default: ["*"]). Controls what `seed-workflows` inserts.
# =============================================================================

name: security-prod
profile: full

backend:
  database:
    name: mission_control_security
  redis:
    db: 1
  temporal:
    task_queue: agent-missions-security

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
  `paths().instance_root.name` and `backend` resolving entirely from `database.yaml` / `temporal.yaml`
  (today's behaviour). A **present but invalid** file → raise with the validation error. Absent is
  fine; malformed is not.
- **`backend` is required when the file exists, optional when it does not.** Model this as
  `backend: BackendSchema | None = None` on the manifest schema, with a validator that raises if
  `backend is None` while the file was loaded from disk. Do not give `backend` field defaults that
  quietly resolve to the core-default database — that is exactly the silent-merge failure this block
  exists to prevent.
- `backend.temporal.task_queue` is required when `profile == "full"` and ignored when `profile ==
  "solo"`. Enforce with a model validator, not a comment.
- Pattern matching uses `fnmatch.fnmatch` against the full `agent_name` / `workflow_name`. Say so in the
  header comment so `security.*` semantics are unambiguous (`security.webapp.scanner.agent` matches).
- **One shared helper, not a local import per caller.** `fnmatch` is already imported locally in
  `agents/security/roe.py`, `services/code_map/parser.py`, `scripts/code_quality.py` and
  `scripts/code_map.py`. This plan needs name matching in **two** seeders plus `instance validate`, so
  add `matches_any(name: str, patterns: list[str]) -> bool` to `modules/backend/core/` once and use it
  in all three. Do not add two more local `fnmatch` imports.

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
- **Do not add row deletion under `force`.** `seed_catalog` deliberately never deletes — the code
  carries the comment `# Never delete — that would cascade to mission team members`, and
  `mission_team_members` has an FK to `agent_catalog`. Deleting rows would cascade-break the teams of
  every existing mission using that agent, or fail on the constraint and make `--force` unusable.
  `force` keeps its current upsert-and-reset-prompts semantics, unchanged.

**Reconcile-and-disable (replaces what deletion was meant to achieve).** Filtering controls what gets
*inserted*, so narrowing the manifest would otherwise have no effect: previously-seeded rows stay
present **and enabled**, Phase 3's reconciliation passes because the modules exist, and `instance show`
reports a narrow pattern list while the instance still dispatches agents it no longer declares.

After seeding, set `enabled = false` on every catalog row **not** matching the patterns, and include a
`"disabled"` count in the return dict. This is non-destructive (no FK cascade), idempotent, and makes
narrowing take effect. Rows are never deleted, so re-widening the patterns re-enables them on the next
seed.

**Go through the existing service, not new queries.** Use
`AgentCatalogService.list_catalog()` to enumerate and `AgentCatalogService.update_entry()` to flip
`enabled`. A seeder issuing its own `select`/`update` would break rule 005.5 (no raw SQL in the service
layer) and duplicate methods that already exist. If `update_entry()` cannot set `enabled` alone, extend
it — do not bypass it.

### 2.3 Filter `seed_workflows()`

Same shape in `services/workflow_seeder.py` → `seed_workflows(service, *, force=False)`.

- Add `workflow_patterns: list[str] | None = None`.
- Filter on `workflow_name` from the parsed YAML (not the filename) — the two can differ.
- Same unmatched-pattern error rule.
- Same reconcile-and-disable step: `workflow_definitions.enabled = false` for non-matching **system
  templates** (`mission_id IS NULL`) only. Never touch mission-scoped definitions — those belong to a
  mission, not to the instance manifest. Return a `"disabled"` count. Use the existing
  `WorkflowDefinitionService.list_templates(enabled_only=False)` and `update_workflow()` — both already
  exist, so no new queries.
- **Check whether `force` deletes here.** `seed_workflows`' docstring says force "delete[s] existing
  system templates before seeding", which — unlike `seed_catalog` — may genuinely delete. If it does,
  scope the delete to matching templates only, and verify nothing FKs to `workflow_definitions` in a way
  that cascades (`workflow_run`, `workflow_schedule` both reference it — check `ondelete` on each before
  changing anything). If a cascade exists, switch `force` to upsert semantics here too and say so in the
  commit message.
- Callers to update: `modules/backend/main.py` lifespan, `admin.py` → `admin_seed_workflows`.
- Note the existing guard: `seed_workflows` skips when any system template exists unless `force`. With
  filtering, "any template exists" is too coarse — an instance that added `security.*` later would be
  skipped. Change the guard to "any template **matching the patterns** exists".

### 2.4 Instance CLI surface

Add to `admin.py` (Click group, `--options` not positional args, per house rules), with handlers in
`modules/clients/cli/` — no logic in the entry file:

- `admin.py instance show` — resolved instance root, name, profile, code root, resolved PostgreSQL
  database name, Redis db index, Temporal namespace + task queue, sanitised database URL, pattern
  lists, and the counts of catalog rows and workflow definitions currently in the DB. The three
  isolation values must be visible here: an operator diagnosing cross-talk needs them in one place.

  **Reuse, do not re-derive.** `core/config.py` already has `get_sanitized_config_view()` — the
  established "expose configuration without leaking secrets" primitive, used by the admin config
  endpoint. Add an `instance` block to it (name, profile, roots, resolved database name, Redis db,
  Temporal namespace/queue — never the password) so `admin.py config`, the admin API and `instance show`
  all get it from one place. For the DB counts, use `PlatformMetricsService.get_overview()`, which
  already counts `AgentCatalog`, missions, sessions and workflow runs; extend it with a
  `workflow_definitions` count rather than writing a new query.
- `admin.py instance validate [--against PATH]...` — exits 1 on any problem, mutates nothing. Runs:
  1. `instance.yaml` schema validation
  2. **config-file and secret validation** — `agents/adapters/system.py` → `validate_config_files()`
     already checks that every `config/settings/*.yaml` exists and parses and that `.env` has non-empty
     critical secrets, which is most of what this needs. It lives in the agent-adapter layer, and a CLI
     handler must not import an agent (rules 001.7 / 008.x). **Move that logic into a service** (e.g.
     `services/config_validation.py`), have the adapter call the service, and have `instance validate`
     call the same service. Do not reimplement it, and do not import the adapter. Make it instance-aware
     while moving it: the settings files come from the layered resolution, `.env` from
     `paths().instance_root`.
  3. the Phase 3.1 catalog-vs-code reconciliation
  4. **the isolation collision checks from 0.2a** — fail when this instance's
     `(db.host, db.port, db.name)`, `(redis.host, redis.port, redis.db)` or
     `(temporal.namespace, temporal.task_queue)` tuple matches any `--against` instance root; and fail
     unconditionally when `instance.yaml` exists, declares a `name` other than the default, and still
     resolves to the **core-default** database name or Redis db index
- `admin.py instance init --path PATH --name NAME --profile full|solo --db-name NAME --redis-db N` —
  creates the directory skeleton (`settings/`, `prompts/organization/`, `var/`), writes an
  `instance.yaml` including the required `backend` block (deriving `temporal.task_queue` as
  `agent-missions-{name}` when profile is `full`), and copies `config/.env.example` to `<path>/.env`.
  `--db-name` and `--redis-db` are **required** — do not default them, and do not derive `--db-name`
  from `--name` silently, because a typo would then create a real-looking but wrong database. It must
  **not** write secrets, and must print the remaining manual steps (fill `.env`, create the database,
  run migrations, seed, bootstrap-user) plus the `instance validate --against` command to run.

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
  unmatched pattern raises; `"filtered"` and `"disabled"` counts are correct; **no row is ever deleted**
  (assert row count is non-decreasing across a narrowing re-seed); narrowing the patterns disables the
  now-unmatched rows; re-widening re-enables them
- `tests/unit/backend/services/test_workflow_seeder.py` — same cases, plus the reworked already-seeded
  guard, plus: mission-scoped definitions (`mission_id IS NOT NULL`) are never touched
- `tests/unit/backend/core/test_config.py` — `get_instance_config()` defaults when the file is absent;
  raises when the file is present and invalid; `Literal` rejects an unknown profile; **`backend` missing
  while the file exists raises**; `temporal.task_queue` missing with `profile: full` raises but is
  accepted with `profile: solo`
- collision detection: two instance roots resolving the same `(host, port, db_name)` fail `validate`;
  same for Redis db index; same for Temporal `(namespace, task_queue)`; and an `instance.yaml` naming a
  non-default instance while resolving to the core-default database name fails without `--against`

---

## 4. Phase 3 — Fail fast on catalog/code drift

### 3.0 Make `AgentRegistry.reload()` atomic — do this first

**Prerequisite for 3.1 and 3.2.** The current implementation destroys state before loading:

```python
def reload(self) -> None:
    self._agents.clear()
    self._instances.clear()
    self._loaded = False
    self._ensure_loaded()
```

Once loading can raise (3.1, 3.2), a failed reload leaves a **running process with zero agents** and
`_loaded = False`, so the next `_ensure_loaded()` either raises again or silently falls through to the
YAML fallback and serves stale disk config. That is strictly worse than the silent per-row skip being
removed: the current bug degrades one agent, this would degrade all of them, at runtime, in response to
a routine admin `PATCH /admin/catalog/{agent_name}`.

**Change:** build into locals, validate, swap only on success.

```python
def reload(self) -> None:
    """Reload from DB. Atomic — on failure the existing registry is untouched.

    Builds a fresh mapping and swaps it in only after a clean load, so a
    malformed catalog row cannot leave a running process with no agents.
    """
```

Requirements:

- Load into a local `dict[str, AgentConfigSchema]`. Assign to `self._agents` only after the load
  completes without raising.
- `self._instances` (cached PydanticAI `Agent` objects) may only be cleared **after** the swap succeeds,
  and only for names whose config actually changed — clearing all of them on every reload discards warm
  instances unnecessarily. If comparing configs is awkward, clear all of them after a successful swap;
  do not clear before.
- Apply the same build-then-swap shape to `_ensure_loaded()`'s first load, so the DB-unavailable YAML
  fallback still works from a clean state.
- On failure, re-raise after logging, leaving `self._agents` and `self._loaded` as they were.

**Test explicitly:** a reload that raises leaves `registry.get("mission.director.agent")` working with
the pre-reload config. This is the regression test for the whole sub-phase.

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

    Uses importlib.util.find_spec, which resolves the leaf module's spec
    WITHOUT executing it — but which does import every parent package on
    the way (modules.backend.agents.<domain>...). Rule 001.3 keeps
    __init__.py files minimal, so those imports are cheap and side-effect
    free; do not move this check anywhere that assumption stops holding.

    Collects every failure and raises a single error listing all of them;
    never raises on the first.
    """
```

**First extract the resolution primitive — this logic already exists twice.**
`services/workflow_validator.py` → `_agent_output_fields()` already calls
`AgentRegistry.resolve_module_path()` then `importlib.import_module()`, and swallows every failure with
`except Exception` + a warning ("we lose only the seed-time guarantee for this specific agent"). Adding a
third resolution site would make three places that each decide independently what a missing module
means.

Add one primitive to `core/agent_registry.py`:

```python
def resolve_agent_module(agent_name: str) -> ModuleType | None:
    """Import an agent's module, or return None if it is not importable.

    The single place that maps an agent_name to its module. Callers decide
    whether None is fatal: verify_catalog_against_code() treats it as an
    error; workflow_validator's output-field introspection treats it as
    "no declared contract to enforce".
    """
```

Then `verify_catalog_against_code()` uses `importlib.util.find_spec` via this primitive's existence
check, and `_agent_output_fields()` uses it for its import — replacing its inline
`resolve_module_path` + `import_module` pair. Neither caller keeps its own `except Exception`.

Requirements:

- The existence check uses `importlib.util.find_spec(AgentRegistry.resolve_module_path(name))`. Do
  **not** import the leaf module. Be accurate about what this does and does not execute: the leaf is not
  executed, **parent packages are**. Do not write a docstring claiming it executes no code.
- `find_spec` raises `ModuleNotFoundError` when a *parent* package is missing, and can propagate any
  exception raised by a parent's `__init__.py`. Catch `ImportError` (which covers
  `ModuleNotFoundError`) plus `ValueError` (raised for a malformed name) and record the row as a
  failure — never let it crash the sweep and lose the other findings.
- `_agent_output_fields()` keeps its current *behaviour* (introspection failure is non-fatal) — this is
  a refactor to one primitive, not a semantic change to the workflow validator. Note in the commit
  message that its silent-failure path is now visible in one place, which is what makes it fixable
  later.
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

### 4.0 Scope Temporal per instance

Implements defect 6. `temporal/client.py` reads `config.namespace`; `temporal/worker.py` reads
`config.task_queue`. Both come from `temporal.yaml`, a core default, so two `full` instances on one
Temporal server poll the identical queue.

- Both call sites resolve from `get_instance_config().backend.temporal` first, falling back to
  `get_app_config().temporal` when `instance.yaml` is absent (default-instance behaviour, unchanged).
- Log the resolved namespace and task queue at INFO on worker startup — `worker.py` already logs
  `task_queue`; make sure it logs the *resolved* value, not the raw config one.
- `admin.py instance validate` fails on a `(namespace, task_queue)` collision against any `--against`
  instance (Phase 0.2a / 2.4).

**Do not attempt to detect a live collision by querying Temporal.** Two workers on one queue is not
observable from the client side without racing. The `validate --against` check is the guard; make its
error message say plainly that sharing a queue causes cross-instance activity execution.

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

### 4.1b Add a real container gate — in the resolver that already exists

Because 4.1a removes the only (dead) global container switch, `solo` needs a live one. Add
`execution_container_enabled: bool` to `FeaturesSchema` and `config/settings/features.yaml`
(default `true`, under the existing "Agent Infrastructure" section with a comment explaining it).

**The gate belongs in `agents/mission_control/dispatch/environment.py`, not in
`ExecutionEnvironmentService`.** v1.1 targeted `get_or_create_for_mission()`, which does not validate
mode at all — it only branches on `local`. The real feasibility gate is `_validate_mode()`, called from
every branch of `resolve_execution_mode()`'s documented 5-level chain (task override → agent YAML →
mission default → tool-based auto → local fallback). Putting the new check anywhere else creates a
second gate in a different layer while leaving the first one unguarded.

**And fix the silent downgrade that is already there.** `_validate_mode()` currently does:

```python
if mode in ("worktree", "container") and not repo_root:
    logger.warning("Execution mode '%s' requires repo_root ... falling back to local", mode)
    return "local"
```

That is precisely the behaviour this plan forbids — an agent runs unisolated when the mission asked for
isolation, and the only trace is a log line with no mission event (rule 014.1). The plan cannot state
"never silently downgrade" as a principle and leave this in place.

Required behaviour for `_validate_mode()`:

- **`repo_root` missing** while `container`/`worktree` requested → raise, naming the mission and the
  requested mode. This is a misconfigured mission, not a runtime condition.
- **`execution_container_enabled` false** while `container`/`worktree` requested → raise, naming the flag
  and the resolved profile.
- Both must **emit a mission event**, not only log — a raised exception whose reason never reaches the
  Console is the Plan 84 Phase 4 defect class. `_validate_mode()` is a pure function today with no event
  bus; rather than threading one in, have it raise a typed exception (e.g. `ExecutionModeUnavailable`
  carrying mode, reason and flag) and have the dispatch caller that already holds the event bus emit the
  event. That keeps the resolver pure and the emission where the bus lives.
- Auto-resolution (level 4) is the one case where falling back is legitimate — nobody asked for
  container mode, the tool heuristic merely suggested it. Keep the fallback **only** on that path, and
  say so in the docstring, so the distinction between "declined a request" and "chose a default" is
  explicit rather than accidental.

**Also validate at mission creation.** `mission.execution_environment` is set when the mission is
created, but `_validate_mode()` only runs at dispatch — so on a `solo` instance an operator can create a
container-mode mission, approve a plan, and discover the failure mid-wave hours later. Add the same
check to the mission-create service path (`services/mission.py`, and the create endpoint's schema
validation if that is where `execution_environment` is accepted), reusing the flag check rather than
duplicating the condition. Keep `_validate_mode()` as the enforcement point — validation at creation is
convenience, not a substitute.

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

# Solo resolves the overlay.
# NOTE: `backend` is required whenever instance.yaml exists (Phase 0.2a), and
# temporal.task_queue is not required under `solo`.
MC_INSTANCE_ROOT=$(mktemp -d) python -c "
import os, pathlib
p = pathlib.Path(os.environ['MC_INSTANCE_ROOT'])
(p/'instance.yaml').write_text(
    'name: t\nprofile: solo\n'
    'backend:\n'
    '  database:\n    name: mission_control_t\n'
    '  redis:\n    db: 9\n'
)
from modules.backend.core.config import get_app_config, get_instance_config
print(get_instance_config().profile)                                       # solo
print(get_app_config().features.experimental_mission_plan_daemon_enabled)  # False
print(get_app_config().temporal.enabled)                                   # False
print(get_app_config().features.execution_container_enabled)               # False
"
```

**New tests required:**
- `solo` profile overlay sets `temporal.enabled=false`, `experimental_mission_plan_daemon_enabled=false`
  and `execution_container_enabled=false`; `full` leaves core defaults intact
- `_validate_mode()` raises when `execution_container_enabled` is false and `container`/`worktree` is
  requested, and when `repo_root` is missing — assert neither falls back to `local`, and that the
  tool-heuristic auto-resolution path (level 4) still does
- a Tier-4 dispatch attempt under `solo` raises with the profile named **and** emits a mission event
- profile appears in `instance show` output

---

## 6. Phase 5 — Prove it with a second instance

This phase is the acceptance test for the whole plan. It creates a real second instance and runs a
mission through it.

### 5.1 Create the laptop instance

```bash
python admin.py instance init --path ~/instances/laptop --name laptop --profile solo \
  --db-name mission_control_laptop --redis-db 2

# fill ~/instances/laptop/.env (own DB_PASSWORD, JWT_SECRET, API_KEY_SALT, provider key)
createdb mission_control_laptop     # or the equivalent for your Postgres setup
```

`~/instances/laptop/instance.yaml` as written by `instance init`, then edited for content:

```yaml
name: laptop
profile: solo

backend:
  database:
    name: mission_control_laptop
  redis:
    db: 2
  # no temporal block — not required under `solo`

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

### 5.2 Confirm isolation BEFORE touching the database

**Run this before any migrate or seed.** Every destructive step below writes to whatever database the
config resolves to, so verify the resolution first — this is the check whose absence in v1.0 would have
pointed the laptop instance at the primary database.

```bash
export MC_INSTANCE_ROOT=~/instances/laptop

python admin.py instance show
#   MUST show: name=laptop, profile=solo,
#              database=mission_control_laptop (NOT mission_control),
#              redis db=2 (NOT 0), temporal=disabled

python admin.py instance validate --against "$(git rev-parse --show-toplevel)/config"
#   exit 0. Fails if the laptop instance resolves the same database, Redis db,
#   or Temporal queue as the default instance.
```

If `instance show` reports `mission_control` or Redis db `0`, **stop** — the `backend` block is not
being honoured, and continuing would merge this instance into the primary.

### 5.3 End-to-end smoke

```bash
python admin.py migrate upgrade head              # against mission_control_laptop
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

**Then switch back and confirm isolation held:**

```bash
unset MC_INSTANCE_ROOT
python admin.py instance show      # default instance, full profile, mission_control, redis 0
python admin.py catalog list       # full catalog, unaffected — security.* still present and enabled
python mc.py mission list          # laptop's mission is NOT here
```

All three must hold. If the laptop mission appears in the default instance, or the default instance's
`security.*` rows were disabled by the laptop's narrower patterns, the isolation from Phase 0.2a is not
in effect and the phase is **not** complete.

**Also verify Redis isolation explicitly**, since it is silent when broken:

```bash
# with the laptop backend running, from the default instance:
unset MC_INSTANCE_ROOT
python mc.py console monitor    # must show NO events from the laptop instance's run
```

### 5.4 Documentation

- **`README.md`** — new "Running multiple instances" section: what an instance directory holds, the
  `--instance` / `MC_INSTANCE_ROOT` mechanism, the `instance init` → fill `.env` → create DB →
  **`instance validate --against`** → migrate → seed → bootstrap-user sequence, and the `full` vs
  `solo` distinction. Call out prominently that `instance validate --against` must be run **before**
  the first migrate, because every later step writes to whichever database the config resolves to. The
  existing Quick Start must remain correct for the default single-instance flow.
- **`USAGE.md`** — the `admin.py instance` command group.
- **`docs/02-architecture/`** — a new document (next free number) recording the decision: instances are
  differentiated by database and configuration, not by code; a plugin architecture was considered and
  rejected because one team owns all agents and tools; and the named triggers for revisiting that
  (second team owning a domain, divergent release cadence, external contribution).
- **`config/.env.example`** — note that this file is the template for `<instance_root>/.env`.

### Verification (Phase 5)

The 5.2 pre-flight and 5.3 smoke sequences **are** the verification, in that order. Record the commands
run and their outcomes in the commit message — specifically the `instance show` output proving the
laptop instance resolved `mission_control_laptop` / Redis db 2, and the post-switch checks proving the
default instance's missions, catalog and event stream were untouched.

Do not mark this phase complete on the smoke test alone. The smoke test passes just as happily when both
instances share one database; only the isolation checks distinguish the two outcomes.

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

### 6.3 Fix the misleading exception tuple

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

**Isolation (the part that makes this a multi-instance platform rather than a config refactor):**

- [ ] `instance.yaml.backend` selects the PostgreSQL database name and Redis db index; `get_database_url()`
      and `get_redis_url()` honour it; `backend` is required when the file exists and absent when it is not
- [ ] Temporal `namespace` / `task_queue` resolve from `instance.yaml.backend.temporal`;
      `task_queue` is required under `profile: full`
- [ ] `admin.py instance validate --against` fails on a database, Redis-db or Temporal-queue collision,
      **and** fails when a named non-default instance still resolves to the core-default database or Redis db
- [ ] `admin.py instance show` displays the resolved database name, Redis db index, and Temporal
      namespace + task queue
- [ ] `admin.py instance init` requires `--db-name` and `--redis-db` and derives nothing silently

**Config resolution:**

- [ ] `find_project_root()` is cwd-independent and resolves from `__file__`
- [ ] One `paths()` accessor (`code_root` / `instance_root` / `var_root`) plus `get_instance_config()`
      and `reset_config_caches()`; cached consistently with their siblings; raises on a
      configured-but-missing instance root. No separate `instance_var_root()` function.
- [ ] `--instance` on all four entry files, listed in each `tree` output, set **before `CliContext` is
      constructed**, with `reset_config_caches()` immediately after
- [ ] Three-layer settings resolution (core default → profile → instance) with documented and tested
      merge semantics; layer 3 skipped when it equals layer 1
- [ ] `.env`, settings overlay, and `prompts/organization/` resolve from `paths().instance_root`;
      logs, worktrees and cache from `paths().var_root`
- [ ] `models.yaml` writes target the instance overlay; the API response and CLI output **state that a
      restart is required** under multi-worker deployment
- [ ] Code paths still resolve from the code root — no config/code confusion in the converted list
- [ ] **Rule 001.8 added to both `docs/04-rules/001_module_boundaries.jsonl` and
      `scripts/code_rules_fast.py`**, severity `error`, so the classification is machine-checked rather
      than a one-time audit

**No duplication (the v1.2 checks):**

- [ ] `reset_config_caches()` **replaces** the six hand-rolled `cache_clear()` calls in
      `tests/unit/backend/core/test_config.py` and `tests/unit/backend/events/test_config.py` — they are
      gone, not sitting alongside it
- [ ] One `matches_any(name, patterns)` helper in `core/`, used by both seeders and `instance validate`;
      no new local `fnmatch` imports
- [ ] One `resolve_agent_module()` primitive in `core/agent_registry.py`, used by both
      `verify_catalog_against_code()` and `workflow_validator._agent_output_fields()`; neither keeps its
      own `except Exception` around resolution
- [ ] `validate_config_files()` logic **moved** out of `agents/adapters/system.py` into a service; the
      adapter and `instance validate` both call the service; the CLI imports no agent module
- [ ] `instance show` extends `get_sanitized_config_view()` and reuses
      `PlatformMetricsService.get_overview()` — no new config view, no new count queries
- [ ] Reconcile-and-disable goes through `AgentCatalogService.update_entry()` and
      `WorkflowDefinitionService.update_workflow()` — no raw SQL in a seeder (rule 005.5)

**Seeding:**

- [ ] `instance.yaml` schema with `extra="forbid"`; absent is fine, malformed raises
- [ ] `seed_catalog()` and `seed_workflows()` filter by pattern via explicit keyword params (no
      `**kwargs`); unmatched patterns raise
- [ ] **No row deletion added under `force` for `seed_catalog`** — pinned by a test asserting the row
      count never decreases across a narrowing re-seed
- [ ] Reconcile-and-disable: rows not matching the patterns are set `enabled = false` (never deleted);
      re-widening re-enables; mission-scoped workflow definitions are never touched

**Fail-fast:**

- [ ] `AgentRegistry.reload()` is atomic (build-then-swap); a failed reload leaves the previous registry
      serving, pinned by a test
- [ ] `verify_catalog_against_code()` runs at API boot, worker boot, and on `registry.reload()`, and
      raises once with every failure listed; its docstring is accurate about `find_spec` importing parents
- [ ] Malformed catalog rows raise instead of being logged and skipped; the DB-unavailable YAML
      fallback is preserved and pinned by a test

**Profiles:**

- [ ] `config/profiles/{full,solo}/` exist with commented options headers and verified key names
- [ ] Orphaned `config/settings/environments.yaml` deleted (nothing read it)
- [ ] `execution_container_enabled` added to `FeaturesSchema` and enforced in
      **`dispatch/environment.py` → `_validate_mode()`** — not in `ExecutionEnvironmentService` —
      raising rather than downgrading to `local`, **and** validated at mission creation
- [ ] **The pre-existing silent downgrade in `_validate_mode()` (missing `repo_root` → `local` with only
      a warning) now raises and emits a mission event**, with the fallback retained *only* on the
      tool-heuristic auto-resolution path
- [ ] `solo` disables Temporal, containers and the daemon; a Tier-4 dispatch under `solo` fails with a
      clear message **and a mission event**
- [ ] Instance name and profile logged at startup and shown in `instance show` and health output

**Acceptance:**

- [ ] Isolation verified **before** the first migrate (Phase 5.2), not after
- [ ] A second instance runs a mission end-to-end; neither instance sees the other's missions, catalog
      state, or events
- [ ] `README.md`, `USAGE.md`, and a new `docs/02-architecture/` decision record are updated
- [ ] Phase 6 cleanups done: dead roster path, duplicated root walk, exception tuple
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
| Separate Temporal server or namespace per instance | Per-instance `task_queue` (Phase 4.0) is sufficient isolation on one server, and a shared namespace keeps the Temporal UI usable across instances | Instances need independent Temporal retention, RBAC, or resource limits |
| Central registry of instances (so `validate` needs no `--against`) | Two or three instances make an explicit `--against` list honest and simple; a registry is state that can go stale and disagree with reality | The instance count reaches the point where an operator cannot list them from memory |
| Automated detection of a live database or Redis collision at runtime | `instance validate --against` is a pre-flight guard; runtime detection would need a heartbeat table or key and is a different kind of mechanism | Instances are provisioned by automation rather than by hand |
