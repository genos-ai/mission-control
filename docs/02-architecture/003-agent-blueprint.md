# Agent Blueprint

*Version: 1.0.0*
*Created: 2026-03-20*

---

## Purpose

This document is the step-by-step recipe for building a new Mission Control agent. It defines the file contract, the function signatures, the configuration schema, and the registration flow. Follow it exactly and the agent will be discoverable, routable, dispatchable, and verifiable with zero framework changes.

---

## 1  The Contract

Every agent consists of exactly **4 files** and **1 roster edit**:

| # | File | Purpose |
|---|------|---------|
| 1 | `config/agents/{category}/{name}/agent.yaml` | Identity, model, keywords, tools, scope, budget |
| 2 | `config/prompts/agents/{category}/{name}/system.md` | System prompt (agent-specific layer) |
| 3 | `modules/backend/agents/vertical/{category}/{name}/agent.py` | PydanticAI agent with tools registered |
| 4 | `modules/backend/agents/schemas.py` | Output schema (add Pydantic model to existing file) |
| — | `config/mission_control/rosters/default.yaml` | Roster entry (makes agent dispatchable) |

Horizontal agents use `modules/backend/agents/horizontal/{name}/agent.py` instead.

---

## 2  Naming Convention

Agent names follow `{category}.{name}.agent`:

| Agent type | Name pattern | Module path |
|------------|-------------|-------------|
| Vertical | `security.pentest.agent` | `modules/backend/agents/vertical/security/pentest/agent.py` |
| Vertical | `code.quality.agent` | `modules/backend/agents/vertical/code/quality/agent.py` |
| Horizontal | `horizontal.planning.agent` | `modules/backend/agents/horizontal/planning/agent.py` |

The registry derives the module path automatically from the agent name and type. The convention is enforced — do not deviate.

---

## 3  Step-by-Step

### 3.1  Define the output schema

Add a Pydantic model to `modules/backend/agents/schemas.py`. This is the structured output the agent must produce.

```python
class PentestFinding(BaseModel):
    """A single vulnerability found during penetration testing."""

    vulnerability: str
    severity: str          # critical, high, medium, low, info
    location: str
    evidence: str
    recommendation: str
    cvss_score: float | None = None


class PentestResult(BaseModel):
    """Structured output from the security pentest agent."""

    summary: str
    risk_score: float
    total_findings: int
    critical_count: int
    high_count: int
    findings: list[PentestFinding]
    targets_scanned: list[str]
```

Rules:
- All fields must be typed — no `Any`, no `dict` without structure
- The agent's LLM output is validated against this schema automatically by PydanticAI
- `output_retries=3` in the agent factory gives the LLM 3 attempts to produce valid output

### 3.2  Create tool implementations (if needed)

Tools live in `modules/backend/agents/tools/`. They are **pure async functions** with no PydanticAI dependency. Each accepts explicit parameters and enforces `FileScope` before any file operation.

```python
# modules/backend/agents/tools/security.py
"""
Shared security tool implementations.

Pure async functions — no PydanticAI dependency. Accept explicit
parameters (target, scope, config) and return plain dicts.
"""

from pathlib import Path

from modules.backend.agents.deps.base import FileScope
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


async def check_security_headers(target_url: str) -> dict:
    """Check HTTP security headers for a target URL."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(target_url)

    headers = dict(response.headers)
    missing = []
    for required in [
        "strict-transport-security",
        "x-content-type-options",
        "x-frame-options",
        "content-security-policy",
    ]:
        if required not in headers:
            missing.append(required)

    return {
        "url": target_url,
        "status_code": response.status_code,
        "headers_present": len(headers),
        "missing_security_headers": missing,
    }


async def scan_config_secrets(
    project_root: Path,
    scope: FileScope,
) -> dict:
    """Scan config files for accidentally committed secrets."""
    scope.check_read("config/")
    # ... implementation ...
    return {"findings": [], "files_scanned": 0}
```

Rules:
- Pure functions — no global state, no PydanticAI imports
- Accept `project_root: Path` and `scope: FileScope` for file operations
- Call `scope.check_read()` / `scope.check_write()` before any filesystem access
- Return plain `dict` — the agent module converts to structured output
- Reuse existing tools when possible (`filesystem.read_file`, `filesystem.list_files`)

### 3.3  Create the deps dataclass (if needed)

If the agent needs dependencies beyond `BaseAgentDeps`, create a dataclass in `modules/backend/agents/deps/base.py`:

```python
@dataclass
class SecurityAgentDeps(BaseAgentDeps):
    """Security agent deps — adds target configuration."""

    target_urls: list[str] = field(default_factory=list)
```

Most agents can use `BaseAgentDeps` directly. Only create a subclass if the agent needs additional injected state. Export from `modules/backend/agents/deps/__init__.py`.

The base provides:

| Field | Type | Purpose |
|-------|------|---------|
| `project_root` | `Path` | Absolute path to project root |
| `scope` | `FileScope` | Filesystem access control (read/write paths from YAML) |
| `config` | `AgentConfigSchema \| None` | The agent's YAML config |
| `session_id` | `str \| None` | Set when running within a session |
| `on_event` | `Callable \| None` | Event emitter for streaming |

### 3.4  Create the agent module

The agent module at `modules/backend/agents/vertical/{category}/{name}/agent.py` must export two functions:

#### `create_agent(model) -> Agent[DepsT, OutputT]`

Called once by the registry on first use. Creates the PydanticAI `Agent` instance and registers all tools.

#### `run_agent(message, deps, agent, usage_limits) -> OutputT`

Called by Mission Control on every invocation. Runs the agent and returns the typed output.

Optionally: `run_agent_stream(message, deps, agent, conversation_id, usage_limits)` for SSE streaming.

```python
"""
Security Pentest Agent (security.pentest.agent).

Web application penetration testing: header analysis, configuration
review, common vulnerability checks. Read-only — does not exploit (P13).
"""

from collections.abc import AsyncGenerator

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.models import Model

from modules.backend.agents.deps.base import BaseAgentDeps
from modules.backend.agents.mission_control.helpers import assemble_instructions
from modules.backend.agents.schemas import PentestResult
from modules.backend.agents.tools import filesystem, security
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(model: str | Model) -> Agent[BaseAgentDeps, PentestResult]:
    """Factory: create a pentest agent with security tools registered."""

    instructions = assemble_instructions("security", "pentest")

    agent = Agent(
        model,
        deps_type=BaseAgentDeps,
        output_type=PentestResult,
        instructions=instructions,
        output_retries=3,
    )

    @agent.tool
    async def check_headers(
        ctx: RunContext[BaseAgentDeps],
        target_url: str,
    ) -> dict:
        """Check HTTP security headers for a target URL."""
        return await security.check_security_headers(target_url)

    @agent.tool
    async def read_config_file(
        ctx: RunContext[BaseAgentDeps],
        file_path: str,
    ) -> dict:
        """Read a configuration file within scope."""
        return await filesystem.read_file(
            ctx.deps.project_root, file_path, ctx.deps.scope,
        )

    @agent.tool
    async def scan_secrets(ctx: RunContext[BaseAgentDeps]) -> dict:
        """Scan config files for accidentally committed secrets."""
        return await security.scan_config_secrets(
            ctx.deps.project_root, ctx.deps.scope,
        )

    logger.info("Pentest agent created", extra={"model": str(model)})
    return agent


async def run_agent(
    user_message: str,
    deps: BaseAgentDeps,
    agent: Agent[BaseAgentDeps, PentestResult],
    usage_limits: UsageLimits | None = None,
) -> PentestResult:
    """Standard agent entry point. Called by Mission Control."""

    logger.info("Pentest agent invoked", extra={"message": user_message})
    result = await agent.run(user_message, deps=deps, usage_limits=usage_limits)

    logger.info(
        "Pentest agent completed",
        extra={
            "summary": result.output.summary,
            "total_findings": result.output.total_findings,
            "risk_score": result.output.risk_score,
            "usage": {
                "requests": result.usage().requests,
                "input_tokens": result.usage().input_tokens,
                "output_tokens": result.usage().output_tokens,
            },
        },
    )
    return result.output


async def run_agent_stream(
    user_message: str,
    deps: BaseAgentDeps,
    agent: Agent[BaseAgentDeps, PentestResult],
    conversation_id: str | None = None,
    usage_limits: UsageLimits | None = None,
) -> AsyncGenerator[dict, None]:
    """Standard streaming entry point. Called by Mission Control."""
    result = await run_agent(user_message, deps, agent, usage_limits=usage_limits)
    yield {
        "type": "complete",
        "result": result.model_dump(),
        "conversation_id": conversation_id,
    }
```

Rules:
- `create_agent` is a factory — called once, result cached by the registry
- `run_agent` is the execution entry point — called every invocation
- Tools are registered with `@agent.tool` — the decorator name is what the LLM sees
- Tool functions receive `RunContext[DepsT]` as first arg — access deps via `ctx.deps`
- Tool functions can accept additional typed parameters that the LLM provides
- Log entry and exit with structured extras

### 3.5  Create the YAML config

`config/agents/{category}/{name}/agent.yaml`:

```yaml
# =============================================================================
# Security Pentest Agent Configuration
# =============================================================================
# Available options:
#   agent_name       - Unique agent identifier (string, format: category.name.agent)
#   agent_type       - Agent type (string: vertical | horizontal)
#   description      - Agent description for routing (string)
#   enabled          - Enable/disable without code deployment (boolean)
#   model            - LLM model identifier (string, provider:model format)
#   keywords         - Keywords for rule-based routing (list of strings)
#   tools            - Shared tool names (list of dotted strings, domain.action)
#   max_input_length - Maximum input character count (integer)
#   max_budget_usd   - Maximum cost per invocation in USD (decimal)
#   max_tokens       - Token limit override (integer, default: system limit)
#   max_requests     - Request limit override (integer, default: system limit)
#   execution        - Execution mode (object)
#     mode           - Execution environment (string: local | container)
#   scope            - Filesystem access control (object)
#     read           - Paths the agent can read (list of strings)
#     write          - Paths the agent can write (list of strings)
#   interface        - Typed I/O contract (object, optional)
#     input          - Input fields: field_name → type_name (dict)
#     output         - Output fields: field_name → type_name (dict)
#   version          - Agent version (string, semver, default: 1.0.0)
# =============================================================================

agent_name: security.pentest.agent
agent_type: vertical
description: "Web application penetration testing: headers, config, common vulnerabilities (read-only)"
enabled: true
model: anthropic:claude-sonnet-4-20250514
max_input_length: 2000
max_budget_usd: 1.00

execution:
  mode: local

keywords:
  - pentest
  - penetration test
  - security scan
  - vulnerability
  - owasp
  - security headers
  - web security

tools:
  - security.check_security_headers
  - security.scan_config_secrets
  - filesystem.read_file

scope:
  read:
    - "config/"
    - "modules/"
  write: []
```

The registry auto-discovers this file via `config/agents/**/agent.yaml` globbing. The `AgentConfigSchema` in `config_schema.py` validates it at load time — unknown keys, wrong types, or missing required fields raise immediately.

### 3.6  Create the system prompt

`config/prompts/agents/{category}/{name}/system.md`:

```markdown
## Security Pentest Agent

You are a web application security testing agent. You perform read-only
penetration testing analysis on web applications and report findings
with severity ratings and remediation recommendations.

### Workflow

1. Check HTTP security headers using check_headers
2. Review configuration files for security misconfigurations
3. Scan for accidentally committed secrets or credentials
4. Assess each finding for severity (critical/high/medium/low/info)
5. Produce a structured report with risk score and recommendations

### Output Requirements

- **summary**: One-sentence overall security posture
- **risk_score**: 0.0 (secure) to 10.0 (critical risk)
- **findings**: List of PentestFinding objects, each with vulnerability,
  severity, location, evidence, and recommendation
- **targets_scanned**: List of URLs/paths that were checked

### Rules

- Read-only — never modify files or send destructive requests (P13)
- Report exact evidence for every finding
- Use CVSS scores where applicable
- Do not report false positives — only findings with clear evidence
```

Prompt layering composes the final instructions automatically:

```
config/prompts/organization/*.md          → Organization principles (all agents)
config/prompts/categories/{category}.md   → Category context (e.g., security category)
config/prompts/agents/{cat}/{name}/system.md → Agent-specific (this file)
```

If the category prompt doesn't exist yet (e.g., `config/prompts/categories/security.md`), create it. Missing layers are silently skipped, but a category prompt provides shared context for all agents in that category.

### 3.7  Add to the roster

Add an entry to `config/mission_control/rosters/default.yaml`:

```yaml
  - agent_name: security.pentest.agent
    agent_version: "1.0.0"
    description: >
      Web application penetration testing: HTTP security headers,
      configuration review, secrets scanning, OWASP Top 10 checks.
      Read-only — does not exploit.
    model:
      name: "anthropic:claude-sonnet-4-20250514"
      temperature: 0.0
      max_tokens: 8192
    tools:
      - security.check_security_headers
      - security.scan_config_secrets
      - filesystem.read_file
    interface:
      input:
        target_url: string
        scan_scope: string
      output:
        summary: string
        risk_score: float
        total_findings: integer
        findings: "list[object]"
        targets_scanned: "list[string]"
    constraints:
      timeout_seconds: 300
      cost_ceiling_usd: 2.00
      retry_budget: 1
      parallelism: safe
```

The `interface` block is what the Planning Agent reads to wire inputs and outputs between agents in multi-agent workflows. Declare what the agent expects and what it produces.

### 3.8  Create `__init__.py` files

Create minimal `__init__.py` files for new directories:

```python
# modules/backend/agents/vertical/security/__init__.py
"""Security domain agents."""
```

```python
# modules/backend/agents/vertical/security/pentest/__init__.py
"""Security pentest agent."""
```

---

## 4  Verification Checklist

After creating all files, verify:

```bash
# Agent appears in the registry
python cli.py agent --list

# Keyword routing works
python cli.py agent "run a security scan" --verbose

# Direct targeting works
python cli.py agent "test headers" --name security.pentest.agent --verbose

# Health check still passes
python cli.py health

# All tests pass
python cli.py test unit
```

---

## 5  Architecture Constraints

| Rule | Enforcement |
|------|-------------|
| Agents must not import from other agents | Module boundary — agents are black boxes |
| Tools must not import PydanticAI | Tools are pure functions, agent module does the wiring |
| Filesystem access must go through `FileScope` | `scope.check_read()` / `scope.check_write()` before any file I/O |
| Agents must not hardcode model names | Model comes from YAML config, injected via `create_agent(model)` |
| Agent modules must not call services directly | Use tools as the interface layer |
| Output must be a Pydantic model | Defined in `schemas.py`, set as `output_type` on the Agent |
| All logging via `get_logger(__name__)` | No `import logging` |
| No hardcoded paths, timeouts, or budgets | All from YAML config or roster constraints |

---

## 6  File Inventory

Complete file listing for a new `security.pentest.agent`:

```
config/
├── agents/security/pentest/agent.yaml          ← Agent config (YAML)
├── prompts/
│   ├── categories/security.md                  ← Category prompt (new)
│   └── agents/security/pentest/system.md       ← Agent prompt
└── mission_control/rosters/default.yaml        ← Roster entry (edit)

modules/backend/agents/
├── schemas.py                                  ← Output schema (edit)
├── tools/security.py                           ← Tool implementations (new)
├── deps/base.py                                ← Deps dataclass (edit, if needed)
└── vertical/security/
    ├── __init__.py                             ← Minimal
    └── pentest/
        ├── __init__.py                         ← Minimal
        └── agent.py                            ← Agent module
```
