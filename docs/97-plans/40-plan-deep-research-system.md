# Plan 40: Deep Research System

## Context

Mission Control needs a first-class deep research capability — like Claude.ai's researcher but running inside the existing orchestration framework. The system must handle general web research, codebase analysis, academic research, and competitive analysis with configurable depth, iterative refinement, multi-source search, citation verification, and persistent knowledge accumulation.

### Research: `docs/98-research/17-Building a production AI research agent with Python.md`

The canonical architecture for deep research agents follows a **Plan→Search→Synthesize** loop with parallel execution, external memory, and multi-model routing. Key findings:

- **Token budget explains ~80% of research quality variance** — multi-agent parallelism with context isolation is the dominant strategy over single-agent approaches
- Anthropic's Claude Research uses an **orchestrator-worker pattern** where Opus acts as lead researcher spawning 3–10 parallel Sonnet subagents — multi-agent outperformed single-agent by **90.2%**
- Search infrastructure: Tavily (best ecosystem integration), Brave (independent index, top quality), Trafilatura (F1 0.958 for content extraction)
- Citation verification via NLI models closes the grounding gap that raw LLM generation leaves open
- The **search→gap-check→search-more** iteration loop with configurable stopping conditions is essential for comprehensive coverage

### Design Decisions

1. **Keep the Planning Agent in the loop.** Every other execution goes through the Planning Agent — bypassing it creates a special case that breaks composability (e.g., a workflow with research step 1 + code generation step 2). Instead, teach the Planning Agent to recognize research rosters and emit a single task with `type: research_loop`. The dispatch loop detects this and routes to the research executor. This is the same pattern `convergence.py` was designed for — we just wire it up.

2. **5 specialized agents, each with a single clear responsibility.** Strategist (decompose + refine), searcher (search + extract), analyst (coverage evaluation — identifies what's covered, what isn't), synthesizer (report with citations), verifier (citation verification). Clear separation makes each agent easier to test, prompt-engineer, and swap independently. The analyst does NOT generate new sub-questions — that's the strategist's job. The analyst only returns structured coverage data (covered/uncovered lists); the strategist generates refined queries from the gap list.

3. **Deterministic coverage scoring.** Following P2 (Deterministic over Non-Deterministic): coverage score is computed by code from structured agent output (fraction of sub-questions with >= 2 independent sources), not an LLM-generated float.

4. **Findings compression before synthesis.** The strategist's analysis phase must rank, deduplicate, and compress findings to a `max_findings_for_synthesis` limit. Without this, the synthesizer's context window blows up on comprehensive runs.

5. **Cumulative budget enforcement.** The loop executor tracks total spend across all agent invocations (not per-agent). Per-agent cost ceilings in the roster are per-invocation limits; the loop's `budget_usd` is the hard cap for the entire research run.

6. **No SourceCacheService in Phase 1.** Redis caching for extracted content is premature. Add it when redundant extraction becomes a measured bottleneck.

8. **`type: research_loop` belongs in the workflow template static input, not inferred by the Planning Agent.** Adding `type: "research_loop"` to the workflow step's `inputs.static` makes dispatch routing deterministic — the Planning Agent simply sees a task with this type and passes it through. No fragile system prompt additions needed. The Planning Agent still creates the plan (one task), just doesn't need to invent the task type.

9. **`AgentResponseChunkEvent` already exists — do not create `ResearchReportChunkEvent`.** The existing event already carries streaming text chunks; add `research_id` as optional metadata or use `source` field. Creating a duplicate event type for what is structurally identical data violates DRY and fragments the frontend event handling.

7. **The experience IS the product.** The backend engine is necessary but not sufficient. What makes this demo-worthy is the real-time narrative: watching sub-questions appear, sources discovered live, coverage climbing, and the report writing itself. Every phase must emit human-readable narrative events alongside structured data. The synthesizer must stream its output. **This research system is the textbook example of how every future mission type should be experienced** — the event patterns, three-panel UI layout, and follow-up conversation model established here become the platform standard.

---

## Architecture Overview

```
User: "research X" via chat or CLI
  │
  ├── Chat path: Mission Director → start_research tool → creates Execution
  └── CLI path:  mc run workflow research.deep-research.workflow → WorkflowRunService → creates Execution
        │
        ▼
  ExecutionService.run_execution()
        │
        ▼
  MissionControlDispatchAdapter.execute()
        │
        ▼
  handle_mission()
        │
        ▼
  Planning Agent (system.planning.agent)
        │   Sees research_team roster → creates single task:
        │   {type: "research_loop", query: "...", loop_config: {...}}
        │
        ▼
  dispatch() in loop.py
        │
        ├── _execute_layer() detects resolved_inputs["type"] == "research_loop"
        │     → routes to execute_research_loop() instead of execute_task()
        │
        ▼
  ResearchLoopExecutor
        ├── Phase 1: Decompose (research.strategist.agent)
        ├── Phase 2: Search Loop (iterative, max N iterations)
        │     ├── Fan-out: K × research.searcher.agent in parallel (context isolation)
        │     ├── Analyze: research.analyst.agent → structured coverage data
        │     ├── Coverage check: deterministic score computed by code
        │     ├── Gate check: continue or stop?
        │     └── Refine: research.strategist.agent (new sub-questions for gaps)
        ├── Phase 3: Compress — rank + deduplicate findings, take top-K (deterministic)
        ├── Phase 4: Synthesize (research.synthesizer.agent — top-K ranked findings)
        ├── Phase 5: Verify (research.verifier.agent — NLI citation checking)
        └── Phase 6: Persist (report to DB, key findings to MCD, stream to user)
```

No Temporal changes needed — the existing `AgentMissionWorkflow` wraps executions for durability. The research loop runs inside a standard execution.

**Known limitation (Phase 1):** If the loop crashes mid-iteration, all accumulated findings are lost. The entire `execute_research_loop()` is one Temporal activity. Checkpointing findings to DB per-iteration is a Phase 2 improvement.

---

## 1. New Agents (5 agents × 4-file contract = 20 files)

### 1.1 `research.strategist.agent`
- **Type**: `vertical` | **Model**: `claude-sonnet-4` (extended thinking)
- **Role**: Decomposes research queries into sub-questions with source hints and dependencies. Also handles gap-based query refinement between iterations (called again with "refine" instructions when gaps are identified).
- **Tools**: None (pure reasoning on structured input)
- **Output**: `ResearchDecomposition` (sub-questions, source strategy, complexity estimate)
- **Budget**: $3.00 per invocation
- **Files**:
  - `config/agents/research/strategist/agent.yaml`
  - `modules/backend/agents/research/strategist/agent.py`
  - `modules/backend/agents/research/strategist/deps.py`
  - `config/prompts/agents/research/strategist/system.md`

### 1.2 `research.searcher.agent`
- **Type**: `vertical` | **Model**: `claude-sonnet-4`
- **Role**: Executes search for ONE sub-question. Each instance gets its own context window (context isolation — 90.2% improvement over single-agent). Searches, extracts content, produces structured findings with citations.
- **Tools**: `web_search`, `fetch_and_extract`, `search_codebase`, `search_confluence`
- **Output**: `SearchFindings` (list of findings with source citations for one sub-question)
- **Budget**: $2.00 per invocation
- **Invocation**: `system` tier (dispatched by loop executor, never user-invoked directly)
- **Files**:
  - `config/agents/research/searcher/agent.yaml`
  - `modules/backend/agents/research/searcher/agent.py`
  - `modules/backend/agents/research/searcher/deps.py`
  - `config/prompts/agents/research/searcher/system.md`

### 1.3 `research.analyst.agent`
- **Type**: `vertical` | **Model**: `claude-sonnet-4`
- **Role**: Evaluates research coverage after each search round. Identifies which sub-questions are covered (with source IDs) and which remain as gaps. Returns **structured data**, not a score — the loop executor computes coverage deterministically from the structured output. Does NOT generate new sub-questions (that is the strategist's job — the strategist receives the gap list and produces refined queries).
- **Tools**: None (pure reasoning on the current findings set)
- **Output**: `CoverageAnalysisData` (covered_questions with source_ids, uncovered_question_ids)
- **Budget**: $2.00 per invocation
- **Files**:
  - `config/agents/research/analyst/agent.yaml`
  - `modules/backend/agents/research/analyst/agent.py`
  - `modules/backend/agents/research/analyst/deps.py`
  - `config/prompts/agents/research/analyst/system.md`

### 1.4 `research.synthesizer.agent`
- **Type**: `vertical` | **Model**: `claude-sonnet-4` (max_tokens: 32768)
- **Role**: Produces the final structured research report with `[N]` inline citations from the **top-K ranked findings** (not all findings — the loop executor pre-filters). High max_tokens because reports can be long. Also emits `context_updates` for the MCD with key findings summary.
- **Tools**: None (pure synthesis on pre-loaded findings)
- **Output**: `ResearchReportOutput` (title, executive_summary, sections with citations, source list, methodology, limitations, context_updates)
- **Budget**: $5.00
- **Files**:
  - `config/agents/research/synthesizer/agent.yaml`
  - `modules/backend/agents/research/synthesizer/agent.py`
  - `modules/backend/agents/research/synthesizer/deps.py`
  - `config/prompts/agents/research/synthesizer/system.md`

### 1.5 `research.verifier.agent`
- **Type**: `vertical` | **Model**: `claude-haiku-4.5` (cost-efficient for structured checking)
- **Role**: NLI-style citation verification. For each claim+citation pair in the synthesizer's report, checks whether the cited source text actually supports the claim. Flags hallucinated or unsupported citations. Re-reads source excerpts passed from the loop executor (not the full URLs — source text is pre-loaded).
- **Tools**: None (verification on pre-loaded source texts; no network access needed)
- **Output**: `VerificationResult` (per-citation verdicts, overall verification_score)
- **Budget**: $1.00
- **Files**:
  - `config/agents/research/verifier/agent.yaml`
  - `modules/backend/agents/research/verifier/agent.py`
  - `modules/backend/agents/research/verifier/deps.py`
  - `config/prompts/agents/research/verifier/system.md`

---

## 2. Research Loop Executor (Core Engine)

**File**: `modules/backend/agents/mission_control/dispatch/research_loop.py`

Follows the structural pattern of `convergence.py` — a standalone executor called from the dispatch loop, using `execute_agent_fn` to invoke agents.

```python
@dataclass
class ResearchConfig:
    """Configuration for a research loop."""
    depth: str = "comprehensive"              # quick | moderate | comprehensive
    max_iterations: int = 5
    min_coverage_ratio: float = 0.8           # fraction of sub-questions with >= 2 sources
    max_sources_per_question: int = 10
    max_findings_for_synthesis: int = 50      # top-K findings sent to synthesizer
    source_types: list[str] = field(default_factory=lambda: ["web"])
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    budget_usd: float = 25.0                  # hard cap for entire research run
    max_concurrent_searches: int = 10         # semaphore limit for parallel searchers
    verification_enabled: bool = True

    # Agent names (configurable for testing)
    strategist_agent: str = "research.strategist.agent"
    searcher_agent: str = "research.searcher.agent"
    analyst_agent: str = "research.analyst.agent"
    synthesizer_agent: str = "research.synthesizer.agent"
    verifier_agent: str = "research.verifier.agent"

    @classmethod
    def from_dict(cls, data: dict) -> ResearchConfig: ...

@dataclass
class SearchRound:
    """Result of a single search iteration."""
    round_number: int
    sub_questions_searched: int
    sources_found: int
    new_findings: int
    coverage_ratio: float              # deterministic: covered / total sub-questions
    gaps_remaining: int
    cost_usd: float

async def execute_research_loop(
    *,
    task_id: str,
    query: str,
    config: ResearchConfig,
    execute_agent_fn: ExecuteAgentFn,
    mission_id: str | None = None,
    gate: GateReviewer | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> TaskResult:
    """Execute a deep research loop.

    Phase 1: Decompose — strategist breaks query into sub-questions
    Phase 2: Search Loop (iterative):
        a. Fan out searcher agents in parallel (one per gap sub-question)
        b. Analyst evaluates coverage (structured output)
        c. Deterministic coverage score: covered_questions / total_questions
        d. Stopping conditions: coverage >= threshold, budget exceeded,
           diminishing returns (< 5% improvement), or max_iterations
        e. Gate check: continue next iteration?
        f. Strategist refines queries for remaining gaps
    Phase 3: Compress — rank and deduplicate findings, take top-K
    Phase 4: Synthesize — produce report with citations
    Phase 5: Verify — NLI citation verification
    Phase 6: Persist — report to DB, key findings to MCD, deliver to user
    """
```

### Deterministic Coverage Scoring

The strategist's "analyze" phase returns structured data:

```python
class CoverageAnalysisData(BaseModel):
    """Structured coverage data from strategist — NOT a score."""
    covered_questions: list[CoveredQuestion]  # [{id, source_ids, confidence_note}]
    uncovered_questions: list[str]             # sub-question IDs with < 2 sources
    suggested_refinements: list[ResearchSubQuestion]

class CoveredQuestion(BaseModel):
    sub_question_id: str
    source_ids: list[str]                     # which sources answer this
    confidence_note: str                      # brief LLM note (for logging only)
```

The loop executor computes the score deterministically:

```python
def compute_coverage_ratio(analysis: CoverageAnalysisData, total_questions: int) -> float:
    """Fraction of sub-questions with >= 2 independent sources."""
    well_covered = sum(1 for q in analysis.covered_questions if len(q.source_ids) >= 2)
    return well_covered / total_questions if total_questions > 0 else 0.0
```

### Stopping Conditions (all deterministic)

```python
def should_stop(rounds: list[SearchRound], config: ResearchConfig) -> tuple[bool, str]:
    latest = rounds[-1]
    if latest.coverage_ratio >= config.min_coverage_ratio:
        return True, "sufficient"
    if sum(r.cost_usd for r in rounds) >= config.budget_usd:
        return True, "budget_exhausted"
    if len(rounds) >= config.max_iterations:
        return True, "max_iterations"
    if len(rounds) >= 2:
        improvement = latest.coverage_ratio - rounds[-2].coverage_ratio
        if improvement < 0.05:
            return True, "diminishing_returns"
    return False, ""
```

### Cumulative Budget Enforcement

The loop executor tracks `cumulative_cost_usd` across ALL agent invocations (strategist calls + all searcher instances + synthesizer). Before each search batch, it:

1. Checks `cumulative_cost_usd >= config.budget_usd` → skip to synthesis if exceeded
2. Computes how many searchers the remaining budget can support: `remaining = config.budget_usd - cumulative_cost_usd; max_batch = int(remaining / per_searcher_cost_ceiling)`. Caps the batch at `min(len(gap_questions), max_batch)` to prevent a single parallel batch from overshooting the budget by `N × cost_ceiling`.

Per-agent `cost_ceiling_usd` in the roster is per-invocation only.

### Analyst Context Efficiency

The analyst is called after each search round. Pass only the **new findings** from the current round + the **previous coverage summary** (the `CoverageAnalysisData` from the last round, if any). Do NOT pass all historical findings — the analyst's input grows unboundedly across iterations otherwise. The analyst updates its coverage view incrementally from the delta, not from the full history.

### Findings Compression (Pre-Synthesis)

Before calling the synthesizer, the loop executor:

1. Collects all `ResearchFinding` objects across all rounds
2. Deduplicates by `source_url` (keep highest relevance_score)
3. Sorts by `relevance_score` descending
4. Takes top `config.max_findings_for_synthesis` (default 50)
5. Groups by sub-question for organized input to synthesizer

This is **deterministic code**, not an LLM call. Ensures the synthesizer's context stays within limits regardless of how many iterations ran.

### Parallel Search with Concurrency Control

```python
semaphore = asyncio.Semaphore(config.max_concurrent_searches)

async def _search_one(sub_question):
    async with semaphore:
        return await execute_agent_fn(
            agent_name=config.searcher_agent,
            instructions=f"Research this sub-question: {sub_question.text}",
            inputs={...},
            usage_limits=...,
        )

results = await asyncio.gather(*[_search_one(sq) for sq in gap_questions])
```

The semaphore prevents overwhelming search API rate limits (Tavily: 100 RPM on Growth plan).

---

## 3. Dispatch Integration

### 3.1 How the Planning Agent creates the research task

The workflow template's step declares `type: "research_loop"` in its static `input` (see §8). The static inputs flow through `resolve_upstream_inputs()` into the task's `resolved_inputs`. The Planning Agent creates a **single task** for this step — it does NOT need to know about `type: research_loop` or produce it. The `type` key is already present in the resolved inputs before the Planning Agent is even called.

The Planning Agent only needs to know ONE thing about research missions: create a **single task** for the research step (do not decompose into multiple tasks). Add a brief note to the Planning Agent system prompt:

```markdown
## Single-task steps

Some workflow steps are self-managing loops (research, convergence) that handle
their own internal decomposition. When a step has a single entry-point agent
(e.g. research.strategist.agent), create ONE task for it — do not decompose it
into sub-tasks. The executor handles internal parallelism.
```

This is minimal and general — it applies to convergence loops too. No research-specific pattern recognition needed in the Planning Agent prompt.

### 3.2 Dispatch loop integration point

**File**: `modules/backend/agents/mission_control/dispatch/loop.py`

In `_execute_layer()`, before creating the `execute_with_step_events` coroutine, detect `research_loop` tasks and route them to the research executor. This is the same integration point where `convergence_loop` tasks would be routed.

```python
# In _execute_layer(), after resolving inputs and before creating coroutines:

for task_id in layer:
    task = plan.get_task(task_id)
    # ... existing roster + input resolution ...

    # Check for specialized dispatch patterns
    resolved_inputs = dict(resolved_inputs)
    task_type = resolved_inputs.get("type")

    if task_type == "research_loop":
        from .research_loop import execute_research_loop, ResearchConfig
        config = ResearchConfig.from_dict(resolved_inputs.get("loop_config", {}))
        coros.append(
            _execute_research_task(
                task=task,
                query=resolved_inputs.get("query", mission_brief),
                config=config,
                execute_agent_fn=execute_agent_fn,
                mission_id=mission_id,
                gate=_gate,
                event_bus=event_bus,
                session_id=session_id,
            )
        )
    elif task_type == "convergence_loop":
        # Same pattern — wire up convergence_loop here too
        ...
    else:
        # Normal dispatch path (existing code)
        coros.append(
            execute_with_step_events(...)
        )
```

The helper `_execute_research_task` wraps `execute_research_loop()` with the same PlanStep event emission that `execute_with_step_events` provides, so the frontend sees consistent step start/complete events.

### 3.3 No schema changes needed

The `dispatch_mode` field from the previous plan revision is **removed**. The routing happens entirely within the dispatch loop based on task input data. The Planning Agent controls what type of task gets created. No changes to `WorkflowStepSchema`, `Execution` model, or `MissionControlDispatchAdapter`.

---

## 4. Search Infrastructure (Service Layer)

**Directory**: `modules/backend/services/search/`

### 4.1 `web_search.py` — WebSearchService
```python
class WebSearchService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._tavily_key = get_settings().tavily_api_key
        self._brave_key = get_settings().brave_api_key

    async def search(self, query: str, *, max_results=10,
                     search_depth="advanced", provider="tavily",
                     include_domains=None, exclude_domains=None) -> list[SearchResult]:
        """Search with automatic fallback: tavily → brave."""
```
- Primary: Tavily API (returns extracted content, best for agents)
- Fallback: Brave Search API (independent index, top quality scores)
- Credentials: `TAVILY_API_KEY`, `BRAVE_API_KEY` from `.env`

### 4.2 `content_extract.py` — ContentExtractService
```python
class ContentExtractService:
    async def extract(self, url: str, *, max_length=50_000,
                      timeout_seconds=15) -> ExtractedContent:
        """Cascading extraction: trafilatura → readability → jina."""
```
- Cascading fallback: Trafilatura (F1 0.958) → readability-lxml → Jina Reader API
- Returns: text, title, author, date, word_count, quality_score

### 4.3 `codebase_search.py` — CodebaseSearchService
- Wraps existing codemap tools for internal codebase search
- Grep + glob + AST-level search

### 4.4 Agent Tools (thin wrappers)

**File**: `modules/backend/agents/tools/research.py`

```python
async def web_search(query, max_results=10, ...) -> dict
async def fetch_and_extract(url, max_length=50000) -> dict
async def search_codebase(query, file_patterns=None) -> dict
# search_confluence: Phase 2 — delegates to Atlassian MCP (mcp__claude_ai_Atlassian__searchAtlassian)
# Not included in Phase 1 — the Atlassian MCP is available as a direct tool for agents
# that have it configured; a wrapper adds no value until we need custom filtering/auth.
```

All are thin wrappers that call the service layer — following P7 (Separate Implementation from Registration) and the existing pattern in `tools/compliance.py`.

**Note on Tavily content**: Tavily's search API already returns content snippets in search results. The `web_search` tool should include those snippets in its return value so the searcher agent can use them directly. Call `fetch_and_extract` only when the Tavily snippet is too short (< 500 chars) or the source is from Brave (no content included). This avoids redundant HTTP extraction on Tavily results and cuts latency per search round.

---

## 5. Knowledge Accumulation

### 5.1 Research Report Model (Persistent Storage)

**File**: `modules/backend/models/research.py`

```python
class ResearchReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "research_reports"

    mission_id: Mapped[str]              # FK to missions
    execution_id: Mapped[str | None]     # FK to executions
    query: Mapped[str]                   # Original research query
    report_markdown: Mapped[str]         # Full report (Text)
    report_structured: Mapped[dict]      # JSON: sections, findings, conclusions
    sources: Mapped[list]                # JSON: [{url, title, relevance, excerpt}]
    metadata: Mapped[dict]              # JSON: iterations, coverage, cost, timing
    status: Mapped[str]                  # draft | verified | published
    tags: Mapped[list]                   # JSON: topic tags
    citation_count: Mapped[int]
    verification_score: Mapped[float | None]
```

### 5.2 MCD Updates (Mission-Level)

The synthesizer agent emits `context_updates` in its output, flowing through the existing `ContextCurator.apply_task_updates()` path:

```python
context_updates = [
    {"op": "add", "path": "research.findings.{topic_slug}",
     "value": {"title": "...", "date": "...", "key_insights": [...], "source_count": N},
     "reason": "Research finding: {title}"},
    {"op": "replace", "path": "current_state.recent_milestones",
     "value": [..., {"type": "research", "title": "...", "date": "..."}],
     "reason": "Completed research: {title}"},
]
```

### 5.3 Report Delivery — How the User Sees the Report

The synthesizer creates the report; the verifier validates it; the loop executor persists it. The user accesses it through multiple channels:

**During execution (real-time — the demo experience):**
- Narrative events stream the "thinking out loud" feed (see Section 7)
- Sources appear in real-time as each searcher discovers them (`ResearchSourceFoundEvent`)
- Sub-question status updates live (`ResearchSubQuestionUpdatedEvent`)
- Coverage ratio climbs visually (`ResearchCoverageEvent`)
- The report **streams in as it's being written** (`ResearchReportChunkEvent`) — the most impressive moment
- Verification results appear after the report is complete

**After completion:**
- **Frontend**: Research report view in the mission workspace. Renders `ResearchReport.report_markdown` with clickable citation tooltips showing source excerpts. Shows verification score badge and source list sidebar.
- **CLI**: `mc research show <execution-id>` displays the report in the terminal (Rich markdown rendering). `mc research list` shows all reports for the current mission.
- **Chat**: Mission Director has a `get_research_report` tool that retrieves the latest report for the mission, or a specific report by execution ID. Returns the executive summary + link to full report.
- **API**: `GET /api/v1/research/reports?mission_id=...` lists reports. `GET /api/v1/research/reports/{id}` returns full report.

**What goes where:**
| Destination | What | Size |
|---|---|---|
| `ResearchReport` table | Full report (markdown + structured JSON + sources + metadata) | Unbounded |
| `Execution.execution_outcome` | TaskResult with report in output_reference | Unbounded |
| MCD `research.findings.{topic}` | Key insights summary only (title, date, top 3-5 insights, source count) | ~500 bytes |
| MCD `current_state.recent_milestones` | One-line milestone entry | ~100 bytes |

### 5.4 Cross-Mission Knowledge Base (Phase 2 — future)

Deferred. See Phase 6 in implementation order.

---

## 6. Schemas & Output Types

**File**: `modules/backend/schemas/research.py` (new)

```python
# --- Sub-question decomposition ---

class ResearchSubQuestion(BaseModel):
    id: str
    text: str
    priority: int                    # 1=highest, 5=lowest
    source_hints: list[str]          # ["web", "codebase", "confluence"]
    # Note: no depends_on in Phase 1 — all gap sub-questions are fanned out in parallel

class ResearchDecomposition(BaseModel):
    """Output from strategist 'decompose' phase."""
    original_query: str
    sub_questions: list[ResearchSubQuestion]
    source_strategy: dict[str, Any]
    estimated_complexity: str        # quick | moderate | comprehensive

# --- Coverage analysis (structured, NOT a score) ---

class CoveredQuestion(BaseModel):
    sub_question_id: str
    source_ids: list[str]            # which sources answer this
    confidence_note: str             # brief note (for logging only)

class CoverageAnalysisData(BaseModel):
    """Output from analyst agent. Score computed by code. No query generation here.

    The analyst only classifies: which questions are covered (with >= 2 sources),
    which are not. The strategist takes the uncovered_question_ids and generates
    refined queries for the next iteration.
    """
    covered_questions: list[CoveredQuestion]
    uncovered_question_ids: list[str]   # sub-question IDs with < 2 sources

# --- Search findings ---

class ResearchFinding(BaseModel):
    sub_question_id: str
    claim: str
    evidence: str                    # excerpt from source
    source_url: str
    source_title: str
    relevance_score: float           # 0.0-1.0
    extraction_method: str

class SearchFindings(BaseModel):
    """Output from one searcher agent invocation."""
    sub_question_id: str
    findings: list[ResearchFinding]
    sources_searched: int
    urls_extracted: list[str]

# --- Synthesis output (from synthesizer agent) ---

class ResearchReportOutput(BaseModel):
    """Output from synthesizer agent."""
    title: str
    executive_summary: str
    sections: list[dict]             # [{heading, content, citations: [int]}]
    sources: list[dict]              # [{id, url, title, relevance}]
    methodology: str
    limitations: str
    context_updates: list[dict]      # For MCD flow

# --- Verification output (from verifier agent) ---

class CitationVerdict(BaseModel):
    citation_id: int
    claim: str
    source_url: str
    verdict: str                     # supported | partially_supported | unsupported
    explanation: str

class CitationVerificationResult(BaseModel):
    """Output from verifier agent.

    Named CitationVerificationResult (not VerificationResult) to avoid collision
    with modules.backend.agents.mission_control.verification.VerificationResult,
    which is used by the existing 3-tier verification pipeline in step_executor.py.
    """
    citation_verdicts: list[CitationVerdict]
    verification_score: float        # fraction of citations that are "supported"
    total_citations: int
    supported_count: int
    unsupported_count: int

# --- Search infrastructure ---

class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    relevance_score: float
    provider: str                    # tavily | brave

class ExtractedContent(BaseModel):
    url: str
    title: str | None
    text: str
    word_count: int
    quality_score: float             # 0.0-1.0
    extraction_method: str           # trafilatura | readability | jina
```

---

## 7. Mission Experience Model (Research as the Reference Implementation)

The research system is the **textbook example** of how every mission in Mission Control should be experienced. The patterns established here — narrative events, live artifact discovery, streaming output, follow-up conversation — become the platform standard that future mission types (code generation, audits, deployments) inherit.

The principle: **the user should feel like they're watching a brilliant team work, not staring at a progress bar.**

### 7.0 Platform Experience Primitives

The research system introduces experience primitives that are designed to generalize:

| Research-Specific | Platform Primitive | Future Use |
|---|---|---|
| `ResearchNarrativeEvent` | `MissionNarrativeEvent` | Any agent thinking out loud during any mission |
| `ResearchSourceFoundEvent` | `MissionArtifactFoundEvent` | Code files generated, APIs discovered, test results |
| `ResearchSubQuestionUpdatedEvent` | `TaskStatusUpdatedEvent` | Any task in any plan changing status live |
| _(use existing)_ `AgentResponseChunkEvent` | `AgentResponseChunkEvent` | Already exists — research emits it with `source="research:{id}"`. No new event needed. |
| Follow-up via `get_research_findings` | Follow-up via mission context | Chat about any completed execution's results |

For Phase 1 we implement these as research-prefixed events. In Phase 2, we extract the platform primitives and retrofit existing mission types to use them. Every mission should eventually feel this alive.

### 7.1 Narrative Events — The "Thinking Out Loud" Layer

Every phase emits a `ResearchNarrativeEvent` with human-readable text alongside structured data events. These are the events the frontend renders as the live research feed.

Example narrative stream during a research run:

```
"Breaking your question into 7 sub-questions..."
"Sub-question 1: What are the dominant architectures for AI coding assistants?"
"Sub-question 2: How do Cursor, GitHub Copilot, and Cody compare on latency?"
...
"Starting search round 1 — investigating 7 sub-questions in parallel..."
"🔍 Searching: 'AI coding assistant architectures 2025'"
"🔍 Searching: 'Cursor vs Copilot vs Cody benchmark comparison'"
"📄 Found: 'The Architecture of Cursor' — cursor.com/blog (relevance: 0.92)"
"📄 Found: 'GitHub Copilot X Technical Overview' — github.blog (relevance: 0.88)"
"📄 Found 3 sources on AI coding assistant pricing models"
...
"Coverage: 5/7 sub-questions answered (71%). 2 gaps remaining."
"Gap: No sources found on 'enterprise deployment patterns' — refining query..."
"Starting search round 2 — targeting 2 remaining gaps..."
...
"Coverage: 7/7 sub-questions answered (100%). Research sufficient."
"Compressing 47 findings to top 50 for synthesis..."
"Writing report: 'Competitive Landscape of AI Coding Assistants'..."
[report streams in as it's being written]
"Verifying 23 citations against source material..."
"✓ 21/23 citations verified (91.3%). 2 partially supported."
"Research complete. 47 sources, 3 iterations, $8.42, 4m 12s."
```

### 7.2 Event Types

**File**: `modules/backend/events/types.py` (extend existing)

```python
# --- Research Events ---

# Narrative event — the "thinking out loud" stream
class ResearchNarrativeEvent(SessionEvent):
    """Human-readable research status update. The primary event for the live feed."""
    event_type: str = "research.narrative"
    research_id: str
    phase: str                       # decompose | search | analyze | synthesize | verify | complete
    message: str                     # human-readable narrative text
    iteration: int | None = None

# Structured lifecycle events (for dashboards, metrics, programmatic use)
class ResearchStartedEvent(SessionEvent):
    event_type: str = "research.started"
    research_id: str
    query: str
    depth: str
    max_iterations: int

class ResearchDecomposedEvent(SessionEvent):
    event_type: str = "research.decomposed"
    research_id: str
    sub_question_count: int
    sub_questions: list[dict]        # [{id, text, priority, status: "pending"}]

class ResearchSubQuestionUpdatedEvent(SessionEvent):
    """A sub-question's status changed (pending → searching → covered → gap)."""
    event_type: str = "research.subquestion.updated"
    research_id: str
    sub_question_id: str
    text: str
    status: str                      # pending | searching | covered | gap
    source_count: int = 0

class ResearchSourceFoundEvent(SessionEvent):
    """A new source was discovered by a searcher agent. Emitted per-source."""
    event_type: str = "research.source.found"
    research_id: str
    iteration: int
    sub_question_id: str
    url: str
    title: str
    snippet: str                     # first ~200 chars of extracted content
    relevance_score: float
    provider: str                    # tavily | brave | codebase | confluence

class ResearchSearchCompletedEvent(SessionEvent):
    event_type: str = "research.search.completed"
    research_id: str
    iteration: int
    sources_found: int
    new_findings: int
    cost_usd: float

class ResearchCoverageEvent(SessionEvent):
    event_type: str = "research.coverage.updated"
    research_id: str
    iteration: int
    coverage_ratio: float            # deterministic
    gaps_remaining: int
    stop_reason: str                 # "" | "sufficient" | "diminishing_returns" | etc.

class ResearchSynthesizingEvent(SessionEvent):
    event_type: str = "research.synthesizing"
    research_id: str
    total_findings: int
    findings_after_compression: int

## NOTE: No ResearchReportChunkEvent needed.
## Use the existing AgentResponseChunkEvent (already in types.py, line ~102).
## The loop executor emits AgentResponseChunkEvent with source=f"research:{task_id}"
## so the frontend can distinguish research streaming from other agent responses.
## Adding a duplicate event type would fragment frontend event handling.

class ResearchCompletedEvent(SessionEvent):
    event_type: str = "research.completed"
    research_id: str
    report_title: str
    total_sources: int
    total_iterations: int
    coverage_ratio: float
    verification_score: float | None
    cost_usd: float
    duration_seconds: float

class ResearchFailedEvent(SessionEvent):
    event_type: str = "research.failed"
    research_id: str
    error: str
    iteration: int
    cost_usd: float
```

Register all in `EVENT_TYPE_MAP`. **Do not register a new event for streaming report chunks** — use the existing `AgentResponseChunkEvent` with `source=f"research:{task_id}"` to distinguish research output from other agents.

### 7.3 Streaming Synthesis — The Report Writes Itself

The synthesizer agent uses PydanticAI's streaming mode. As it generates the report, the loop executor captures response chunks and emits `ResearchReportChunkEvent`s via the event bus. The user watches the report appear paragraph by paragraph — the most impressive moment in the demo.

```python
# In research_loop.py, Phase 4:
async with agent.run_stream(synthesis_prompt, deps=deps) as stream:
    async for chunk in stream.stream_text(delta=True):
        await _emit(event_bus, ResearchReportChunkEvent,
            session_id=session_id,
            source=f"research:{task_id}",
            research_id=task_id,
            content=chunk,
        )
    # After streaming completes, get the final structured output
    result = await stream.get_output()
```

**Design decision — single call, split output:**

The synthesizer is called ONCE. Its output is structured as two parts:

**(d) Split output (recommended):**
- Stream the `report_markdown` field as plain text — this is what appears live in `<StreamingReport>` via `AgentResponseChunkEvent`s
- After streaming completes, the final structured output contains the lightweight metadata: `title`, `executive_summary`, `sources`, `methodology`, `limitations`, `context_updates`
- The `report_markdown` is the concatenation of all streamed chunks (PydanticAI makes this available via `stream.get_output()` after streaming)

This means the synthesizer returns `ResearchReportOutput` with a `report_markdown` field that streams live, and all other fields are available synchronously at end. One LLM call, not two. The previous approaches (a) and (b) are rejected:
- (a) Two calls: doubles cost (up to $10 for a $5 synthesis budget)
- (b) Markdown→schema parsing: brittle and unnecessary

```python
# In research_loop.py, Phase 4 (streaming synthesis):
async with synthesizer_agent.run_stream(synthesis_prompt, deps=deps) as stream:
    async for chunk in stream.stream_text(delta=True):
        await _emit(event_bus, AgentResponseChunkEvent,
            session_id=session_id,
            source=f"research:{task_id}",
            agent_name=config.synthesizer_agent,
            content=chunk,
            is_complete=False,
        )
    result: ResearchReportOutput = await stream.get_output()
    # result.report_markdown == "".join(all chunks) — already stored
```

### 7.4 Follow-Up Conversation

After research completes, the user should be able to chat about the findings. The Mission Director gets a `get_research_findings` tool:

```python
@agent.tool
async def get_research_findings(
    ctx: RunContext[MissionDirectorDeps],
    execution_id: str | None = None,
) -> str:
    """Get the latest research report for this mission, or a specific report by execution ID.

    Returns the executive summary, key findings, and source list.
    Use this to answer follow-up questions about completed research.
    """
```

The Mission Director can then answer questions like "tell me more about finding #3" or "what did you find about pricing specifically?" by referencing the stored report and source excerpts.

### 7.5 Frontend Experience Blueprint (Separate Plan — Backend Contracts Here)

The backend emits events; the frontend consumes them. The frontend is a separate plan, but the backend must emit the right events. **This is the reference UI that future mission types will follow.**

The research view has **three panels** that generalize to all missions:

**Left: Mission Activity Feed** (generalizes to all missions)
1. **Narrative feed** — scrolling text showing the team "thinking out loud"
   - Events: `ResearchNarrativeEvent` → future `MissionNarrativeEvent`
   - This panel is identical for every mission type — it's the universal "what's happening" view

**Center: Mission Workspace** (specialized per mission type)
2. **Sub-question tree** — list of sub-questions with live status badges (pending → searching → covered)
   - Events: `ResearchDecomposedEvent`, `ResearchSubQuestionUpdatedEvent`
   - Generalizes to: task plan tree for any mission
3. **Coverage progress ring** — animated 0% → 100%
   - Events: `ResearchCoverageEvent`
   - Generalizes to: mission progress indicator
4. **Streaming report** — the report appearing paragraph by paragraph
   - Events: `ResearchReportChunkEvent`
   - Generalizes to: streaming agent output for any agent

**Right: Artifact Panel** (generalizes to all missions)
5. **Live source/artifact feed** — sources appearing in real-time as searchers find them
   - Events: `ResearchSourceFoundEvent` → future `MissionArtifactFoundEvent`
   - Generalizes to: files created, APIs discovered, test results, build artifacts
6. **Source detail** — clickable citation references showing source excerpt tooltips
   - Data: `ResearchReport.sources` with `evidence` excerpts from findings
7. **Quality badge** — "21/23 citations verified (91.3%)"
   - Data: `VerificationResult.verification_score`
   - Generalizes to: verification results, test pass rates, PQI scores

This three-panel layout (activity feed | workspace | artifacts) becomes the **standard mission experience** across the platform.

---

## 8. Workflow Template

**File**: `config/workflow_templates/research.deep-research.workflow.yaml`

```yaml
workflow_name: research.deep-research.workflow
description: "Deep research with iterative multi-agent search, synthesis, and citation verification"
objective:
  statement: "Produce a comprehensive, cited research report"
  category: research
  owner: user
  priority: high
version: 1
enabled: true

trigger:
  type: on_demand
  match_patterns:
    - "deep research"
    - "research report"
    - "investigate"
    - "research"

budget:
  max_cost_usd: 25.00

context:
  research_depth: "comprehensive"
  max_iterations: 5
  source_types: ["web"]
  min_coverage_ratio: 0.8
  verification_enabled: true

steps:
  - id: research
    description: "Execute deep research loop"
    capability: research.strategist
    roster: research_team
    complexity_tier: complex
    cost_ceiling_usd: 25.00
    environment: local
    input:
      # type: research_loop is declared here — NOT inferred by the Planning Agent.
      # This makes dispatch routing deterministic. The Planning Agent creates a
      # single task for this step; the dispatch loop sees type=research_loop and
      # routes to execute_research_loop() before execute_with_step_events.
      type: "research_loop"
      query: "@context.query"
      loop_config:
        depth: "@context.research_depth"
        max_iterations: "@context.max_iterations"
        source_types: "@context.source_types"
        min_coverage_ratio: "@context.min_coverage_ratio"
        verification_enabled: "@context.verification_enabled"
    output_mapping:
      summary_key: research_summary
      field_mappings:
        - source_task: research
          source_field: report
          target_key: research_report
    timeout_seconds: 3600
    termination: criteria_met
```

**Roster**: `config/mission_control/rosters/research_team.yaml`

```yaml
# Per-agent cost ceilings are PER-INVOCATION limits.
# The research loop's budget_usd is the cumulative hard cap.
agents:
  - agent_name: research.strategist.agent
    constraints:
      timeout_seconds: 120
      cost_ceiling_usd: 3.00
      retry_budget: 1
  - agent_name: research.searcher.agent
    constraints:
      timeout_seconds: 60
      cost_ceiling_usd: 2.00
      retry_budget: 0               # searchers don't retry — skip on failure
  - agent_name: research.analyst.agent
    constraints:
      timeout_seconds: 90
      cost_ceiling_usd: 2.00
      retry_budget: 1
  - agent_name: research.synthesizer.agent
    constraints:
      timeout_seconds: 300
      cost_ceiling_usd: 5.00
      retry_budget: 1
  - agent_name: research.verifier.agent
    constraints:
      timeout_seconds: 120
      cost_ceiling_usd: 1.00
      retry_budget: 0               # verification is best-effort
```

---

## 9. Configuration

**File**: `config/settings/research.yaml`

```yaml
# Research depth presets
presets:
  quick:
    max_iterations: 2
    max_sub_questions: 5
    max_sources_per_question: 5
    max_findings_for_synthesis: 25
    budget_usd: 5.00
  moderate:
    max_iterations: 3
    max_sub_questions: 7
    max_sources_per_question: 8
    max_findings_for_synthesis: 40
    budget_usd: 10.00
  comprehensive:
    max_iterations: 5
    max_sub_questions: 10
    max_sources_per_question: 15
    max_findings_for_synthesis: 50
    budget_usd: 25.00

# Search provider configuration
search:
  primary_provider: tavily
  fallback_provider: brave
  max_concurrent_searches: 10

# Content extraction
extraction:
  max_content_length: 50000
  timeout_seconds: 15
  fallback_chain: [trafilatura, readability, jina]

# Stopping conditions
stopping:
  min_coverage_ratio: 0.8
  diminishing_returns_threshold: 0.05
  min_sources_per_question: 2
```

---

## 10. Mission Director Integration

Add a `start_research` tool to the existing `mission.director.agent` so users can trigger research from chat:

```python
@agent.tool
async def start_research(
    ctx: RunContext[MissionDirectorDeps],
    query: str,
    depth: str = "comprehensive",
) -> str:
    """Start a deep research investigation on any topic.

    Args:
        query: The research question to investigate.
        depth: Research depth — "quick" (2-5 min), "moderate" (5-15 min),
               or "comprehensive" (15-30 min).
    """
    # Triggers research.deep-research.workflow with query + depth in context.
    # The workflow creates an Execution, Planning Agent sees research_team roster
    # and creates a research_loop task, dispatch routes to the research executor.
    # Runs in background — returns execution ID immediately.
```

---

## 11. Frontend: Mission Live View

### 11.1 Current State

The frontend renders all agent output as `whitespace-pre-wrap` plain text — no markdown, no code highlighting, no rich formatting. The mission workspace has 8 tabs (Overview, Team, Chat, Workflows, Runs, Console, Workshop, Context) organized by data type. When a mission runs, you choose between the Console (raw event firehose) or Chat (conversational thread). Neither gives you the "watching a team work" feeling.

### 11.2 New Dependencies

```json
{
  "react-markdown": "^9.0.0",
  "remark-gfm": "^4.0.0",
  "rehype-highlight": "^7.0.0",
  "highlight.js": "^11.9.0"
}
```

### 11.3 `<MarkdownRenderer>` — Platform-Wide Component

**File**: `modules/frontend/src/components/ui/markdown-renderer.tsx`

Not research-specific — used everywhere agent output appears: chat messages, task results, reports, console detail views.

```tsx
interface MarkdownRendererProps {
  content: string;
  className?: string;
  onCitationClick?: (citationId: number) => void;  // for research reports
}
```

Features:
- GitHub-flavored markdown (tables, task lists, strikethrough)
- Syntax-highlighted code blocks
- Citation link interception (`[N]` → `onCitationClick(N)`)
- Tailwind prose styling (`prose prose-sm dark:prose-invert`)
- Sanitized HTML output (no XSS)

**Retrofit existing views**: Once this component exists, replace `whitespace-pre-wrap` rendering in chat.tsx, console.tsx, and output-preview-panel.tsx. Every agent response instantly looks better.

### 11.4 `<MissionLiveView>` — The Three-Panel Experience

**File**: `modules/frontend/src/components/mission/mission-live-view.tsx`

This is an **overlay component** that appears within the mission workspace when an execution is actively running. It does NOT replace the 8-tab structure — it sits above it and hides when idle. Triggered by the existing `useLiveRunStore` detecting an active run.

```
┌─────────────────────────────────────────────────────────────────┐
│  Mission: "AI Coding Assistant Landscape"          [$8.42] [4m] │
├──────────────┬──────────────────────────┬──────────────────────┤
│              │                          │                      │
│  ACTIVITY    │     WORKSPACE            │    ARTIFACTS         │
│  FEED        │                          │                      │
│              │  ┌─ Sub-questions ────┐  │  Sources (47)        │
│  "Breaking   │  │ ✓ Architectures   │  │  ┌──────────────┐   │
│   into 7     │  │ ✓ Pricing models  │  │  │ cursor.com   │   │
│   sub-qs..." │  │ ◉ Enterprise...   │  │  │ relevance 92%│   │
│              │  │ ○ Open source...  │  │  │ "The arch... │   │
│  "Searching: │  └───────────────────┘  │  └──────────────┘   │
│   AI coding  │                          │  ┌──────────────┐   │
│   assistant  │  Coverage: ████████░ 71% │  │ github.blog  │   │
│   2025..."   │                          │  │ relevance 88%│   │
│              │  ─── Report ──────────── │  └──────────────┘   │
│  "Found 3    │  # Competitive Landscape │                      │
│   sources    │                          │  ┌──────────────┐   │
│   from       │  The AI coding assistant │  │ ...more      │   │
│   Anthropic" │  market has converged on │  └──────────────┘   │
│              │  three dominant...       │                      │
│  "Coverage   │  [streaming...]          │  Verification       │
│   at 71%..." │                          │  21/23 ✓ (91.3%)   │
│              │                          │                      │
├──────────────┴──────────────────────────┴──────────────────────┤
│  ◉ Researching  │  Iteration 2/5  │  47 sources  │  $8.42     │
└─────────────────────────────────────────────────────────────────┘
```

### 11.5 New Components

| Component | File | Responsibility |
|---|---|---|
| `<MarkdownRenderer>` | `components/ui/markdown-renderer.tsx` | Platform-wide markdown + code rendering. Used by all views. |
| `<MissionLiveView>` | `components/mission/mission-live-view.tsx` | Three-panel overlay during active execution. Orchestrates the sub-components below. |
| `<NarrativeFeed>` | `components/live/narrative-feed.tsx` | Left panel. Scrolling text feed of `ResearchNarrativeEvent`s with auto-scroll. Each entry has a timestamp, phase icon, and message. |
| `<SubQuestionTree>` | `components/mission/sub-question-tree.tsx` | Center panel (research-specific). Live status badges: `○` pending, `◉` searching (animated), `✓` covered, `✗` gap. Driven by `ResearchSubQuestionUpdatedEvent`. |
| `<CoverageRing>` | `components/ui/coverage-ring.tsx` | Animated SVG progress ring 0→100%. Driven by `ResearchCoverageEvent`. Shows percentage + label. |
| `<StreamingReport>` | `components/mission/streaming-report.tsx` | Center panel (below tree). Renders `AgentResponseChunkEvent` chunks (filtered by `source.startsWith("research:")`) through `<MarkdownRenderer>`. Growing document with scroll-to-bottom. |
| `<ArtifactPanel>` | `components/live/artifact-panel.tsx` | Right panel. Cards appearing in real-time as `ResearchSourceFoundEvent`s arrive. Each card: title, URL, snippet preview, relevance badge. Clickable to expand full excerpt. |
| `<CitationTooltip>` | `components/ui/citation-tooltip.tsx` | Hover/click `[N]` in report → popover showing source excerpt + link. Powered by sources stored in `useResearchStore`. |
| `<LiveFooter>` | `components/live/live-footer.tsx` | Extend existing. Add phase indicator, iteration counter, source count alongside existing cost/task counters. |

### 11.6 New State: `useResearchStore`

**File**: `modules/frontend/src/stores/research.ts`

```typescript
interface ResearchState {
  // Identity
  researchId: string | null;
  query: string;
  depth: string;

  // Sub-questions (live tree)
  subQuestions: SubQuestion[];           // [{id, text, status, sourceCount}]

  // Sources (live feed)
  sources: SourceCard[];                 // [{url, title, snippet, relevance, subQuestionId}]

  // Coverage (live ring)
  coverageRatio: number;                 // 0.0–1.0
  iteration: number;
  maxIterations: number;

  // Report (streaming)
  reportChunks: string[];                // accumulated markdown chunks
  reportComplete: boolean;

  // Verification
  verificationScore: number | null;
  citationVerdicts: CitationVerdict[];

  // Narrative (activity feed)
  narrativeEvents: NarrativeEntry[];     // [{timestamp, phase, message}]

  // Actions
  handleEvent(event: SseEvent): void;    // routes SSE events to state updates
  reset(): void;
}
```

The `handleEvent` method is the single integration point — called from the existing `useRunStream` hook whenever a `research.*` event arrives. It routes each event type to the appropriate state update. No new SSE connections needed.

### 11.7 SSE Integration

The existing `useRunStream(sessionId)` hook already receives all session events. Add a `research.*` event handler that delegates to `useResearchStore.handleEvent()`:

```typescript
// In the existing useRunStream event handler:
if (event.event_type.startsWith('research.')) {
  useResearchStore.getState().handleEvent(event);
}
// AgentResponseChunkEvent for streaming report (source starts with "research:")
if (event.event_type === 'agent.response.chunk' &&
    (event.source ?? '').startsWith('research:')) {
  useResearchStore.getState().handleEvent(event);
}
```

The `<MissionLiveView>` detects that a research loop is running (first `research.started` event) and switches the workspace content from the default task view to the research-specific sub-question tree + streaming report.

### 11.8 Markdown Retrofit (Existing Views)

Once `<MarkdownRenderer>` exists, apply it to:

| View | Current | After |
|---|---|---|
| Chat messages | `whitespace-pre-wrap` | `<MarkdownRenderer content={message.content} />` |
| Console event detail | `whitespace-pre-wrap` | `<MarkdownRenderer content={detail} />` |
| Output preview panel | JSON dump / raw text | `<MarkdownRenderer>` for text, keep JSON view for structured data |
| Workshop output | Raw text | `<MarkdownRenderer>` |

This is a quick win that makes the entire platform look more polished — not just research.

### 11.9 What NOT to Change

- **Don't touch the 8-tab structure** — it works for mission management
- **Don't replace the Console** — power users need raw events for debugging
- **Don't replace Chat** — it stays conversational, but gets markdown rendering
- **Don't build a custom editor** — reports are read-only; agents create them
- **Don't add PDF export in Phase 1** — markdown is the deliverable format

---

## 12. Dependencies

**Backend (Python):**
```
pip install tavily-python    # Tavily search API client
pip install trafilatura       # Content extraction (F1 0.958)
pip install readability-lxml  # Fallback content extraction
```

**Frontend (npm):**
```
npm install react-markdown remark-gfm rehype-highlight highlight.js
```

---

## 13. Implementation Order (Critical Path)

### Phase 1: Search Infrastructure
1. `modules/backend/schemas/research.py` — all research schemas
2. `modules/backend/services/search/__init__.py`
3. `modules/backend/services/search/web_search.py` — Tavily + Brave
4. `modules/backend/services/search/content_extract.py` — Trafilatura cascade
5. `modules/backend/services/search/codebase_search.py` — wrap existing codemap
6. `modules/backend/agents/tools/research.py` — thin tool wrappers
7. Tests for search services (mocked HTTP)

### Phase 2: Research Agents (5 agents × 4 files = 20 files)
1. `research.searcher.agent` — simplest, tests tool integration
2. `research.strategist.agent` — query decomposition + refinement
3. `research.analyst.agent` — coverage evaluation + gap analysis
4. `research.synthesizer.agent` — report generation with citations (streaming output)
5. `research.verifier.agent` — NLI citation verification
6. Research category prompt: `config/prompts/categories/research.md`

### Phase 3: Research Loop Executor + Dispatch Integration + Experience Events
1. `modules/backend/agents/mission_control/dispatch/research_loop.py` — core loop with narrative event emission at every phase transition
2. Task-type routing in `modules/backend/agents/mission_control/dispatch/loop.py` — detect `type: research_loop` in resolved inputs (which arrive from the workflow template's static inputs, not the Planning Agent), route to `execute_research_loop()` via `_execute_research_task()` wrapper that emits PlanStepStarted/Completed events
3. Planning Agent system prompt update: add single-task loop hint (§3.1 — minimal, general-purpose, not research-specific)
4. All research event types in `modules/backend/events/types.py` — `ResearchNarrativeEvent`, `ResearchSourceFoundEvent`, `ResearchSubQuestionUpdatedEvent`; **do not add ResearchReportChunkEvent** — reuse existing `AgentResponseChunkEvent`
5. Streaming synthesis integration — loop executor streams synthesizer output as `AgentResponseChunkEvent`s with `source=f"research:{task_id}"`

### Phase 4: Workflow & Integration
1. `config/workflow_templates/research.deep-research.workflow.yaml`
2. `config/mission_control/rosters/research_team.yaml`
3. `config/settings/research.yaml`
4. `start_research` tool in mission.director.agent
5. `get_research_findings` tool in mission.director.agent (follow-up conversation)
6. End-to-end integration test

### Phase 5: Persistence & Knowledge
0. **Prerequisite**: Move `_MCD_MAX_SIZE` and `_MCD_TARGET_SIZE` out of `modules/backend/services/mission_context.py` and into `config/settings/missions.yaml` (or equivalent config). These are currently hardcoded to 20KB/15KB — not appropriate for a research system writing potentially large context updates. Load them via `get_app_config()` instead.
1. `modules/backend/models/research.py` — ResearchReport model
2. Alembic migration
3. `modules/backend/repositories/research.py`
4. `modules/backend/services/research.py` — ResearchService (persist + retrieve)
5. `GET /api/v1/research/reports` — API endpoint for report retrieval
6. MCD context_updates flow (via existing ContextCurator)

### Phase 6: Frontend — Mission Live View + Markdown Renderer
1. Install frontend dependencies: `react-markdown`, `remark-gfm`, `rehype-highlight`, `highlight.js`
2. `<MarkdownRenderer>` component — platform-wide, used by all views
3. Retrofit existing views: chat messages, console detail, output preview, workshop → use `<MarkdownRenderer>`
4. `useResearchStore` — Zustand store for research-specific state
5. Wire `research.*` events from existing `useRunStream` hook → `useResearchStore.handleEvent()`
6. `<NarrativeFeed>` — left panel activity feed
7. `<ArtifactPanel>` — right panel source cards
8. `<SubQuestionTree>` + `<CoverageRing>` — center panel research workspace
9. `<StreamingReport>` + `<CitationTooltip>` — center panel report view
10. `<MissionLiveView>` — three-panel orchestrator, overlay during active execution
11. `<LiveFooter>` — extend existing with research phase/iteration/source counters

### Phase 7 (Future): Platform Experience Generalization
1. Extract platform primitives: `MissionNarrativeEvent`, `MissionArtifactFoundEvent`, `TaskStatusUpdatedEvent` from research-specific events
2. Retrofit existing mission types (code quality, health check, architecture review) to emit narrative + artifact events — every mission feels alive
3. Cross-mission knowledge base (KnowledgeEntry model + service)
4. Source caching (Redis-backed SourceCacheService)
5. Per-iteration checkpoint persistence (crash recovery)
6. Vector embeddings for semantic knowledge search (pgvector)

---

## 14. Verification Plan

1. **Unit tests**: Search services with mocked HTTP (httpx mock), content extraction with fixture HTML, deterministic coverage scoring
2. **Agent tests**: PydanticAI TestModel — validate output schemas and tool calls for all 5 agents independently
3. **Integration test**: End-to-end research loop with TestModel agents, verify:
   - Event emission sequence: narrative events at every phase, source events per-source, sub-question status updates, report streaming chunks, final completion
   - Deterministic coverage score computation from analyst structured output
   - Findings compression (top-K filtering before synthesis)
   - Budget enforcement (stops when cumulative cost exceeds budget)
   - Iteration control (stops on coverage threshold, diminishing returns, max iterations)
   - Gate behavior (abort between iterations)
   - Concurrency limit (semaphore prevents > N concurrent searchers)
4. **Streaming test**: Verify synthesizer streams `ResearchReportChunkEvent`s and the final report matches the concatenated chunks
5. **Planning Agent test**: Verify that given research_team roster, the Planning Agent creates a single task (TestModel with expected output fixture). The `type: research_loop` comes from the workflow template static inputs, not from the Planning Agent — verify the Planning Agent does NOT need to output the type.
6. **Dispatch routing test**: Verify `_execute_layer` routes `type: research_loop` tasks (from static workflow inputs) to `execute_research_loop()` instead of `execute_task()`
7b. **Budget batch-size test**: Verify that when remaining budget allows only 3 searchers, a batch of 8 gap questions dispatches at most 3 searchers (not all 8).
7. **Report delivery test**: Verify ResearchReport is persisted to DB, MCD receives condensed context_updates, and report is accessible via API endpoint
8. **Follow-up conversation test**: Verify Mission Director can retrieve research findings and answer questions about them
9. **Demo test**: Manual end-to-end with real Tavily API key — verify the narrative event stream tells a coherent story, sources appear live, report streams in, citations are valid
