# Project Principles

Guiding principles for all architectural decisions, plans, and implementation work in this project. These are non-negotiable — every plan and PR should be evaluated against them.

---

## Context

These are **project-specific principles** for the Mission Control agentic platform. They build on top of the **reference architecture core principles** defined in `docs/10-reference-architecture/01-core-principles.md` (P1–P8: Backend Owns Logic, Stateless Clients, Single Source of Truth, Explicit Over Implicit, Fail Fast, Idempotency, No Hardcoded Values, Secure by Default).

The reference architecture principles are universal software engineering rules. The principles below are specific to how *this project* builds its agentic platform — platform structure, agent behavior, and development process.

**Numbering note:** This document uses P1–P14. The reference architecture also uses P1–P8 for different principles. When referencing principles from this document in plans or code, include the name (e.g., "P12: Test Against Real Infrastructure") to avoid ambiguity with reference architecture P-numbers.

---

## Platform Architecture

*How the system is built — structural decisions about infrastructure, coordination, state management, and layering.*

### P1: Infrastructure Before Agents

**Build the platform first. Agents are cheap to add on top of solid infrastructure.**

We invest upfront in sessions, event streaming, mission control, plan management, and verification — so that adding a new agent is a YAML file and a thin Python module, not a refactoring project. The cost of retrofitting infrastructure under existing agents is always higher than building it right once.

This means:
- When choosing between "build an agent now and adapt infrastructure later" vs. "build infrastructure now and agents drop in later" — choose infrastructure.
- A new agent follows the 4-file contract defined in the Agent Blueprint (`docs/02-architecture/003-agent-blueprint.md`): YAML config, system prompt, Python module with `create_agent()` / `run_agent()`, and a roster entry. Nothing else.
- The registry auto-discovers agents. The roster controls dispatch. The verification pipeline, cost tracking, event streaming, and gate reviews apply automatically.

**Test:** Can a developer add a fully functional agent in under an hour without touching mission control, session, or infrastructure code? If not, the platform isn't ready.

---

### P15: The Mission Is the Domain Primitive, the Session Is the Transport Primitive

**Two primitives at different levels. Neither replaces the other.**

The mission is the persistent container that carries the brief, team, workflows, and accumulated context over months or years. It is what users create, name, and reason about. The session is the persistent bidirectional context that carries real-time events, multi-channel bindings, and conversation history for a single execution. It is what the transport layer routes on.

This means:
- Missions outlive any session, run, or execution. They are the organizational boundary.
- Sessions outlive any request, connection, or server restart. They are the communication channel.
- Each workflow run creates a session scoped to that execution, not to the mission.
- Long-term knowledge accumulates on the mission (via MissionContext). Ephemeral state lives on the session.
- Cost budgets exist at both levels: mission-level (total ceiling) and session-level (per-run ceiling).

**Test:** If a mission runs daily for a year, does each run have clean session state while the mission retains accumulated context? If not, the scoping is wrong.

---

### P5: Streaming Is the Default Path

**Every agent interaction produces a typed event stream. Synchronous responses are the degraded case.**

Mission control's `handle()` returns `AsyncIterator[SessionEvent]`. Every channel (API, TUI, Telegram, MCP, A2A) consumes the same event stream. Callers that need a synchronous result call `collect()` which drains the iterator.

This means:
- There is no separate synchronous execution path. One code path, always.
- Events are both yielded to the caller AND published to the session event bus.
- Error handling yields error events instead of throwing — the stream always terminates cleanly.

---

### P6: Mission Control Is Infrastructure, Not Intelligence

**Mission control routes, enforces, tracks, and yields events. It does not reason, plan, or make domain decisions.**

Mission control is a state machine. It applies middleware (cost tracking, guardrails, budget enforcement), routes to agents, and manages the event stream. Domain intelligence belongs in agents. Strategic intelligence belongs in the Planning Agent (which mission control invokes at bounded points). Mission control never calls an LLM directly — it delegates to the Planning Agent for task decomposition and to the Verification Agent for quality evaluation.

This means:
- All agent dispatch goes through mission control, ensuring middleware always applies.
- Adding a new concern (logging, tracing, rate limiting) happens in mission control middleware, not in agent code.
- The Planning Agent reasons about task decomposition — but mission control validates the plan, dispatches agents, and enforces budgets deterministically.
- Mission control is not an astronaut. It does not do the work. It orchestrates, monitors, and makes go/no-go decisions. The agents are the astronauts.

---

### P9: Temporal Owns Orchestration, PostgreSQL Owns Domain

**Never mix durable execution state with business data.**

Temporal manages workflow position, retry counts, signal queues, and durable timers. PostgreSQL manages conversations, plans, decisions, and domain entities. Activities bridge between them by reading/writing PostgreSQL and reporting results to Temporal.

This means:
- No large data in Temporal event history — Activities pass IDs, not objects.
- ORM objects never cross the Temporal boundary — serializable dataclasses (DTOs) do.
- The system works without Temporal (Tiers 1-3). Temporal activates only for Tier 4.

---

### P10: Every Phase Is an Expansion, Not a Rewrite

**New capabilities layer on top of existing ones. Existing patterns remain unchanged.**

Stateless CRUD endpoints continue to work without sessions. Simple agent calls work without plan management. Sessions work without Temporal. Each tier of complexity is opt-in.

This means:
- `GET /api/v1/notes` never creates a session or touches the event bus.
- A one-shot agent call can auto-create an ephemeral session transparently.
- The graduated complexity model: Tier 1 (CRUD) → Tier 2 (stateless agent) → Tier 3 (interactive session) → Tier 4 (long-running autonomous).

---

## Agent Design

*How agents behave — design rules for agent capabilities, tool usage, and failure handling.*

### P2: Deterministic Over Non-Deterministic

**Never use an agent where a tool will do the job faster, cheaper, and better.**

An LLM call is non-deterministic, slow, and expensive. A deterministic tool is predictable, fast, and free. If a task can be solved with a regex, a SQL query, a rule engine, or any deterministic logic — that's a tool, not an agent task. Agents are for reasoning, judgment, and ambiguity. Everything else is a tool.

This means:
- Compliance scanning uses deterministic regex rules (tools), not an LLM reading code and guessing.
- File listing, search, and filtering are tools. An agent decides *what* to search for.
- Routing by keyword match is a tool. An agent handles only the ambiguous cases the rules can't resolve.
- DAG traversal, cycle detection, and ready-task queries are deterministic algorithms, not agent reasoning.
- Cost calculation, budget enforcement, and state machine transitions are pure functions.

**Test:** Before adding an LLM call, ask: "Would a deterministic function produce the same or better result?" If yes, write the function.

---

### P4: Scope Is Configuration, Not Code

**What an agent can do is defined in YAML. How it does it is defined in Python.**

Agent capabilities (tools, filesystem access, delegation targets, model selection, budget) are declared in YAML config and injected via dependency injection. Changing an agent's permissions, model, or tool access is a config change, not a code change.

This means:
- `AgentConfigSchema` validates every agent YAML at load time.
- `FileScope` enforces read/write paths from config, not from hardcoded logic.
- Delegation allowlists, budget caps, and model selection come from YAML.
- Adding an agent to a new project with different permissions = different YAML, same Python.

---

### P7: Separate Implementation from Registration

**Tool implementations are pure functions. Tool registrations are thin wrappers.**

Shared tools (filesystem, compliance scanning, delegation) are implemented as plain Python functions with no PydanticAI dependency. Agent files contain thin `@agent.tool` wrappers that call the shared implementation, passing scope from deps.

This means:
- Tools are testable as plain functions without any agent runtime.
- Multiple agents reuse the same tool implementations with different scopes.
- PydanticAI version changes don't break tool logic.

---

### P13: No Agent Self-Evaluation

**No agent should be judge and jury of its own work.**

The agent that produces output must not be the agent that evaluates it. Self-assessment is unreliable — LLMs are biased toward their own output and will consistently rate it higher than an independent reviewer would. Quality gates, compliance checks, and acceptance criteria are evaluated by a different agent, a deterministic tool, or a human.

This means:
- A coding agent does not review its own code. A QA agent or compliance scanner does.
- A planning agent does not approve its own plan. The PM agent or a human does.
- A summarization agent does not judge summary quality. A validation step (deterministic or separate agent) does.
- Self-correction loops (agent retrying its own failed output) are acceptable for mechanical errors (syntax, format). Judgment calls (quality, correctness, completeness) require an external evaluator.

**Test:** If the same agent produces and approves an artifact, who catches its blind spots?

---

### P17: Tools Over Structured Output for Complex Schemas

**When an LLM must produce a complex data structure, have it build incrementally via tool calls — never ask for a monolithic blob.**

LLMs are good at making sequential tool calls with simple schemas. They are bad at producing perfectly-structured multi-KB JSON blobs in one shot. When the output schema exceeds ~5 `$defs` or ~2 KB, grammar compilers reject it, prompted output is unreliable, and the system ends up with extraction heuristics, normaliser layers, and retry loops to compensate.

The fix is architectural: decompose the output into small tool calls that each have a trivially simple schema, and let the system accumulate the result server-side. The LLM calls `add_task(description, agent)` five times instead of producing a 7.8 KB TaskPlan JSON blob once.

This means:
- Any agent that must produce a complex structured output (plans, security reports, assessments) uses tools to build it incrementally, not `output_type=ComplexModel`.
- Each tool schema is small enough for native constrained decoding (NativeOutput) — no prompted fallbacks.
- Validation errors are returned inline via tool responses. The LLM self-corrects with another tool call instead of a full retry.
- A dynamic system prompt injects the current state of the accumulated structure before each model call, so the LLM always knows what it has built so far.
- The accumulated structure uses the same Pydantic model as the final output — tools build it, they don't replace it.

**Test:** If the agent's output schema has more than 5 `$defs`, is the agent using tools to build it? If it's producing raw JSON, refactor to tools.

---

### P8: Plan Revision Over Replanning

**When a task fails, modify the remaining plan. Don't throw away completed work.**

Failed tasks trigger retry → revision → escalation. Revision means adjusting remaining tasks and dependencies while preserving completed work. Full replanning is a last resort.

This means:
- The plan data model supports mutable task graphs with version tracking.
- Completed tasks and their outputs are immutable after completion.
- Every decision (retry, revise, escalate) is logged in an audit trail with reasoning.

---

## Development Process

*How we work — testing, CI, and development workflow rules.*

### P11: Test Without LLMs

**CI never makes a real LLM call. Tests use deterministic fixtures.**

PydanticAI's `TestModel` and `ALLOW_MODEL_REQUESTS = False` are enforced globally. Agent tests verify tool wiring, schema validation, and control flow — not LLM quality. Integration tests that need realistic responses use recorded fixtures.

This means:
- Tests are fast, deterministic, and free.
- Every agent test uses `TestModel(call_tools=[...])` to simulate specific tool sequences.
- Flaky tests from LLM variability don't exist.

---

### P12: Test Against Real Infrastructure

**Tests run against the live platform. Mock only what you don't operate.**

A test that mocks the database proves your mock works, not your code. Tests connect to real PostgreSQL, real Redis, real FastStream, and real Temporal. Write operations use transaction rollback so tests don't pollute data, but every query, constraint, and subscription exercises the real system.

This means:
- Service tests call real repositories against real PostgreSQL. No mocked sessions, no mocked repos.
- Event bus tests publish and subscribe on real Redis. No `AsyncMock(return_value=1)`.
- Temporal tests use the real Temporal test server, not mocked workflow execution.
- The only mocks are for external services you don't operate: LLM providers (TestModel per P11), Telegram API, third-party webhooks.
- Tests that pass against mocks but fail against real infrastructure are worthless — they hide bugs instead of catching them.

**Test:** If you remove all mocks from a test and it breaks, was it testing your code or testing your mocks?

---

### P14: Modular, Reusable, Elegant, Robust

**Every component should be written once, used everywhere, and easy to understand.**

Code is modular when it does one thing and composes with other modules. It is reusable when a second caller can use it without modification. It is elegant when the implementation is the simplest thing that works. It is robust when edge cases are handled at the boundary, not scattered through callers.

This means:
- Extract shared logic into centralized modules (e.g. display primitives in `report.py`, config loading in `core/config.py`). Callers import and compose — they don't reinvent.
- A function that two handlers need is a shared primitive. A function that one handler needs stays local. Don't pre-extract; extract on second use.
- Prefer keyword arguments and sensible defaults over positional parameters and flag soup. The call site should read like a sentence.
- Handle validation and edge cases at system boundaries (input parsing, config loading, API entry points). Internal functions trust their callers.
- If a module requires a paragraph of explanation to use, simplify the interface. If it requires none, you're done.

**Test:** Can a new developer use the function correctly by reading only its signature and docstring?


---

### P18: Entry Files Are Self-Describing

**Every root-level CLI entry file must expose a `tree` subcommand that lists every command and option it provides.**

Tooling, onboarding scripts, and context-gathering prompts need a single, programmatic way to ask "what does this CLI do?" without parsing free-form help text. `tree` is that contract — it prints the full subcommand and flag hierarchy as a stable, navigable view that survives across refactors.

This means:
- `python <entry>.py tree` succeeds (exit 0) on every entry file in the repo root.
- Output enumerates subcommands and their flags, suitable for piping into context assembly.
- The implementation introspects the actual parser (Click group or argparse subparsers) — it is never a hand-maintained list that can drift from the real command surface.
- Rule 010.1 (`docs/04-rules/010_entry_discoverability.jsonl`) states the rule but **is not machine-checked**. It appears in no pre-commit hook, no CI job, and not in `scripts/code_rules_fast.py`. The contract currently holds by convention: `mc.py`, `admin.py`, `services.py` and `tui.py` all pass `tree` as of 2026-09-08. Verify manually when adding an entry file, or implement the check.

**Test:** Can a new developer (or an LLM context prompt) discover every feature of every CLI by running `tree` on each root entry file? If any entry file fails or omits a feature, the contract is broken.

---

### P16: Idempotency for Expensive Mutations

**Any endpoint that triggers non-trivial work must be safe to retry.**

Network requests time out. Clients retry. Without idempotency, a retry on a timed-out POST that successfully launched an agent execution starts a second execution. Agent runs consume real LLM tokens, write to the database, and are difficult to cancel mid-flight. Duplicate runs are expensive and confusing.

Implementation: clients send `Idempotency-Key: <uuid>` on POST requests. The server caches the response in Redis for 24 hours. Retries with the same key return the cached response immediately.

This means:
- Any endpoint that calls `asyncio.create_task()`, `run_execution()`, or `start_temporal_execution()` must accept and honour an `Idempotency-Key` header.
- The idempotency guard must **fail open** — a Redis outage means the key is not checked, but the endpoint still responds. Never block a request on a cache failure.
- Cheap operations (add team member, update name) don't require idempotency — the cost of a duplicate is low enough that client-side deduplication suffices.
- The pre-commit hook (`code_rules_fast.py` rule 009.1) will block any endpoint that fires background execution without declaring the `idempotency: Idempotency` parameter.

**Test:** Can a client call `POST /executions/{id}/execute` five times with the same `Idempotency-Key` and get exactly one execution run? If not, the implementation is incomplete.

---

## Temporary Principles

*These principles have explicit expiration conditions and will be replaced.*

### P3: Breaking Changes Are Free (During Dev)

**We are in dev mode. We have not shipped to production. We do not carry backward-compatibility debt.**

This means:
- Refactor in-place. No shims, no `_legacy` aliases, no deprecation wrappers.
- Delete what's replaced. Don't comment it out or re-export unused symbols.
- Rename freely when the new name is clearer.
- Tests that break because of interface changes get rewritten, not patched around.

**Expires:** When we ship the first production deployment, this principle is replaced by a versioning and migration strategy.
