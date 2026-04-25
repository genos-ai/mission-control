# Plan 65: Tool Registry — Pluggable, Reusable Agent Tools

## Status: Proposed
## Priority: High
## Depends on: None (standalone architectural improvement)

---

## 1. Problem Statement

Tools are defined twice with no connection between the two definitions:

1. **Catalog metadata** — `tools: ["research.web_search"]` in agent YAML/DB. Used for UI display, planning, and routing. Not executable.
2. **Agent code** — `@agent.tool` decorators hardcoded in each agent's `create_agent()` factory. The actual runtime implementation.

This causes three problems:

- **Duplication**: To give a new agent `web_search`, you copy-paste the decorator code from the searcher agent. The tool implementation in `agents/tools/research.py` is shared, but the PydanticAI wiring is not.
- **No swappability**: Tavily is hardcoded as the search provider. Switching to Perplexity means editing the service layer and every agent that uses search.
- **Catalog lies**: The `tools` list in the catalog is documentation, not reality. It can drift from what the agent actually registers at runtime.

## 2. Goal

Define a tool **once** as a reusable component. Assign it to any agent via catalog config. The tool registry creates the PydanticAI tool wrapper automatically at agent creation time.

```
tool defined once → tool registry → assigned via catalog → injected at agent creation
```

## 3. Naming Convention

### Pattern: `{verb}_{noun}`

Every tool name is an action. The verb tells the LLM what it can do. The noun tells it what it acts on.

```
search_web            NOT web_search (noun_verb reads as a label, not an instruction)
search_codebase       NOT codebase_search
search_knowledge      NOT knowledge.search (no namespace dots)
fetch_url             NOT url_fetcher
read_file             NOT filesystem.read_file (no domain prefix)
list_directory        NOT ls
scan_imports          NOT compliance.scan_imports
generate_code_map     NOT codemap.generate
score_code_quality    NOT run_quality_score
extract_content       NOT content_extract
validate_schema       NOT schema_validator
```

### Why verb_noun:
- **AI-friendly**: reads as an instruction — "search the web", "read a file"
- **Grep-friendly**: `search_*` finds all search tools, `*_file` finds all file tools
- **No domain coupling**: `search_web` works for research, pentest, or any mission type
- **No provider coupling**: `search_web` not `tavily_search` — tool identity is stable when providers swap
- **Scales to anything**: `deploy_container`, `send_notification`, `summarize_document`, `check_compliance`

### Current → Renamed

| Current name | New name | File |
|-------------|----------|------|
| `web_search` | `search_web` | `search_web.py` |
| `fetch_and_extract` | `fetch_url` | `fetch_url.py` |
| `search_codebase` | `search_codebase` | `search_codebase.py` (already correct) |
| `read_file` | `read_file` | `read_file.py` (already correct) |
| `list_directory` | `list_directory` | `list_directory.py` (already correct) |
| `generate_code_map` | `generate_code_map` | `generate_code_map.py` (already correct) |
| `run_quality_score` | `score_code_quality` | `score_code_quality.py` |
| `scan_imports` | `scan_imports` | `scan_imports.py` (already correct) |
| `load_project_standards` | `load_standards` | `load_standards.py` |
| `search_knowledge` | `search_knowledge` | `search_knowledge.py` (already correct) |

## 4. Tool Template

Every tool follows the same file structure. A developer copies the template, fills in the blanks, drops it in `modules/backend/tools/`, and it's available to any agent.

### 4.1 Template

```python
"""
Tool: {verb}_{noun}

{One-line description of what this tool does.}
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any


# ── Contract ─────────────────────────────────────────────

@dataclass
class Input:
    """What the tool receives. Each field becomes a tool parameter."""
    query: str
    max_results: int = 10


@dataclass
class Output:
    """What the tool returns. Documents the shape for the LLM."""
    url: str
    title: str
    snippet: str


# ── Dependencies ─────────────────────────────────────────

REQUIRED_DEPS = ["http_client"]  # fields needed from agent RunContext.deps


# ── Implementation ───────────────────────────────────────

async def {verb}_{noun}(
    http_client: Any,
    query: str,
    *,
    max_results: int = 10,
) -> list[dict]:
    """{Docstring — this is what the LLM sees as the tool description.}"""
    from modules.backend.services.{service} import {ServiceClass}

    svc = {ServiceClass}(http_client)
    results = await svc.{method}(query, max_results=max_results)
    return [r.model_dump() for r in results]
```

### 4.2 Rules

1. **One file = one tool.** File name matches function name: `search_web.py` exports `search_web()`
2. **Input dataclass** — typed parameters with defaults. The registry reads this to generate the PydanticAI tool schema automatically
3. **Output dataclass** — typed return shape. Documents what the LLM receives. Used by the registry for output schema validation
4. **REQUIRED_DEPS list** — declares which `RunContext.deps` fields this tool needs (e.g. `["http_client"]`, `["project_root", "scope"]`). The registry validates at registration time that the agent's deps type has these fields
5. **Single async function** — same name as the file. This IS the tool. No classes, no decorators, no setup code
6. **Service layer delegation** — the tool function is a thin wrapper. Business logic lives in `services/`. Tools never import PydanticAI
7. **Return `list[dict]` or `dict`** — always JSON-serializable. No Pydantic models in return types (the LLM sees raw JSON)

### 4.3 Example: search_web.py

```python
"""
Tool: search_web

Search the web for information using the configured search provider.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class Input:
    query: str
    max_results: int = 10
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None


@dataclass
class Output:
    url: str
    title: str
    snippet: str
    content: str
    relevance_score: float
    provider: str


REQUIRED_DEPS = ["http_client"]


async def search_web(
    http_client: Any,
    query: str,
    *,
    max_results: int = 10,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web for information on a topic.

    Returns ranked results with url, title, snippet, content,
    and relevance_score. Provider is selected from config.
    """
    from modules.backend.services.search.web_search import WebSearchService

    svc = WebSearchService(http_client)
    results = await svc.search(
        query,
        max_results=max_results,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    return [r.model_dump() for r in results]
```

### 4.4 YAML Definition (minimal — module is the source of truth)

```yaml
# config/tools/search_web.yaml
tool_name: search_web
description: "Search the web for information on a topic"
module: modules.backend.tools.search_web
```

The registry imports the module, discovers the function (same name as module), reads `Input`/`Output` dataclasses for schema, reads `REQUIRED_DEPS` for validation, and generates the PydanticAI tool wrapper. Zero duplication between Python and YAML.

## 5. Architecture

### 5.1 Tool Definition (config/tools/*.yaml)

Each tool is a YAML file declaring its identity, parameters, and implementation binding:

```yaml
# config/tools/search_web.yaml
tool_name: web_search
description: "Search the web for information on a topic. Returns ranked results with titles, snippets, and URLs."
category: search

parameters:
  query:
    type: string
    description: "Search query"
    required: true
  max_results:
    type: integer
    description: "Maximum results to return"
    default: 10
  include_domains:
    type: list[string]
    description: "Only include results from these domains"
    required: false
  exclude_domains:
    type: list[string]
    description: "Exclude results from these domains"
    required: false

returns:
  type: list[dict]
  description: "List of search results with url, title, snippet, content, relevance_score"

# Implementation binding — which Python function implements this tool
implementation:
  module: modules.backend.agents.tools.research
  function: web_search
  # Dependencies injected from the agent's RunContext.deps
  deps_mapping:
    http_client: ctx.deps.http_client
```

More examples:

```yaml
# config/tools/fetch_and_extract.yaml
tool_name: fetch_and_extract
description: "Fetch a URL and extract readable text content from the HTML."
category: search

parameters:
  url:
    type: string
    description: "URL to fetch"
    required: true

returns:
  type: dict
  description: "{url, title, content, content_length}"

implementation:
  module: modules.backend.agents.tools.research
  function: fetch_and_extract
  deps_mapping:
    http_client: ctx.deps.http_client
```

```yaml
# config/tools/read_file.yaml
tool_name: read_file
description: "Read a file from the project repository."
category: filesystem

parameters:
  path:
    type: string
    description: "File path relative to project root"
    required: true

returns:
  type: string
  description: "File content"

implementation:
  module: modules.backend.agents.tools.filesystem
  function: read_file
  deps_mapping:
    project_root: ctx.deps.project_root
    scope: ctx.deps.scope
```

### 3.2 Tool Registry (modules/backend/agents/tools/registry.py)

A singleton registry that loads tool definitions from YAML and creates PydanticAI tool wrappers on demand.

```python
class ToolRegistry:
    """Loads tool definitions from config/tools/*.yaml.

    Creates PydanticAI-compatible tool functions that can be dynamically
    registered on any Agent instance. Each tool is a thin wrapper that
    resolves deps from RunContext and delegates to the implementation function.
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load all tool YAML files from config/tools/."""
        ...

    def get(self, tool_name: str) -> ToolDefinition:
        """Get a tool definition by name. Raises KeyError if not found."""
        ...

    def list_all(self) -> list[dict]:
        """List all registered tools with metadata."""
        ...

    def create_tool_function(self, tool_name: str) -> Callable:
        """Create a PydanticAI-compatible async tool function.

        Returns an async function with the correct signature and docstring
        that PydanticAI can register via agent.tool(). The function resolves
        deps from RunContext and delegates to the implementation module.
        """
        ...

    def register_tools_on_agent(
        self, agent: Agent, tool_names: list[str]
    ) -> None:
        """Register multiple tools on a PydanticAI Agent instance.

        Called by the agent executor at agent creation time. Reads the
        agent's tools list from the catalog config and registers each
        tool dynamically.
        """
        for name in tool_names:
            fn = self.create_tool_function(name)
            agent.tool(fn)
```

### 3.3 ToolDefinition Schema

```python
@dataclass
class ToolParameter:
    name: str
    type: str              # string, integer, float, boolean, list[string], dict
    description: str
    required: bool = True
    default: Any = None

@dataclass
class ToolImplementation:
    module: str            # Python module path
    function: str          # Function name in that module
    deps_mapping: dict[str, str]  # param_name → ctx.deps.field_name

@dataclass
class ToolDefinition:
    tool_name: str
    description: str
    category: str
    parameters: list[ToolParameter]
    returns_type: str
    returns_description: str
    implementation: ToolImplementation
```

### 3.4 Agent Creation Flow (changed)

Current flow (hardcoded tools):
```python
def create_agent(model):
    agent = Agent(model, ...)

    @agent.tool
    async def web_search(ctx, query, max_results=10):  # hardcoded
        return await research_tools.web_search(...)

    return agent
```

New flow (registry-driven tools):
```python
def create_agent(model, tool_names: list[str] | None = None):
    agent = Agent(model, ...)

    # Agent-specific tools (business logic, not reusable)
    # These stay as @agent.tool decorators — they're unique to this agent
    @agent.tool
    async def some_agent_specific_tool(ctx):
        ...

    # Shared tools from registry (reusable across agents)
    if tool_names:
        tool_registry = get_tool_registry()
        tool_registry.register_tools_on_agent(agent, tool_names)

    return agent
```

### 3.5 Agent Executor Integration

In `agent_executor.py`, where agents are instantiated:

```python
# Current (tools from create_agent hardcoded decorators):
module = importlib.import_module(module_path)
agent = module.create_agent(model)

# New (tools from catalog config):
module = importlib.import_module(module_path)
agent = module.create_agent(model, tool_names=agent_config.tools)
```

### 3.6 Provider Swappability

The tool YAML points to an implementation function. To swap providers (Tavily → Perplexity), you either:

**Option A — Change the YAML binding** (zero code change):
```yaml
# config/tools/web_search.yaml
implementation:
  module: modules.backend.agents.tools.search_perplexity  # was: research
  function: web_search
```

**Option B — Provider config in the tool YAML** (implementation decides):
```yaml
# config/tools/web_search.yaml
implementation:
  module: modules.backend.agents.tools.research
  function: web_search
  config:
    provider: perplexity  # passed to the function, it picks the right service
```

Option B is better — the implementation function handles provider routing, and you can A/B test providers.

## 4. What Tools Look Like

### 4.1 Shared Tools (defined in YAML, registered via registry)

These are the reusable tools any agent can use:

| Tool Name | Category | Current Location | Description |
|-----------|----------|-----------------|-------------|
| `web_search` | search | agents/tools/research.py | Tavily/Brave web search |
| `fetch_and_extract` | search | agents/tools/research.py | URL fetch + HTML extraction |
| `read_file` | filesystem | agents/tools/filesystem.py | Read a project file |
| `list_directory` | filesystem | agents/tools/filesystem.py | List directory contents |
| `generate_code_map` | codemap | agents/tools/codemap.py | Generate structural code map |
| `run_quality_score` | codemap | agents/tools/codemap.py | Run PQI quality scoring |
| `scan_imports` | compliance | agents/tools/compliance.py | Scan Python imports |
| `search_knowledge` | knowledge | agents/tools/knowledge.py | Search platform knowledge base |

### 4.2 Agent-Specific Tools (stay as @agent.tool decorators)

These are unique to one agent and don't make sense as shared tools:

| Agent | Tool | Why not shared |
|-------|------|---------------|
| mission.director | `run_objective` | Orchestrates the full mission pipeline |
| mission.director | `start_research` | Creates research team + dispatches |
| mission.director | `get_artifacts` | Reads mission_artifacts for this mission |
| mission.director | `refine_plan` | Modifies the mission plan |
| mission.supervisor | `classify_situation` | Supervisor-specific decision logic |

**Rule of thumb**: If a tool could be useful on 2+ agents, it goes in the registry. If it's business logic unique to one agent, it stays as a decorator.

## 5. Implementation Phases

### Phase 0: Restructure — one tool per file (do first)

The current `agents/tools/` groups tools by domain (`research.py`, `compliance.py`, `filesystem.py`).
This makes tools hard to find, couples unrelated tools, and prevents clean YAML-per-tool mapping.

**Restructure to one tool per file:**

```
# BEFORE (domain-grouped, tools buried)
modules/backend/agents/tools/
  research.py          ← web_search + fetch_and_extract + search_codebase
  compliance.py        ← scan_imports + load_project_standards
  filesystem.py        ← read_file + list_directory
  codemap.py           ← generate_code_map + run_quality_score

# AFTER (one tool per file, flat)
modules/backend/tools/
  __init__.py
  web_search.py
  fetch_and_extract.py
  search_codebase.py
  read_file.py
  list_directory.py
  scan_imports.py
  load_project_standards.py
  generate_code_map.py
  run_quality_score.py
  search_knowledge.py
```

Each file exports a single async function with the same name as the file.
The function signature is the tool's contract — parameters, types, return type.
Services layer (`services/search/`, `services/code_map/`) stays unchanged — tools call services.

**Migration steps:**
1. Create `modules/backend/tools/` directory
2. Extract each function from the domain files into its own file
3. Update all imports in agent `create_agent()` factories
4. Delete the old `agents/tools/` domain files
5. Verify all agents work

**Why now:** The platform has 10+ tools. Every new tool means deciding which domain file to put it in, and every consumer must know the domain grouping to import it. Flat structure scales better and maps 1:1 to the YAML definitions in Phase 1.

### Phase 1: Tool Registry Core (foundation)

Files to create:
- `modules/backend/tools/registry.py` — ToolRegistry class
- `modules/backend/tools/schema.py` — ToolDefinition, ToolParameter dataclasses
- `config/tools/web_search.yaml` — first tool definition
- `config/tools/fetch_and_extract.yaml`

Files to modify:
- `modules/backend/agents/mission_control/helpers/agent_executor.py` — pass tool_names to create_agent
- `modules/backend/agents/research/searcher/agent.py` — remove hardcoded @agent.tool decorators for shared tools, accept tool_names parameter

Validation:
- Research searcher agent works with registry-injected tools
- `mc.py run` produces the same research report as before
- No change to agent catalog schema (tools list already exists)

### Phase 2: Migrate Remaining Shared Tools

Create YAML definitions for all remaining shared tools:
- `config/tools/read_file.yaml`
- `config/tools/list_directory.yaml`
- `config/tools/generate_code_map.yaml`
- `config/tools/run_quality_score.yaml`
- `config/tools/scan_imports.yaml`
- `config/tools/search_knowledge.yaml`

Update each agent's `create_agent()` to accept `tool_names` and remove the shared tool decorators.

### Phase 3: Provider Swappability

- Add `config` section to tool YAML for provider selection
- Implement `search_perplexity.py` as alternative to `web_search.py`
- Add admin UI for tool configuration (provider selection, API keys)

### Phase 4: Tool Catalog API + UI

- API endpoint: `GET /tools` — list all registered tools
- API endpoint: `GET /tools/{name}` — tool detail with parameters
- Admin UI: browse tools, test them, assign to agents
- CLI: `mc.py tools list`, `mc.py tools test web_search --query "test"`

## 6. Files Reference

### Existing files (to modify)

| File | Change |
|------|--------|
| `modules/backend/agents/mission_control/helpers/agent_executor.py` | Pass `agent_config.tools` to `create_agent()` |
| `modules/backend/agents/research/searcher/agent.py` | Remove hardcoded shared tool decorators |
| `modules/backend/agents/research/analyst/agent.py` | Same |
| `modules/backend/agents/software/quality/agent.py` | Same |
| `modules/backend/agents/mission/director/agent.py` | Keep agent-specific tools, add registry for shared |

### Existing files (delete after Phase 0)

| File | Replaced by |
|------|-------------|
| `modules/backend/agents/tools/research.py` | `modules/backend/tools/web_search.py` + `fetch_and_extract.py` + `search_codebase.py` |
| `modules/backend/agents/tools/compliance.py` | `modules/backend/tools/scan_imports.py` + `load_project_standards.py` |
| `modules/backend/agents/tools/filesystem.py` | `modules/backend/tools/read_file.py` + `list_directory.py` |
| `modules/backend/agents/tools/codemap.py` | `modules/backend/tools/generate_code_map.py` + `run_quality_score.py` |
| `modules/backend/agents/tools/knowledge.py` | `modules/backend/tools/search_knowledge.py` |

### Existing files (no change needed)

| File | Why |
|------|-----|
| `modules/backend/services/search/web_search.py` | Service layer stays unchanged — tools call services |
| `modules/backend/services/search/content_extract.py` | Same |
| `modules/backend/services/code_map/` | Same |
| `modules/backend/agents/config_schema.py` | `tools: list[str]` already exists |
| `modules/backend/models/agent_catalog.py` | `tools` column already exists |
| `config/agents/*/agent.yaml` | `tools:` list already exists |

### New files to create

| File | Purpose |
|------|---------|
| `modules/backend/tools/__init__.py` | Package init |
| `modules/backend/tools/web_search.py` | Web search (Tavily/Brave/Perplexity) |
| `modules/backend/tools/fetch_and_extract.py` | URL fetch + HTML extraction |
| `modules/backend/tools/search_codebase.py` | Grep-style local code search |
| `modules/backend/tools/read_file.py` | Read a project file |
| `modules/backend/tools/list_directory.py` | List directory contents |
| `modules/backend/tools/scan_imports.py` | Python import scanning |
| `modules/backend/tools/load_project_standards.py` | Load compliance standards |
| `modules/backend/tools/generate_code_map.py` | Structural code map |
| `modules/backend/tools/run_quality_score.py` | PQI quality scoring |
| `modules/backend/tools/search_knowledge.py` | Platform knowledge search |
| `modules/backend/tools/registry.py` | ToolRegistry singleton |
| `modules/backend/tools/schema.py` | ToolDefinition dataclass |
| `config/tools/web_search.yaml` | Web search tool definition |
| `config/tools/fetch_and_extract.yaml` | URL fetch tool definition |
| `config/tools/read_file.yaml` | File read tool definition |
| `config/tools/list_directory.yaml` | Directory listing tool definition |
| `config/tools/generate_code_map.yaml` | Code map tool definition |
| `config/tools/run_quality_score.yaml` | PQI tool definition |
| `config/tools/scan_imports.yaml` | Import scanning tool definition |
| `config/tools/search_knowledge.yaml` | Knowledge search tool definition |

## 7. Constraints

- **No breaking changes**: Existing agents must work during migration. Agents can have both hardcoded and registry tools simultaneously.
- **No new dependencies**: Uses PydanticAI's existing `agent.tool()` API. No custom tool protocol.
- **YAML is optional**: If no YAML exists for a tool name, fall back to the current hardcoded behavior. This allows incremental migration.
- **Deps compatibility**: Tool functions must work with any agent's deps type. The `deps_mapping` in YAML resolves this — each tool declares which deps fields it needs.
- **Anthropic + Copilot**: Tool registration is model-agnostic. PydanticAI handles the model-specific tool protocol (Anthropic tool_use, Copilot tool handlers).

## 8. Success Criteria

1. A new tool can be added by creating a single YAML file — no Python code changes
2. An existing tool can be assigned to a new agent by adding its name to the agent's `tools:` list — no code changes
3. Search provider can be swapped from Tavily to Perplexity by changing a config value — no agent code changes
4. All existing research runs produce identical results after migration
5. `mc.py tools list` shows all registered tools with their parameters
