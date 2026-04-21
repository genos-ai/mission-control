# Mission Control

*An autonomous agent platform for executing complex, multi-day goals.*

---

## What It Is

Mission Control is a platform where a human describes an ambitious goal, walks away, and returns to trustworthy output. The platform decomposes the goal into tasks, dispatches specialist AI agents, verifies their work, and iterates — advancing through waves of execution until the objective is met or human attention is needed.

It is not a chatbot. It is not a single-agent wrapper. It is an orchestration platform that coordinates teams of agents across hours, days, or weeks of autonomous work.

---

## How It Works

```
Human describes a goal
  → Director understands intent, delegates to Planning Agent
    → Planning Agent decomposes into a task DAG (dependencies, agents, verification)
      → Dispatcher executes tasks in topological waves (parallel within each wave)
        → Each task: agent runs → 3-tier verification → retry with feedback if needed
          → Supervisor evaluates the wave outcome
            → Advance (approve next wave or refine the plan)
            → Propose complete (notify human, stay ready for more)
            → Escalate (pause, explain what went wrong)
```

The human re-enters the loop only when the supervisor escalates or the mission is done. Everything else runs autonomously.

---

## Key Concepts

**Mission** — The domain primitive. A long-lived container that holds the goal, team, plan, context, history, artifacts, and costs. Missions persist for days, weeks, or months.

**Plan** — A DAG of tasks with dependencies, agent assignments, and verification specs. Created by the Planning Agent, stored in the database, executed wave by wave. Tasks can be added manually or through refinement.

**Task** — A single unit of work assigned to one agent. Has instructions, inputs (static or from upstream tasks), verification criteria, and produces an output that downstream tasks can consume.

**Wave** — A set of tasks with no dependencies between them, executed in parallel. The dispatcher sorts the DAG topologically and executes one wave at a time.

**Agent** — A specialist AI (PydanticAI) with a system prompt, tools, typed interface, and YAML config. Agents are black boxes — the platform dispatches to them and verifies their output without knowing their internals. Adding an agent is a YAML file and a Python module.

**Supervisor** — The post-wave evaluator. Rules-first (7 of 8 branches are deterministic Python), Haiku fallback for ambiguous cases. Decides whether to advance, refine, or escalate. Circuit breakers prevent runaway loops (budget, iteration cap, stall detection).

**Director** — The human-facing conversational agent. Manages the mission on the user's behalf — creates plans, approves tasks, reports outcomes. The user's delegate, not a dispatcher.

**Gate Mode** — Controls how much autonomy the platform has:
- `interactive` — human approves every task
- `ai_assisted` — Director can auto-approve, human can veto
- `autonomous` — full autonomy, supervisor drives the loop
- `off` — same as autonomous, no gate reviews during dispatch

**MCD (Mission Context Document)** — A living knowledge brief maintained per mission. Updated after each task with structured patches from agent outputs. Loaded into every agent's context window so accumulated knowledge carries forward.

**Verification** — 3-tier quality pipeline applied to every task output:
- Tier 1: structural (schema validation, required fields)
- Tier 2: deterministic (registered check functions)
- Tier 3: AI evaluation (independent agent judges quality — no self-evaluation)

---

## Architecture

Three layers with clear boundaries:

```
┌─────────────────────────────────────────────────┐
│  Mission                                        │
│  The domain primitive. Owns the goal, team,     │
│  plan, context, history, and budget.            │
├─────────────────────────────────────────────────┤
│  Mission Control                                │
│  Orchestration infrastructure. Routes, tracks,  │
│  enforces budgets, streams events. No reasoning │
│  — delegates planning to the Planning Agent,    │
│  evaluation to the Verification Agent.          │
├─────────────────────────────────────────────────┤
│  Agents                                         │
│  Specialist AI that executes tasks. Black boxes │
│  with typed interfaces. Swappable, verifiable,  │
│  cost-tracked.                                  │
└─────────────────────────────────────────────────┘
```

**Execution path:** Temporal workflows own all autonomous dispatch. One path — no fallback mechanisms, no dual execution loops. Durable, crash-recoverable, replayable.

**Event system:** All events persist by default (blacklist for noise, not whitelist for inclusion). Redis pub/sub for live streaming, PostgreSQL `mission_events` table for history. Console and narrative views read from the same source.

**Cost tracking:** Every LLM call recorded in `llm_calls` with agent attribution and mission scoping. Budget enforcement at plan level. Cost dashboard with per-agent breakdown.

---

## Principles That Shape the Design

**Single paths.** One way to dispatch. One way to persist. One way to evaluate. Two paths to the same outcome is a maintenance burden and a source of bugs.

**Infrastructure before agents.** The platform (sessions, events, dispatch, verification, cost tracking) is built first. Adding an agent is a config file and a module — no framework changes.

**Deterministic over non-deterministic.** If a rule can make the decision, don't call an LLM. The supervisor's 8-branch decision matrix has 7 deterministic branches. Haiku handles only the ambiguous 8th.

**Plan revision over replanning.** When a task fails, modify the remaining plan. Don't throw away completed work. Task IDs are preserved across refinements so approvals and execution history survive.

**No agent self-evaluation.** The agent that produces output never judges its own quality. Verification is always external — a different agent, a deterministic check, or a human.

**The user decides when they're done.** The supervisor proposes completion but never marks the mission complete. The plan stays active with zero approved tasks — idle, not locked. The user archives when ready.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Python 3.12+, SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16+ (pgvector for embeddings) |
| Cache / Events | Redis 7+ (pub/sub for SSE, caching) |
| Durable Execution | Temporal.io (workflows, activities, schedules) |
| Agent Framework | PydanticAI (structured output, streaming, tools) |
| Frontend | React 18, Vite, Tailwind, TanStack Query |
| CLI | Click (mc.py for users, admin.py for ops) |

---

## Current State

The platform is in active development. What works today:

- Multi-wave autonomous execution with supervisor loop
- Parallel task dispatch within waves, cross-wave result flow
- 12 specialist agents (Director, Planning, Verification, Summarization, Quality, Architecture, Health, Supervisor, Synthesis, Knowledge Officer, Workflow Architect, Platform Director)
- Full cost tracking with per-agent attribution
- Plan management with manual task addition, approval, and retry
- Event persistence and Console timeline
- Safety controls: budget guards, iteration caps, status re-checks, emergency stop
- CLI (`mc.py`) and web UI for mission management
- Temporal-backed durable execution with crash recovery

What's next: rich workflow model (Plan 45), deterministic workflow nodes, long-running endurance testing (Plan 46 Phase 6).
