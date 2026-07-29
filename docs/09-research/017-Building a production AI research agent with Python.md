# Building a production AI research agent with Python

**The canonical architecture for a deep research agent follows a Plan→Search→Synthesize loop with parallel execution, external memory, and multi-model routing.** This pattern, validated by systems from Anthropic, OpenAI, and Google, can be implemented with PydanticAI for agent orchestration, FastStream/NATS for async task distribution, and a cascading stack of search APIs and content extractors. The key insight from production systems: **token budget explains ~80% of research quality variance**, making multi-agent parallelism with context isolation the dominant strategy over single-agent approaches. Below is a complete technical blueprint for building this system.

---

## How Claude Research, Perplexity, and Deep Research actually work

Every major deep research system implements the Plan→Search→Synthesize loop, but with fundamentally different orchestration strategies:

**OpenAI Deep Research** uses a single **o3-deep-research** model trained end-to-end with reinforcement learning on browsing tasks. It runs a ReAct loop (Plan-Act-Observe) with a lightweight gpt-4.1 clarifier upfront. A single query triggers **30–60 web searches**, **120–150 page fetches**, and takes 5–30 minutes. The model learned search strategy, backtracking, and pivoting through RL — not prompt engineering. Stopping criteria combine coverage-based checks (2+ independent sources per sub-question) with hard budget limits on time, searches, and reasoning iterations.

**Anthropic Claude Research** takes the opposite approach: an **orchestrator-worker pattern** where Claude Opus 4 acts as lead researcher, spawning 3–10 parallel Claude Sonnet 4 subagents. Each subagent gets an independent context window, preventing "context rot" — the degradation that occurs as a single context fills up. Multi-agent outperformed single-agent by **90.2%** on Anthropic's internal benchmark. The lead agent stores its research plan in external memory to survive context truncation, and subagents write findings to a filesystem rather than passing them through conversation history.

**Google Gemini Deep Research** uses an asynchronous task manager with shared state between a planner model and execution models, browsing up to hundreds of websites in under 20 minutes. **Perplexity** operates differently as a real-time answer engine built on a Vespa-powered index of **200B+ URLs**, routing queries through classifier models to select the cheapest adequate LLM. **Stanford STORM** takes the most creative approach: it simulates multi-perspective expert conversations, discovering diverse viewpoints from similar Wikipedia articles and using each perspective to generate deeper questions.

The canonical state machine for a research agent graph looks like this:

```python
from typing import TypedDict, List, Optional

class ResearchState(TypedDict):
    query: str
    research_plan: List[str]       # Decomposed sub-questions
    search_queries: List[str]       # Generated search terms
    sources: List[dict]             # Retrieved source documents
    findings: List[str]             # Extracted key findings
    gaps: List[str]                 # Identified information gaps
    iteration: int
    max_iterations: int
    final_report: Optional[str]

def should_continue(state: ResearchState) -> str:
    if state["iteration"] >= state["max_iterations"]:
        return "synthesize"
    if not state["gaps"]:  # No gaps identified
        return "synthesize"
    return "search_more"
```

## Query decomposition determines research quality

The compositionality gap — where LLMs correctly answer simple sub-queries but fail on their compositions — **widens non-linearly with query complexity**. This makes decomposition essential. Four proven patterns dominate production systems:

**Parallel decomposition** (Anthropic's approach) breaks a query into 3–7 independent subtasks executed simultaneously. A cheap model handles decomposition; expensive models handle each research thread. This is ideal for analytical questions where subtopics are independent. **Sequential iterative decomposition** (OpenAI's approach) interleaves reasoning and retrieval in a single chain-of-thought, letting each search result inform the next query. This works better for multi-hop questions requiring chained evidence. **Perspective-guided decomposition** (STORM) discovers diverse viewpoints first, then generates questions from each perspective — producing broader, less biased research. **DAG-based planning** (used by Egnyte's production system) models research as a directed acyclic graph with explicit dependencies, enabling topological traversal for maximum parallelism.

The practical prompt pattern for decomposition follows the "start wide, then narrow" principle documented by Anthropic:

```python
DECOMPOSITION_PROMPT = """Break this research question into 3-7 sub-questions.
For each, specify the sub-question, why it matters, what source
type would best answer it, and priority (high/medium/low).

Rules:
- Phase 1 queries should be SHORT and BROAD (2-4 words)
- Phase 2 narrows based on what's found
- WRONG: "specific regulatory requirements for AI medical devices
  in the EU under MDR 2017/745"
- RIGHT: Start with "AI medical device regulation" → then narrow

Question: {query}"""
```

Gap analysis after each iteration drives the search-vs-synthesize decision. The FAIR-RAG approach uses Structured Evidence Assessment to evaluate coverage, scoring **4.45/5.0** on query refinement quality. When 2+ independent sources cover each sub-question and no new information emerges from recent searches, synthesis begins.

## PydanticAI orchestrates the agent graph with type safety

PydanticAI provides the cleanest abstraction for building research agents in this stack. Its dependency injection system threads external services (search clients, databases) through `RunContext`, while structured outputs guarantee valid research reports via Pydantic model validation with automatic LLM retry on failure.

The core agent pattern wires search tools, content extractors, and state tracking through dependency injection:

```python
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

@dataclass
class ResearchDeps:
    http_client: httpx.AsyncClient
    search_api_key: str
    collected_sources: list[str] = field(default_factory=list)

class ResearchReport(BaseModel):
    title: str
    executive_summary: str
    findings: list[dict] = Field(description="Key findings with evidence")
    sources: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

research_agent = Agent(
    'anthropic:claude-sonnet-4-5',
    deps_type=ResearchDeps,
    output_type=ResearchReport,
    instructions='Research analyst. Use tools to search and extract, then produce a structured report.',
)

@research_agent.tool
async def web_search(ctx: RunContext[ResearchDeps], query: str) -> str:
    """Search the web for information."""
    response = await ctx.deps.http_client.get(
        'https://api.tavily.com/search',
        params={'query': query, 'search_depth': 'advanced'},
        headers={'Authorization': f'Bearer {ctx.deps.search_api_key}'}
    )
    results = response.json()
    ctx.deps.collected_sources.extend(r['url'] for r in results.get('results', []))
    return str(results)
```

**Multi-agent delegation** is where PydanticAI shines for research. A coordinator agent calls specialist agents as tools, each potentially using different models:

```python
from pydantic_ai import Agent, RunContext, UsageLimits

# Cheap model for decomposition
decomposer = Agent('groq:llama-3.3-70b-versatile', output_type=list[str],
    instructions='Break a research query into 3-5 specific sub-questions.')

# Powerful model with fallback for deep research
from pydantic_ai.models.fallback import FallbackModel
resilient_model = FallbackModel(
    'anthropic:claude-sonnet-4-5',   # Primary
    'azure:gpt-4o',                   # Fallback
    'ollama:llama3.2',                # Local last resort
)
researcher = Agent(resilient_model, deps_type=ResearchDeps, output_type=ResearchReport)

# Coordinator delegates to specialist agents
coordinator = Agent('anthropic:claude-sonnet-4-5')

@coordinator.tool
async def delegate_research(ctx: RunContext, subtopic: str) -> str:
    result = await researcher.run(subtopic, deps=ctx.deps, usage=ctx.usage)
    return result.output.model_dump_json()
```

For complex state machines with explicit transitions, PydanticAI offers `pydantic-graph`:

```python
from pydantic_graph import Graph, BaseNode, End, GraphRunContext

@dataclass
class ResearchState:
    query: str = ''
    search_results: list[str] = field(default_factory=list)
    draft: str = ''
    revision_count: int = 0

@dataclass
class SearchNode(BaseNode[ResearchState]):
    async def run(self, ctx: GraphRunContext[ResearchState]) -> WriteNode:
        # Execute searches, populate ctx.state.search_results
        return WriteNode()

@dataclass
class ReviewNode(BaseNode[ResearchState]):
    async def run(self, ctx: GraphRunContext[ResearchState]) -> WriteNode | End[str]:
        if ctx.state.revision_count >= 3 or quality_sufficient(ctx.state.draft):
            return End(ctx.state.draft)
        ctx.state.revision_count += 1
        return WriteNode()  # Loop back for revision

graph = Graph(nodes=[SearchNode, WriteNode, ReviewNode])
```

**FallbackModel** is critical for production resilience. Disable SDK-level retries (`max_retries=0`) for fast failover, and use `ConcurrencyLimitedModel` to cap parallel requests per provider. Cost-aware routing uses a cheap classifier to determine task complexity, then routes to the appropriate model tier.

## Choosing search APIs for high-volume agent research

For a production agent doing 10–50+ searches per task, the search API choice significantly impacts both quality and cost. Two legacy options are no longer viable: **Bing Web Search API shut down in August 2025**, and **Google Custom Search is closed to new customers** with migration required by January 2027.

The current landscape breaks into distinct tiers. **Brave Search API** achieved the highest Agent Score (**14.89** in the AIMultiple December 2025 benchmark) with the lowest latency (**669ms average**) and an independent 30B+ page index, but returns snippets only — no full content extraction. **Tavily** is the de facto standard for AI agents, used as the default search engine in GPT-Researcher and deeply integrated with LangChain/PydanticAI ecosystems, returning AI-optimized structured results at **$5–8/1k queries**. **Exa.ai** offers built-in full-page content extraction with neural semantic search, scoring 91% on SimpleQA, but performs poorly on time-sensitive queries (24% FreshQA). **Serper.dev** is the budget champion at **$0.30–1/1k queries** with real Google SERP results and 300 QPS throughput, but returns SERP metadata only.

| API | Cost/1k queries | Full content? | Latency | Best for |
|-----|----------------|---------------|---------|----------|
| **Brave Search** | $5–9 | Snippets only | ~670ms | Quality + speed |
| **Tavily** | $5–8 | Via Extract endpoint | ~1.9s | Agent ecosystems |
| **Exa.ai** | $7–15 | Built-in | ~1.2s | Semantic/factual |
| **Serper.dev** | $0.30–1 | SERP only | ~1–2s | Budget scale |
| **You.com** | $5 (+$1 content) | Via Contents API | ~400ms | Freshness |
| **Firecrawl** | Varies | Built-in | ~2s | All-in-one |

The optimal strategy for production uses **Tavily as primary** (best ecosystem integration, proven architecture), **Brave as secondary** (independent index provides different perspective, top quality scores), and **Jina Reader for content extraction** when full page text is needed beyond snippets. At 30 searches per task and 100 tasks/month, this costs approximately **$30–50/month**. For budget-constrained deployments, Serper.dev + Jina Reader handles the same workload for under $10/month.

## Content extraction feeds clean text to the synthesis pipeline

Raw web pages are HTML soup. The extraction layer must produce clean, LLM-ready text while preserving source provenance. **Trafilatura** leads open-source extractors with an **F1 score of 0.958** (outperforming newspaper4k at 0.949 and Mozilla Readability at 0.947), runs at production scale on millions of documents, and outputs directly to Markdown — reducing token count ~67% versus raw HTML. It cannot handle JavaScript-rendered pages, however.

The production pattern uses a **cascading fallback** pipeline:

```python
import trafilatura
from readability import Document

def extract_content(url: str, html: str = None) -> str:
    # Tier 1: Trafilatura (fastest, best F1)
    downloaded = html or trafilatura.fetch_url(url)
    if downloaded:
        result = trafilatura.extract(downloaded, output_format='markdown',
                                      include_tables=True)
        if result and len(result) > 200:
            return result

    # Tier 2: readability-lxml
    doc = Document(downloaded or requests.get(url).text)
    if (summary := doc.summary()) and len(summary) > 200:
        return html_to_markdown(summary)

    # Tier 3: Jina Reader API (handles JS rendering)
    resp = requests.get(f"https://r.jina.ai/{url}",
                        headers={"Accept": "application/json"})
    if resp.ok:
        return resp.json().get("content", "")

    # Tier 4: Playwright for JS-heavy SPAs (slowest, most reliable)
    return playwright_render_and_extract(url)
```

For managed solutions, **Crawl4AI** (50k+ GitHub stars) provides async Playwright-based crawling with built-in chunking strategies, anti-bot detection, and LLM-ready Markdown output — entirely free and open-source. **Firecrawl** offers a paid all-in-one alternative with search + extraction + agent endpoints.

**Chunking** peer-reviewed benchmarks (Vectara NAACL 2025) found that **recursive character splitting at 512 tokens with 10–20% overlap** consistently outperforms semantic chunking on realistic document sets. Semantic chunking achieves 91.9% retrieval recall but only 54% end-to-end accuracy because fragments average just 43 tokens — too small for useful LLM context. For relevance scoring, a three-stage pipeline of BM25 → dense embedding retrieval → **cross-encoder reranking** delivers the best results. Cross-encoder rerankers like `ms-marco-MiniLM-L-6-v2` dramatically outperform pure vector similarity for selecting which chunks actually answer the query.

## Synthesis with citations requires grounding at every step

Source provenance must be preserved from retrieval through synthesis — not retrofitted after generation. The most reliable approach uses **[N] numbered inline citations** embedded in the generation prompt, with each source assigned an ID that maps back to its URL, title, and extracted content.

```python
SYNTHESIS_PROMPT = """Synthesize information from sources into a comprehensive answer.

RULES:
1. Use ONLY the provided sources. Cite with [1], [2] after every claim.
2. Every factual statement MUST have at least one citation.
3. If sources conflict, note the disagreement and cite both.
4. NEVER fabricate information not in the sources.

SOURCES:
{formatted_sources}

QUESTION: {query}"""
```

Research shows LLMs achieve only **~74% citation accuracy** in generative search (CiteFix, arXiv 2504.15629). Post-processing verification is essential. An NLI-based cross-encoder checks whether each cited source actually entails the claimed statement:

```python
from sentence_transformers import CrossEncoder

def verify_citations(response, sources) -> dict:
    nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")
    verified = 0
    for citation in response.citations:
        source = sources[citation.source_id - 1]
        score = nli_model.predict([(source.text, citation.claim)])
        if float(score[0]) > 0.3:
            verified += 1
    return {"total": len(response.citations), "verified": verified}
```

The **quote-then-answer** approach reduces hallucination further by forcing the LLM to first extract exact quotes from sources, then synthesize only from those quotes. Perplexity operates on an even stricter principle: "you are not supposed to say anything that you didn't retrieve." For maximum grounding, combine citation-forcing prompts with a post-hoc verification loop that re-prompts the model to revise any ungrounded claims identified by the NLI checker.

## FastStream with NATS handles async fan-out/fan-in

FastStream integrates into FastAPI via `NatsRouter`, sharing dependency injection and running message handlers alongside HTTP endpoints in the same application. **NATS with JetStream** is the recommended broker for research agents: sub-millisecond core latency, native request-reply for agent coordination, wildcard subject matching (`research.search.*`), built-in queue groups for load balancing, and a KeyValue store for task state — all from a single 20MB Go binary with minimal operational overhead.

The fan-out/fan-in pattern for parallel search distribution:

```python
from faststream.nats.fastapi import NatsRouter
from faststream.nats import JStream

router = NatsRouter("nats://localhost:4222")
research_stream = JStream("RESEARCH", subjects=["research.>"])

# Coordinator fans out search sub-tasks
@router.subscriber("research.requests", stream=research_stream)
async def coordinate(request: ResearchRequest, logger):
    for source_type in ["web", "arxiv", "docs"]:
        await router.broker.publish(
            SearchSubTask(task_id=request.task_id, query=request.query,
                          source_type=source_type),
            f"research.search.{source_type}", stream="RESEARCH")

# Workers process in parallel with concurrency control
@router.subscriber("research.search.web", stream=research_stream, max_workers=10)
async def search_web(task: SearchSubTask, logger):
    results = await perform_web_search(task.query)
    await router.broker.publish(
        SearchResult(task_id=task.task_id, results=results),
        "research.results", stream="RESEARCH")

# Aggregator collects results and triggers synthesis
@router.subscriber("research.results", stream=research_stream)
async def aggregate(result: SearchResult, db=Depends(get_db)):
    await save_result(db, result)
    if await all_subtasks_complete(db, result.task_id):
        await router.broker.publish({"task_id": result.task_id}, "research.synthesize")
```

**Streaming progress to users** uses Server-Sent Events. Workers publish progress updates to a NATS subject; an SSE endpoint subscribes and streams events to the browser:

```python
from fastapi.sse import EventSourceResponse  # FastAPI >= 0.135.0

@app.get("/research/{task_id}/stream", response_class=EventSourceResponse)
async def stream_progress(task_id: str):
    queue = asyncio.Queue()
    progress_queues[task_id] = queue
    try:
        while True:
            update = await asyncio.wait_for(queue.get(), timeout=30.0)
            yield {"event": "progress", "data": json.dumps(update)}
            if update.get("status") == "completed":
                break
    finally:
        progress_queues.pop(task_id, None)
```

For task state persistence, PostgreSQL tracks research tasks and subtasks with checkpoint-based resumability, while **TimescaleDB hypertables** store time-series agent performance metrics (search latency, token usage, source quality) with automatic compression and continuous aggregates for dashboards.

## What open-source implementations teach us

**GPT-Researcher** (25.7k stars) is the most battle-tested implementation. It uses a Plan-and-Execute pattern: a planner generates research questions, parallel crawler agents scrape sources for each question, a summarizer condenses findings, and a publisher produces the final report. Average cost is **~$0.005–$0.10 per task** in 2–3 minutes. Its enhanced multi-agent mode adds editor, reviewer, and revisor agents for iterative quality improvement.

**STORM** (Stanford) takes the most academically rigorous approach, simulating multi-perspective expert conversations before writing. It discovers diverse viewpoints from similar Wikipedia articles, then uses each perspective to control question generation — yielding 25% better organization and 10% broader coverage versus baselines. 70% of Wikipedia editors found STORM's output helpful for pre-writing.

**dzhng/deep-research** is the minimalist reference implementation at **under 500 lines of code**. It elegantly controls research scope through two parameters: `breadth` (parallel queries per iteration) and `depth` (recursive iterations). Each recursion halves the breadth and decrements depth, creating a tree of progressively focused searches. This is the best starting point for understanding the core loop.

**DeerFlow 2.0** (ByteDance, 45k+ stars) evolved into a production-grade SuperAgent harness with Docker-sandboxed execution, Kubernetes support, and parallel sub-agent architecture that cuts research time by ~75%. **Egnyte's production system** provides the most detailed public architecture documentation, using DAG-based research planning with topological traversal, cross-encoder reranking, and Maximal Marginal Relevance diversification.

Critical lessons across all implementations: context isolation per subagent prevents degradation; cross-encoder reranking dramatically outperforms vector similarity for source selection; tool descriptions matter enormously (Anthropic found agent-rewritten descriptions improved task completion by 40%); and scaling effort to query complexity — not every question needs 10 subagents.

## Putting it all together

The complete production architecture wires these components into a coherent system:

```
FastAPI HTTP Layer
  ├── POST /research/start → Publishes to NATS "research.requests"
  ├── GET /research/{id}/stream → SSE progress stream
  └── GET /research/{id}/result → Final report from PostgreSQL

FastStream/NATS Message Layer
  ├── research.requests → Coordinator (PydanticAI Agent, Claude Sonnet)
  │     ├── Decomposes query (Groq/Llama, cheap model)
  │     ├── Fans out to research.search.{source_type}
  │     └── Monitors progress, triggers synthesis
  ├── research.search.* → Worker Agents (PydanticAI, FallbackModel)
  │     ├── Search via Tavily/Brave API
  │     ├── Extract via Trafilatura → Jina fallback
  │     ├── Chunk (512 tokens, recursive) → Rerank (cross-encoder)
  │     └── Publish results to research.results
  ├── research.results → Aggregator
  │     ├── Stores in PostgreSQL
  │     ├── Publishes progress to research.progress
  │     └── Triggers research.synthesize when complete
  └── research.synthesize → Synthesis Agent (Claude Opus, expensive model)
        ├── Builds cited report from all findings
        ├── Verifies citations via NLI cross-encoder
        └── Stores final report in PostgreSQL

PostgreSQL/TimescaleDB
  ├── research_tasks (state, checkpoints, results)
  ├── search_subtasks (per-source tracking)
  └── agent_metrics (TimescaleDB hypertable for observability)
```

The minimum viable implementation requires roughly 2,000 lines of Python: a PydanticAI coordinator agent with search tools, Tavily for search, Trafilatura for extraction, recursive chunking, and a synthesis prompt with [N] citations. Scale from there by adding FastStream for async distribution, multiple search providers for redundancy, cross-encoder reranking for relevance, and NLI verification for citation accuracy. Start with dzhng/deep-research's 500-line recursive pattern to validate the core loop, then layer in the production infrastructure.

## Conclusion

Building a production research agent is less about novel algorithms and more about engineering the right composition of proven patterns. The Plan→Search→Synthesize loop with parallel multi-agent execution is the winning architecture, validated independently by Anthropic, OpenAI, Google, and multiple open-source projects. PydanticAI's type-safe agent abstraction with dependency injection maps naturally to this pattern, while FastStream/NATS provides the async backbone for fan-out/fan-in without Kafka's operational weight. The most impactful single decision is search API choice — Tavily for ecosystem integration, Brave for quality, Serper for budget — paired with Trafilatura's 0.958 F1 extraction and cross-encoder reranking. Citation verification via NLI models closes the grounding gap that raw LLM generation leaves open. The open-source ecosystem, particularly GPT-Researcher and STORM, provides production-tested reference architectures to build from rather than designing from scratch.
