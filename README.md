# Mission Control

AI-first autonomous agent platform. FastAPI backend, PydanticAI agents, PostgreSQL, Redis, FastStream, Temporal.

## Architecture

- **Backend**: Python 3.14+ with FastAPI
- **Frontend**: React with Vite, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with SQLAlchemy (async)
- **Cache/Queue**: Redis with Taskiq

See [Architecture Standards](docs/10-reference-architecture/00-overview.md) for complete documentation.

## Project Structure

```
.
├── config/                 # Configuration (secrets in .env, settings in YAML)
│   ├── .env.example       # Environment variables template
│   ├── agents/            # Per-agent YAML (seed data for the agent catalog)
│   ├── prompts/           # Layered system prompts
│   ├── settings/          # YAML application settings
│   └── workflow_templates/
├── docs/                   # Documentation
├── modules/
│   ├── backend/           # FastAPI backend
│   │   ├── agents/        # AI agent system (mission control, planning, QA, health)
│   │   ├── api/           # HTTP endpoints
│   │   ├── core/          # Configuration, logging, protocols
│   │   ├── events/        # Event bus and typed event definitions
│   │   ├── gateway/       # Channel adapter registry and security
│   │   ├── migrations/    # Alembic migrations
│   │   ├── models/        # Database models
│   │   ├── repositories/  # Data access layer
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic (PQI, code map, context assembly)
│   │   ├── tasks/         # Background tasks
│   │   ├── temporal/      # Workflows, activities and worker
│   │   └── tools/         # Shared agent tool implementations
│   ├── clients/           # Thin presentation layers — no business logic
│   │   ├── cli/           # CLI command implementations and report.py primitives
│   │   ├── common/        # Shared client helpers
│   │   ├── service_manager/
│   │   ├── telegram/      # Telegram bot (aiogram v3)
│   │   └── tui/           # Terminal UI (Textual-based)
│   └── frontend/          # React frontend
│       └── src/
├── tests/                  # Test suite (unit, integration, e2e)
├── scripts/                # Utility scripts (code map, PQI, execution trace)
└── var/                    # Runtime data (logs, cache, tmp) — not tracked
```

## Quick Start

### Prerequisites

- Python 3.14+
- Node.js 20+
- PostgreSQL 16+
- Redis 7+
- Temporal CLI (`brew install temporal`) — `services.py` launches the dev server
- Docker — required by the preflight checks and container-backed agents

### Install

Using **uv** (recommended for web apps - see [environment management](docs/10-reference-architecture/12-core-development-workflow.md#python-environment-management)):

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create environment and install
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

# Frontend dependencies
(cd modules/frontend && npm install)

# Configure environment
cp config/.env.example config/.env
# Edit config/.env with your settings
```

### Start everything

`services.py` is the canonical dev launcher. One command runs preflight checks
(PostgreSQL, Redis, Docker, ports), applies Alembic migrations, seeds dev users
and the agent catalog, and starts the Temporal dev server, the backend, the
Temporal worker, and the frontend:

```bash
python services.py start

# Related:
python services.py check    # preflight checks only
python services.py status   # what's running
python services.py stop     # stop services
```

### First mission (prove the install works)

```bash
# Log in with a seeded dev user (admin@missioncontrol.dev, password: DEV_ADMIN_PASSWORD in config/.env).
# Dev users have well-known passwords, so they are only created when the environment
# (config/settings/application.yaml) is development or test; elsewhere seeding is refused.
python mc.py login --email admin@missioncontrol.dev

# Create a mission (becomes the active mission)
python mc.py mission create --name "First mission" --description "Smoke test"

# Run an objective against it
python mc.py run --objective "run a system health check" --budget 1.00
```

See [USAGE.md](USAGE.md) for the full CLI reference (`python mc.py tree` and
`python admin.py tree` list every command).

**Production / non-dev setups:** skip dev seeding and create the first admin
explicitly with `python admin.py admin bootstrap-user --email you@example.com --name "You"`.

### Manual startup (advanced)

Running the backend directly skips migrations, seeding, Temporal, and the worker
— missions will not execute until those are provided some other way:

```bash
uvicorn modules.backend.main:app --reload --port 8000
```

### Access Points

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| Temporal UI | http://localhost:8233 |

## Development

### Code Quality

```bash
# Format
black modules/backend tests
isort modules/backend tests

# Lint
flake8 modules/backend tests

# Type check
mypy modules/backend
```

### Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=modules/backend

# Specific markers
pytest -m unit
pytest -m integration
```

## Architecture Standards

This project follows documented architecture standards:

- [Core Principles](docs/10-reference-architecture/01-core-principles.md)
- [Backend Architecture](docs/10-reference-architecture/03-core-backend-architecture.md)
- [Python Coding Standards](docs/10-reference-architecture/08-core-python-coding-standards.md)
- [Frontend Architecture](docs/10-reference-architecture/22-opt-frontend-architecture.md)
- [TypeScript Standards](docs/10-reference-architecture/23-opt-typescript-coding-standards.md)

## License

[Add license here]
