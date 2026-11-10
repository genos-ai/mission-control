# AGENTS.md — AI Assistant Instructions

# Decisions and questions
Ask me questions or decisions one by one, with a short description and a reccomendation

# NO HACKS, NO WORKAROUNDS

Read `.codemap/map.md` for a structural overview of the codebase ranked by importance. Machine-readable version in `.codemap/map.json`.

This file tells AI coding assistants how to work with this codebase.
For full details, see `docs/10-reference-architecture/`.

## Design Principles

- **AI-first, not human-first.** Agents are the primary consumers of this platform. Humans participate; agents drive.
- **Tier 4 is the target.** Every decision must support long-running autonomous tasks (hours/days/weeks). No shortcuts that need retrofitting.
- **The mission is the domain primitive. The session is the transport primitive.** Missions outlive any session, run, or execution — they carry the brief, team, workflows, and accumulated context over months or years. Sessions outlive any request, connection, or server restart — they carry real-time events, multi-channel bindings, and conversation history for a single execution.
- **Write code that never needs editing.** Black box modules, testable interfaces, replacement readiness.

## Platform Overview

AI-first autonomous agent platform. FastAPI backend, PydanticAI agents, PostgreSQL, Redis, FastStream, Temporal.

## Critical Rules

- **Clients must be as thin as possible.** All business logic lives in `modules/backend/services/`. Client modules (CLI, Telegram, frontend, TUI) are thin presentation/dispatch layers only — they parse input, call backend services, and render output. They never import repositories, run queries, compute business rules, or implement validation. If two clients need the same logic, it belongs in a shared backend service.
- **No skipping layers.** API endpoints call services. Services call repositories. Never import repositories or models directly in API endpoints or client code. Each layer only calls the layer directly below it.
- **No hardcoded values.** All configuration from `config/settings/*.yaml`. All secrets from `config/.env`. No hardcoded fallbacks in code, ever.
- **Absolute imports only.** Always `from modules.backend.core.config import ...`. Never relative imports.
- **Centralized logging only.** Always `from modules.backend.core.logging import get_logger`. Never `import logging` directly.
- **Timezone-aware UTC datetimes.** Use `from modules.backend.core.utils import utc_now`. All datetimes carry `tzinfo=timezone.utc`. All DB columns are `DateTime(timezone=True)` (timestamptz). Never `datetime.utcnow()` (deprecated) or `datetime.now()` (local time).
- **`.project_root` marker** determines the project root. Use `find_project_root()` from `modules.backend.core.config`.
- **Every root entry file exposes a `tree` subcommand (P18, rule 010.1).** To discover what a CLI does, run `python <entry>.py tree` — never hand-maintain a list of entry files. Discover them dynamically with `for f in $(find . -maxdepth 1 -name '*.py' -type f); do grep -q '__name__ == "__main__"' "$f" && echo "$f"; done` and run `tree` on each. The output enumerates every subcommand and flag, suitable for context assembly. New root entry files must add a `tree` subcommand that introspects the actual parser (Click group or argparse subparsers) — never a hand-maintained list. Every Click group shows help when called bare; `--verbose` and `--debug` live on the root group only.
- **CLI display is centralized in `report.py`.** All Rich tables, panels, formatting, and styling use shared primitives from `modules/clients/cli/report.py`. Never create `Console`, `Table`, or `Panel` directly in handlers — use `get_console()` from `report.py`.
- **Files must not exceed 1000 lines.** Target ~400-500 lines. Split into focused submodules if larger.
- **`__init__.py` files must be minimal.** Docstring and necessary exports only. No business logic.
- **Secure by default (P8).** All external interfaces deny access when unconfigured. Empty allowlists = deny all. Missing secrets = startup failure. New channels/features disabled by default.

## Architecture

### Layered Backend (strict — no skipping layers)

```
API Layer (modules/backend/api/)         → HTTP handlers, request/response
Service Layer (modules/backend/services/) → Business logic, orchestration
Repository Layer (modules/backend/repositories/) → Data access, queries
Model Layer (modules/backend/models/)     → SQLAlchemy entities
```

### Configuration

- Secrets (passwords, tokens, keys): `config/.env` via Pydantic Settings
- Application settings: `config/settings/*.yaml` via `get_app_config()`
- Access in code: `from modules.backend.core.config import get_settings, get_app_config`

### Entry Points

- `mc.py` — User-facing CLI (run, chat, design, status, history, team, mission)
- `admin.py` — Admin/ops CLI (server, db, migrate, execution, workflow, catalog, admin)
- `modules/backend/main.py` — FastAPI application (for uvicorn)

### Key Modules

| Module | Purpose |
|--------|---------|
| `modules/backend/core/config.py` | Configuration loading (YAML + .env) |
| `modules/backend/core/logging.py` | Centralized structured logging (structlog → logs/system.jsonl) |
| `modules/backend/core/exceptions.py` | Custom exception hierarchy |
| `modules/backend/core/middleware.py` | Request context (X-Request-ID, X-Frontend-ID → source field) |
| `modules/backend/core/database.py` | Async SQLAlchemy engine and sessions |
| `modules/backend/core/security.py` | JWT, password hashing, API keys |
| `modules/backend/core/utils.py` | Utilities (utc_now) |
| `modules/backend/core/config_schema.py` | Pydantic schemas for YAML config validation |
| `modules/backend/tasks/broker.py` | Taskiq broker (Redis backend) |
| `modules/backend/agents/` | Agent coordinator and vertical agents (PydanticAI) |
| `modules/backend/gateway/` | Channel adapter registry and security (rate limiting, startup checks) |
| `modules/telegram/` | Telegram bot (aiogram v3, webhook mode) |
| `modules/frontend/` | React + Vite + Tailwind |

## Code Patterns

### Error Handling

```python
from modules.backend.core.exceptions import NotFoundError, ValidationError
```

Raise domain exceptions in services. Exception handlers in `core/exception_handlers.py` convert to HTTP responses.

### Logging

```python
from modules.backend.core.logging import get_logger
logger = get_logger(__name__)
logger.info("Operation completed", extra={"task_id": task.id, "duration": elapsed})
```

### Database Sessions

```python
from modules.backend.core.dependencies import DbSession

@router.get("/items")
async def get_items(db: DbSession):
    ...
```

### Background Tasks

```python
from modules.backend.tasks.broker import get_broker
broker = get_broker()
```

## Testing

- `tests/unit/` — fast, mocked, no external dependencies
- `tests/integration/` — real database
- `tests/e2e/` — full stack
- Framework: pytest with pytest-asyncio
- Run: `pytest tests/unit -v`

## Codebase Intelligence Tools

Two scripts in `scripts/` provide structural and quality analysis:

```bash
# Code map — structural overview for LLM context
python scripts/code_map.py --scope modules/ --format markdown --stats

# PQI score — composite 0-100 quality metric across 7 dimensions
python scripts/code_quality.py --scope modules/ tests/

# PQI with actionable recommendations. Bandit, Radon and the code map all run
# by default; opt out with --no-bandit, --no-radon, --no-code-map.
python scripts/code_quality.py --scope modules/ tests/ --recommendations
```

Use these as quick-reference tools when assessing code quality, planning refactors, or understanding module structure. The code map shows symbol importance (PageRank), cross-references, and import graphs. PQI breaks down into: Maintainability, Security, Modularity, Testability, Robustness, Elegance, Reusability.

### Execution Trace — Troubleshooting "why did this fail"

```bash
# Trace the most recent run for a mission
python scripts/trace_execution.py --mission ai-research --last

# Trace a specific execution record (prefix match)
python scripts/trace_execution.py --execution 019dec4d

# Trace a specific Temporal workflow
python scripts/trace_execution.py --workflow mission-run-019dcac7-30e

# Show only errors and state transitions
python scripts/trace_execution.py --mission ai-research --last --filter errors,transitions

# JSON output for piping
python scripts/trace_execution.py --mission ai-research --last --json
```

Produces a single chronological timeline correlating Director tool calls, plan task states, Temporal workflow activities, SSE events, DB writes, LLM calls, and structured logs — with an automated diagnosis section that identifies common failure patterns (budget validation failures, stale task states, Director not detecting failures). Use this first when investigating execution failures.

## Agent Catalog

The `agent_catalog` table is the authoritative source for agent configuration at runtime. YAML files are seed-only.

**Read path:** `GET /catalog/agents/{name}` → `AgentCatalogService` → DB. Never read from YAML at runtime.

**Mutating catalog data on a running system:**
```bash
# Correct — updates DB directly
PATCH /admin/catalog/{agent_name}
Body: { "tools": ["tool_a", "tool_b"], "description": "..." }
```

Then run `python admin.py catalog sync-yaml` to write the change back into the matching `config/agents/**/agent.yaml` (`--dry-run` to preview, `--check` exits 1 on drift). Do not hand-edit the YAML to match.

**`seed-catalog --force` is a blunt reset** — it wipes the DB and repopulates from YAML, destroying any changes made via the admin API. Only use it for:
- Initial bootstrap of a new environment
- Deliberately reverting the catalog to YAML defaults

The YAML `tools` list defines everything the agent exposes. For a developer-facing tool, no distinction between "user-facing" and "internal" tools is necessary — list everything the agent can call.

## What NOT to Do

- Do not put business logic in client code (CLI handlers, Telegram handlers, frontend components)
- Do not import repositories or models in API endpoints or client code — go through services
- Do not instantiate `Console()` directly — use `get_console()` from `report.py`
- Do not create helper or wrapper scripts (except in `scripts/`)
- Do not add business logic to `__init__.py` files
- Do not use `os.getenv()` with fallback defaults
- Do not create standalone loggers with `logging.getLogger()`
- Do not use relative imports
- Do not use `datetime.now()` or `datetime.utcnow()`
- Do not hardcode URLs, ports, timeouts, or any configurable value
- Do not skip layers (API calling repository directly)
- Do not run `seed-catalog --force` to update catalog fields on a running system — use `PATCH /admin/catalog/{agent_name}` instead

## Reference Architecture

Full standards in `docs/10-reference-architecture/`:

| Doc | Topic |
|-----|-------|
| **Core (01-16)** | |
| 01 | Core Principles |
| 03 | Backend Architecture |
| 05 | Authentication |
| 06 | Security Standards |
| 08 | Python Coding Standards |
| 09 | Error Codes |
| 10 | Observability |
| 11 | Testing Standards |
| 14 | Background Tasks |
| **Optional Platform (20-28)** | |
| 21 | Event Architecture |
| 24 | LLM Integration |
| 27 | TUI Architecture (Textual + Textual Web) |
| 28 | CLI Architecture (Click groups and subcommands, service lifecycle, testing) |
| **AI-First Platform (40-47)** | |
| 40 | Agentic AI Architecture (conceptual) |
| 41 | Agentic AI PydanticAI Implementation |
| 42 | Agent-First Infrastructure (MCP, A2A, agent identity) |
| 43 | AI-First Interface Design (adapter registry, self-describing APIs, service factory) |
| 44 | Multi-Channel Gateway (channel adapters, sessions, WebSocket, security) |
| 46 | Event-Driven Session Architecture (session model, event bus, streaming coordinator, plan management, memory, approval gates, cost tracking) |
| 47 | Agent Module Organization (layout, naming, agent types, shared tools, layered prompts, access control) |
