# Architecture

## Overview

This project follows a Backend-for-Frontend (BFF) pattern with a Python backend and React frontend.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                         │
│                     modules/frontend/                            │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ HTTP/REST
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BFF Layer (FastAPI)                         │
│                     modules/backend/                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  API Layer  │──│  Services   │──│     Repositories        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│      PostgreSQL         │       │         Redis           │
│    (Primary Store)      │       │   (Cache/Tasks/Queue)   │
└─────────────────────────┘       └─────────────────────────┘
```

## Backend Layers

| Layer | Responsibility | Location |
|-------|----------------|----------|
| API | HTTP handlers, request/response | `modules/backend/api/` |
| Services | Business logic, orchestration | `modules/backend/services/` |
| Repositories | Data access, queries | `modules/backend/repositories/` |
| Models | Database entities | `modules/backend/models/` |
| Schemas | Pydantic models | `modules/backend/schemas/` |

## Documents in this directory

| Doc | Topic |
|-----|-------|
| [001-project-context-layer.md](001-project-context-layer.md) | Project Context Layer — context assembly and the Mission Context Document |
| [002-codebase-intelligence.md](002-codebase-intelligence.md) | Code Map, Exemplar Registry, Task File Manifest. Partially superseded by ADR-005 |
| [003-agent-blueprint.md](003-agent-blueprint.md) | The 4-file contract for adding an agent. Start here to build one (P1) |
| [004-adr-unified-async-architecture.md](004-adr-unified-async-architecture.md) | **ADR-004** — three-layer execution model, and the in-process chat path |
| [005-adr-mission-primitive-no-projects-playbooks.md](005-adr-mission-primitive-no-projects-playbooks.md) | **ADR-005** — mission as sole domain primitive; Projects and Playbooks removed |
| [006-provider-capability-layer.md](006-provider-capability-layer.md) | Provider capability layer — model selection and provider abstraction |
| [007-api-reference.md](007-api-reference.md) | API reference |
| [008-copilot-sdk-integration.md](008-copilot-sdk-integration.md) | GitHub Copilot SDK integration, including tool-based structured output |

Read the two ADRs first if you are new: they explain why the current model looks
the way it does, and ADR-005 in particular supersedes parts of older documents.

## Key Principles

The five rules below are the local summary. The authoritative sets are the
project principles (P1–P18) in
[../03-principles/01-project-principles.md](../03-principles/01-project-principles.md)
and the universal core principles (P1–P8) in
[../10-reference-architecture/01-core-principles.md](../10-reference-architecture/01-core-principles.md).
The two sets number independently, so cite principles by name as well as number.

1. **Backend owns all business logic** - Frontend is presentation only
2. **Layered architecture** - Each layer only calls the layer below
3. **Absolute imports** - No relative imports
4. **No hardcoded values** - All config from YAML/env files
5. **Fail fast** - Missing config fails at startup

## Architecture Standards

See [Architecture Standards](../10-reference-architecture/00-overview.md) for complete documentation.
