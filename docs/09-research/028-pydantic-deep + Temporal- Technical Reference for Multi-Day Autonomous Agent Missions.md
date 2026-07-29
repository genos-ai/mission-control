# pydantic-deep + Temporal: Technical Reference for Multi-Day Autonomous Agent Missions

## TL;DR

- **pydantic-deep is a "harness" of capabilities and toolsets layered on PydanticAI** (`create_deep_agent()` returns a standard `Agent[DeepAgentDeps, OutputT]`), composing six standalone packages (`pydantic-ai-todo`, `pydantic-ai-backend`, `subagents-pydantic-ai`, `summarization-pydantic-ai`, `pydantic-ai-shields`, `pydantic-ai-middleware`). Every feature — planning, filesystem, sub-agents, hooks, checkpoints, cost tracking, context compression, teams — is implemented as a pydantic-ai `Capability`/`Toolset` and runs inside a single agent run.
- **Temporal durability is provided by PydanticAI's `TemporalAgent` wrapper, not by pydantic-deep itself.** Wrapping `create_deep_agent()`'s output in `TemporalAgent` automatically offloads model requests, tool calls, and MCP I/O to Temporal Activities, while the agent loop runs deterministically inside the workflow. Multi-day missions require workflow-level patterns (`workflow.sleep`, signals, `continue_as_new`) on top of the agent run, plus an external durable store (PostgreSQL via `pydantic-ai-todo`, file checkpoints, `MEMORY.md`) because a single PydanticAI `agent.run()` is the unit of activity execution, not the unit of long-running orchestration.
- **For week-long missions, treat each `agent.run()` as a bounded activity inside a long-lived Temporal workflow.** Persist task graphs in PostgreSQL (`pydantic-ai-todo`), persist filesystem state in `LocalBackend` or `DockerSandbox` with named workspaces, persist conversation in `FileCheckpointStore`, and use `continue_as_new` every ~10K events or when context exceeds limits. pydantic-deep does not currently ship a Temporal-aware backend, a workflow-aware checkpoint store, or signal-driven sub-agent orchestration — these must be implemented at the workflow layer.

---

## Key Findings

| Question | Answer |
|---|---|
| Does pydantic-deep have a Temporal integration? | No — it inherits PydanticAI's `TemporalAgent` because `create_deep_agent()` returns a plain `Agent`. There is no `pydantic_deep.durable_exec` module. |
| Can a deep agent run autonomously for days? | Not as a single `agent.run()` call. It can, when wrapped as Temporal Activities and orchestrated by a workflow that loops, sleeps, accepts signals, and persists state externally. |
| What's the unit of durability? | A Temporal Activity ≈ one model request or one tool call. A Temporal Workflow ≈ the orchestration loop calling `temporal_agent.run(...)` repeatedly. |
| Where does long-running state live? | PostgreSQL (`pydantic-ai-todo` task graph), filesystem (`LocalBackend`/`DockerSandbox` files, `MEMORY.md`), checkpoint store (`FileCheckpointStore`/`InMemoryCheckpointStore`), and Temporal Event History (workflow variables ≤50 MB / 51,200 events). |
| Hard Temporal limits to design around | 2 MB payload per request, 4 MB per event-history transaction, 50 MB / 51,200 events per workflow run, 2,000 in-flight pending activities/signals/child workflows, 10 K events warning threshold. |
| Production use case fit | Coding assistants, deep-research agents, codebase migrations, multi-day refactors, monitoring/scheduling agents. Not currently suited to >100 concurrent in-flight tools per workflow without continue-as-new. |

---

## Details

### 1. pydantic-deep architecture

#### 1.1 Stack

```
┌─────────────────────────────────────────────────────────────┐
│  create_deep_agent()  →  Agent[DeepAgentDeps, OutputT]      │  pydantic-deep
├─────────────────────────────────────────────────────────────┤
│  Capabilities  (extend AbstractCapability)                  │
│  ├─ Internal: Planning, Filesystem, Subagents, Skills,      │
│  │           Teams, Plan, Memory, ContextFiles              │
│  └─ External: Cost (shields), ContextManager (summ),        │
│              Checkpoints, Hooks, WebSearch, WebFetch,       │
│              Thinking, MCP                                  │
├─────────────────────────────────────────────────────────────┤
│  Toolsets:  TodoToolset, ConsoleToolset, SubAgentToolset,   │
│             SkillsToolset, CheckpointToolset,               │
│             AgentMemoryToolset, ContextToolset, TeamToolset │
├─────────────────────────────────────────────────────────────┤
│  pydantic-ai 1.x  (Capabilities API, history_processors,    │
│                    Toolsets, Hooks, MiddlewareAgent)        │
├─────────────────────────────────────────────────────────────┤
│  Backends (BackendProtocol/SandboxProtocol):                │
│    StateBackend | LocalBackend | FilesystemBackend |        │
│    DockerSandbox | DaytonaSandbox | CompositeBackend        │
└─────────────────────────────────────────────────────────────┘
```

Component packages (all MIT, all individually `pip`-installable):

| Package | Provides | `create_deep_agent` flag |
|---|---|---|
| `pydantic-ai-todo` | `read_todos`, `write_todos`, `add_todo`, `add_subtask`, `set_dependency`, `get_available_tasks`, `update_todo_status`, `remove_todo`. PostgreSQL or in-memory async storage. DFS cycle detection. Event emitter for webhooks. | `include_todo=True` |
| `pydantic-ai-backend` | `ConsoleCapability` + tools (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`); permission ruleset; `LocalBackend`, `StateBackend`, `FilesystemBackend`, `DockerSandbox`, `DaytonaSandbox`, `CompositeBackend`, `SessionManager`, `RuntimeConfig`. | `include_filesystem=True` |
| `subagents-pydantic-ai` | `SubAgentCapability` with `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `soft_cancel_task`, `hard_cancel_task`, `answer_subagent`, `ask_parent`. Sync/async/auto execution modes; nested sub-agents; `DynamicAgentRegistry`; `create_agent_factory_toolset`. | `include_subagents=True` |
| `summarization-pydantic-ai` | `SummarizationProcessor` (LLM compression), `SlidingWindowProcessor` (zero-cost trim), `ContextManagerCapability` (real-time token tracking + auto-compress at 90 % + tool-output truncation), `LimitWarnerProcessor` (URGENT/CRITICAL warnings at 70 %). | `context_manager=True`, `history_processors=[…]` |
| `pydantic-ai-shields` | `CostTracking(budget_usd=…)` raising `BudgetExceededError`; `ToolGuard`, `InputGuard`, `OutputGuard`; `PromptInjection`, `PiiDetector`, `SecretRedaction`, `BlockedKeywords`, `NoRefusals` content shields. | `cost_tracking=True`, `cost_budget_usd=…` |
| `pydantic-ai-middleware` | `MiddlewareAgent`, `CostTrackingMiddleware`, `permission_handler`. | implicit when `middleware=` is set |
| `pydantic-deep` itself | `create_deep_agent`, `create_default_deps`, `DeepAgentDeps`, `Hook`/`HookEvent`, `Checkpoint`, `CheckpointStore`/`InMemoryCheckpointStore`/`FileCheckpointStore`, `RewindRequested`, `fork_from_checkpoint`, `SharedTodoList`, `TeamMessageBus`, `AgentTeam`, `LoopDetectionCapability`, `LimitWarnerCapability`, `EvictionCapability`, `PatchToolCallsCapability`, plan-mode, skills, context files, memory, custom commands. | various `include_*` flags |

#### 1.2 Lifecycle and `create_deep_agent`

```python
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="...",
    backend=LocalBackend(root_dir="/workspace"),
    # Toggleable capabilities
    include_todo=True,
    include_filesystem=True,
    include_subagents=True,
    include_skills=True,
    include_memory=True,        # MEMORY.md per agent
    include_plan=True,          # planner sub-agent
    include_teams=True,         # SharedTodoList + MessageBus
    include_web=True,           # WebSearch + WebFetch
    include_checkpoints=True,
    context_manager=True,       # auto-summarize at 90% of token budget
    context_manager_max_tokens=200_000,
    cost_tracking=True,         # default: True
    cost_budget_usd=50.0,       # raises BudgetExceededError
    on_cost_update=lambda info: ...,
    on_context_update=lambda pct, cur, mx: ...,
    eviction_token_limit=20_000,  # save large tool outputs to file
    thinking="high",            # default in v0.3.3+
    hooks=[Hook(event=HookEvent.PRE_TOOL_USE, command="...")],
    subagents=[SubAgentConfig(name=..., description=..., instructions=..., preferred_mode="sync")],
    subagent_extra_toolsets=[mcp_server],
    subagent_registry=DynamicAgentRegistry(),
    skill_directories=[{"path": "./skills", "recursive": True}],
    history_processors=[create_summarization_processor(...)],
    output_type=MyPydanticModel,  # type-safe structured output
    retries=3,
    descriptions={"write_file": "Custom description..."},  # tool description override
)
```

Returns a standard `Agent[DeepAgentDeps, OutputT]`. Lifecycle is the standard PydanticAI run lifecycle (graph traversal of model-request → tool-call → model-request nodes), but with capabilities injecting hooks at every stage.

#### 1.3 Backends

| Backend | Storage | Use-case for multi-day mission |
|---|---|---|
| `StateBackend` | In-memory dict | Tests only — state is lost on worker restart, breaks Temporal replay. |
| `LocalBackend(root_dir, allowed_directories, enable_execute, permissions=…)` | Real disk, sandboxed by path | Survives crashes; volume-mount it into Temporal worker pod. |
| `FilesystemBackend` | Real disk with path sandboxing | Same. |
| `DockerSandbox(image, container_name=…, volumes=…, runtime=RuntimeConfig(…))` | Docker container, named (`auto_remove=False`) for persistence between sessions | Recommended for code-executing missions; the named container persists installed packages between Temporal activity runs. |
| `DaytonaSandbox(sandbox_id)` | Cloud sandbox via Daytona | For untrusted code, multi-tenant. |
| `CompositeBackend(default, routes={...})` | Path-based routing | Mix in-memory cache + on-disk project. |

The `BackendProtocol` exposes `read`, `write`, `edit`, `ls`, `glob`, `grep`, plus `execute` on sandbox-capable backends.

#### 1.4 Permission presets (from `pydantic_ai_backends.permissions`)

| Preset | Reads | Writes | Execute | Notes |
|---|---|---|---|---|
| `DEFAULT_RULESET` | Allow | Ask for approval | Ask | Safe default; non-blocking reads. |
| `PERMISSIVE_RULESET` | Allow | Allow | Allow | Trusted-environment fast path. |
| `READONLY_RULESET` | Allow | Tools hidden from model | Tools hidden | Strongest gate against mutation. |
| `STRICT_RULESET` | Ask | Deny by default | Deny | Most conservative. |

All presets honour glob rules, built-in secret detection (`.env`, credentials, key files), and system-file protection. `Bandit` runs in CI on the package. `MD5(usedforsecurity=False)` is used for tool-call deduplication only.

#### 1.5 Planning system

Planning is the `pydantic-ai-todo` toolset, plus an optional `PlanCapability` that spawns a dedicated planner sub-agent which asks clarifying questions before execution. Tools registered on the model:

- `write_todos(todos)` — bulk replace.
- `read_todos()` — list.
- `add_todo(content, ...)` / `update_todo_status(id, status)` / `remove_todo(id)`.
- `add_subtask(parent_id, content)` — hierarchy.
- `set_dependency(task_id, depends_on_id)` — DAG; **rejects cycles via DFS** (`_has_cycle`); error returns to model.
- `get_available_tasks()` — returns tasks whose dependencies are all `completed` (used by the model to decide what to work on next).

Storage backends: `AsyncMemoryStorage` (default) or `create_storage("postgres", connection_string=..., session_id=...)`. The `session_id` provides multi-tenancy. `get_todo_system_prompt_async(storage)` injects current todo list into the system prompt on every model request, so plan state survives across runs/restarts.

#### 1.6 Sub-agent delegation

`SubAgentToolset` (from `subagents-pydantic-ai`) gives the parent these tools:

```
task(name, prompt, mode="sync"|"async"|"auto") -> TaskHandle
check_task(task_id) -> TaskStatus
wait_tasks(task_ids) -> list[result]
list_active_tasks()
soft_cancel_task(task_id)  # cooperative
hard_cancel_task(task_id)  # asyncio.Task.cancel
answer_subagent(question_id, answer)
```

- **Sync mode**: blocks parent until child finishes (cheap, deterministic).
- **Async mode**: child runs in `asyncio.Task`; parent continues; results retrieved later via `check_task`/`wait_tasks`.
- **Auto mode**: heuristic chooses based on `TaskCharacteristics`.

Sub-agents are themselves `create_deep_agent()` results from v0.3.3 (filesystem + web + memory + eviction + patch by default). `max_nesting_depth` defaults to 1 (one level of nested sub-agents).

`DeepAgentDeps.clone_for_subagent(max_depth=N)` produces isolated deps:

```python
def clone_for_subagent(self, max_depth: int = 0) -> DeepAgentDeps:
    return DeepAgentDeps(
        backend=self.backend,           # shared — same files
        files=self.files,               # shared reference
        todos=[],                       # isolated — fresh todo list
        subagents={} if max_depth <= 0 else self.subagents.copy(),
        uploads=self.uploads,           # shared reference
    )
```

`share_todos=True` on `DeepAgentDeps` makes sub-agents share the parent's todo list (useful for teams). `DynamicAgentRegistry` plus `create_agent_factory_toolset(allowed_models=[…], max_agents=5)` lets the model spawn brand-new specialist agents at runtime.

#### 1.7 Context management

- `ContextManagerCapability` (default `context_manager=True`, `max_tokens=200_000`, `compress_threshold=0.9`) tracks input tokens against the model's context window (auto-detected via `genai-prices`) and triggers `SummarizationProcessor.summarize_messages` at 90 %.
- `LimitWarnerCapability` injects URGENT/CRITICAL `SystemPromptPart` warnings at 70 % so the model can wrap up before forced compression.
- `EvictionCapability` (default 20 K tokens) intercepts large tool outputs *before* they enter history (via `after_tool_execute` hook), saves them to a file in the backend, and replaces the message with a preview + file reference.
- `PatchToolCallsCapability` repairs orphaned tool calls/results in history before each model request — critical when resuming after crashes or rewinds.
- Hard-keep default is `keep=("messages", 0)` from v0.x (Claude-Code-style: only the summary survives compression, maximally compact).

Trigger types: `("tokens", N)`, `("messages", N)`, `("fraction", 0.0–1.0)`. Compression preserves tool-call/tool-result pairing (safe cutoff in `_cutoff.py`).

`on_before_compress(messages_to_discard, cutoff_index)` and `on_after_compress(compressed_messages) -> str | None` callbacks let you persist full history to disk before pruning and inject the returned string back as a `SystemPromptPart` (Claude-Code SessionStart/compact hook pattern). `messages_path` enables continuous append-only persistence to `messages.json`.

#### 1.8 Checkpoint / Rewind / Fork

```python
from pydantic_deep import (
    Checkpoint, CheckpointStore, InMemoryCheckpointStore, FileCheckpointStore,
    CheckpointMiddleware, CheckpointToolset, RewindRequested, fork_from_checkpoint,
)

agent = create_deep_agent(
    include_checkpoints=True,
    checkpoint_store=FileCheckpointStore(directory="./checkpoints"),
    checkpoint_frequency="every_tool",  # or "every_turn", "manual_only"
)

while True:
    try:
        result = await agent.run(user_input, deps=deps, message_history=history)
        history = result.all_messages()
    except RewindRequested as e:
        history = e.messages  # roll back to e.label
```

- **Auto-prune**: keeps the last 20 checkpoints by default.
- **Tools exposed to the model**: `save_checkpoint(label)`, `list_checkpoints()`, `rewind_to(label)` — the *agent itself* can call these autonomously.
- **`fork_from_checkpoint(checkpoint_id)`**: creates a new session ID branching from that point — explore alternative approaches without losing the original.
- **`RewindRequested`**: app-level exception thrown when the rewind tool runs; caller substitutes the rewound history.

#### 1.9 Budget enforcement

`CostTracking` is on by default. The middleware adds a callback that runs *before* every model call, computes cumulative USD via `genai-prices`, and raises `BudgetExceededError` *before* the API request is sent (so a runaway retry loop cannot silently bill thousands of dollars). `on_cost_update` callback fires after every model call with `(prompt_tokens, completion_tokens, total_usd)`.

#### 1.10 Lifecycle hooks (`HooksCapability`)

```python
Hook(event=HookEvent.PRE_TOOL_USE, command="echo $TOOL_NAME >> audit.log")
Hook(event=HookEvent.POST_TOOL_USE, handler=my_python_async_handler)
Hook(event=HookEvent.POST_TOOL_USE_FAILURE, ...)
```

v0.3.3 added 5 capability-lifecycle events (run start/end, capability dispatch, etc.). Exit-code conventions: `0=allow`, `2=deny`. Supports regex matchers, per-hook timeout, background execution, tool-name filtering.

#### 1.11 Hashline editing

To work around the ~30 % failure rate of `str_replace`-style edits on smaller models, `edit_file` shows the model line-numbered + 2-char content hashes:

```
1:a3|function hello() {
2:f1|  return "world";
3:0e|}
```

The model edits by `(line_number, hash)` range instead of reproducing exact strings. Per Vstorm benchmarks across 16 models: +5 to +64 percentage-points improvement vs. `str_replace`. **No equivalent in LangChain Deep Agents.**

#### 1.12 Agent Teams (`include_teams=True`)

- `SharedTodoList` — `asyncio.Lock`-backed task list, agents claim concurrently, dependency blocking.
- `TeamMessageBus` — per-agent message queues for peer-to-peer.
- `AgentTeam` — coordinator with tools `spawn`, `assign`, `broadcast`, `check`, `message`, `wait_all`, `dissolve`.
- **No central orchestrator**: agents claim from the shared queue and message each other directly.

#### 1.13 Other capabilities

- `MemoryCapability` — `read_memory`/`write_memory`/`update_memory` tools backed by `MEMORY.md` per agent (first 200 lines auto-injected into the system prompt). Per-subagent memory; opt out with `extra={"memory": False}`.
- `ContextFilesCapability` — auto-discovers and injects `DEEP.md`, `AGENTS.md`, `CLAUDE.md`, `SOUL.md`, `.cursorrules`, `.github/copilot-instructions.md`, `CONVENTIONS.md`, `CODING_GUIDELINES.md` into the system prompt.
- `SkillsCapability` — loads `SKILL.md` files on demand. Built-ins: code-review, refactor, test-writer, git-workflow. Subprocess-isolated executable skill scripts.
- `LoopDetectionCapability` — detects identical tool calls, A-B-A-B alternations, no-op calls; warns the model or stops the run.

---

### 2. Temporal integration

#### 2.1 What's available today

There is **no** `pydantic_deep.durable_exec.temporal`. Durability comes from PydanticAI's `pydantic_ai.durable_exec.temporal` module (in beta since v0.7, GA-stable in v1.x, requires `pydantic-ai-slim[temporal]`). Because `create_deep_agent()` returns an ordinary `Agent`, you can wrap it directly:

```python
from pydantic_ai.durable_exec.temporal import TemporalAgent, PydanticAIWorkflow, PydanticAIPlugin

deep_agent = create_deep_agent(name="mission_orchestrator", model="anthropic:claude-sonnet-4-6", ...)
temporal_agent = TemporalAgent(deep_agent)
```

#### 2.2 Mapping of agent concepts to Temporal

| pydantic-deep / PydanticAI | Temporal |
|---|---|
| `agent.run(prompt)` (the whole thing) | One **Workflow** invocation that issues many activities (or one Activity inside a larger workflow) |
| Single model request | **Activity** (auto-generated, named `<agent_name>__model_request`) |
| Tool call (`FunctionToolset`, MCP server) | **Activity** (named `<agent_name>__<toolset_id>__<tool_name>`) |
| `output_type` validation | Inside the workflow (deterministic, no I/O) |
| Capabilities (hooks, cost, summarization) | Run inside the workflow (deterministic) |
| `context_manager` summarization (LLM call) | Activity (because it issues a model request) |
| `agent.run` orchestration loop | Workflow code (deterministic asyncio event loop) |

`TemporalAgent` constructor parameters:

- `name` — required for Temporal; activity names are derived from it. **Never change once deployed** — breaks active workflows.
- `activity_config` — base `ActivityConfig` (default `start_to_close_timeout=60s`).
- `model_activity_config` — overrides for model requests.
- `toolset_activity_config: dict[str, ActivityConfig]` — per-toolset overrides (key = toolset `id`).
- `tool_activity_config: dict[str, dict[str, ActivityConfig | False]]` — per-tool overrides; pass `False` to inline a no-I/O tool into the workflow.
- `temporal_run_context_class` — custom subclass to serialize extra `RunContext` fields. By default only `deps`, `run_id`, `metadata`, `retries`, `tool_call_id`, `tool_name`, `tool_call_approved`, `retry`, `max_retries`, `run_step`, `usage`, `partial_output` cross the workflow ↔ activity boundary.

#### 2.3 Required toolset and agent IDs

Every `FunctionToolset`/`MCPServer` used inside a workflow **must have a stable `id`** so Temporal can name the activity. For pydantic-deep this means:

```python
deep_agent = create_deep_agent(
    name="mission_v1",  # REQUIRED
    # toolsets created by pydantic-deep already have stable ids:
    # "todo", "console", "subagent", "skills", "team", "checkpoint"
)
```

For dynamic toolsets via `@agent.toolset` you must set `id=` explicitly. `per_run_step=False` is ignored under Temporal — the toolset is recreated inside each activity.

#### 2.4 Determinism & non-async tools

- Workflow code must be deterministic. `pydantic-deep` capabilities themselves are deterministic Python, but two pieces are problematic:
  - The **default sandbox** in Temporal Python re-imports the workflow module per replay; pass `pydantic_ai`, `pydantic_deep`, and `pydantic` as **passthrough modules** (or use `workflow.unsafe.imports_passed_through()`) — they import non-deterministic things during initialization.
  - Tools must be `async def` — sync tools run in threads, which are non-deterministic and only legal inside activities (so set `tool_activity_config[toolset][tool] = ActivityConfig(...)`).
- Disable provider-side retries (`OpenAIProvider(max_retries=0)`); let Temporal's retry policy do retries.
- HTTP request retries on the agent should be turned off.

#### 2.5 Workflow patterns for multi-day missions

Three composable patterns:

##### Pattern A — One workflow, one giant `agent.run()`

Simplest. Suitable when the mission is ≤ a few hours and ≤ ~1 K tool calls.

```python
@workflow.defn
class MissionWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [temporal_agent]

    @workflow.run
    async def run(self, prompt: str) -> Mission:
        return (await temporal_agent.run(prompt)).output
```

Limitations: a single `agent.run` can blow past the 50 MB / 51,200-event limit if it makes thousands of tool calls; Temporal will terminate.

##### Pattern B — Workflow loop with periodic `agent.run` calls

The workflow runs forever, calling `agent.run` once per "tick" (a goal, a user message, a scheduled wakeup). State carried in workflow variables.

```python
@workflow.defn
class LongMissionWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [temporal_agent]

    def __init__(self):
        self.history: list[ModelMessage] = []
        self.pending: asyncio.Queue[Goal] = asyncio.Queue()
        self.completed: list[Goal] = []
        self.budget_used_usd: float = 0.0

    @workflow.run
    async def run(self, mission: MissionSpec) -> None:
        await self.pending.put(mission.initial_goal)
        while True:
            await workflow.wait_condition(lambda: not self.pending.empty())
            goal = self.pending.get_nowait()
            result = await temporal_agent.run(
                goal.prompt,
                message_history=self.history,
                deps=mission.deps,
            )
            self.history = result.all_messages()
            self.completed.append(goal)
            # Continue-as-new every N events to stay under history limits
            if workflow.continue_as_new_suggested():
                workflow.continue_as_new(mission.with_state(self.history, self.completed))

    @workflow.signal
    async def add_goal(self, goal: Goal) -> None:
        await self.pending.put(goal)

    @workflow.signal
    async def human_approval(self, request_id: str, approved: bool) -> None:
        ...

    @workflow.query
    async def status(self) -> MissionStatus:
        return MissionStatus(completed=len(self.completed), budget=self.budget_used_usd)
```

Use `workflow.sleep(timedelta(hours=8))` for scheduled wakeups (Temporal durable timer; survives worker restarts; consumes only 2 events).

##### Pattern C — Each task as its own child workflow

For very large fan-outs: parent workflow creates a plan via one `agent.run`, then `start_child_workflow` per top-level todo. Each child has its own 50 MB budget. Combine with `pydantic-ai-todo` PostgreSQL storage so the plan is queryable from outside.

#### 2.6 Continue-as-new triggers

| Signal | Action |
|---|---|
| `workflow.continue_as_new_suggested()` returns `True` | Pre-emptive checkpoint to avoid 50 MB / 51,200-event termination. |
| Event count > ~10 K (warning threshold) | Same. |
| Worker version upgrade | External supervisor signals workflow to `continue_as_new`. |
| Context-manager triggered compression | Optionally call `continue_as_new` after compression so the new run starts with the compressed history (smaller event log). |

State to pass to `continue_as_new`: `(message_history_after_compression, todos_snapshot, completed_goals, budget_used)`. **Do not** pass the entire raw history; compress it first, persist the rest to PostgreSQL or files.

#### 2.7 Heartbeats and timeouts

- Default `start_to_close_timeout=60s` is too short for slow models. Override per-toolset:

```python
TemporalAgent(
    deep_agent,
    model_activity_config=ActivityConfig(
        start_to_close_timeout=timedelta(minutes=10),
        heartbeat_timeout=timedelta(minutes=2),
        retry_policy=RetryPolicy(maximum_attempts=5,
                                 non_retryable_error_types=["BudgetExceededError"]),
    ),
    tool_activity_config={
        "console": {
            "execute": ActivityConfig(start_to_close_timeout=timedelta(hours=1),
                                      heartbeat_timeout=timedelta(minutes=1)),
            "read_file": False,  # inline (no I/O after backend caches)
        },
    },
)
```

- For long-running shell `execute` activities, the activity body should call `temporalio.activity.heartbeat(progress_payload)` periodically. This:
  1. Prevents the heartbeat-timeout firing.
  2. Makes the activity cancellable.
  3. Persists progress (`activity.info().heartbeat_details`) for retries.
- pydantic-deep does **not** automatically heartbeat tool execution — you must wrap the tool yourself if it runs longer than the heartbeat timeout.

#### 2.8 Signals & queries for human-in-the-loop

Map pydantic-ai's `DeferredToolRequests` to Temporal signals:

```python
@workflow.signal
async def approve_tool_call(self, request_id: str, decision: bool) -> None:
    self._approvals[request_id] = decision

@workflow.query
async def pending_approvals(self) -> list[ToolCallRequest]:
    return list(self._pending_approvals.values())
```

When the agent emits `DeferredToolRequests`, the workflow sets workflow state, awaits `workflow.wait_condition(...)`, then resumes the agent with `DeferredToolResults` in the next `temporal_agent.run`. Workflows can sleep for hours/days waiting for the signal — Temporal preserves all state.

#### 2.9 Streaming under Temporal

`agent.run_stream` is **not** available inside a workflow. Instead set an `event_stream_handler` on the agent or `TemporalAgent`. The handler runs **inside the activity** (separate process from the workflow), so:

- Pass data into the handler via the `deps` dataclass.
- Pass data out via an external bus (Redis, Kafka, Postgres NOTIFY).
- Workflow reads from the same bus through another activity, or via signals from a frontend.

---

### 3. State management for multi-day missions

#### 3.1 What survives where

| Layer | Lifetime | What lives here |
|---|---|---|
| Temporal Event History | Until workflow closes (or `continue_as_new`) | `message_history`, `todos` snapshot, `completed_goals`, `budget_used`, signals received. **Hard cap: 50 MB / 51,200 events.** |
| Workflow variables (`self.x`) | Same as Event History | Pending queue, in-flight approvals, intermediate plan. |
| Activity outputs / inputs | Per request | 2 MB hard cap. Use `external_storage` `StorageDriver` for >2 MB tool outputs. |
| PostgreSQL (`pydantic-ai-todo`) | Forever | Task graph, dependencies, status, subtask tree. Multi-tenant by `session_id`. |
| Filesystem (`LocalBackend`/`DockerSandbox`) | Forever (volume-mount) | Files written/edited by agent, `MEMORY.md`. |
| `FileCheckpointStore` | Forever (configurable pruning, default 20) | Conversation snapshots for `rewind_to`/`fork_from_checkpoint`. |
| External storage (S3/etc.) | Forever | Large tool outputs evicted by `EvictionCapability`. |

#### 3.2 PostgreSQL pattern (recommended)

```python
storage = create_storage(
    "postgres",
    connection_string="postgresql://...",
    session_id=mission_id,        # one row-set per mission
)
await storage.initialize()        # idempotent migration
todo_toolset = create_todo_toolset(async_storage=storage, enable_subtasks=True)
```

Schema (simplified): `todos(id, session_id, parent_id, content, status, depends_on[], active_form, created_at, updated_at)`. Cycle detection runs in-memory before INSERT/UPDATE.

Workflow consumption: read todo list inside the workflow via a *query-only* activity (`get_todo_system_prompt_async`) → inject into the system prompt.

#### 3.3 Checkpoint pruning

Default keeps 20 most recent (FIFO eviction). For multi-day missions, increase or implement a custom `CheckpointStore` over PostgreSQL/S3 with retention rules per:

- Time (keep last 24 h every-tool + last 30 d every-turn).
- Label (keep manually-labeled checkpoints forever).
- Cost (keep checkpoints before any single tool call costing >$1).

`Checkpoint` is a Pydantic model — serializable to JSON, postgres `JSONB`, or S3.

#### 3.4 Context-window strategy decision tree

| Mission shape | Recommendation |
|---|---|
| Long but bounded (≤ a few days, single goal) | `context_manager=True`, `max_tokens=~80% of context_window`, `compress_threshold=0.9`, eviction at 20 K. |
| Indefinite (entity workflow, week+) | Sliding window every-N-messages + pre-`continue_as_new` summarization + persistent `MEMORY.md` + Postgres todo store. **Do not** rely solely on summarization — on `continue_as_new` the new run starts clean unless you pass the compressed history through. |
| Heavy tool output (search, big files) | Aggressive `EvictionCapability(threshold=5_000)`; `external_storage` payload codec on Temporal Client; tool outputs returned as `s3://` references the model can re-fetch on demand. |
| Reasoning chains > 200 K tokens | Hierarchical summarization by sub-agent: each sub-agent has its own context, returns a compact summary; parent stays small. |

---

### 4. Planning and task decomposition

#### 4.1 The `read_todos`/`write_todos` pattern

The model is given an explicit todo tool. The system prompt (auto-injected by `get_todo_system_prompt_async`) instructs:

> *"Before starting, write a todo list. Mark exactly one task `in_progress` at a time. Mark `completed` only when verified."*

Empirically (Vstorm production data) this reduces hallucinated steps and skipped work. `write_todos([Todo(...), Todo(...)])` replaces the entire list (idempotent for replay).

Hierarchy: subtasks via `add_subtask(parent_id, content)`; dependencies via `set_dependency(task_id, depends_on_id)`. `get_available_tasks()` returns tasks with all deps in `completed` state (the model's "what to do next" query).

Cycle detection (DFS):

```python
def _has_cycle(todo_id, dependency_id, todos):
    visited = set()
    def visit(current_id):
        if current_id == todo_id:    return True
        if current_id in visited:    return False
        visited.add(current_id)
        for dep in _get_todo_by_id(current_id).depends_on:
            if visit(dep): return True
        return False
    return visit(dependency_id)
```

#### 4.2 Plan Mode (`include_plan=True`)

Spawns a dedicated planner sub-agent at the start of the run that asks clarifying questions ("ask_user" tool) before any execution. Headless-compatible: in headless runner, plan mode deferred questions are auto-accepted or surfaced via the `--task-file` channel.

#### 4.3 Progress tracking & events

`TodoEventEmitter` fires `on_added`, `on_completed`, `on_failed`, `on_dependency_set`. Connect to a webhook to update an external dashboard. In a Temporal workflow, the emitter handler should `workflow.execute_activity(send_webhook, ...)` rather than firing HTTP from the activity directly.

---

### 5. Production patterns

#### 5.1 Cost / budget

```python
agent = create_deep_agent(
    cost_tracking=True,
    cost_budget_usd=100.0,            # raises BudgetExceededError before next API call
    on_cost_update=lambda info: workflow.execute_activity(
        record_cost, info, start_to_close_timeout=timedelta(seconds=5),
    ),
)
```

In a multi-day workflow, persist `info.total_usd` to a workflow variable; mark `BudgetExceededError` as **non-retryable** in the activity retry policy so it bubbles to the workflow and triggers a `human_approval` signal flow rather than retrying.

#### 5.2 Error recovery

- Temporal handles transient infrastructure errors (network, restarts, OOMs) via replay. Do not catch them.
- Catch `BudgetExceededError`, `RewindRequested`, `UnexpectedModelBehavior`, and tool-domain errors at the workflow level.
- For the model going off the rails: the agent itself can call `rewind_to("last good")` — this raises `RewindRequested`; the workflow swaps `message_history` and re-runs.
- Stuck-loop detection (`LoopDetectionCapability`) auto-stops runs in identical-tool-call A-B-A-B patterns.

#### 5.3 Observability

```python
import logfire
logfire.configure()
logfire.instrument_pydantic_ai()         # emits OTel spans for runs, models, tools
# Temporal also emits OTel spans natively; Logfire ingests both via OTLP
```

`InstrumentationSettings(include_content=False)` strips prompts/outputs from spans for compliance. Spans follow OpenTelemetry GenAI semantic conventions. Logfire-Temporal integration shows replay vs. fresh-execution spans differently (cached activities are visually distinct).

#### 5.4 Security

| Concern | pydantic-deep mechanism |
|---|---|
| Code execution | `DockerSandbox` (default per-user named container, `auto_remove=False` preserves installed packages); `RuntimeConfig(packages=[...])` pre-installs deps. |
| Filesystem traversal | `LocalBackend(allowed_directories=[...])` + permission ruleset. |
| Secret leakage | `pydantic-ai-shields` `SecretRedaction`; built-in detection of `.env`, `credentials`, `*.key`, `*.pem`. |
| Prompt injection | `PromptInjection` content shield; `InputGuard(guard=lambda p: …)` for custom rules. |
| PII | `PiiDetector` shield; `OutputGuard` for outbound. |
| Tool gating | `ToolGuard(blocked=[…], require_approval=[…])`; permission presets `READONLY`/`STRICT`. |
| Supply chain | Bandit in CI on `pydantic_deep/`; signed PyPI publishes via OIDC; 100 % test coverage required. |

For multi-tenant deployments, give each tenant its own `session_id` (`pydantic-ai-todo`), its own `DockerSandbox` (per `SessionManager.get_or_create(user_id)`), and its own checkpoint directory. The agent itself is stateless; only `DeepAgentDeps` carries tenant state.

---

### 6. Code example: long-running mission with Temporal

Complete, runnable skeleton for a week-long codebase-modernization mission.

```python
# mission.py — top-level definitions (must be importable by workflow + worker + client)
from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import logfire
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import (
    PydanticAIPlugin, PydanticAIWorkflow, TemporalAgent,
)
from pydantic_ai_backends import LocalBackend, DEFAULT_RULESET
from pydantic_ai_todo import create_storage, create_todo_toolset
from pydantic_deep import (
    create_deep_agent, DeepAgentDeps, FileCheckpointStore,
    Hook, HookEvent, SubAgentConfig,
)
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker
from temporalio.workflow import ActivityConfig

logfire.configure()
logfire.instrument_pydantic_ai()

# ---------- Domain models (Pydantic, fully serializable across workflow/activity) ----------
class MissionSpec(BaseModel):
    mission_id: str
    repo_url: str
    target_python: str = "3.12"
    workspace_root: str
    postgres_dsn: str
    checkpoint_dir: str
    budget_usd: float = 500.0

class MissionStatus(BaseModel):
    state: str
    todos_total: int
    todos_completed: int
    budget_used_usd: float
    last_activity_iso: str

# ---------- Deps factory (called inside activities; safe to do I/O here) ----------
@dataclass
class MissionDeps(DeepAgentDeps):
    backend: LocalBackend
    todo_storage: Any
    files: dict[str, bytes] = field(default_factory=dict)
    todos: list = field(default_factory=list)
    subagents: dict = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> "MissionDeps":
        return MissionDeps(
            backend=self.backend,
            todo_storage=self.todo_storage,
            files=self.files,
            todos=[],
            subagents={} if max_depth <= 0 else self.subagents.copy(),
        )

async def build_deps(spec: MissionSpec) -> MissionDeps:
    backend = LocalBackend(
        root_dir=spec.workspace_root,
        allowed_directories=[spec.workspace_root],
        enable_execute=True,
        permissions=DEFAULT_RULESET,
    )
    storage = create_storage("postgres",
                             connection_string=spec.postgres_dsn,
                             session_id=spec.mission_id)
    await storage.initialize()
    return MissionDeps(backend=backend, todo_storage=storage)

# ---------- Agent definition (frozen at module import; required by Temporal) ----------
deep_agent: Agent[MissionDeps, str] = create_deep_agent(
    name="modernization_mission_v1",         # REQUIRED for Temporal
    model="anthropic:claude-sonnet-4-6",
    instructions=(
        "You are a senior engineer modernizing a Python codebase. "
        "Plan with todos. Verify with tests. Use sub-agents for parallel investigation. "
        "Save checkpoints before any destructive change."
    ),
    include_todo=True,
    include_filesystem=True,
    include_subagents=True,
    include_skills=True,
    include_memory=True,
    include_plan=True,
    include_checkpoints=True,
    checkpoint_store=FileCheckpointStore(directory="/var/lib/missions/checkpoints"),
    checkpoint_frequency="every_tool",
    context_manager=True,
    context_manager_max_tokens=180_000,
    cost_tracking=True,
    cost_budget_usd=500.0,
    eviction_token_limit=10_000,
    thinking="high",
    subagents=[
        SubAgentConfig(name="researcher",
                       description="Investigates code; never writes files.",
                       instructions="You research only.", preferred_mode="async"),
        SubAgentConfig(name="test-runner",
                       description="Runs the test suite; reports failures.",
                       instructions="Run pytest; never modify code.", preferred_mode="sync"),
    ],
    hooks=[
        Hook(event=HookEvent.PRE_TOOL_USE,
             command="logger -t mission '$TOOL_NAME on $ARGS'"),
    ],
)

temporal_agent = TemporalAgent(
    deep_agent,
    activity_config=ActivityConfig(
        start_to_close_timeout=timedelta(minutes=15),
        heartbeat_timeout=timedelta(minutes=2),
        retry_policy=RetryPolicy(
            maximum_attempts=4,
            non_retryable_error_types=["BudgetExceededError", "PermissionDenied"],
        ),
    ),
    model_activity_config=ActivityConfig(
        start_to_close_timeout=timedelta(minutes=20),  # slow reasoning models
    ),
    tool_activity_config={
        "console": {
            "execute": ActivityConfig(
                start_to_close_timeout=timedelta(hours=2),    # long builds/tests
                heartbeat_timeout=timedelta(minutes=1),
            ),
        },
    },
)

# ---------- Plain activities (the workflow uses these too) ----------
@activity.defn
async def initialize_workspace(spec: MissionSpec) -> None:
    # git clone, create venv, etc.  Real I/O.
    ...

@activity.defn
async def emit_status(mission_id: str, status: MissionStatus) -> None:
    # Push to dashboard, Slack, etc.
    ...

# ---------- The long-running workflow ----------
@workflow.defn
class ModernizationMissionWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [temporal_agent]

    def __init__(self) -> None:
        self.history: list = []
        self.budget_used: float = 0.0
        self.completed_goals: int = 0
        self.pending_goals: asyncio.Queue[str] = asyncio.Queue()
        self.approvals: dict[str, bool] = {}
        self.cancel_requested: bool = False
        self.spec: MissionSpec | None = None

    @workflow.run
    async def run(self, spec: MissionSpec, resume_history: list | None = None) -> str:
        self.spec = spec
        if resume_history is None:
            await workflow.execute_activity(
                initialize_workspace, spec,
                start_to_close_timeout=timedelta(minutes=30),
            )
            await self.pending_goals.put(
                f"Begin modernization of {spec.repo_url} to Python {spec.target_python}. "
                "Start with a planning phase: read the codebase, write todos, identify risks."
            )
        else:
            self.history = resume_history

        while not self.cancel_requested:
            # Wait for next goal (sleep durably for up to 7 days)
            try:
                await workflow.wait_condition(
                    lambda: not self.pending_goals.empty() or self.cancel_requested,
                    timeout=timedelta(days=7),
                )
            except asyncio.TimeoutError:
                # Idle scheduled wakeup
                await self.pending_goals.put("Status check: review progress, continue work.")
                continue

            if self.cancel_requested:
                break

            goal = self.pending_goals.get_nowait()

            # One agent.run = one durable, replayable execution.
            # Inside it: many activities (model + tools).
            try:
                result = await temporal_agent.run(
                    goal,
                    message_history=self.history,
                    deps=workflow.unsafe.imports_passed_through()  # built outside workflow
                                 and await workflow.execute_activity(
                                     build_deps_activity, spec,
                                     start_to_close_timeout=timedelta(seconds=30),
                                 ),
                )
                self.history = result.all_messages()
                self.completed_goals += 1
            except Exception as e:
                # BudgetExceededError, PermissionDenied, etc.
                workflow.logger.error(f"Goal failed: {e}")
                await self.pending_goals.put(
                    f"Recover from error: {e}. Adjust plan and continue."
                )

            # Emit status
            await workflow.execute_activity(
                emit_status, spec.mission_id,
                MissionStatus(
                    state="running",
                    todos_total=0, todos_completed=self.completed_goals,
                    budget_used_usd=self.budget_used,
                    last_activity_iso=workflow.now().isoformat(),
                ),
                start_to_close_timeout=timedelta(seconds=10),
            )

            # Continue-as-new before hitting Temporal limits
            if workflow.continue_as_new_suggested():
                # Compress history first if we want; here we just hand it off
                workflow.continue_as_new(spec, self.history)

        return f"Mission {spec.mission_id} complete: {self.completed_goals} goals."

    # ---------- Signals (human-in-the-loop) ----------
    @workflow.signal
    async def add_goal(self, goal: str) -> None:
        await self.pending_goals.put(goal)

    @workflow.signal
    async def approve(self, request_id: str, decision: bool) -> None:
        self.approvals[request_id] = decision

    @workflow.signal
    async def cancel(self) -> None:
        self.cancel_requested = True

    # ---------- Queries ----------
    @workflow.query
    def status(self) -> MissionStatus:
        return MissionStatus(
            state="running" if not self.cancel_requested else "cancelling",
            todos_total=0,
            todos_completed=self.completed_goals,
            budget_used_usd=self.budget_used,
            last_activity_iso=workflow.now().isoformat(),
        )

    @workflow.query
    def history_size(self) -> int:
        return len(self.history)


@activity.defn
async def build_deps_activity(spec: MissionSpec) -> MissionDeps:
    return await build_deps(spec)

# ---------- Worker / client entry points ----------
async def run_worker() -> None:
    client = await Client.connect("temporal:7233", plugins=[PydanticAIPlugin()])
    worker = Worker(
        client,
        task_queue="missions",
        workflows=[ModernizationMissionWorkflow],
        activities=[initialize_workspace, emit_status, build_deps_activity],
    )
    await worker.run()

async def start_mission(spec: MissionSpec) -> None:
    client = await Client.connect("temporal:7233", plugins=[PydanticAIPlugin()])
    await client.start_workflow(
        ModernizationMissionWorkflow.run,
        spec,
        id=f"mission-{spec.mission_id}",
        task_queue="missions",
    )

if __name__ == "__main__":
    asyncio.run(run_worker())
```

Notes on the example:

- `deep_agent` and `temporal_agent` are module-level globals — required because Temporal worker registration and workflow code both import them.
- `build_deps_activity` does I/O (Postgres connect, filesystem checks); it must be an Activity, not workflow code.
- `workflow.continue_as_new` runs after each goal completes if Temporal suggests — keeps Event History under 50 MB.
- `workflow.wait_condition(timeout=timedelta(days=7))` is a durable timer; Temporal de-schedules the workflow until either a signal arrives or the timer fires.
- All exceptions raised by `BudgetExceededError` and permission errors are non-retryable per the policy — they surface to the workflow for control-flow decisions instead of burning retries.

---

### 7. Limitations and gaps for multi-day autonomous missions

#### 7.1 What pydantic-deep does **not** ship

| Gap | Workaround |
|---|---|
| **No Temporal-aware backend.** `LocalBackend`/`DockerSandbox` operate on disk, but pydantic-deep does not provide a backend that reads/writes through Temporal Activities (so concurrent workflows see consistent state). | Volume-mount the same workspace into all workers; or write a custom `BackendProtocol` that proxies to a database/S3 via activities. |
| **No PostgreSQL `CheckpointStore`.** Only `InMemoryCheckpointStore` and `FileCheckpointStore`. | Implement `CheckpointStore` protocol against your DB. |
| **Sub-agent execution is in-process `asyncio.Task`, not Temporal child workflows.** `task(name, prompt, mode="async")` does **not** create a Temporal child workflow; it runs as part of the parent workflow's activities. A worker crash mid-task-run loses async sub-agent progress unless it has separately checkpointed via the todo system. | Manually spawn `workflow.start_child_workflow(SubAgentWorkflow.run, …)` instead of calling `task()` for tasks that must survive crashes independently. |
| **`SharedTodoList` and `TeamMessageBus` are `asyncio.Lock`/`Queue`-based, in-memory**. They do not span workers/processes. | For multi-worker teams, replace with Postgres `SELECT … FOR UPDATE SKIP LOCKED` task claiming and Redis/Postgres LISTEN/NOTIFY messaging in a custom `TeamCapability` impl. |
| **Checkpoints are opaque blobs**. `rewind_to` swaps the entire `message_history`, not file/sandbox state. If the agent wrote a file and then `rewind_to`, the file is **not** rolled back. | Wrap risky ops in a `git stash`/snapshot via a hook before tool execution; restore on rewind. |
| **No automatic Temporal heartbeating** in tools. Long shell `execute` calls will hit `heartbeat_timeout` and be killed-and-retried. | Wrap `execute` in a custom toolset that calls `temporalio.activity.heartbeat()` on every chunk of stdout. |
| **`continue_as_new` is not automatic across `agent.run` boundaries**. The pydantic-deep ContextManager triggers in-run summarization, but does not signal "now is a good time to continue-as-new" to the Temporal workflow. | Workflow manually calls `workflow.continue_as_new_suggested()` between goals as in the example above. |
| **No native streaming inside Temporal workflows**. `agent.run_stream` is unsupported under `TemporalAgent`. | Use `event_stream_handler` and a side-channel (Redis pub/sub) as documented; OR run UI-facing agent runs *outside* Temporal and only durable-execute the long-running coordination. |
| **2 MB activity payload cap bites pydantic-deep tools**. `read_file` of a large file, `glob` of a big repo, `grep` with thousands of hits — any of these can exceed 2 MB. The pydantic-deep `EvictionCapability` saves to disk *after* the tool returns; the activity itself can still fail. | Configure `external_storage` `StorageDriver` on the Temporal `DataConverter` (e.g. an S3 driver). Or pre-truncate inside the tool. |
| **Determinism risk in capabilities**. `LimitWarnerCapability`'s wall-clock comparison, `LoopDetectionCapability`'s `hashlib.md5` (deterministic), and `MemoryCapability`'s file-mtime read can be non-deterministic on replay if not handled. | Rely on `workflow.now()` rather than `datetime.now()`; ensure `MEMORY.md` reads only happen inside an activity, not in the workflow body. As of v0.3.8, eviction and orphan repair migrated to capabilities hooks (`after_tool_execute`/`before_model_request`) — these run inside model/tool activities, which is correct under Temporal. |
| **No multi-day "supervisor" pattern out of the box**. There is no built-in "wake up every 24 h, check progress, decide whether to continue" loop in pydantic-deep. | Implement at the workflow layer (Pattern B above). |
| **No cross-workflow agent communication**. Agent Teams assume single-process; cross-workflow A2A requires you to use Temporal signals to other workflows manually. | Use `workflow.get_external_workflow_handle_for(...)` + signals; or PydanticAI's A2A capability. |
| **Sub-agent/parent shared backend is not transactional**. Two sub-agents writing the same file race. | Hold a lock per file path in the `DeepAgentDeps`; or partition workspace by sub-agent. |
| **No built-in evals on long-running missions**. `pydantic-evals` exists but is geared to single-run scoring. | Run periodic eval workflows that read the mission's todo state and grade progress. |
| **No editor integration for monitoring** (vs. LangChain Deep Agents which has Zed via ACP). pydantic-deep added an ACP adapter in v0.3.3, but it is one-session-at-a-time. | Use Logfire UI + Temporal UI side-by-side. |

#### 7.2 Temporal-side caveats

- Workflow Event History terminates the workflow at **51,200 events / 50 MB**. A 500-tool-call agent run (≈ 3,000 events for tool scheduling + completion) consumes ~6 % of that budget. Plan for `continue_as_new` every ~10–20 K events.
- 2,000 in-flight pending activities/signals/child-workflows per workflow is a hard limit — relevant if you spawn many async sub-agents.
- Workflow Task timeout default 10 s with a 1 s deadlock detector — pydantic-deep capability code that does heavy computation in the workflow body must be moved to activities. The default `create_deep_agent` capabilities are all small-CPU.
- Continue-as-new in the middle of unfinished async sub-agents loses their state — drain or cancel them first.
- Sandbox-imported modules: explicitly pass through `pydantic_ai`, `pydantic_deep`, `pydantic`, `pydantic_ai_backends`, `pydantic_ai_todo`, `subagents_pydantic_ai`, `summarization_pydantic_ai`, `pydantic_ai_shields`, `pydantic_ai_middleware` to avoid expensive re-imports on every replay.

#### 7.3 Production-readiness summary

| Area | Status |
|---|---|
| Single-day autonomous mission | ✅ Ready (out of the box). |
| Multi-day mission with periodic human review | ✅ Ready with Pattern B (workflow loop + signals + Postgres todos). |
| Week+ entity workflow with no human input | ⚠️ Requires custom `continue_as_new` strategy and external state mirror. |
| Multiple agents collaborating across workers | ❌ `AgentTeam`/`SharedTodoList` are in-process only — must rebuild. |
| Cross-region multi-tenant deployment | ⚠️ `SessionManager` per tenant works; full isolation requires per-tenant Temporal namespaces and per-tenant DB schemas. |
| Eval-driven self-correction over days | ❌ No built-in support; build it as a sibling workflow. |

---

## Caveats

- **Versioning**: pydantic-deep moves fast (v0.3.x as of April 2026; "Beta — Development Status 4" on PyPI). API names cited here (`include_*` flags, `CheckpointMiddleware`, capability names) reflect v0.3.x. Some early docs use `pydantic_deep.backends` / `pydantic_deep.processors`; current code re-exports from `pydantic_ai_backends` / `summarization_pydantic_ai`. The two GitHub repos `vstorm-co/pydantic-deep` and `vstorm-co/pydantic-deepagents` appear to refer to the same project at different naming periods — the current canonical repo is `vstorm-co/pydantic-deepagents`, with the package name `pydantic-deep` on PyPI.
- **PydanticAI Temporal beta status**: native Temporal integration arrived in PydanticAI v0.7 (beta) and matured through 1.x. Some claims in this report (like exact activity-naming format) may evolve; consult `ai.pydantic.dev/durable_execution/temporal/` before production deployment.
- **No publicly-documented "pydantic-deep × Temporal" reference application** exists at the time of writing. The integration patterns in this report compose two production-grade pieces (pydantic-deep, PydanticAI's `TemporalAgent`) but the combination is "supported by virtue of `create_deep_agent` returning a standard Agent," not a tested end-to-end product. The closest public examples are `pydantic/pydantic-ai-temporal-example` (Slack dinner bot) and `simoncalabrese94/temporal.pydanticai.codeact` (Docker code execution), neither of which uses pydantic-deep.
- **Cost-and-budget assertion** that `BudgetExceededError` raises *before* the API call is documented in Vstorm's own comparison post and `pydantic-ai-shields` README. Network round-trip considerations may still leak a small request through if a request is in flight when the budget is exceeded.
- **Hashline edit success metrics** (+5 to +64 pp vs. `str_replace`) are Vstorm in-house benchmarks across 16 models. They cite Can Boluk's hashline research as the origin but provide no published reproducible benchmark.
- **Determinism of `LimitWarnerCapability` and similar capabilities under Temporal replay** is asserted in pydantic-deep release notes (v0.3.8 migration to capabilities hooks) but has not been independently audited. Treat with scrutiny when running mission-critical workflows; add Temporal replay tests.
- **The `pydantic-ai` package version requirements** floor at `pydantic-ai>=1.71.0` for current pydantic-deep; the Temporal extras are gated behind `pydantic-ai-slim[temporal]`. Ensure both extras and version pins line up.
- All Temporal limit numbers (50 MB / 51,200 events / 2 MB payload / 4 MB transaction / 2,000 pending) are Temporal Cloud defaults as of 2026; self-hosted defaults are similar but configurable via dynamic config.
