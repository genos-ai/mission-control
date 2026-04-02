# Agentic Execution Environments: Change Specification

**Version:** 1.0.0
**Date:** 2026-03-15
**Author:** Herman (Group CISO, Icarus) + Architecture Review
**Status:** Approved for implementation
**Target:** BFA Reference Architecture v3.5.0

---

## 1. Executive Summary

This document specifies changes to the BFA Reference Architecture to introduce **git worktrees as a first-class execution primitive** for agentic coding workflows, **worktree-inside-container composition** for full-stack validation, and an **iterative QA convergence loop** as a standard plan pattern. These changes affect six existing documents and introduce no new documents.

The core insight: the current architecture (doc 45) jumps from "run in the platform process" (`local`) to "run in a Docker container" (`container`) with nothing in between. For coding agents performing refactors, linting fixes, type annotation passes, or documentation updates — tasks where the agent writes code but doesn't need to *execute* it — Docker is overkill. Git worktrees provide filesystem-level isolation (separate branch, separate working directory, shared object store) without any runtime overhead. The agent works on its own branch while the developer continues working on `main`, undisturbed.

Furthermore, the architecture lacks a pattern for the most natural agentic coding workflow: an iterative loop where a QA agent finds issues, a coder agent fixes them, and the cycle repeats until quality gates are met. This is not a linear plan or a DAG — it's a bounded convergence loop, and the plan management system needs to support it natively.

### What This Enables

1. **Parallel agent/human development** — Developer works on `main` while agents work on feature branches via worktrees. No stashing, no context switching, no interference.

2. **Two-tier execution model** — Worktrees for speed when the agent only needs to read/write files. Containers for safety when the agent needs to install packages, run tests, or access databases. The coordinator decides which tier based on task characteristics.

3. **Full end-to-end validation** — Ephemeral containers with worktrees inside them. Each mission starts from scratch: clone via worktree, `pip install`, run migrations, seed fixtures, execute QA cycle. If the install process or migrations are broken, you find out before the code hits `main`.

4. **Iterative quality improvement** — QA Agent → Coder Agent → QA Agent loop with bounded iterations, convergence conditions, per-cycle commits, and an optional final clean verification step.

---

## 2. Background: The Conversation That Produced These Changes

### 2.1 Starting Point: Git Worktrees for Agentic Development

The discussion began with the question: "How do git worktrees work, especially as it relates to agentic AI development in March 2026?"

**Git worktrees** allow multiple working directories from a single `.git` repository, each with its own checked-out branch, HEAD, index, and working tree. They share the same object store, refs, and history. The constraint: no two worktrees can have the same branch checked out simultaneously.

For agentic development, worktrees solve the **parallelism problem** for code-generating agents. Without worktrees, an agent and a developer working in the same checkout collide — the agent modifies files the developer is reading, test runners conflict, and builds interfere. Worktrees eliminate this by giving each agent its own isolated directory on its own branch.

The key mapping to the BFA architecture:
- **Mission = Branch** — each mission creates a feature branch
- **Agent = Worktree** — each agent operates in its own worktree on that branch
- **PR = Merge point** — when the mission completes, the branch goes through normal PR review

### 2.2 The Iterative QA Cycle

The second topic explored was an iterative QA/fix cycle:

```
QA Agent runs tests, static analysis, linting
    ↓ produces findings
Coder Agent reads findings, applies fixes
    ↓ commits to feature branch
QA Agent re-runs suite
    ↓ still failing? loop back to Coder
    ↓ passing? signal done
```

Key design decisions from the discussion:

1. **Shared branch, separate roles.** Both agents work on the same worktree and branch. A turn-based protocol (or Temporal workflow) coordinates them so they don't step on each other.

2. **Bounded iteration.** Always set a `max_iterations` (default: 5-6). An agent pair that can't converge has a deeper design problem that needs human eyes.

3. **Commit per cycle.** The Coder agent commits after each fix pass. This creates an auditable progression — if cycle 4 introduces a regression, you can diff between cycles.

4. **Quality gate as convergence condition.** Configurable: all tests pass, coverage threshold hit, PyQuality Index above threshold, zero critical linting violations.

### 2.3 Docker Container vs. Git Worktree — Not Either/Or

The discussion then explored whether to use Docker containers (full isolation with live DB, install verification) or worktrees (lightweight, fast). The conclusion: **use both, matched to the risk and scope of the change.**

**Worktree (lightweight, no runtime isolation):**
- Small refactors, renaming, restructuring
- Documentation updates, config changes
- Code style / linting fixes, adding type annotations
- Anything where the agent doesn't need to *run* the code

**Container + Worktree (full isolation, full validation):**
- New features touching the database
- Dependency changes, migration work
- API contract changes, auth/payment paths
- Large refactors spanning multiple modules
- PyQuality Index improvement sweeps

The deciding question: **does the agent need to execute the code to know if it's correct?** If yes → container. If static analysis and the agent's own reasoning suffice → worktree.

### 2.4 Ephemeral Containers for End-to-End Validation

The decision was made to use **ephemeral containers** rather than long-lived ones. Each mission spins up a fresh container, installs from scratch, runs migrations, seeds test data, and executes the QA cycle. This means the end-to-end process — install, migrations, dependency resolution — is tested as a side effect of the ephemeral model.

The optimal pattern that emerged:

1. **Ephemeral per mission** — container lives for the duration of all QA/fix cycles within one mission. Fresh from `main`, but loop iterations within share the running environment.

2. **Final clean verification** — as the very last step before opening the PR, spin up a completely fresh container, check out the branch, bootstrap from zero, and run the full test suite. If that passes, the branch is genuinely deployable.

### 2.5 The Two-Tier Decision as Coordinator Logic

The final convergence was that this becomes a **property of the Mission definition**:

```python
class ExecutionEnvironment(str, Enum):
    LOCAL = "local"           # In-process, FileScope isolation
    WORKTREE = "worktree"     # Git isolation only
    CONTAINER = "container"   # Full runtime isolation (Docker + worktree inside)

class MissionSpec(BaseModel):
    objective: str
    environment: ExecutionEnvironment
    quality_gate: QualityGateConfig
    max_iterations: int = 5
```

The coordinator resolves the execution environment from the task metadata. The agent never knows whether it's in a worktree, a container, or the main process.

---

## 3. Gap Analysis: What the Current Architecture Lacks

### 3.1 Gap: No Lightweight Isolation Between `local` and `container`

**Current state:** Doc 45 defines two execution modes — `local` (in-process, FileScope) and `container` (Docker). Doc 47 Dimension 4 mirrors this with `execution.mode: local | container`.

**Problem:** There's no middle ground. A coding agent doing a rename refactor doesn't need Docker — it needs its own branch and working directory. But `local` mode shares the developer's working tree, creating collision risk.

**Impact:** Agents are forced into containers for tasks that don't need runtime isolation, adding latency (container spin-up), complexity (Docker dependency), and cost (resource overhead) to lightweight operations.

### 3.2 Gap: No Git-Aware Container Pattern

**Current state:** Doc 45's containers are standalone — provision, execute commands, capture output. There's no concept of mounting the host's git object store or creating worktrees inside containers.

**Problem:** Without git awareness, containers must do a full `git clone` (duplicating the entire object history) or receive code as a volume mount (coupling the container to the host filesystem). Neither supports the branch-based workflow where the container works on a feature branch while the developer works on `main`.

**Impact:** Container-based agent work is disconnected from git workflow. There's no clean merge path back to `main`, no per-cycle commit history, and no branch-based PR review.

### 3.3 Gap: No Iterative Convergence Loop Plan Pattern

**Current state:** Doc 40 describes linear plans and DAGs. Doc 46 Section 4 covers mutable DAGs with dependency tracking. All plan patterns are acyclic.

**Problem:** The QA/fix cycle is inherently cyclic — QA finds issues, Coder fixes them, QA re-validates, loop until convergence. This doesn't map to a DAG (cycles are forbidden) or a linear sequence (the step count is unknown at planning time).

**Impact:** Implementing iterative QA cycles requires ad-hoc workarounds in the plan engine rather than being a first-class pattern with proper bounded iteration, convergence tracking, and cycle-level audit trails.

### 3.4 Gap: Execution Mode Resolution Not in Coordinator

**Current state:** Doc 41's coordinator routes based on agent type and keywords. The execution environment is defined statically in agent YAML (doc 47) or playbook steps, but there's no dynamic resolution logic in the coordinator.

**Problem:** The same agent may need different execution environments depending on the task. A `code.coder.agent` doing a type annotation pass needs only a worktree. The same agent adding a new database model needs a container. Static configuration can't capture this.

**Impact:** Either every coding task runs in a container (wasteful) or every coding task runs locally/worktree (insufficient isolation for some tasks).

### 3.5 Gap: No Branch Strategy for Agent Work

**Current state:** Doc 12 defines branch naming (`feature/`, `hotfix/`) but has no convention for agent-created branches, no automated cleanup policy, and no PR workflow for agent output.

**Problem:** Agents creating worktrees or working in containers on feature branches need a consistent naming convention, a cleanup mechanism for stale branches/worktrees, and an automated path from "agent work complete" to "PR opened for review."

**Impact:** Without conventions, agent branches accumulate, naming is inconsistent, and the human review workflow is ad-hoc.

---

## 4. Detailed Change Specifications

### 4.1 Document: 47-agentic-module-organization.md

**Section affected:** "Access Control Model → Dimension 4: Execution Mode"

**Change type:** Update existing content

**Current content (to replace):**

The current Dimension 4 defines two modes: `local` and `container`. The YAML schema shows `execution.mode: local | container`.

**New content:**

Dimension 4 gains a third execution mode: `worktree`. The three modes form a graduated isolation hierarchy:

```yaml
execution:
  mode: local | worktree | container
```

| Mode | Isolation Level | Runtime | Branch Isolation | Install/Test | Overhead | When to Use |
|------|----------------|---------|-----------------|-------------|----------|-------------|
| `local` | Logical (FileScope) | In-process | No — shares developer's working tree | No | None | LLM calls, file analysis, code review, read-only tasks — agent doesn't write code or doesn't need isolation from developer activity |
| `worktree` | Filesystem (git branch + separate working directory) | In-process | Yes — own branch, own directory, shared `.git` object store | No — agent cannot run `pip install`, `pytest`, or access DB | Low (~100ms setup) | Small refactors, linting fixes, type annotations, config changes, documentation updates — agent writes code but doesn't need to execute it |
| `container` | Physical (Docker namespace: PID, mount, network) | Container process | Yes — worktree created inside container from mounted `.git` | Yes — full environment: install, migrate, test, access DB | Medium (~5-30s setup) | New features, dependency changes, migrations, API changes, large refactors, anything requiring code execution for validation |

**Key properties of `worktree` mode:**

1. **Git worktree created per mission** — branch named `agent/{mission-id}/{task-type}`, worktree in a sibling directory (e.g., `../agent-workspaces/{mission-id}/`)
2. **Shared `.git` object store** — no clone overhead, instant branching, minimal disk usage
3. **Agent sees a normal directory** — the worktree is transparent to the agent. It reads and writes files as if it were in the main checkout. The execution environment service manages the git operations.
4. **Branch is the continuity mechanism** — when the mission completes, the branch exists as a normal feature branch. PR workflow is identical regardless of whether the branch was created by a worktree or a container.
5. **No two worktrees share a branch** — git enforces this constraint. Each mission gets its own branch.
6. **Worktree cleanup** — the lifecycle maintenance task (doc 45) cleans up worktrees when missions complete or branches are merged/pruned.

**Deciding between modes:**

The execution mode can be set statically in agent YAML or resolved dynamically by the coordinator based on task characteristics:

```yaml
# Static: agent always uses worktree mode
execution:
  mode: worktree

# Dynamic: coordinator resolves based on task
execution:
  mode: auto   # NEW — coordinator decides at runtime
  prefer: worktree   # Hint: prefer worktree unless task requires container
```

When `mode: auto`, the coordinator applies these rules (see doc 41 changes below):
- Task requires package installation → `container`
- Task modifies database schemas or migrations → `container`
- Task runs tests or builds → `container`
- Task only reads/writes source files → `worktree`
- Task doesn't touch code → `local`

**Access Control Matrix update:**

Add a column for the new mode to the existing access control matrix:

| Agent | Execution Mode | Rationale |
|-------|---------------|-----------|
| `code.qa.agent` (scan only) | `local` | Reads files, runs static analysis in-process — no writes |
| `code.qa.agent` (scan + fix) | `worktree` | Writes fixes to files but doesn't need to run tests |
| `code.qa.agent` (full cycle) | `container` | Needs to run `pytest` after fixes, verify nothing broke |
| `code.coder.agent` (refactor) | `worktree` | Restructures code but doesn't change behavior — static validation sufficient |
| `code.coder.agent` (new feature) | `container` | Needs install, migrations, test execution |
| `system.health.agent` | `local` | Reads logs and config, calls health endpoints — no code changes |
| `horizontal.pm.agent` | `local` | Reads docs, delegates — never touches code |

**YAML schema update for agent config:**

```yaml
# config/agents/{category}/{name}/agent.yaml
execution:
  mode: worktree | container | local | auto   # auto = coordinator resolves
  prefer: worktree                             # hint for auto mode
  template: code-workspace                     # container template (doc 45), used when mode=container
  branch_prefix: agent                         # prefix for worktree branch names
  worktree_base_dir: ../agent-workspaces       # where worktrees are created (relative to repo root)
```

---

### 4.2 Document: 45-agentic-execution-environments.md

**Change type:** Major update — add Worktree Backend section, add Git-Aware Container section, update architecture diagram

#### 4.2.1 New Section: "Worktree Backend" (insert before "Container Lifecycle" section)

**Rationale:** This section defines the worktree execution primitive — how worktrees are created, managed, cleaned up, and how the agent interacts with them. It sits at the same level as the Docker content.

```markdown
## Worktree Execution Mode

### What It Is

A git worktree is a separate working directory checked out from the same `.git` repository. It has its own branch, its own HEAD, its own index — but shares the object store with the main checkout. Creating a worktree is near-instant (milliseconds) because no data is copied — it's a lightweight pointer into the shared object store.

For agent execution, a worktree means: the agent gets its own branch and its own directory to work in, while the developer (or other agents) continue working on `main` (or their own branches) undisturbed. When the agent is done, its branch is a normal feature branch that can be reviewed and merged via standard PR workflow.

### What It Is Not

- **Not process isolation.** The agent runs in the main platform process. A worktree gives filesystem separation, not security boundaries. If untrusted code execution is involved, use `container` mode.
- **Not a clone.** Cloning duplicates the entire object store. A worktree shares it. For a 500MB repo, a clone takes seconds and uses 500MB. A worktree takes milliseconds and uses ~1KB.
- **Not a replacement for containers.** Worktrees cannot install packages, run test suites against databases, or provide network isolation. They are for tasks where the agent only needs to read and write source files.

### When to Use Worktrees

| Use Case | Why Worktree Works |
|----------|-------------------|
| Code refactoring (rename, restructure) | Agent writes files, no execution needed to validate |
| Linting fixes, formatting corrections | Static analysis tools run in-process on the worktree files |
| Adding type annotations | Agent reads code structure, adds annotations — no runtime validation |
| Documentation updates (inline docs, README) | Pure file writes |
| Configuration changes (YAML, env files) | File changes only, validation is structural |
| Dependency version bumps (requirements.txt) | File edit only — testing the install belongs in a container |
| Code style standardization | Automated formatting, consistent patterns |
| Adding logging statements, error handling | Code changes validated by agent reasoning, not execution |

### When NOT to Use Worktrees

| Use Case | Why Container Needed |
|----------|---------------------|
| New feature with database model | Agent must run migrations, seed data, test queries |
| API endpoint changes | Agent must run the server and test HTTP responses |
| Dependency installation | `pip install` must run in an isolated environment |
| Running test suites | `pytest` needs a running database, Redis, etc. |
| Build pipeline changes | Build must execute to validate |
| Migration scripts | Must run against a real database to verify |
| Any task involving `subprocess`, `os.system`, or external commands | Process isolation required |

### WorktreeBackend

The `WorktreeBackend` implements the same abstract interface as `ContainerBackend` (with a subset of operations) so the `ExecutionEnvironmentService` can manage worktrees through the same lifecycle.

```python
# modules/backend/services/worktree_backend.py

class WorktreeBackend:
    """Git worktree management backend.

    Creates and manages worktrees for agent tasks. Worktrees provide
    filesystem-level isolation (separate branch, separate directory)
    without container overhead.

    Unlike ContainerBackend, this does not provide:
    - Process isolation
    - Network isolation
    - Resource limits
    - Package installation capability

    Use for tasks where the agent reads/writes source files but does
    not need to execute them.
    """

    async def create_worktree(
        self,
        repo_root: Path,
        worktree_path: Path,
        branch_name: str,
        base_branch: str = "main",
    ) -> WorktreeHandle:
        """Create a new worktree on a new branch.

        Creates branch from base_branch and checks it out in worktree_path.
        The worktree shares the .git object store with repo_root.

        Args:
            repo_root: Path to the main repository
            worktree_path: Where to create the worktree directory
            branch_name: Name for the new branch (e.g., agent/m-abc123/refactor)
            base_branch: Branch to create from (default: main)

        Returns:
            WorktreeHandle with path and branch info

        Raises:
            WorktreeCreationError if branch already exists or path is occupied
        """
        ...

    async def execute_in_worktree(
        self,
        handle: WorktreeHandle,
        command: list[str],
        timeout_seconds: int = 300,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a command with the worktree as working directory.

        The command runs in the main platform process (not isolated).
        Use only for safe operations: static analysis tools, file
        operations, git commands.

        For arbitrary code execution, use container mode.
        """
        ...

    async def commit_changes(
        self,
        handle: WorktreeHandle,
        message: str,
        author: str = "BFA Agent <agent@bfa.local>",
    ) -> str:
        """Commit all changes in the worktree. Returns commit hash."""
        ...

    async def push_branch(
        self,
        handle: WorktreeHandle,
        remote: str = "origin",
    ) -> None:
        """Push the worktree's branch to the remote."""
        ...

    async def cleanup_worktree(
        self,
        handle: WorktreeHandle,
        delete_branch: bool = False,
    ) -> None:
        """Remove the worktree directory and optionally the branch.

        The branch is NOT deleted by default — it persists for PR review.
        Set delete_branch=True only after the branch has been merged or
        explicitly abandoned.
        """
        ...

    async def prune_stale_worktrees(
        self,
        repo_root: Path,
        max_age_days: int = 7,
    ) -> list[str]:
        """Remove worktrees whose branches have been merged or are stale.

        Called by the lifecycle maintenance scheduled task.
        Returns list of pruned worktree paths.
        """
        ...
```

**Data types:**

```python
@dataclass
class WorktreeHandle:
    """Lightweight handle for a git worktree."""
    worktree_path: Path
    branch_name: str
    base_branch: str
    repo_root: Path
    created_at: datetime

@dataclass
class WorktreeInfo:
    """Status information for a worktree."""
    path: Path
    branch: str
    head_commit: str
    is_clean: bool           # No uncommitted changes
    ahead_count: int         # Commits ahead of base branch
    last_commit_at: datetime
```

### Worktree Lifecycle

```
create_worktree()
    │
    ▼
ACTIVE (agent works in worktree directory)
    │
    ├── commit_changes() — agent commits after each work cycle
    │
    ├── push_branch() — push to remote for PR
    │
    ▼
cleanup_worktree(delete_branch=False)
    │
    ▼
BRANCH PERSISTS (for PR review)
    │
    ├── Human merges PR → branch deleted by PR workflow
    │
    └── Branch stale → prune_stale_worktrees() deletes branch and worktree
```

### Configuration

```yaml
# config/settings/environments.yaml — add worktree section

worktree:
  enabled: true
  base_dir: "../agent-workspaces"          # Relative to repo root
  branch_prefix: "agent"                    # Branches named: agent/{mission-id}/{task-type}
  default_base_branch: "main"               # Branch to create from
  max_concurrent_worktrees: 10              # Per repository
  stale_branch_ttl_days: 7                  # Auto-prune branches with no activity
  commit_author_name: "BFA Agent"
  commit_author_email: "agent@bfa.local"
  cleanup_interval_minutes: 60              # Scheduled task frequency
```

### Database Table

Worktrees are tracked in the same `execution_environments` table as containers, with `mode = 'worktree'`. No separate table needed.

Additional columns or JSON metadata fields for worktree-specific data:

| Field | Storage | Purpose |
|-------|---------|---------|
| branch_name | `metadata` JSON | The git branch associated with this worktree |
| base_branch | `metadata` JSON | The branch it was created from |
| worktree_path | `metadata` JSON | Filesystem path to the worktree directory |
| commit_count | `task_count` (reused) | Number of commits made in this worktree |
| last_commit_hash | `metadata` JSON | HEAD commit of the worktree |
| is_pushed | `metadata` JSON | Whether the branch has been pushed to remote |
| pr_url | `metadata` JSON | URL of the PR opened for this branch (null if not yet opened) |
```

#### 4.2.2 New Section: "Git-Aware Container Environments" (insert after Worktree section)

**Rationale:** This defines the composition pattern where a worktree is created *inside* a container, combining git-level branch isolation with Docker runtime isolation. This is the pattern for full end-to-end validation.

```markdown
## Git-Aware Container Environments

### The Composition Pattern

For tasks requiring both branch isolation AND runtime isolation (install, test, migrate), the platform creates a worktree inside a Docker container. The container mounts the host's `.git` object store (read-only) and creates a worktree from it. This gives the agent:

- **Branch isolation** — working on its own branch, not `main`
- **Runtime isolation** — its own filesystem, process tree, network namespace
- **Shared git history** — no full clone needed, instant worktree creation
- **Commit capability** — agent commits to its branch from inside the container
- **PR workflow** — same branch-based merge path as worktree-only mode

```
┌──────────────────────────────────────────────────┐
│  Docker Container (runtime isolation)             │
│                                                   │
│  ┌─────────────────────────────────────────┐     │
│  │  /repo/.git  (read-only volume mount)   │     │
│  │  (host's .git object store)             │     │
│  └──────────────┬──────────────────────────┘     │
│                 │                                  │
│                 │  git worktree add               │
│                 │  /workspace feature/mission-xyz │
│                 ▼                                  │
│  ┌─────────────────────────────────────────┐     │
│  │  /workspace  (worktree working dir)     │     │
│  │  - pip install -r requirements.txt      │     │
│  │  - alembic upgrade head                 │     │
│  │  - pytest                               │     │
│  │  - agent reads/writes code here         │     │
│  └─────────────────────────────────────────┘     │
│                                                   │
│  /output  (results extracted by platform)         │
│                                                   │
└──────────────────────────────────────────────────┘
```

### Environment Template

Add a `git_aware` flag and `git_mount` path to environment templates:

```yaml
# config/settings/environments.yaml — new template

templates:
  code-workspace:
    description: "Python workspace with git worktree support for coding agents"
    dockerfile: "code-workspace.Dockerfile"
    git_aware: true                          # Enables worktree-in-container
    git_mount: "/repo/.git"                  # Read-only mount of host .git
    workspace_dir: "/workspace"              # Worktree created here
    cpu_limit: 2.0
    memory_limit_mb: 2048
    long_lived: false                        # Ephemeral per mission
    auto_stop_after_seconds: 3600
    auto_destroy_after_seconds: 7200
    volumes:
      workspace:
        mount: "/workspace"
        persist: false                       # Fresh per mission
      pip_cache:
        mount: "/root/.cache/pip"
        persist: true                        # Cache pip downloads across missions
    network:
      egress_allowlist:
        - "pypi.org"
        - "files.pythonhosted.org"
        - "github.com"
```

### Container Startup Sequence (Git-Aware)

When `git_aware: true`, the `ExecutionEnvironmentService` performs these additional steps after container creation:

1. Mount host `.git` directory as read-only volume at `git_mount` path
2. Inside the container: `git worktree add {workspace_dir} {branch_name}`
3. Verify the worktree is on the correct branch and at the expected commit
4. Agent task execution proceeds in `workspace_dir`

After task completion:
1. Agent commits are on the branch inside the container
2. The platform pushes the branch to the remote from inside the container
3. Container is destroyed (ephemeral) or stopped (long-lived)
4. The worktree reference in the host's `.git` is cleaned up via `git worktree prune`

### The Ephemeral-with-Final-Verification Pattern

For maximum confidence that a branch is deployable:

```
Mission Start
    │
    ▼
Ephemeral Container #1 (for iterative QA cycle)
    ├── Create worktree on feature branch
    ├── pip install, migrate, seed data
    ├── QA/Coder loop (N iterations)
    ├── Each cycle: commit to branch
    ├── Push branch on convergence
    └── Destroy container
    │
    ▼
Ephemeral Container #2 (final clean verification)
    ├── Create worktree on SAME branch
    ├── pip install from scratch
    ├── Migrate from scratch
    ├── Run full test suite
    ├── If pass → open PR
    ├── If fail → flag for human review
    └── Destroy container
```

This pattern proves the branch is deployable from zero — the install process, the migrations, and the test suite all work on a clean machine. The iterative cycle (Container #1) stays fast because the environment persists across iterations. The final verification (Container #2) provides the clean-slate guarantee.
```

#### 4.2.3 Update: Architecture Diagram

The architecture diagram at the top of doc 45 should be updated to show three execution paths:

```
                    Platform Process (FastAPI + Workers)
                    ────────────────────────────────────
    ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
    │   Coordinator   │  │ Temporal Worker  │  │  Taskiq Worker   │
    └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘
             │                    │                     │
             │ resolve execution mode                   │
             │                                          │
        ┌────┴──────────────┬───────────────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   ┌─────────┐     ┌──────────────┐    ┌────────────────────┐
   │  LOCAL   │     │  WORKTREE    │    │    CONTAINER        │
   │          │     │              │    │  (git-aware)        │
   │ In-proc  │     │ Own branch,  │    │                     │
   │ FileScope│     │ own workdir  │    │  Docker + worktree  │
   │          │     │ shared .git  │    │  full isolation     │
   └─────────┘     └──────────────┘    └────────────────────┘
```

#### 4.2.4 Update: Execution Modes Table

The existing "Execution Modes" section should be updated with the three-tier table:

| Mode | Where task runs | Isolation | Git branch | Can install/test | Overhead | When to use |
|------|----------------|-----------|-----------|-----------------|----------|-------------|
| `local` | In the platform process | Logical (FileScope) | No (shares developer's checkout) | No | None | Default. LLM calls, file analysis, code review — no code changes or changes that don't need isolation |
| `worktree` | In the platform process, worktree directory | Filesystem (own branch, own working dir) | Yes (own branch, shared object store) | No | ~100ms | Small refactors, linting, type annotations, config changes — agent writes code but doesn't need to run it |
| `container` | In a Docker container | Physical (namespace boundary) | Yes (worktree inside container when `git_aware: true`) | Yes (full environment) | ~5-30s | New features, dependencies, migrations, testing — agent needs to execute code |
| `sandbox` | In a hardened Docker container (gVisor) | Physical (user-space kernel) | Yes (worktree inside container) | Yes | ~10-60s | Untrusted code execution, third-party scripts |

---

### 4.3 Document: 40-agentic-architecture.md

**Section affected:** "Orchestration: Phase-by-Phase Behavior → Phase 2: Plan"

**Change type:** Add new plan pattern

#### New Subsection: "Convergence Loop Pattern"

Insert after the existing "Phase 2: Plan" content:

```markdown
### Convergence Loop Pattern

Some workflows are inherently cyclic: an evaluation agent identifies issues, a remediation agent fixes them, and the cycle repeats until quality gates are met. This pattern is distinct from a DAG (which forbids cycles) and from a simple retry (which repeats the same agent on the same task).

**Structure:**

```
┌──────────────────────────────────────────────────────┐
│  CONVERGENCE LOOP                                     │
│                                                       │
│  Evaluation Agent: run suite, produce findings        │
│     ↓                                                │
│  Convergence condition met? ──→ EXIT (success)        │
│     ↓ (not met)                                      │
│  Iteration limit exceeded? ──→ EXIT (escalate)        │
│     ↓                                                │
│  Remediation Agent: read findings, apply fixes        │
│     ↓ commit changes                                 │
│  Loop back to Evaluation Agent                        │
│                                                       │
│  Optional: Final Clean Verification on exit           │
│     Fresh environment, bootstrap from zero, run suite │
│     Pass → open PR. Fail → flag for human review.    │
└──────────────────────────────────────────────────────┘
```

**Configuration:**

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `max_iterations` | int | 5 | Hard cap on loop iterations. Prevents infinite cycling. |
| `convergence_condition` | ConvergenceCondition | all_tests_pass | What "done" means — see conditions below |
| `commit_per_cycle` | bool | true | Whether the remediation agent commits after each fix pass |
| `final_verification` | bool | false | Whether to run a clean-environment verification before PR |
| `evaluation_agent` | str | — | Agent type for the evaluation role (e.g., code.qa.agent) |
| `remediation_agent` | str | — | Agent type for the fix role (e.g., code.coder.agent) |

**Convergence conditions:**

| Condition | Description |
|-----------|-------------|
| `all_tests_pass` | `pytest` returns exit code 0 |
| `zero_critical_findings` | Evaluation agent reports no findings with severity ≥ critical |
| `zero_findings` | Evaluation agent reports no findings at any severity |
| `quality_threshold` | A composite metric (e.g., PyQuality Index) exceeds a configured threshold |
| `custom` | A callable that receives the evaluation output and returns bool |

**Task records for a convergence loop:**

A loop with 3 iterations produces these AgentTask/TaskExecution records:

```
Plan Task: "QA Convergence Loop" (type=convergence_loop)
  ├── Cycle 1
  │   ├── Evaluation: QA Agent run (findings: 12)
  │   └── Remediation: Coder Agent run (fixes: 10, commit: abc123)
  ├── Cycle 2
  │   ├── Evaluation: QA Agent run (findings: 4)
  │   └── Remediation: Coder Agent run (fixes: 4, commit: def456)
  ├── Cycle 3
  │   ├── Evaluation: QA Agent run (findings: 0) → CONVERGED
  │   └── (no remediation needed)
  └── Final Verification (optional): clean environment, full suite → PASS
```

Each cycle's evaluation and remediation are standard AgentTask records with `parent_task_id` pointing to the loop task. The loop task's `reasoning` JSON tracks: cycle count, findings per cycle, convergence metric per cycle, and the final convergence decision.

**Execution environment for convergence loops:**

The convergence loop pattern composes with the execution environment model:

| Execution Mode | Loop Behavior |
|----------------|--------------|
| `worktree` | Both agents work in the same worktree. Coder commits after each cycle. Evaluation re-reads files from the worktree. |
| `container` | Both agents work in the same container's worktree. Container persists across cycles (ephemeral per mission, not per cycle). Coder commits inside the container. |
| `container` + `final_verification` | After convergence, a NEW ephemeral container is spun up. It checks out the same branch, installs from scratch, runs the full suite. This proves the branch is deployable from zero. |

**When to use convergence loops vs. linear plans:**

| Use Case | Pattern | Why |
|----------|---------|-----|
| Known sequence of steps | Linear/DAG plan | Steps are defined at planning time |
| Issue discovery → remediation | Convergence loop | Don't know how many cycles needed until convergence |
| Test failure → fix → retest | Convergence loop | Inherently cyclic with unknown iteration count |
| Code review → revision → re-review | Convergence loop | Same pattern: evaluate, fix, re-evaluate |
| Build → deploy → smoke test | Linear plan | Steps are always the same |
```

---

### 4.4 Document: 46-agentic-event-session-architecture.md

**Section affected:** Section 2 (Event Bus) — add new event types. Section 4 (Plan Management) — add loop task type.

**Change type:** Add content

#### New Event Types (add to Section 2, EVENT_TYPE_MAP):

```python
# Convergence loop events
class ConvergenceIterationEvent(SessionEvent):
    event_type: str = "plan.convergence.iteration"
    plan_id: UUID
    loop_task_id: UUID
    cycle_number: int
    findings_count: int
    fixes_applied: int
    convergence_metric: float | None       # e.g., PyQuality Index score
    converged: bool

class ConvergenceCompletedEvent(SessionEvent):
    event_type: str = "plan.convergence.completed"
    plan_id: UUID
    loop_task_id: UUID
    total_cycles: int
    final_metric: float | None
    outcome: str                           # "converged", "max_iterations", "error"
    branch_name: str | None                # Git branch with the changes
    pr_url: str | None                     # PR URL if auto-opened

class FinalVerificationEvent(SessionEvent):
    event_type: str = "plan.verification.completed"
    plan_id: UUID
    loop_task_id: UUID
    passed: bool
    test_summary: str                      # "47 passed, 0 failed" or error details
    environment_mode: str                  # "container" — always runs in fresh container
```

#### Plan Schema Update (Section 4):

Add `convergence_loop` as a task type in the `tasks` table. The loop configuration is stored in `input_data`:

```sql
-- A convergence loop task's input_data contains:
{
    "loop_config": {
        "max_iterations": 5,
        "convergence_condition": "zero_critical_findings",
        "convergence_threshold": null,
        "commit_per_cycle": true,
        "final_verification": true,
        "evaluation_agent": "code.qa.agent",
        "remediation_agent": "code.coder.agent",
        "evaluation_config": { ... },
        "remediation_config": { ... }
    }
}

-- Loop execution state is tracked in output_data (updated per cycle):
{
    "cycles": [
        {
            "cycle_number": 1,
            "evaluation_task_id": "uuid",
            "remediation_task_id": "uuid",
            "findings_count": 12,
            "fixes_applied": 10,
            "commit_hash": "abc123",
            "convergence_metric": 0.72
        },
        ...
    ],
    "converged": true,
    "total_cycles": 3,
    "final_verification_passed": true
}
```

---

### 4.5 Document: 41-agentic-pydanticai.md

**Section affected:** Coordinator Pattern, CoordinatorRequest model, Entry Points

**Change type:** Update existing content

#### CoordinatorRequest Update

Add execution mode resolution to `CoordinatorRequest`:

```python
class CoordinatorRequest(BaseModel):
    user_input: str
    session_id: UUID
    user_id: str
    entry_point: EntryPoint
    channel: str = "api"
    session_type: str = "direct"
    tool_access_level: str = "sandbox"
    execution_mode: str | None = None      # NEW — "local", "worktree", "container", or None (auto-resolve)
```

#### Execution Mode Resolution (new function in coordinator)

```python
# modules/backend/agents/coordinator/environment.py

def resolve_execution_mode(
    task_definition: dict,
    agent_config: dict,
) -> str:
    """Resolve the execution mode for a task.

    Priority order:
    1. Explicit mode in task definition (from playbook step)
    2. Explicit mode in agent YAML config
    3. Auto-resolution based on task characteristics

    Auto-resolution rules:
    - Task requires package installation → container
    - Task modifies database schemas/migrations → container
    - Task runs tests or builds → container
    - Task only reads/writes source files → worktree
    - Task doesn't touch code → local
    """
    # Check explicit overrides
    task_mode = task_definition.get("execution_environment")
    if task_mode and task_mode != "auto":
        return task_mode

    agent_mode = agent_config.get("execution", {}).get("mode", "local")
    if agent_mode != "auto":
        return agent_mode

    # Auto-resolution heuristics
    tools = set(agent_config.get("tools", []))
    has_execution_tools = bool(tools & {
        "code.run_tests", "code.build", "system.install_packages",
        "system.run_migrations", "system.exec_command",
    })
    has_write_tools = bool(tools & {
        "filesystem.write_file", "code.apply_fix",
        "filesystem.create_file", "filesystem.delete_file",
    })

    if has_execution_tools:
        return "container"
    elif has_write_tools:
        return agent_config.get("execution", {}).get("prefer", "worktree")
    else:
        return "local"
```

---

### 4.6 Document: 12-core-development-workflow.md

**Section affected:** "Version Control → Branch Strategy"

**Change type:** Add new subsection

#### New Subsection: "Agent Branches"

```markdown
### Agent Branches

Agents create branches when working in `worktree` or `container` execution mode. These branches follow a distinct naming convention and lifecycle.

**Branch naming:**

```
agent/{mission-id}/{task-type}

Examples:
agent/m-abc123/qa-cycle
agent/m-def456/refactor-auth
agent/m-ghi789/add-type-annotations
```

The `mission-id` is the short form of the mission UUID. The `task-type` is a human-readable slug derived from the task description. The `agent/` prefix distinguishes agent branches from human branches (`feature/`, `hotfix/`).

**Branch from:** Always `main` (or the configured `default_base_branch` in `environments.yaml`). Agents never branch from `develop` — they work against the production-ready code.

**Merge target:** Always `main` via PR. Agent branches merge through the same PR review process as human branches. No direct pushes to `main`.

**Commit messages from agents:**

```
[AGENT:{agent-name}] Short description (max 72 chars)

Mission: {mission-id}
Task: {task-id}
Cycle: {cycle-number} (for convergence loops)
Agent: {agent-name}

- Detailed changes
- Files modified
```

**Cleanup policy:**

| Condition | Action | Trigger |
|-----------|--------|---------|
| Branch merged via PR | Delete branch and worktree | Post-merge webhook or PR workflow |
| Mission completed, PR not yet opened | Keep branch, open PR automatically | Mission completion handler |
| Mission failed | Keep branch for debugging, tag as `agent/failed/` | Mission failure handler |
| Branch stale (no activity for `stale_branch_ttl_days`) | Delete branch and worktree | Scheduled maintenance task |
| Worktree exists but branch was deleted externally | Prune worktree | `git worktree prune` in maintenance task |

The cleanup is managed by the lifecycle maintenance scheduled task defined in doc 45, which runs periodically (default: every 60 minutes) via Taskiq.

**PR automation:**

When an agent mission completes successfully (convergence loop converged, or single-pass task completed), the platform:
1. Pushes the branch to the remote
2. Opens a PR with a generated description containing: mission objective, agent(s) used, number of iterations (for convergence loops), files changed, convergence metrics
3. Assigns the project owner as reviewer (from the Project entity, doc 48)
4. Labels the PR with `agent-generated`

The human reviews the PR like any other. The agent's per-cycle commits provide an auditable history of how the code evolved.
```

---

### 4.7 Document: 00-overview.md

**Change type:** Update changelog and version

Add to changelog:

```
- 3.5.0 (2026-03-15): Added git worktree execution mode to 47-agentic-module-organization.md (Dimension 4: three-tier execution — local/worktree/container); added Worktree Backend and Git-Aware Container sections to 45-agentic-execution-environments.md; added Convergence Loop plan pattern to 40-agentic-architecture.md; added convergence loop events and schema to 46-agentic-event-session-architecture.md; added execution mode resolution to 41-agentic-pydanticai.md coordinator; added agent branch strategy to 12-core-development-workflow.md
```

Update version to `3.5.0`.

---

## 5. Implementation Sequence

These changes should be implemented in this order, as each phase builds on the previous:

### Phase 1: Worktree Foundation (doc 47 + doc 45)

1. Update doc 47 Dimension 4 with three execution modes
2. Add `WorktreeBackend` to doc 45
3. Add worktree configuration to `environments.yaml`
4. Add worktree tracking to `execution_environments` table

**Deliverable:** Agents can be configured for `worktree` mode. WorktreeBackend can create, manage, and clean up worktrees. The lifecycle maintenance task handles stale worktree cleanup.

### Phase 2: Git-Aware Containers (doc 45)

1. Add `git_aware` template option
2. Implement worktree-inside-container composition
3. Add `code-workspace` template with Dockerfile
4. Test: container mounts `.git`, creates worktree, agent commits, branch is pushable

**Deliverable:** Containers can create worktrees from the host's git object store. Agent commits inside the container land on a feature branch that can be PR'd.

### Phase 3: Convergence Loop Pattern (doc 40 + doc 46)

1. Add convergence loop plan pattern to doc 40
2. Add loop task type and schema to doc 46 plan management
3. Add convergence loop events to doc 46 event bus
4. Implement loop execution in the plan service: bounded iteration, convergence checking, per-cycle commits

**Deliverable:** The plan engine supports iterative QA/fix cycles with configurable convergence conditions, max iterations, and per-cycle audit trails.

### Phase 4: Coordinator Integration (doc 41)

1. Add `execution_mode` to `CoordinatorRequest`
2. Implement `resolve_execution_mode()` with auto-resolution heuristics
3. Wire the coordinator to provision the correct execution environment before agent execution

**Deliverable:** The coordinator dynamically selects worktree vs. container based on task characteristics. Agents are unaware of their execution environment.

### Phase 5: Branch Strategy (doc 12)

1. Add agent branch naming convention
2. Implement cleanup policy in lifecycle maintenance task
3. Implement PR automation (push, open PR, assign reviewer, label)

**Deliverable:** Agent branches follow a consistent naming convention. PRs are opened automatically when missions complete. Stale branches are pruned.

### Phase 6: Final Verification Pattern

1. Implement the "ephemeral per mission + final clean verification" pattern
2. After convergence loop completes, optionally spin up a fresh container, check out the branch, bootstrap from zero, run full suite
3. If pass → open PR. If fail → flag for human review.

**Deliverable:** The platform can prove a branch is deployable from zero before any human sees the PR.

---

## 6. Cross-Reference: Which Existing Content to Preserve

These changes are additive. No existing content is deleted. Specific preservation notes:

| Document | Existing Content | Status |
|----------|-----------------|--------|
| 45 (Execution Environments) | Container lifecycle, DockerBackend, network isolation, gVisor, Temporal integration | **Unchanged** — worktree content is added alongside, not replacing |
| 47 (Module Organization) | Dimensions 1-3 (tool access, filesystem scope, delegation authority) | **Unchanged** — only Dimension 4 is updated |
| 40 (Agentic Architecture) | Linear plans, DAG plans, phase descriptions | **Unchanged** — convergence loop is added as a new pattern |
| 46 (Event Session Architecture) | All existing event types, plan schema, memory architecture | **Unchanged** — new events and schema additions only |
| 41 (Agentic PydanticAI) | Coordinator, routing, entry points, middleware, testing | **Unchanged** — execution mode resolution is added to the coordinator |
| 12 (Development Workflow) | Git strategy, CI/CD, dependency management | **Unchanged** — agent branch section is added |

---

## 7. Testing Strategy for These Changes

### Unit Tests

| Component | Test |
|-----------|------|
| `WorktreeBackend.create_worktree()` | Creates worktree on new branch, verifies branch exists, verifies worktree directory exists |
| `WorktreeBackend.cleanup_worktree()` | Removes worktree directory, optionally deletes branch |
| `WorktreeBackend.prune_stale_worktrees()` | Identifies and removes worktrees older than TTL |
| `resolve_execution_mode()` | Returns correct mode for various tool/config combinations |
| Convergence loop iteration | Tracks cycle count, applies convergence condition, respects max_iterations |
| Convergence loop events | Correct event types emitted at each stage |

### Integration Tests

| Test | Requires |
|------|----------|
| Create worktree, write file, commit, push, verify branch on remote | Real git repository |
| Create container with `git_aware: true`, mount `.git`, create worktree inside, verify commits | Docker daemon |
| Full convergence loop: QA finds issues → Coder fixes → QA re-validates → converges | Real git repo + Docker (for container mode) or worktree |
| Final verification: fresh container, checkout branch, install, test | Docker daemon |
| Stale branch cleanup | Real git repository with aged branches |

### CI Considerations

- Worktree tests require a real git repository (create temp repo in test fixtures)
- Container tests require Docker daemon (tagged `@pytest.mark.integration`)
- Convergence loop tests with real agents require `TestModel` (no LLM calls)
- Branch cleanup tests require a git remote (can use bare repo as test fixture)

---

## 8. Glossary of New Terms

| Term | Definition |
|------|-----------|
| **Worktree** | A git working directory checked out from a shared `.git` object store. Has its own branch, HEAD, and index. Near-instant creation. |
| **Git-aware container** | A Docker container that mounts the host's `.git` object store and creates a worktree inside for branch-isolated code execution with full runtime isolation. |
| **Convergence loop** | An iterative plan pattern where an evaluation agent and a remediation agent alternate until a quality gate is met or a maximum iteration count is reached. |
| **Convergence condition** | The quality gate that determines when a convergence loop has succeeded: all tests pass, zero findings, metric threshold, etc. |
| **Final clean verification** | An optional step after convergence where a fresh ephemeral container bootstraps from zero (install, migrate, test) to prove the branch is deployable. |
| **Execution mode resolution** | The coordinator's process of determining whether a task runs in `local`, `worktree`, or `container` mode, based on task characteristics, agent config, and explicit overrides. |
| **Agent branch** | A git branch created by the platform for agent work, following the naming convention `agent/{mission-id}/{task-type}`. |
| **Ephemeral per mission** | Container lifecycle where the container exists for the duration of all iterations within one mission, then is destroyed. Loop iterations share the running environment; each new mission gets a fresh container. |

---

## 9. Open Questions for Architecture Review

1. **Worktree path location:** Should worktrees be created in a sibling directory (`../agent-workspaces/`) or in a subdirectory within the repo (`.agent-workspaces/`, gitignored)? Sibling is cleaner for git but may surprise users who `ls` the parent directory.

2. **Concurrent worktree limit:** What's the right default for `max_concurrent_worktrees`? The conversation suggested 5-10 concurrent agents. Git itself has no limit, but filesystem and process resources are finite.

3. **Submodule handling:** Git worktrees and submodules interact poorly — each worktree needs its own submodule initialization. Should the architecture explicitly prohibit submodules in BFA projects, or document the workaround?

4. **Lock cleanup:** If an agent process dies uncleanly, stale lock files may prevent worktree operations. Should the maintenance task include `git worktree prune` and stale lock detection?

5. **Container image caching:** For the `code-workspace` template, how aggressively should Docker layer caching be used? Caching pip downloads saves ~30s per mission but can serve stale packages.

6. **PR automation scope:** Should the platform open PRs automatically for all agent work, or only for convergence loops? Single-pass worktree tasks (e.g., "add type annotations to this file") might be too small for a full PR workflow.

---

## 10. New Design Principles

These changes introduce two new principles that must be added to the architecture. They are grounded in existing BFA project principles P2 (Deterministic Over Non-Deterministic) and P13 (No Agent Self-Evaluation) from `docs/03-principles/01-project-principles.md`.

### Principle #29: Separation of Evaluation and Execution (doc 40)

**Add to:** `40-agentic-architecture.md`, Design Principles table, Phase 1.

> An agent that produces output must not evaluate the quality of that output. Evaluation and remediation must be performed by different agent instances with different system prompts, different filesystem scope, and ideally different models. This is the agentic equivalent of separation of duties — the same control that prevents the person who writes a cheque from approving it.

**Rationale:** LLMs are systematically biased toward their own output. An agent that writes code and then declares it correct has a single point of failure in its reasoning. Two separate agents with different prompts, different models, and different filesystem access create an adversarial dynamic that catches more errors. Self-correction loops (retrying on syntax errors) are acceptable for mechanical failures. Judgment calls (quality, correctness, completeness) require an external evaluator.

**Enforcement mechanism:** Filesystem scope (doc 47 Dimension 2). An agent with write access to `modules/` cannot have tools that evaluate code quality. An agent with evaluation tools cannot have write access to `modules/`. The access control matrix structurally prevents self-evaluation — it is not a convention, it is a configuration constraint.

**Relationship to project principles:**
- Extends P13 (No Agent Self-Evaluation) from project principles into the reference architecture
- Complements P2 (Deterministic Over Non-Deterministic) — deterministic tools handle the mechanical evaluation (test runners, linters), agents handle only the judgment that requires reasoning

### Principle #30: Deterministic Infrastructure, Non-Deterministic at the Edges (doc 40)

**Add to:** `40-agentic-architecture.md`, Design Principles table, Phase 1.

> Platform infrastructure — environment provisioning, plan dispatch, budget enforcement, state machine transitions, branch management, PR automation — is deterministic code. Agents are invoked only at the edges where reasoning is required: task decomposition, code generation, quality judgment, and failure recovery. Never use an agent where a script, a tool, or a state machine will produce the same or better result.

**Rationale:** An LLM call is non-deterministic, slow, and expensive. A bash script running `pip install` is deterministic, fast, and free. The line between "infrastructure" and "intelligence" is sharp: infrastructure does the same thing every time from the same inputs; intelligence reasons about ambiguous situations with unknown structure. Crossing this line in the wrong direction (using an agent for deterministic work) wastes money and introduces non-determinism where reproducibility is needed.

**Relationship to project principles:**
- Direct implementation of P2 (Deterministic Over Non-Deterministic)
- Reinforces P6 (Mission Control Is Infrastructure, Not Intelligence) — mission control is deterministic orchestration code, not an agent

---

## 11. Agent Roster for the Convergence Loop

This section defines the complete agent roster for a QA convergence loop, the access control constraints that enforce separation of duties, and the deterministic platform steps that bookend the agent work.

### 11.1 The Roster

The convergence loop requires **four core agents** plus **two optional agents** and **three deterministic platform steps**. The distinction between agent and platform code follows P2: if it requires reasoning, it's an agent. If it's the same sequence every time, it's platform code.

#### Platform Step: Environment Provisioning (deterministic)

This is NOT an agent. It is `ExecutionEnvironmentService` code that executes a deterministic sequence from the environment template.

| Concern | Value |
|---------|-------|
| What it does | Create worktree or container, `pip install`, run migrations, seed fixtures, verify all exit codes |
| Why not an agent | Same commands every time for a given project. No judgment. No ambiguity. P2 says use a tool. |
| When it runs | Once, before the loop starts |
| Failure handling | If any step fails → invoke `system.env.agent` for recovery (see below) |

The provisioning sequence for a git-aware container:

```
1. docker create (from template)              ← deterministic
2. docker start                               ← deterministic
3. git worktree add /workspace {branch}       ← deterministic
4. pip install -r requirements.txt            ← deterministic
5. alembic upgrade head                       ← deterministic
6. python -m pytest --co -q (collect only)    ← deterministic (verify tests discoverable)
7. seed test fixtures                         ← deterministic
8. verify: all exit codes == 0                ← deterministic
```

No LLM touches this sequence. It's a script.

#### Agent 1: `code.planner.agent` — The Architect

Looks at the mission objective and produces the TaskPlan. Decides what needs to happen. Never touches code. Runs once before the loop.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet or Opus — needs strong reasoning for task decomposition |
| **Filesystem read** | `docs/`, `config/`, Code Map (doc 49), PCD (doc 48) |
| **Filesystem write** | None |
| **Tools** | `plan.create_plan`, `plan.revise_plan`, `filesystem.read_file`, `filesystem.list_files` |
| **Execution mode** | `local` — reads project structure, no code modification |
| **Role in loop** | Pre-loop only. Produces the plan. May be consulted mid-loop if the Coder escalates or the plan needs revision (P8). |
| **Separation of duties** | Plans the work but never executes it. Cannot see test results or code changes. |
| **P2 alignment** | The Planner uses LLM reasoning because task decomposition is inherently ambiguous — it requires understanding intent, assessing complexity, and making scope judgments. A deterministic tool cannot do this. |

#### Agent 2: `code.coder.agent` — The Developer

Reads findings from the QA agent, applies fixes, commits. Writes code but **never runs tests and never evaluates its own changes**.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs strong coding capability |
| **Filesystem read** | `modules/`, `config/` (source code only) |
| **Filesystem write** | `modules/`, `config/` |
| **Explicitly excluded** | `tests/` — cannot read test assertions. `docs/` — cannot read specifications. |
| **Tools** | `filesystem.read_file`, `filesystem.write_file`, `filesystem.list_files`, `filesystem.search_files`, `code.apply_fix`, `git.commit` |
| **Execution mode** | `worktree` or `container` (depending on mission) |
| **Role in loop** | Receives findings → reads affected files → applies fixes → commits. One cycle per iteration. |
| **Separation of duties** | Writes code but cannot evaluate it. Has no access to test files (cannot game tests). Has no access to docs (cannot expand scope beyond targeted fixes). |
| **P2 alignment** | Applying code fixes from structured findings requires reasoning about code structure, naming, patterns, and side effects. A deterministic tool cannot do this — it's the core creative act. |
| **P13 alignment** | Cannot run tests. Cannot assess quality. Must hand back to QA for evaluation. |

**Why exclude `tests/` and `docs/`?** Two critical constraints:

1. **No `tests/` access prevents test gaming.** If the Coder can read test assertions, it can write code that satisfies the specific assertion rather than fixing the underlying issue. By denying access to tests, the Coder must fix the root cause based on the QA findings, not the symptoms based on test expectations.

2. **No `docs/` access constrains scope.** The Coder's job is to fix what QA flagged — nothing more. If it can read documentation, it may decide to "improve" things beyond the findings, expanding scope and introducing unplanned changes. The findings are the Coder's work order. Nothing else.

#### Agent 3: `code.tester.agent` — The Test Engineer

Writes and updates tests. Has the **inverse access pattern** to the Coder — reads `docs/` and `tests/` but **cannot see or modify source code**.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs to understand both documentation intent and test patterns |
| **Filesystem read** | `docs/`, `tests/`, `config/` |
| **Filesystem write** | `tests/` only |
| **Explicitly excluded** | `modules/` — cannot see source code implementation |
| **Tools** | `filesystem.read_file`, `filesystem.write_file`, `filesystem.list_files`, `code.run_tests` |
| **Execution mode** | `worktree` or `container` |
| **Role in loop** | Optional. Pre-loop: reviews whether existing tests cover the mission objective, adds tests if needed. Post-loop: adds regression tests for issues found during the cycle. |
| **Separation of duties** | Writes tests but cannot write source code. Tests are derived from documentation (intent), not from implementation (current behavior). |
| **P2 alignment** | Understanding documentation intent and translating it into test assertions requires reasoning about specifications, edge cases, and coverage gaps. Deterministic tools cannot do this. |
| **P13 alignment** | The Tester does not evaluate whether the source code is correct — it defines what "correct" means in test form. The QA agent evaluates by running those tests. |

**Why exclude `modules/` from the Tester?** This is the most powerful constraint in the roster. By denying the Tester access to implementation, it writes tests that verify **what the system should do** (from docs), not **what the code currently does** (from implementation). This prevents the tautological test problem where tests merely assert current behavior — including bugs — rather than correct behavior.

A test written from documentation catches implementation bugs. A test written from implementation enshrines them.

#### Agent 4: `code.qa.agent` — The Quality Gate

Runs the test suite, static analysis, linting, and composite quality metrics. Produces structured findings. **Cannot modify any code.** Pure evaluator.

| Dimension | Value |
|-----------|-------|
| **Model** | Haiku — fast and cheap. Runs predefined checks, not creative reasoning. |
| **Filesystem read** | Everything: `modules/`, `tests/`, `config/`, `docs/` (full visibility needed to evaluate) |
| **Filesystem write** | None — zero write access anywhere |
| **Tools** | `code.run_tests`, `code.lint`, `compliance.scan_*`, `filesystem.read_file`, `filesystem.list_files` |
| **Execution mode** | Same as the Coder (operates in the same worktree/container) |
| **Role in loop** | The evaluation half of the convergence loop. Runs suite → produces structured findings → hands to Coder. Every iteration. |
| **Separation of duties** | Can observe everything but change nothing. This makes it a trustworthy evaluator — it has no ability to hide its own mistakes because it cannot make any. |
| **P2 alignment** | The individual checks (pytest, flake8, mypy) are deterministic tools invoked by the agent. The agent's role is interpreting composite results, prioritizing findings by severity, and deciding whether convergence criteria are met. The mechanical execution is P2-compliant (tools do the scanning); the judgment layer is where the LLM adds value. |
| **P13 alignment** | The QA agent never wrote the code it's evaluating. It has no authorship bias. |

#### Agent 5 (Optional): `code.reviewer.agent` — The Code Reviewer

Post-loop qualitative review of the entire diff. Catches things automated QA misses: logic errors that pass tests, misleading naming, architectural drift.

| Dimension | Value |
|-----------|-------|
| **Model** | Opus — needs the strongest judgment for qualitative assessment |
| **Filesystem read** | Everything: `modules/`, `tests/`, `docs/`, `config/` |
| **Filesystem write** | None |
| **Tools** | `filesystem.read_file`, `git.diff`, `git.log` |
| **Execution mode** | `local` — reviewing a diff, not executing code |
| **Role in loop** | Post-loop only. Runs once after convergence, before PR. Produces: approve, request changes, or escalate to human. If it requests changes, findings feed back to the Coder for one more iteration. |
| **Separation of duties** | Reviews but does not write. Different model (Opus) from the Coder (Sonnet) ensures different reasoning patterns. |
| **P2 alignment** | Qualitative code review — "is this the right abstraction? will this scale? does this naming communicate intent?" — is inherently non-deterministic. It requires judgment, experience, and reasoning about implications. This is the correct use of an LLM. |

#### Agent 6 (Invoked on failure): `system.env.agent` — Infrastructure Recovery

NOT part of the happy path. Invoked only when deterministic provisioning fails. Reads error output, diagnoses the problem, applies a fix, and returns retry instructions.

| Dimension | Value |
|-----------|-------|
| **Model** | Sonnet — needs to read error messages and reason about fixes |
| **Filesystem read** | Everything — needs to inspect `requirements.txt`, `Makefile`, `pyproject.toml`, `docker-compose.yml`, migration files, error logs |
| **Filesystem write** | `config/`, environment template files, Dockerfiles — can fix environment configuration |
| **Tools** | `filesystem.read_file`, `filesystem.list_files`, `system.exec_command`, `system.read_logs`, `system.install_packages` |
| **Execution mode** | Runs INSIDE the container (fixing the environment it's standing in) |
| **Role in loop** | Not part of the QA convergence loop. Upstream. Called only when provisioning fails. |
| **Separation of duties** | Can fix the environment but cannot evaluate whether it's correct. Correctness is structural: did the commands exit 0? That's a deterministic check. |
| **P2 alignment** | Diagnosing "why did `pip install` fail?" requires reading error output, understanding dependency conflicts, and reasoning about system library requirements. This is non-deterministic by nature. But it's at the edge — the recovery agent is invoked only when deterministic automation hits something it can't handle. The happy path never touches an LLM. |

### 11.2 The Access Control Matrix

This is the enforcement mechanism for Principle #29 (Separation of Evaluation and Execution). No single agent can both modify the system AND declare it correct.

| Agent | Read `modules/` | Write `modules/` | Read `tests/` | Write `tests/` | Read `docs/` | Run tests | Evaluate quality | Fix code |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `code.planner` | — | — | — | — | ✓ | — | — | — |
| `code.coder` | ✓ | **✓** | — | — | — | — | — | **✓** |
| `code.tester` | — | — | ✓ | **✓** | ✓ | ✓ | — | — |
| `code.qa` | ✓ | — | ✓ | — | ✓ | **✓** | **✓** | — |
| `code.reviewer` | ✓ | — | ✓ | — | ✓ | — | **✓** | — |
| `system.env` | ✓ | — | — | — | ✓ | — | — | — |

**Three structural constraints enforced by this matrix:**

1. **The Coder cannot run tests.** It cannot verify its own fixes. It must hand back to QA.
2. **The QA agent cannot write code.** It cannot fix what it finds. It must hand to the Coder.
3. **The Tester cannot see source code.** It writes tests from documentation intent, not from implementation reality.

No single agent can both modify the system AND declare it correct. This is not a convention — it is enforced by the `scope` configuration in each agent's YAML (doc 47, Dimension 2).

### 11.3 The Full Flow with Deterministic/Non-Deterministic Boundaries

Every step is explicitly labeled as **deterministic platform code** (P2: tool/script) or **non-deterministic agent** (reasoning required). The boundary between the two is sharp and intentional.

```
code.planner.agent ← NON-DETERMINISTIC (task decomposition requires reasoning)
    │ Produces: TaskPlan + file manifests + convergence criteria
    │ Access: docs/, config/, Code Map, PCD (read-only)
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (same sequence every time from template)
    │ Provision execution environment:
    │   create worktree/container → pip install → migrate → seed → verify exit codes
    │
    │ ── ALL EXIT CODES 0? → proceed
    │ ── ANY FAILURE? ─────→ system.env.agent ← NON-DETERMINISTIC (diagnose + fix)
    │                              │                  (edge case: reasoning about errors)
    │                              └→ retry provisioning (deterministic)
    │
    ▼
code.tester.agent (optional) ← NON-DETERMINISTIC (translating doc intent to test assertions)
    │ Reviews: do existing tests cover the mission objective?
    │ Writes: new/updated tests in tests/ only
    │ Access: docs/ + tests/ (cannot see modules/)
    │
    ▼
┌─── CONVERGENCE LOOP ─────────────────────────────────────────────────────┐
│                                                                          │
│   code.qa.agent ← PARTIALLY DETERMINISTIC                               │
│     │ Tools (deterministic): pytest, flake8, mypy, compliance scanners  │
│     │ Agent (non-deterministic): interpret composite results, prioritize │
│     │ Produces: structured findings with severity                        │
│     │ Access: everything (READ-ONLY — zero writes)                       │
│     │                                                                    │
│     │ PLATFORM CODE (deterministic): check convergence condition         │
│     │   ├── Converged? (all tests pass / zero criticals / metric > N)   │
│     │   │   → EXIT LOOP (success)                                       │
│     │   ├── Max iterations exceeded?                                     │
│     │   │   → EXIT LOOP (escalate to human)                             │
│     │   └── Continue                                                     │
│     │                                                                    │
│     ▼                                                                    │
│   code.coder.agent ← NON-DETERMINISTIC (applying code fixes)            │
│     │ Reads: findings + source code in modules/                          │
│     │ Writes: fixes to modules/, config/                                 │
│     │ Cannot see: tests/, docs/                                          │
│     │                                                                    │
│     │ PLATFORM CODE (deterministic): git commit                          │
│     │   commit message follows template, no LLM needed                  │
│     │                                                                    │
│     └──→ LOOP BACK TO QA                                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
    │
    ▼
code.tester.agent (optional) ← NON-DETERMINISTIC
    │ Adds: regression tests for issues found during loop
    │ Access: docs/ + tests/ (cannot see modules/)
    │
    ▼
code.reviewer.agent (optional) ← NON-DETERMINISTIC (qualitative judgment)
    │ Reviews: the full diff (branch vs main)
    │ Produces: approve / request changes / escalate
    │ Access: everything (READ-ONLY)
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (same verification every time)
    │ Final Clean Verification:
    │   fresh container → checkout branch → pip install → migrate → pytest
    │   All exit codes checked. No LLM involved.
    │   Pass → continue. Fail → escalate to human.
    │
    ▼
PLATFORM CODE ← DETERMINISTIC (git + API calls)
    │ Push branch → open PR → assign reviewer → add labels
    │ PR description generated from mission metadata (template, not LLM)
    │
    ▼
DONE — human reviews PR
```

### 11.4 Why Each Non-Deterministic Step Requires an Agent

Per P2, every LLM call must justify itself. Here's the justification for each agent invocation:

| Agent | Why a deterministic tool cannot do this |
|-------|----------------------------------------|
| `code.planner` | Task decomposition requires understanding intent, assessing complexity, identifying dependencies, and scoping work. There is no algorithm that decomposes "improve the authentication module" into specific file-level tasks. |
| `code.coder` | Applying code fixes from structured findings requires understanding code context, choosing the right abstraction, maintaining naming consistency, and avoiding side effects. A regex find-replace can handle trivial cases; a refactor requires reasoning. |
| `code.tester` | Translating documentation intent ("the system should validate email format") into test assertions (`assert service.validate("bad@@email") raises ValidationError`) requires understanding specifications, identifying edge cases, and writing idiomatic test code. |
| `code.qa` | Individual tools (pytest, flake8) are deterministic and invoked as tools — not via LLM. The agent adds value by interpreting *composite* results: "15 test failures, 3 linting warnings, and a type error — what's the root cause? What should the Coder fix first?" That prioritization requires reasoning. |
| `code.reviewer` | Qualitative review — "is this the right abstraction? will this scale? does this naming communicate intent?" — is inherently non-deterministic. It requires judgment about code quality that no static analysis tool can provide. |
| `system.env` | Diagnosing provisioning failures ("pip install failed because lxml needs libxml2-dev on this platform") requires reading error output, understanding system dependencies, and reasoning about fixes. But this is the edge case — the happy path is fully deterministic. |

### 11.5 What Stays Deterministic (Per P2)

These operations are **never** routed through an agent, even if an agent could theoretically do them:

| Operation | Why It's Deterministic | Implementation |
|-----------|----------------------|----------------|
| Create worktree / container | Same template → same result every time | `ExecutionEnvironmentService` |
| `pip install` | Lockfile-driven, no reasoning needed | Bash in container |
| `alembic upgrade head` | Migrations are versioned scripts | Bash in container |
| Run pytest | Command execution, exit code check | Tool: `code.run_tests` |
| Run flake8 / mypy | Command execution, parse output | Tool: `compliance.scan_*` |
| Check convergence condition | Compare metric to threshold | Platform code: `if metric >= threshold` |
| Git commit | Template-driven message, no reasoning | Platform code: `git.commit` |
| Git push + open PR | API calls with template data | Platform code |
| Worktree/branch cleanup | Age-based pruning | Scheduled Taskiq task |
| Budget enforcement | Compare accumulated cost to cap | Platform code: `if cost > budget` |
| State machine transitions | Plan status changes | Platform code: `update task set status = ...` |

---

## 12. Changes Required to Existing Principles Documents

### 12.1 Reference Architecture: doc 40 (Agentic Architecture)

**Add to Design Principles table:**

| # | Principle | Phase |
|---|-----------|-------|
| 29 | Separation of Evaluation and Execution — the agent that produces output must not evaluate it. Different agents, different prompts, different filesystem scope, different models. Enforced by access control configuration, not convention. | 1 |
| 30 | Deterministic Infrastructure, Non-Deterministic at the Edges — platform infrastructure is deterministic code. Agents are invoked only where reasoning is required. Never use an agent where a script or tool will produce the same or better result. | 1 |

### 12.2 Reference Architecture: doc 47 (Agent Module Organization)

**Add to "Access Control Model" section** (after the existing access control matrix):

A new subsection: "Worked Example: Convergence Loop Access Control"

This should contain the full access control matrix from Section 11.2 of this document, with the explanation of why each constraint exists. This serves as the canonical example of how filesystem scope enforces separation of duties in a multi-agent workflow.

**Add to "Anti-Patterns" table:**

| Anti-pattern | Why prohibited |
|-------------|---------------|
| Agent evaluates its own output | Violates P29 (Separation of Evaluation and Execution). LLMs are biased toward their own output. Evaluation and remediation must be different agents with different scope. |
| Agent has both write access and evaluation tools | Structurally enables self-evaluation. If an agent can write code AND run tests, it can game the tests. Scope must prevent this. |
| Using an LLM for deterministic operations | Violates P30 (Deterministic Infrastructure). `pip install`, `pytest`, `git commit`, state machine transitions, and budget checks are deterministic. Using an agent adds cost, latency, and non-determinism for zero benefit. |
| Coding agent with access to test files | Enables test gaming — the agent writes code to satisfy specific assertions rather than fixing the underlying issue. Coder scope must exclude `tests/`. |
| Test agent with access to source code | Produces tautological tests that assert current behavior (including bugs) rather than correct behavior. Tester scope must exclude `modules/`. |

### 12.3 Project Principles: docs/03-principles/01-project-principles.md

P13 (No Agent Self-Evaluation) is already present. Two additions:

**Strengthen P13 with enforcement mechanism:**

Add to P13's "This means" section:
- Filesystem scope (doc 47) structurally prevents self-evaluation. An agent with write access to `modules/` cannot have tools that run tests. An agent with evaluation tools cannot have write access to `modules/`. This is configuration-enforced, not convention-based.
- In convergence loops: the Coder agent cannot see `tests/` (prevents test gaming). The Tester agent cannot see `modules/` (prevents tautological tests). The QA agent cannot write anything (prevents self-remediation).

**Add cross-reference between P2 and P13:**

P2 (Deterministic Over Non-Deterministic) and P13 (No Agent Self-Evaluation) together define the boundaries of the convergence loop:
- P2 determines which steps are agents (reasoning) vs. platform code (deterministic)
- P13 determines which agents are distinct (no self-evaluation across the evaluation/execution boundary)

---

## 13. Agent YAML Configuration Examples

These examples show the concrete YAML for each agent in the convergence loop roster, following the schema from doc 47.

### code.coder.agent

```yaml
# config/agents/code/coder/agent.yaml
agent_name: code.coder.agent
agent_type: vertical
description: "Applies code fixes based on structured findings from QA agents"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 2.00
max_input_length: 32000

keywords:
  - fix code
  - apply fix
  - refactor
  - implement

tools:
  - filesystem.read_file
  - filesystem.write_file
  - filesystem.list_files
  - filesystem.search_files
  - code.apply_fix
  - git.commit

# CRITICAL: No tests/, no docs/ — P13 enforcement
scope:
  read:
    - "modules/"
    - "config/"
  write:
    - "modules/"
    - "config/"

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.tester.agent

```yaml
# config/agents/code/tester/agent.yaml
agent_name: code.tester.agent
agent_type: vertical
description: "Writes and updates tests based on documentation intent, not implementation"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 1.00
max_input_length: 32000

keywords:
  - write tests
  - test coverage
  - add tests
  - regression test

tools:
  - filesystem.read_file
  - filesystem.write_file
  - filesystem.list_files
  - code.run_tests

# CRITICAL: No modules/ — P13 enforcement (tests from intent, not implementation)
scope:
  read:
    - "docs/"
    - "tests/"
    - "config/"
  write:
    - "tests/"

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.qa.agent

```yaml
# config/agents/code/qa/agent.yaml
agent_name: code.qa.agent
agent_type: vertical
description: "Evaluates code quality via test execution, linting, and static analysis"
enabled: true
model: anthropic:claude-haiku-4-5-20251001
max_budget_usd: 0.50
max_input_length: 32000

keywords:
  - qa
  - quality
  - audit
  - check code
  - compliance
  - run tests

tools:
  - code.run_tests
  - code.lint
  - compliance.scan_imports
  - compliance.scan_datetime
  - compliance.scan_hardcoded
  - compliance.scan_file_sizes
  - filesystem.read_file
  - filesystem.list_files

# CRITICAL: Read everything, write nothing — pure evaluator
scope:
  read:
    - "modules/"
    - "tests/"
    - "config/"
    - "docs/"
  write: []

execution:
  mode: auto
  prefer: worktree
  template: code-workspace
```

### code.reviewer.agent

```yaml
# config/agents/code/reviewer/agent.yaml
agent_name: code.reviewer.agent
agent_type: vertical
description: "Qualitative code review of diffs — catches what automated QA misses"
enabled: true
model: anthropic:claude-opus-4-20250514
max_budget_usd: 3.00
max_input_length: 64000

keywords:
  - review
  - code review
  - review diff
  - review changes

tools:
  - filesystem.read_file
  - filesystem.list_files
  - git.diff
  - git.log

# Read everything, write nothing — reviewer does not modify code
scope:
  read:
    - "modules/"
    - "tests/"
    - "config/"
    - "docs/"
  write: []

execution:
  mode: local
```

### system.env.agent

```yaml
# config/agents/system/env/agent.yaml
agent_name: system.env.agent
agent_type: vertical
description: "Diagnoses and recovers from execution environment provisioning failures"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_budget_usd: 1.00
max_input_length: 32000

keywords:
  - environment
  - install failed
  - pip error
  - migration error
  - setup failed

tools:
  - filesystem.read_file
  - filesystem.list_files
  - system.exec_command
  - system.read_logs
  - system.install_packages

scope:
  read:
    - "*"
  write:
    - "config/"

execution:
  mode: container
```

---

*End of change specification.*
