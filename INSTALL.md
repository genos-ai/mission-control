# Installing and Running Mission Control

For the CLI reference, see [USAGE.md](USAGE.md). For what the platform is, see [README.md](README.md).

## 1.0 Prerequisites

- Python 3.14+
- Node.js 20+
- PostgreSQL 16+
- Redis 7+
- Temporal CLI (`brew install temporal`); `services.py` launches the dev server
- Docker, required by the preflight checks and container-backed agents

## 2.0 Install

Using **uv** (see [environment management](docs/10-reference-architecture/12-core-development-workflow.md#python-environment-management)):

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

## 3.0 Start everything

`services.py` is the canonical dev launcher. One command runs preflight checks (PostgreSQL, Redis, Docker, ports), applies Alembic migrations, seeds dev users and the agent catalogue, and starts the Temporal dev server, the backend, the Temporal worker and the frontend:

```bash
python services.py start

# Related:
python services.py check    # preflight checks only
python services.py status   # what's running
python services.py stop     # stop services

# Act on individual services (api, worker, frontend, temporal):
python services.py restart api worker   # restart only the API and the worker
python services.py restart worker       # e.g. after editing a workflow or activity
python services.py stop frontend
```

Named services run detached and skip preflight, migrations and seeding. They are refused when the stack was started in a foreground terminal (no `--daemon`), because that session shuts everything down as soon as one service exits; in that case the API already reloads on code changes. Run `python services.py tree` for every command and flag.

## 4.0 First mission

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

`python mc.py tree` and `python admin.py tree` list every command.

**Production or non-dev setups:** skip dev seeding and create the first admin explicitly with `python admin.py admin bootstrap-user --email you@example.com --name "You"`.

## 5.0 Manual startup (advanced)

Running the backend directly skips migrations, seeding, Temporal and the worker, so missions will not execute until those are provided some other way:

```bash
uvicorn modules.backend.main:app --reload --port 8000
```

## 6.0 Access points

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| Temporal UI | http://localhost:8233 |

## 7.0 Repository layout

```
.
├── config/                 # Secrets in .env, settings in YAML
│   ├── agents/            # Per-agent YAML (seed data for the agent catalogue)
│   ├── prompts/           # Layered system prompts
│   ├── settings/          # YAML application settings
│   └── workflow_templates/
├── docs/                   # Vision, ADRs, plans, research, reference architecture
├── modules/
│   ├── backend/
│   │   ├── agents/        # Mission control, planning, research, security, quality
│   │   ├── api/           # HTTP endpoints
│   │   ├── core/          # Configuration, logging, protocols
│   │   ├── events/        # Event bus and typed events
│   │   ├── gateway/       # Channel adapter registry and security
│   │   ├── migrations/    # Alembic migrations
│   │   ├── models/        # Database models
│   │   ├── repositories/  # Data access layer
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   ├── tasks/         # Background tasks
│   │   ├── temporal/      # Workflows, activities and worker
│   │   └── tools/         # Shared agent tools
│   ├── clients/           # Thin presentation layers
│   │   ├── cli/  common/  service_manager/  telegram/  tui/
│   └── frontend/          # React web app
├── tests/                  # unit, integration, e2e
├── scripts/                # Code map, PQI, execution trace, rule checks
└── var/                    # Runtime data (untracked)
```

## 8.0 Development

```bash
# Format, lint, type check
black modules/backend tests
isort modules/backend tests
flake8 modules/backend tests
mypy modules/backend

# Tests
pytest                      # all
pytest --cov=modules/backend
pytest -m unit
pytest -m integration

# Platform rules and quality score
python scripts/code_rules.py
python scripts/code_quality.py --scope modules/ tests/ --recommendations
```

## 9.0 Technology stack

- **Backend**: Python 3.14+, FastAPI, PydanticAI agents
- **Orchestration**: Temporal (workflows), FastStream and Taskiq on Redis (events, background tasks)
- **Data**: PostgreSQL with async SQLAlchemy and Alembic
- **Frontend**: React, Vite, TypeScript, Tailwind CSS

Full standards: [docs/10-reference-architecture/](docs/10-reference-architecture/00-overview.md).
