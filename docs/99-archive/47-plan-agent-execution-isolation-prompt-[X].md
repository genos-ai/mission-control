# Task: Plan 47 — Agent Execution Isolation (investigate, plan, implement)

You are being dispatched into an existing codebase (Mission Control) to investigate a
critical gap, produce a plan doc, and implement the solution. Work in the repository
at `/Users/herman.young/development/mission-control`.

**This is a standalone brief.** The person handing you this prompt has full conversation
context; you do not. Read the referenced files first, then the referenced plan docs, then
build your own mental model before proposing a design.

---

## 1  Why this matters (business motivation)

Mission Control is a platform that runs AI agents on behalf of users. Two agent tiers:

- **Platform agents** (`platform.*`, `system.*`) — execute infrastructure, health checks,
  directors. They run on the platform process itself with unrestricted host access.
  No isolation required.
- **User agents** (`mission.*`, `software.*`, and — critically — the upcoming research
  agent from Plan 40) — execute on behalf of a user's mission. They **MUST** run in an
  isolated execution environment (container) so that:
  1. A runaway agent cannot destroy the host filesystem or shared state
  2. Two concurrent user missions cannot interfere with each other
  3. An untrusted agent (e.g. running attacker-controlled search-result content) cannot
     escape into the host
  4. Autonomous overnight runs (Plan 42 daemon) can be trusted to run unattended

The platform currently ships the *infrastructure* for container-based execution
([Plan 37](37-plan-execution-environments-[X].md) Phases 1–5 are done). But
**agents don't actually use it**. They still read files and run subprocesses directly on
the host. The container gets provisioned, sits idle, and is torn down. This is the
single blocker preventing Mission Control from safely running user missions unattended —
and it blocks the current roadmap
([Plan 46 — Autonomous Mission Roadmap](../08-plans/046-plan-autonomous-mission-roadmap.md))
from exiting Phase 1.

Your job is to close this gap properly — investigation, design, plan doc, implementation,
verification — so that **every user-tier agent's filesystem reads/writes and command
executions run inside its mission's container**, while platform agents continue to run
with direct host access.

---

## 2  Current state — read this before anything else

### 2.1  Critical files to read in full

Read these files first; they contain the existing infrastructure you'll be building on.

**Plan docs (read in this order):**
1. [docs/97-plans/46-plan-autonomous-mission-roadmap.md](../08-plans/046-plan-autonomous-mission-roadmap.md) —
   the standing roadmap. Pay attention to §4 Phase 1 (where this work belongs), §5
   (anti-drift rules you must honour), and §7 (out-of-scope items).
2. [docs/97-plans/37-plan-execution-environments.md](37-plan-execution-environments-[X].md) —
   the original execution environments plan. Read §2–5 for the architectural intent and
   the Phase 1–5 commitments that were delivered. Note the close-out block at the top
   explaining what moved to Plan 48.
3. [docs/97-plans/48-plan-convergence-loop-and-branch-automation.md](../08-plans/048-plan-convergence-loop-and-branch-automation.md) —
   so you understand what's deliberately **out** of the execution-environments remit
   and is owned by a follow-up plan. Do not absorb Plan 48 into Plan 47.

**Existing isolation code (already landed):**
4. [modules/backend/services/execution_environment.py](modules/backend/services/execution_environment.py) —
   `ExecutionEnvironmentService` facade, `EnvironmentHandle` dataclass, `CommandResult`
   dataclass, `ExecutionBackend(Protocol)`, `LocalBackend`, DB persistence of
   `execution_environments` rows, restart-on-stopped recovery logic.
5. [modules/backend/services/container_backend.py](modules/backend/services/container_backend.py) —
   Docker-based `ContainerBackend`. Lazy docker-py client, `create`/`execute`/`cleanup`,
   git-aware worktree-in-container pattern (mounts host repo at `/repo` read-write,
   creates a worktree at `/workspace` on a new `agent/<mission-id>/dispatch` branch).
6. [config/dockerfiles/code-workspace.Dockerfile](config/dockerfiles/code-workspace.Dockerfile) —
   the `code-workspace:latest` image (python:3.14-slim + git, sleep infinity as PID 1).
7. [modules/backend/models/execution_environment.py](modules/backend/models/execution_environment.py) —
   the SQLAlchemy model + `EnvironmentStatus` enum.
8. [modules/backend/agents/mission_control/dispatch/environment.py](modules/backend/agents/mission_control/dispatch/environment.py) —
   `resolve_execution_mode()` priority chain and the `_CONTAINER_TOOLS` /
   `_WRITE_TOOLS` frozensets it auto-resolves against.
9. [modules/backend/agents/mission_control/mission_control.py](modules/backend/agents/mission_control/mission_control.py)
   around lines 739–803 — where the container is provisioned via
   `ExecutionEnvironmentService.get_or_create_for_mission()` and the `env_handle` is
   threaded into `_make_agent_executor`.

**The tool layer agents actually call:**
10. [modules/backend/agents/tools/filesystem.py](modules/backend/agents/tools/filesystem.py) —
    `read_file`, `list_files`. **Both hit the host filesystem directly via
    `project_root / file_path`.** No check of any environment handle. No write tool.
11. [modules/backend/agents/tools/code.py](modules/backend/agents/tools/code.py) —
    `apply_fix` (writes files via `full_path.write_text`) and `run_tests` (uses
    `subprocess.run` with `cwd=project_root`). **Both bypass the environment entirely.**
    Note: these are defined but currently unused by any agent (see §2.3).
12. [modules/backend/agents/tools/environment.py](modules/backend/agents/tools/environment.py) —
    `run_command`, the ONE tool that actually routes through `environment_handle` when
    present. Currently zero agents import this tool.
13. [modules/backend/agents/tools/codemap.py](modules/backend/agents/tools/codemap.py),
    [modules/backend/agents/tools/compliance.py](modules/backend/agents/tools/compliance.py) —
    scanners that also operate on `project_root` locally.

**Where agent deps get built:**
14. [modules/backend/agents/deps/base.py](modules/backend/agents/deps/base.py) — the
    `BaseAgentDeps` dataclass. Notice `environment_handle: Any = None` at line ~62 and
    `project_root: Path` somewhere near the top. These are the two fields that matter.
15. [modules/backend/agents/mission_control/helpers/agent_setup.py](modules/backend/agents/mission_control/helpers/agent_setup.py) —
    `_build_agent_deps()` and `build_deps_from_config()`. Line ~32 hard-codes
    `project_root: find_project_root()` — this is the host repo path, regardless of
    whether a container environment exists.
16. [modules/backend/agents/mission_control/helpers/agent_executor.py](modules/backend/agents/mission_control/helpers/agent_executor.py)
    around lines 38–68 — where the dispatch loop injects `environment_handle` into the
    deps before running the agent. Notice it sets `deps.environment_handle =
    environment_handle` but **does not** update `deps.project_root` to point at the
    container workspace.

**Example agents that need isolation:**
17. [modules/backend/agents/software/quality/agent.py](modules/backend/agents/software/quality/agent.py) —
    QA compliance agent, currently read-only against `ctx.deps.project_root`.
18. [modules/backend/agents/software/architecture/agent.py](modules/backend/agents/software/architecture/agent.py) —
    architecture agent, same shape.

**Example agents that do NOT need isolation (platform-tier):**
19. [modules/backend/agents/platform/director/agent.py](modules/backend/agents/platform/director/agent.py) —
    platform director, full host access.
20. [modules/backend/agents/platform/health/agent.py](modules/backend/agents/platform/health/agent.py) —
    platform health scanner.
21. [modules/backend/agents/system/planning/agent.py](modules/backend/agents/system/planning/agent.py) —
    system.planning, the agent that produces TaskPlans.

**Agent YAML config to understand the tier system:**
22. [modules/backend/agents/config_schema.py](modules/backend/agents/config_schema.py) —
    `AgentConfigSchema` with `invocation.tier` (user/platform/system),
    `execution.mode`/`execution.prefer`, `tools[]`, `scope` with read/write paths.
23. [config/agents/software/quality/agent.yaml](config/agents/software/quality/agent.yaml),
    [config/agents/platform/director/agent.yaml](config/agents/platform/director/agent.yaml) —
    concrete examples of user-tier vs platform-tier agent configs.

### 2.2  Relevant commits

These commits landed the infrastructure you'll build on. Use `git show <hash>` to see
the diffs if you want more context than the files give.

- `25811b3` — Phase 3: Execution environment model
- `9b20a44` — Phase 4: Container backend + ExecutionBackend protocol
- `2a1b8ed` — Persistent containers: per-mission lifecycle with DB tracking
- `8cd45c8` — Wire mission execution_environment from DB + fix enum case in tracking
- `7a30ff9` — Restart stopped containers instead of creating new ones
- `b376a09` — Fix container lifecycle logging to use structlog extra pattern
- `60b7afb` — Refactor: extract console history to service, add execution environment
  endpoint, clean up CLI clients
- `3d0fba2` — Plan 46 Phase 1: narrow Plan 37 scope, extract convergence loop to
  Plan 48 (explains why Plan 37 is now "Phases 1–5 done" and what's parked)

### 2.3  The specific gaps I (the previous reviewer) found

These are the concrete, verifiable gaps that prompted this plan. **Re-verify all of
them yourself** — do not trust my findings without checking. If any of them is wrong
in the current code, say so in your plan doc.

1. **`deps.environment_handle` is never read by any agent.** Searching the entire
   `modules/backend/agents/` tree for `environment_handle` turns up only the places
   that *set* it (agent_executor.py, mission_control.py, deps/base.py) and the
   `run_command` tool that checks it. Zero agent reads it.

2. **`tools/environment.py::run_command` is not imported by any agent.** The one tool
   that would actually route through the container is orphaned. `from modules.backend.
   agents.tools.environment` grep → empty.

3. **`tools/code.py::apply_fix` and `run_tests` are similarly orphaned.** They use
   `file.write_text()` and `subprocess.run()` directly against `project_root` — both
   bypass the environment entirely — but they're also not imported by any agent, so
   the host-filesystem leak is latent, not active.

4. **`tools/filesystem.py` has no write tool at all.** Only `read_file` and `list_files`,
   both operating on the host filesystem via `project_root / file_path`. No `write_file`,
   no `create_file`, no `delete_file`.

5. **`deps.project_root` is set to `find_project_root()` unconditionally** in
   `build_deps_from_config()` (agent_setup.py line ~32). Even when a container
   environment is active, `project_root` stays as the host repo root. The agent's
   filesystem tools therefore operate on the host, not the container workspace.

6. **The `ContainerBackend.create()` mounts the host repo at `/repo` read-write and
   creates a git worktree at `/workspace` inside the container.** Because the worktree
   lives **inside** the container's filesystem (not bind-mounted out), there is no
   host path that corresponds to the worktree. The host filesystem still only sees the
   main repo at `repo_root`.

7. **Net effect:** when a mission runs with `execution_environment = "container"`,
   a container IS provisioned, IS kept warm between runs, and IS cleaned up on mission
   archive — but zero work happens inside it during task execution. The agent process
   runs on the host, its tools read/write the host filesystem, and the container is
   effectively decorative. Isolation is theoretical, not exercised.

These gaps are not Plan 37 bugs — Plan 37 only committed to infrastructure. They're
the gap between "infrastructure exists" and "agent execution is actually isolated",
which is what Plan 46 Phase 1 DoD item 3 requires.

---

## 3  What you need to produce

Three artifacts, in order:

### Artifact 1 — Investigation findings (update or refute §2.3)

Before designing anything, re-verify every finding in §2.3 against the current code.
For each:

- Confirm the finding is still true (ideally with a concrete grep or a file:line
  citation), OR
- Refute the finding with evidence (in which case the design changes accordingly)

Also answer these additional investigation questions:

a. **Does any user-tier agent anywhere in the tree currently write files or run
   subprocesses via any path I missed?** If yes, where, and how?
b. **What does `repo_root` look like in practice?** Is it always the same path as
   `find_project_root()` on user missions? Are there missions where a user brings
   their own `repo_url` and it clones somewhere else? Read `models/mission.py` and the
   mission creation flow to find out. This affects the bind-mount strategy.
c. **What happens to the container's `/workspace` worktree when the container is
   torn down?** Is it preserved anywhere on the host, or is it destroyed with the
   container? (Answer determines whether agent output can be extracted after the
   mission.)
d. **What's the existing pattern for distinguishing platform-tier agents from
   user-tier agents at dispatch time?** Does the dispatch loop already know the
   tier? Or is tier only checked at API authorization time and lost by the time we
   get to the agent executor? (Look at `invocation.tier` and how it's consumed.)
e. **Are there any tests for the container backend?** I found none, but re-check.
f. **Are there any integration tests for the agent → filesystem tool path that
   currently assume host execution?** Those will need to be updated if you change
   the tool layer.

### Artifact 2 — A plan doc at `docs/97-plans/47-plan-agent-execution-isolation.md`

Use the same metadata-header + numbered-section format as Plans 41, 42, 43, 46, 48.
Required sections:

1. **Metadata header** (Status, Created, Depends on, Target, Coordinator,
   Supersedes). Mark as `Draft`.
2. **§1 Why this plan exists** — the business motivation (see §1 of this brief).
3. **§2 The current gap** — your verified version of §2.3 from this brief, with
   file:line citations. Replace anything that turned out to be wrong.
4. **§3 Design options considered** — you must explicitly enumerate at least three
   design options and explain the trade-offs. My initial thoughts (not binding,
   override with your own analysis):

   - **Option A: Full-routing transparent isolation.** Every filesystem / code tool
     checks `deps.environment_handle` and routes through docker exec when present.
     Tools become environment-aware. Pros: agents stay unchanged, cleanest separation
     of concerns. Cons: every `read_file` becomes a ~100ms docker-exec roundtrip,
     need to handle text transfer through stdio, need to decide on command arg
     escaping, container-internal path becomes the canonical path.

   - **Option B: Host-side worktree + bind-mount.** Create the git worktree on the
     HOST (e.g. at `/tmp/mission-control/worktrees/<mission-id>`), bind-mount that
     directory into the container at `/workspace`, and set `deps.project_root` to
     the host-side worktree path. Agent filesystem tools continue to use host
     filesystem operations (fast), the container sees the same files via the bind
     mount, and any command the agent wants to run (tests, builds, package installs)
     goes through `run_command` → docker exec → runs inside the container where it
     sees the worktree at `/workspace`. Pros: minimum agent-side change, full
     filesystem isolation via the worktree, command isolation via the container.
     Cons: worktree lifecycle needs to track container lifecycle, need to handle
     worktree cleanup on mission archive, need to decide where worktrees live,
     cross-platform considerations (does this work on macOS with OrbStack's shared
     volumes? Linux prod?). **This is my leading guess for the right answer**, but
     you should verify.

   - **Option C: Run the agent process itself inside the container.** The Python
     interpreter hosting the pydantic-ai agent runs inside docker exec. Pros:
     strongest possible isolation. Cons: agent loses direct access to the DB session,
     event bus, session state, progress callbacks. Would require a full remote-agent
     protocol. Almost certainly too big a change for Phase 1.

   - **Option D: Hybrid** — something you come up with by looking at how other
     platforms (GitHub Codespaces, Daytona, Coder, Replit, Gitpod) structure this.
     Do a 10-minute prior-art scan before settling.

   For each option enumerate: what changes in the agent layer, what changes in the
   tool layer, what changes in the dispatch loop, what changes in the container
   lifecycle, what the security posture actually looks like, and what the rough
   implementation cost is. **Pick one and justify why**.

5. **§4 Detailed design** — for the option you pick, full technical spec:
   - New/changed types and protocols
   - The precise flow: user creates mission → dispatch loop runs → container + worktree
     provisioned → agent executes → tools route through X → container persists → next
     run reuses → mission archived → cleanup
   - How platform-tier vs user-tier is detected at dispatch time and what it changes
   - How `project_root` gets set for user-tier vs platform-tier agents
   - Migration: how existing filesystem/code tools get updated (or replaced, or
     wrapped) without breaking platform-tier agents
   - Backwards compat for any mission still configured with `execution_environment =
     "local"` — it should keep working as today
   - Where worktrees/containers live on the host filesystem
   - Cleanup semantics (on mission complete, on mission archive, on timeout,
     on backend restart)
   - Security boundary analysis: what an attacker-controlled agent CAN and CANNOT
     do after this plan ships
6. **§5 Implementation sequence** — phased work breakdown. Each phase has a concrete
   deliverable and a verifiable exit criterion. Phases you should consider:
   - Phase A: Tier-aware dispatch — user-tier always goes through a container,
     platform-tier never does
   - Phase B: Worktree lifecycle + bind-mount wiring (if Option B)
   - Phase C: Tool layer routing (if Option A, or the filesystem-write tools for
     Option B)
   - Phase D: Agent deps `project_root` redirect
   - Phase E: End-to-end verification script (a demo mission that writes a file,
     runs a command, and proves both happened inside the isolation boundary)
   - Phase F: Integration tests
7. **§6 Exit criteria for the whole plan** — observable, not subjective. At
   minimum:
   - A user-tier agent running a mission in container mode cannot read or write
     any file outside the mission's worktree (verified by a test that attempts to
     read `/etc/passwd` or write to the host repo and observes the operation fail
     or land in the worktree only)
   - A platform-tier agent continues to run with direct host access unchanged
   - The research agent from [Plan 40](40-plan-deep-research-system-[X].md)
     can be run end-to-end inside a container (if Plan 40's agent isn't
     implemented yet, prove the plan is compatible by walking through the flow)
   - An end-to-end verification script lives in `scripts/verify_isolation.py` (or
     equivalent) and can be re-run after any future change to prove the isolation
     still holds
   - [Plan 46](../08-plans/046-plan-autonomous-mission-roadmap.md) Phase 1 DoD
     item 3 ("tasks run in isolated execution environments") is satisfied in fact,
     not just on paper
8. **§7 What this plan does NOT do** — explicit scope cuts. Almost certainly out
   of scope:
   - The convergence loop (Plan 48)
   - The rich workflow model (Plan 45)
   - Network isolation beyond what Docker gives you by default
   - gVisor / firecracker / user namespaces beyond container defaults
   - Multi-tenant secrets management
   - Cross-mission file sharing
9. **§8 References** — every plan doc you looked at, every file you touched, every
   prior-art link.

**Commit the plan doc on its own before writing any code.** Use the commit message
footer `Phase 1 — Plan 47 design` so `git log --grep "Phase 1"` pulls it up.

### Artifact 3 — Implementation

Only start coding after the plan doc is committed and the design is clear. Work in
phases per §5 of your plan doc. Each phase = one logical commit. Every commit message
footer should carry `Phase 1 — Plan 47 <phase letter>`.

Implementation constraints (MUST honour):

- **Follow existing patterns.** The codebase has strong conventions for services,
  repositories, schemas, tools, and agents. Before adding a new pattern, grep for an
  analogous existing one and match it.
- **Do not break platform-tier agents.** They must continue to work identically.
  Isolation only kicks in for user-tier agents.
- **Do not create new TODOs or "we'll fix this later" comments.** If a decision has
  to be made, make it in the plan doc and write down the reasoning.
- **Backwards compat for `execution_environment = "local"`.** A mission with explicit
  local mode must keep behaving exactly as today. No forced container.
- **No new dependencies without justification.** `docker-py` is already a dep; use
  it. If you need anything else, explain why in the plan doc first.
- **Respect the thin-client rule.** Business logic goes in the backend services layer.
  CLI/TUI/frontend clients must not learn about execution environments beyond surface
  metadata.
- **Use the codebase's logging pattern** (`structlog` via `core.logging.get_logger`
  with `extra={}` kwargs; see any existing service).
- **Use the codebase's datetime pattern** (`core.utils.utc_now`, NEVER
  `datetime.utcnow()` or `datetime.now()`).
- **Use the codebase's error pattern** (custom exceptions in
  `core/exceptions.py`; do not raise plain `Exception`).
- **Follow AGENTS.md file-size limits** — no file over 1000 lines, target 400–500.
  If your implementation naturally grows past that, split before committing.
- **Every new or changed service method needs a docstring** explaining what it does,
  its args, its return value, and what it raises.
- **No hidden network calls or host filesystem access in hot paths.** If the isolation
  model is "agent tools run in the container", then leaking out to the host (even
  for a single read) is a bug, not a convenience.

Each implementation phase must end with the corresponding exit criterion from §5
actually observed — run the code, verify the behaviour, and only then commit.
The final commit of the sequence should be the end-to-end verification script
running green.

---

## 4  How to verify the work (the acceptance test)

When you believe Plan 47 is implemented, you must produce a **repeatable verification
script** that a future reviewer can run. It should:

1. Start from a clean state (no leftover containers for the test mission)
2. Create a mission with `execution_environment = "container"` and a user-tier agent
3. Dispatch a plan that includes at least these steps:
   a. Read a file inside the mission's scope (must succeed, must be reading from
      the worktree, not the host repo)
   b. Attempt to read `/etc/passwd` or the host repo's `.git/config` outside the
      worktree (must fail, with a clear error)
   c. Write a file into the worktree (must succeed, must NOT appear on the host
      repo's main branch)
   d. Run a shell command that lists the working directory (must run inside the
      container, must show the worktree contents)
   e. Run a shell command that attempts to touch the host's `/tmp/isolation-leak`
      (must fail)
4. After the mission completes, verify:
   a. The container is still running (persistent across executions)
   b. The worktree exists with the written file
   c. The host repo's main branch has NOT changed
   d. No file called `isolation-leak` exists in `/tmp`
5. Archive the mission and verify:
   a. The container is torn down
   b. The worktree is cleaned up (or preserved with a clear retention policy — you
      decide in the plan doc, just be consistent)

Also run the same test with a platform-tier agent and verify it does **not** get
isolated (as it shouldn't).

Save the verification script as `scripts/verify_isolation.py` (or similar path that
matches the codebase's existing script conventions — check first). It should be
re-runnable any number of times.

---

## 5  Anti-goals — things you must NOT do

- **Do NOT expand scope into Plan 48** (convergence loop, branch/PR automation, final
  verification pattern). That's a separate plan. Your plan might touch the branch
  naming convention incidentally because worktrees imply branches, but you're not
  implementing PR automation or iterative QA.
- **Do NOT expand scope into Plan 45** (rich workflow model). Workflows still dispatch
  via the existing `WorkflowRunService`. Your plan only affects how a single agent's
  tools execute within its assigned environment.
- **Do NOT rewrite the dispatch loop structure.** `dispatch/loop.py` stays as-is
  architecturally; you're changing what gets passed *into* it and how the tools
  inside each task-step behave.
- **Do NOT try to re-implement Docker.** Use docker-py. Don't shell out to `docker`
  CLI. Don't add Podman support. Don't add Kubernetes support.
- **Do NOT touch platform-tier agents** except to verify they still work. No new
  platform agent features, no refactors.
- **Do NOT add UI** — no frontend changes, no new admin endpoints beyond what's
  strictly necessary to verify isolation. If you need one endpoint for the
  verification script, justify it in the plan doc.
- **Do NOT design for Temporal** (Plan 16). Your design should be Temporal-compatible
  (i.e. should not depend on process-local state that wouldn't survive an activity
  restart), but you are not migrating to Temporal.
- **Do NOT write tests that mock Docker.** The verification script runs against real
  Docker (OrbStack locally, daemon in prod). Mocked Docker tests give false
  confidence for isolation code specifically.
- **Do NOT skip re-verifying §2.3 yourself.** That section is the previous reviewer's
  findings from a code walk. You must re-verify every claim before designing against
  it.

---

## 6  Deliverables summary

When you hand control back:

1. **A committed plan doc** at `docs/97-plans/47-plan-agent-execution-isolation.md`
   with all nine sections from §3 Artifact 2.
2. **A sequence of implementation commits** following the phase plan, each with a
   `Phase 1 — Plan 47 <phase>` footer.
3. **A committed verification script** at `scripts/verify_isolation.py` (or the
   codebase's conventional script path — check first) that exits 0 when isolation
   holds and exits non-zero with a clear message when it doesn't.
4. **Any Plan 46 updates**: if your investigation changes Plan 46 Phase 1's work
   units or exit criteria, update `docs/97-plans/46-plan-autonomous-mission-roadmap.md`
   in a separate commit with the footer `Phase 1 — Plan 47 roadmap sync`.
5. **A short handoff note** at the end (plain markdown in the final commit body or
   a `/tmp/plan47-handoff.md` file) covering:
   - What you actually built vs what the plan doc said
   - Any gotchas a reviewer should know about
   - What's left unfinished, if anything
   - What you'd do differently if starting over
   - Confidence level that isolation actually holds (honest assessment)

Good luck. The person you're handing this back to will be looking closely at the
security boundary analysis and the verification script — those are the two things
that determine whether this plan actually solved the problem or just moved the
furniture around.
