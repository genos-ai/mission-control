# Cutting Anthropic spend on the BFA platform

**Bottom line up front.** The cheapest and most compliant way to reduce Anthropic costs on your PydanticAI-based Mission Control deep-research platform is not to reroute Claude Max through OAuth proxies (that pattern is now explicitly banned, technically blocked, and economically nullified) but to **re-architect BFA around a self-hosted LiteLLM gateway**, push most agent steps to **Gemini 2.5 Flash, GPT-5.4-mini, or DeepSeek V3.2 via Fireworks**, keep **Claude Sonnet 4.6 only for planning and final synthesis with aggressive prompt caching**, and offload cheap sub-tasks (reranking, summarisation, classification) to **local MLX inference on your M4 Max**. Realistic saving versus your current all-Anthropic baseline is **65–85 percent per research run** with no meaningful quality loss, and every element of the recommended stack sits inside sanctioned terms of service.

The rest of this briefing gives you the regulatory, technical, and commercial evidence behind that conclusion, in a structure you can hand to engineering and to procurement without modification.

---

## 1.0 Anthropic Max and Claude Code OAuth for programmatic use

### 1.1 The regulatory position as of April 2026

Consumer Terms §3.7 have forbidden non-API automated access since 2024, but the controlling document for your question is the new **Claude Code Legal and Compliance page** (code.claude.com/docs/en/legal-and-compliance), published in February 2026. It states plainly that **OAuth authentication is intended exclusively for ordinary individual use of Claude Code and other native Anthropic applications**, and that **using OAuth tokens obtained through Claude Free, Pro, or Max accounts in any other product, tool, or service, including the Agent SDK, is not permitted and constitutes a violation of the Consumer Terms**. Anthropic reserves the right to enforce without notice. The Agent SDK documentation itself now repeats the ban: developers building products that interact with Claude, including via the Agent SDK, must use API key authentication through Claude Console, Bedrock, Vertex, or Foundry.

### 1.2 What actually happened with Clawdbot and OpenClaw

Peter Steinberger's **Clawdbot** (November 2025, ~100k GitHub stars by January) was the trigger. On **9 January 2026** Anthropic deployed server-side blocks that detected third-party tools spoofing the Claude Code harness and mass-banned associated accounts. Anthropic legal sent a trademark cease-and-desist on 27 January; the project was renamed Moltbot, then **OpenClaw**. Steinberger joined OpenAI in mid-February. On **4 April 2026** Anthropic shifted from outright blocking to a **pay-as-you-go "extra usage" billing tier** for third-party tool traffic on Pro/Max, producing **10–50× cost spikes** for ~135,000 OpenClaw instances. Boris Cherny, Anthropic's head of Claude Code, was unambiguous in the accompanying press statement: Anthropic's subscriptions "weren't built for the usage patterns of these third-party tools" and capacity will be prioritised for first-party customers and API.

### 1.3 What the Claude Agent SDK and CLI do support, headlessly, on an API key

The renamed **Claude Agent SDK** (previously Claude Code SDK) is available as `@anthropic-ai/claude-agent-sdk` (TypeScript), `claude_agent_sdk` (Python), or directly via the `claude` CLI. The sanctioned headless invocation pattern for BFA is:

```bash
claude --bare -p "research question" \
  --output-format stream-json --verbose --include-partial-messages \
  --allowedTools "Read,WebFetch,Bash" --permission-mode acceptEdits \
  --json-schema '{"type":"object","properties":{"answer":{"type":"string"}}}'
```

The `--bare` flag skips OAuth and keychain reads and demands `ANTHROPIC_API_KEY` (or Bedrock/Vertex/Foundry environment variables). Output formats `text`, `json`, and `stream-json` (NDJSON) give you retry telemetry via `system/api_retry` events, session resumption via `--resume <session_id>`, and deterministic policy enforcement via `.claude/hooks/` (PreToolUse, PostToolUse, SubagentStop, Stop, UserPromptSubmit, Notification). **Subagents** via `.claude/agents/*.md` or the `agents` SDK parameter run in fresh contexts and can execute concurrently, up to roughly 7–10 in parallel; they cannot spawn their own subagents. Custom base URL via `ANTHROPIC_BASE_URL` is explicitly supported for corporate proxies.

### 1.4 CLI wrappers — which survive ToS, which do not

A wave of proxies appeared in 2025 attempting to expose Claude Code as an OpenAI-compatible backend. As of April 2026, status by ToS posture:

**Sanctioned when used with your own API keys:** anyclaude (coder), claude-code-proxy (1rgs, fuergaosi233), UniClaudeProxy, claude-code-fastapi (e2b-dev), claude-code-router (musistudio, ~26k stars — routes "background" and "longContext" traffic to DeepSeek/Gemini/Ollama while leaving Anthropic on Anthropic, with per-provider keys), **ccusage** (ryoppippi, purely local JSONL log analysis), **Claude-Code-Usage-Monitor** (Maciek-roboblog).

**Explicitly banned by the February 2026 policy:** horselock/claude-code-proxy (PKCE OAuth against claude.ai), CLIProxyAPI's Claude path, opencode-with-claude/Meridian, any "multi-Max round-robin" project. OpenCode (anomalyco) removed Pro/Max account-key support in commit `973715f` in February 2026 citing Anthropic legal requests — a good signal that the enforcement is real and that mature OSS projects are migrating off.

**Operational reality check:** Pro/Max OAuth tokens expire in 8–12 hours and require browser-based renewal. Even setting ToS aside, the auth model is unfit for a 24/7 backend. Session windows on Max5 (~88k tokens per 5 hours) and Max20 (~220k tokens per 5 hours) are too tight for a multi-agent research platform.

### 1.5 Verdict

**Do not architect BFA around your personal Claude Max plan.** The cost arbitrage disappeared on 4 April 2026 and the contractual path is closed. Anthropic spend can only be meaningfully reduced by (a) moving most traffic off Anthropic, (b) caching aggressively what remains on Anthropic, and (c) using Bedrock or Vertex if your organisation already has committed-spend discounts there. Keep Claude Max for your personal IDE use via Claude Code on your laptop; that remains sanctioned ordinary-individual-use and is orthogonal to BFA.

---

## 2.0 Codex as a general agent backend

### 2.1 The "Codex for (almost) everything" announcement

OpenAI published **"Codex for (almost) everything"** on **16 April 2026** at openai.com/index/codex-for-almost-everything/. Thibault Sottiaux framed it as "building the super app out in the open". The release added **background computer-use agents** (macOS first), an in-app browser, image generation via `gpt-image-1.5`, memory preview for Enterprise/Education, Automations v2 (scheduling, multi-day task resumption), 90+ plugins (Atlassian Rovo, CircleCI, GitLab, Microsoft, Neon, Render), and in-app SSH to remote devboxes. Despite the title, the messaging still anchors Codex to software-lifecycle work. Wider knowledge-worker use is hinted but not formally unlocked in the ToS for non-developer workloads.

### 2.2 What Codex actually is, and where it lives

Codex is now a **multi-surface product**: the open-source Rust CLI (`codex`, installed via `npm i -g @openai/codex`), Codex Cloud async agents, IDE extensions (VS Code, Cursor, Visual Studio), the Codex macOS app (launched 2 February 2026) and Windows app (4 March 2026), Codex in ChatGPT, and `@codex` on GitHub. All surfaces authenticate against a single ChatGPT account.

**Model lineup as of mid-April 2026:** `gpt-5.3-codex` is the CLI default, `gpt-5.2-codex` is the review workhorse (being deprecated from the picker on 14 April), `gpt-5.3-codex-spark` is a fast Pro-only research preview, `gpt-5.4` is the general GPT-5 flagship usable in Codex, and `gpt-5.4-mini` is the cheap variant.

### 2.3 Codex in ChatGPT Enterprise

Codex **is included** with ChatGPT Plus, Pro, Business, Edu, and Enterprise subscriptions, but access is **rate-limited by 5-hour rolling plus weekly caps**, not token-metered at the seat level. ChatGPT Business now supports two seat types, **standard** and **Codex seats**, and Enterprise admins can purchase additional workspace credits for overflow via "flexible pricing". Sanctioned programmatic entry points are `codex exec --json --output-schema schema.json` (non-interactive JSONL events), the TypeScript SDK `@openai/codex-sdk`, and the experimental Python SDK `codex_app_server`. `codex login` uses an OAuth browser flow that draws from your plan's Codex quota; `codex login --with-api-key` is the alternative for metered billing.

### 2.4 Can you run BFA on a ChatGPT Enterprise Codex seat?

Technically yes via `codex exec` and the TS SDK. Contractually there is **no explicit ToS clause forbidding non-coding use of Codex**, and the 16 April announcement explicitly expands sanctioned scope. But three structural constraints make this a poor backend substrate for Mission Control:

- **Rate limits** are 5-hour rolling and weekly; a production deep-research platform under any non-trivial load will exhaust Plus or Business Codex quota. Enterprise overflow is billed at workspace-credit rates that approximate the API rate card — the apparent "free at the margin" advantage collapses at scale.
- **Model tuning** of `gpt-5.3-codex` is optimised for code. OpenAI's own guidance routes non-coding work to plain `gpt-5.4`. You would be using the wrong model and paying for it with Codex quota.
- There is **no OpenAI-compatible `/v1/chat/completions` endpoint reachable with only a ChatGPT login**. To hit the Responses API or Chat Completions programmatically you need an API key with separate billing.

**Recommendation:** use the OpenAI Responses API with an API key for BFA's OpenAI traffic. Keep Codex CLI for your developer-facing tools where ChatGPT Enterprise seat cost is already a sunk cost and the user owns the session.

---

## 3.0 GitHub Copilot Enterprise as a programmatic LLM backend

### 3.1 What your Copilot Enterprise seat buys

Copilot Enterprise is £39/user/month plus the required GitHub Enterprise Cloud at £21/user/month — effective **~£60 per user per month** — for 1,000 premium requests, overage at $0.04 per premium request. The full model menu is broad: **GPT-5.4, GPT-5.4-mini, GPT-5.3-Codex, GPT-4.1, Claude Haiku 4.5, Sonnet 4/4.5/4.6, Opus 4.5/4.6/4.7 (with a 7.5× premium multiplier promotion through 30 April), Gemini 2.5 Pro, Gemini 3 Flash Preview, Gemini 3.1 Pro Preview, Grok Code Fast 1**. April 2026 also introduced an `auto` model picker (GA 17 April) that routes between GPT-5.4, GPT-5.3-Codex, Sonnet 4.6, and Haiku 4.5.

### 3.2 The programmatic access question

GitHub offers **two sanctioned programmatic paths**. The first is the **GitHub Models API** at `models.github.ai`, OpenAI-compatible, billed separately from Copilot seats via a fine-grained PAT with Models:Read scope. Free-tier rate limits are low (10 RPM, 50 RPD on GPT-4o class models, 8K/4K token ceilings, 2 concurrent requests); production use requires upgrading to Azure AI Foundry Models. The second is **Copilot Extensions and Skillsets** published via the Copilot Extensibility Platform — the only way to programmatically invoke Copilot from outside IDE surfaces, and only as an extension-shaped experience.

The **unofficial path** — projects like `ericc-ch/copilot-api`, `caozhiyuan/copilot-api`, `yuchanns/copilot-openai-api`, `jmdaly/llm-github-copilot`, and LiteLLM's `github_copilot` provider — extracts the OAuth token from `~/.config/github-copilot/hosts.json` and proxies `https://api.githubcopilot.com/chat/completions`. GitHub's written position on this, from community discussion #178117, is explicit:

> "Using it as a generic model provider or integrating it into other applications outside those clients would violate GitHub's Terms of Service and the Copilot license agreement."

Copilot's Product Specific Terms define "Prompt" exclusively as "the collection of code and supporting contextual information", and GitHub's responsible-use docs state that Copilot Chat **is not designed to answer non-coding questions**. Using Copilot as the BFA backend is therefore a double breach: programmatic endpoint misuse plus domain misuse.

### 3.3 Verdict

For a CISO-led platform this is a clear prohibition. Copilot Enterprise stays as developer productivity tooling; **GitHub Models API is available if you want single-billing via Azure**, but at that point you are paying Azure rate cards, not leveraging Copilot seat value.

---

## 4.0 CLI coding agents as SDK backends — the defensible subset

Across Claude Code, Codex CLI, Aider, Cursor CLI, and Gemini CLI, the pattern that survives ToS scrutiny is narrow:

1. **Aider** is itself a Python wrapper that accepts per-vendor API keys. Legitimate for headless invocation via `aider --message "…" --yes-always`.
2. **Claude Code CLI** with `--bare -p` plus `ANTHROPIC_API_KEY` is sanctioned under Commercial Terms. This is the right shape if you want the Claude tool harness (Read, WebFetch, Bash, Edit) inside BFA.
3. **Codex CLI** with API-key mode (`codex login --with-api-key`) is sanctioned; subscription-mode is technically tolerated and Sottiaux publicly endorsed third-party harness use of Codex subscriptions, but CI recommendation is API key.
4. **Gemini CLI** followed Anthropic in blocking third-party tool OAuth during February 2026.
5. **Cursor CLI** remains subscription-locked to Cursor's own platform.

The canonical Python subprocess pattern for wrapping `claude -p` as a PydanticAI tool:

```python
import asyncio, json
async def run_claude(prompt: str, allowed_tools: list[str], cwd: str):
    proc = await asyncio.create_subprocess_exec(
        "claude", "--bare", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--allowedTools", ",".join(allowed_tools),
        "--permission-mode", "acceptEdits",
        cwd=cwd,
        env={"ANTHROPIC_API_KEY": "sk-ant-...", "PATH": "/usr/bin"},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async for line in proc.stdout:
        if line.strip():
            yield json.loads(line)
```

Wrap each call in `asyncio.timeout()`, consume `system/api_retry` events for backoff, and resume long-running sessions with `--resume <session_id>` captured from a first `--output-format json` call. Run **ccusage** (`ryoppippi/ccusage`) on the host to monitor burn by project.

---

## 5.0 LLM router and gateway selection

### 5.1 The landscape in one table

| Router | Self-host | Pricing | Caching | OpenAI-compat | Standout |
|---|---|---|---|---|---|
| **LiteLLM** (BerriAI) | Yes, MIT | OSS free; Enterprise via AWS Marketplace | Redis, exact + semantic | Yes | 2,000+ models, virtual keys, per-team budgets, Prometheus/OTEL/Langfuse sinks |
| **OpenRouter** | No, SaaS | 0% token markup; 5.5% credit-purchase fee; BYOK 5% after 1M req/mo | Anthropic cache passthrough, sticky routing | Yes | 290+ models, one key, ZDR provider filter |
| **Portkey** | Yes, Apache-2 | OSS free; hosted per-seat | Simple + semantic | Yes | 50+ guardrails, SOC2 + ISO + HIPAA + GDPR |
| **Helicone** | Yes, OSS (YC W23) | 10k req/mo free; from £20/seat | Built-in proxy cache | Yes | Observability-first, proxy or async |
| **Kong AI Gateway** | Yes, Enterprise | Konnect Plus ~£250/mo + £200/1M req; Enterprise custom | Via plugins | Yes | Unified API + MCP + A2A Agent Gateway, APIM origin |
| **Not Diamond / Martian** | SaaS | Contact sales | N/A | Yes | Predictive best-of-N routing (claims +25% accuracy / 10× cost cut) |
| **RouteLLM** (lm-sys) | Yes | Free | N/A | Yes | Academic, effectively unmaintained since Aug 2024 |
| **Bifrost** (maximhq) | Yes, Apache-2 (Go) | OSS free; Enterprise | Semantic cache | Yes | Vendor benchmark claims 9.5× faster than LiteLLM at 5k RPS |
| **Vercel AI Gateway** | No, SaaS | 0% markup even with BYOK | Paid tier | Yes + Anthropic Messages | PydanticAI-supported provider |
| **Pydantic AI Gateway** (Logfire) | No, SaaS | Bundled with Logfire Enterprise | Provider-native passthrough | Native in PydanticAI | Zero-translation, SSO/RBAC |

### 5.2 PydanticAI integration

PydanticAI's model catalogue already includes native Model/Provider classes for **OpenAI, Anthropic, Google (Gemini/Vertex), DeepSeek, xAI, Cohere, Mistral, Perplexity, Azure AI Foundry, Bedrock, Ollama, LiteLLM, Groq, OpenRouter, Together, Fireworks, Cerebras, HuggingFace, GitHub Models, Heroku, Vercel AI Gateway, Nebius, OVHcloud, DashScope, SambaNova, and the Pydantic AI Gateway**. Any OpenAI-compatible endpoint plugs in via `OpenAIChatModel` with a custom `OpenAIProvider(base_url=...)`. The `FallbackModel` primitive automates quality-or-cost failover:

```python
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.models.fallback import FallbackModel

litellm = AsyncOpenAI(api_key="sk-litellm-vk", base_url="http://litellm.internal:4000", max_retries=0)
primary = OpenAIChatModel("gemini-2.5-flash", provider=OpenAIProvider(openai_client=litellm))
secondary = OpenRouterModel("anthropic/claude-sonnet-4-6",
                             provider=OpenRouterProvider(api_key="sk-or-..."))
agent = Agent(FallbackModel(primary, secondary))
```

### 5.3 CISO-appropriate picks

For Mission Control specifically, a **two-layer gateway** is the right shape. **LiteLLM self-hosted in your VPC** is the data-plane: MIT-licensed, cosign-signed images, virtual keys per tenant or agent role, per-key budgets, Redis cache, Prometheus/OTEL/Langfuse sinks, and the reference integration for PydanticAI's OpenAI-compatible client path. Layer a **policy and guardrails component** on top: either **Portkey OSS** (50+ sync guardrails including PII, prompt injection, schema validation, Palo Alto AIRS) or the **Pydantic AI Gateway on Logfire** if you are already committed to Logfire observability. Both give SSO, RBAC, and auditability that a CISO needs for compliance.

**Avoid for compliance-first deployment:** OpenRouter and Vercel AI Gateway (SaaS only, prompts leave your network; OpenRouter is SOC 2 Type I only); RouteLLM (unmaintained); Not Diamond and Martian as primary gateways. **Bifrost** is worth piloting only if throughput becomes the binding constraint.

---

## 6.0 Cheaper providers for deep-research workloads

### 6.1 Price reference table

Verified against official pricing pages April 2026. All figures USD per 1M tokens.

| Provider | Model | In | Out | Cache read | Ctx | Tool-use | Compliance note |
|---|---|---|---|---|---|---|---|
| Anthropic | Sonnet 4.6 | $3.00 | $15.00 | $0.30 | 1M | High | SOC2, HIPAA |
| Anthropic | Opus 4.7 | $5.00 | $25.00 | $0.50 | 1M | High | New tokenizer uses ~35% more tokens |
| Anthropic | Haiku 4.5 | $1.00 | $5.00 | $0.10 | 200K | High | Best Claude $/quality |
| OpenAI | GPT-5.4 | $2.50 | $15.00 | $0.25 | 400K | High | ZDR available |
| OpenAI | GPT-5.4-mini | $0.75 | $4.50 | $0.075 | 400K | High | Sweet spot for agent loops |
| OpenAI | GPT-5.4-nano | $0.20 | $1.25 | — | 400K | Med | Extract/classify |
| Google | Gemini 2.5 Pro | $1.25/$2.50* | $10/$15* | $0.125 | 1M–2M | High | Vertex has FedRAMP High, VPC-SC |
| Google | Gemini 2.5 Flash | $0.30 | $2.50 | $0.075 | 1M | Med-High | Workhorse |
| Google | Gemini 2.5 Flash-Lite | $0.10 | $0.40 | — | 1M | Med | Cheapest mainstream |
| Google | Gemini 3.1 Pro | $2.00/$4.00* | $12/$18* | — | 1M | High | March 2026 |
| DeepSeek direct | V3.2 | $0.28 | $0.42 | $0.028 | 128K | Med-High | **PRC data path** |
| DeepSeek direct | R1 | $0.55 | $2.19 | $0.14 | 128K | Med | **PRC data path** |
| Fireworks | DeepSeek V3.2 | ~$0.56 | ~$1.68 | — | 128K | Med-High | US, SOC2+HIPAA |
| Fireworks | DeepSeek R1 | ~$3.00 | ~$8.00 | — | 128K | Med | US, SOC2+HIPAA |
| Alibaba DashScope | Qwen3-Max | $1.20–1.60 | $6.00–6.40 | — | 1M | Med-High | **PRC parent** |
| Groq | Llama 3.3 70B | $0.59 | $0.79 | 50% off | 128K | Med | 394 TPS |
| Groq | Kimi K2 0905 | $1.00 | $3.00 | — | 262K | High | Agent-trained MoE |
| Cerebras | Llama 3.3 70B | $0.60 | $0.60 | — | 128K | Med | 2,100 TPS, SOC2 |
| xAI | Grok 4.1 Fast | $0.20 | $0.50 | 50% off | 2M | Med-High | SpaceX ownership |
| xAI | Grok 4 | $3.00 | $15.00 | — | 256K | High | |

*Gemini long-context tier doubles above 200K input; OpenAI separates above 270K; Claude Sonnet long-context >200K is 2×.

### 6.2 Top three combinations for Mission Control

**Rank 1 — Gemini 2.5 Flash primary, 2.5 Pro for hard steps, on Vertex AI.** A 10-step research workflow at ~100K input plus ~3K output per step costs roughly **£0.35–0.70 per run with caching**, versus ~£3.45 uncached on Sonnet 4.5 direct. That is 70–85 percent cheaper. Flash is below Sonnet on nuanced synthesis; Pro sits within 5 percent. Vertex gives SOC2, HIPAA, ISO27001, FedRAMP High, VPC-SC, CMEK, and regional residency. PydanticAI's `GoogleModel` with `vertexai=True` handles this natively, including server-side `WebSearchTool` and `CodeExecutionTool`.

**Rank 2 — GPT-5.4-mini for the agent loop, GPT-5.4 for synthesis, OpenAI direct with ZDR.** Blended cost **~£0.60–1.10 per run**, roughly 50 percent cheaper than Sonnet-with-caching. Structured output via the Responses API is the most reliable for Pydantic validation in production. PydanticAI's `OpenAIResponsesModel` is the most mature integration path in the framework.

**Rank 3 — DeepSeek V3.2 via Fireworks for loop steps, Sonnet 4.6 for final synthesis.** Blended **~£0.40–0.80 per run** (~75 percent cheaper). V3.2's agent-post-training gives it τ²-Bench scores competitive with GPT-5-High and "thinking-in-tool-use" for multi-step reasoning. **Never use DeepSeek direct for Mission Control** — PRC data residency is disqualifying. Fireworks is SOC2 Type II plus HIPAA and US-hosted; Azure AI Foundry is the enterprise-DPA alternative. Structured output reliability is 5–10 percent below Sonnet, so validate with PydanticAI retry prompts.

**Honourable mentions:** Groq with Kimi K2 0905 for latency-bound paths; Gemini 3.1 Pro as a Sonnet-equivalent step up; Grok 4.1 Fast for workloads that can stuff raw Tavily corpora into a 2M context rather than compressing.

---

## 7.0 Prompt caching and cost-optimisation patterns

### 7.1 Anthropic prompt caching — what you are almost certainly leaving on the table

Caching premiums and discounts: **5-minute cache write at 1.25× base input**, **1-hour cache write at 2.0×**, **cache read at 0.1× (90% discount)**. Break-even is after one read for the 5-minute TTL and two reads for the 1-hour TTL. Multipliers stack with the Batch API 50 percent discount and with data-residency uplift. As of 5 February 2026 caches are workspace-isolated on the first-party API and Azure AI Foundry; Bedrock and Vertex remain org-level.

Anthropic processes requests in order `tools → system → messages`, and **tool definitions are cacheable**. For BFA the optimal layout is: stable tool schemas, then system prompt, then stable retrieved Tavily context marked with `cache_control`, then the variable user turn. Minimum cacheable prefix is 1,024 tokens on Sonnet. Exact-match is required — any whitespace change breaks reuse. Reported real-world savings run 85–95 percent on input cost for long stable prefixes; Anthropic's own book-example benchmark shows 11.5s → 2.4s latency.

**If Herman's current BFA implementation is calling Anthropic without `cache_control` markers, a single afternoon of refactoring will cut his Anthropic bill by roughly 70–80 percent on its own**, before any provider migration.

### 7.2 Batch API and context compression

The **Batch API** remains at a 50 percent discount, 24-hour SLA (most batches complete in under an hour), 100,000 requests or 256 MB per batch, with Opus 4.6 and Sonnet 4.6 supporting 300K output tokens per request via the `output-300k-2026-03-24` beta header. For Mission Control this fits nightly research digests, corpus-wide enrichment, and eval runs — not interactive user queries.

**Context editing and the memory tool** (launched 29 September 2025, beta header `context-management-2025-06-27`) are the biggest 2025-vintage feature most teams haven't adopted. `clear_tool_uses_20250919` auto-clears old tool results when a threshold is hit; `memory_20250818` gives client-controlled file-based memory outside the context window. Anthropic's internal evals show context-editing alone delivers **+29 percent** task performance over baseline and **84 percent token reduction** on web-search agents. Combined with the memory tool, **+39 percent** versus baseline. For a deep-research agent this is arguably more valuable than caching — caching cuts cost on stable prefixes, context editing cuts cost on long tool histories.

**LLMLingua-2** (Microsoft) is the best-supported open compression library for additional savings; LongLLMLingua achieves 4× compression with a +21.4 percent performance gain on NaturalQuestions and up to 94 percent cost reduction on LooGLE. Integrate between tool calls where history would otherwise grow unbounded.

### 7.3 Model cascading

Haiku 4.5 is 1/3 the cost of Sonnet and 1/5 the cost of Opus on input. The canonical pattern — classifier routes to Haiku for simple sub-tasks (classification, extraction, reranking, reformatting), Sonnet for core reasoning, Opus only on retry or high-stakes synthesis — delivers **50–60 percent per-request savings** versus all-Sonnet (CallSphere, Morph, Augment reports). Combined with caching, compaction, and batching, total reduction reaches **70–85 percent**, optimistic reports 90+ percent.

---

## 8.0 Local inference on M4 Max — the free marginal tier

### 8.1 MLX runtime choices

On a 64GB or 128GB M4 Max (546 GB/s memory bandwidth on the 16-core GPU variant), four runtimes matter:

- **`mlx_lm.server`** — native MLX, OpenAI-compatible (`/v1/chat/completions`), fastest on Apple Silicon, documented as "not production" by Apple (basic auth only).
- **LM Studio** with its `mlx-engine` — GUI-first but has a headless `lms` CLI and REST server on port 1234; the fastest practical option.
- **Ollama 0.19** (30 March 2026 preview) — MLX backend activated automatically on Apple Silicon when the model architecture is supported (Qwen3.5 first, Gemma 4 in 0.20), 32GB+ required, 1.6× prefill and 1.9× decode uplift over the llama.cpp+Metal path.
- **llama.cpp** `llama-server` — GGUF-only, Metal backend, 30–50 percent slower than MLX on Apple Silicon but the most mature headless story.

Practical ranking for BFA headless use: **mlx-lm ≈ LM Studio > Ollama 0.19 MLX > Ollama ≤0.18 ≈ llama.cpp**.

### 8.2 Realistic throughput on M4 Max

| Model | Q4 size | Decode tok/s | Fits 64GB? |
|---|---|---|---|
| Qwen3-Coder-30B-A3B (MoE, 3.3B active) | ~17.5 GB | **70–100** | Comfortably |
| Qwen3-32B dense | ~18 GB | 20–30 | Yes |
| Mistral Small 24B | ~13 GB | 35–45 | Yes |
| Gemma 3 27B | ~15 GB | 30–40 | Yes |
| DeepSeek-R1-Distill-Llama-70B | ~40 GB | **10–17** | Tight; 128GB better |
| Llama 3.3 70B Instruct | ~40 GB | 10–14 | Tight; 128GB better |

The Qwen3-Coder-30B-A3B MoE is the sweet spot: 70–100 tok/s decode, fits with plenty of KV-cache headroom on 64GB, strong tool-use and agent behaviour.

### 8.3 Where local fits in the BFA pipeline

Local MLX replaces the Haiku tier in the cascade for internal-only sub-tasks: **reranking and relevance scoring** of Tavily retrievals (Qwen3-8B or Gemma 3 4B at 80+ tok/s); **step-boundary summarisation** and conversation compaction (Qwen3-14B, Mistral Small); **draft writing** for research section composition (Qwen3-32B); **classification and routing decisions** (Qwen3-0.6B/1.7B at hundreds of tok/s); **tool-argument extraction** and JSON structuring; **cheap reflection** before escalating to Sonnet or Opus. These are high-volume low-stakes turns where local marginal cost is effectively zero.

### 8.4 PydanticAI integration

```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.ollama import OllamaProvider

# LM Studio or mlx_lm.server
local_rerank = OpenAIChatModel(
    model_name="qwen3-8b-mlx",
    provider=OpenAIProvider(base_url="http://localhost:1234/v1", api_key="lm-studio"),
)

# Ollama (preferred provider; 0.19+ uses MLX automatically)
local_summarise = OpenAIChatModel(
    model_name="qwen3:14b",
    provider=OllamaProvider(base_url="http://localhost:11434/v1"),
)
```

The dummy `api_key` on the OpenAI provider is a known PydanticAI quirk (issues #812, #891). Shorthand `Agent("ollama:qwen3-coder:30b")` works if `OLLAMA_BASE_URL` is set in environment.

---

## 9.0 Recommended BFA architecture

### 9.1 Target topology

The recommended Mission Control BFA architecture has four layers:

1. **PydanticAI agents** using `FallbackModel` for per-role model selection. Planning agent uses Sonnet 4.6; research-loop agents use Gemini 2.5 Flash or GPT-5.4-mini; synthesis agent uses Sonnet 4.6 with heavy caching (Opus 4.7 only on explicit escalation).
2. **LiteLLM self-hosted gateway** in your VPC as the unified data-plane. Virtual keys per agent role, per-key budgets, Redis cache, Prometheus/OTEL/Langfuse sinks, cosign-signed images.
3. **Portkey OSS or Pydantic AI Gateway** as the policy and guardrails layer (PII, prompt-injection, schema validation, SSO, RBAC, audit).
4. **Two backends behind LiteLLM**: **Google Vertex AI** (Gemini 2.5 Flash, 2.5 Pro, 3.1 Pro) and **OpenAI direct with ZDR** (GPT-5.4-mini, GPT-5.4) as primaries, **Anthropic direct** (Sonnet 4.6, Opus 4.7, Haiku 4.5) for planning and synthesis with full prompt caching enabled, and **Fireworks** (DeepSeek V3.2) as the cost-floor fallback. A **local MLX endpoint** on Herman's M4 Max exposed via LM Studio or `mlx_lm.server` handles reranking, compaction, and classification sub-tasks.

### 9.2 Cost envelope

Against a baseline 10-step research run at ~100K input plus ~3K output per step on Sonnet 4.5 direct uncached (~£3.45 per run), the recommended stack delivers:

- **Add Anthropic prompt caching only** — ~70 percent reduction to ~£1.20 per run. Zero architectural risk.
- **Add Gemini 2.5 Flash as loop default, Sonnet for planning and synthesis** — ~80–85 percent reduction to ~£0.50–0.70 per run.
- **Add DeepSeek V3.2 via Fireworks as cost-floor, local MLX for reranking and summarisation** — ~85–90 percent reduction to ~£0.35–0.55 per run.
- **Add Batch API for nightly digests and eval runs** — stacks a further 50 percent on those workloads.

### 9.3 Sanctioned versus prohibited, for the record

**Sanctioned and recommended:** Anthropic direct with API key plus caching; Bedrock or Vertex for Claude with committed spend; OpenAI Responses API with API key and ZDR; Google Vertex AI; Fireworks for DeepSeek and Qwen (SOC2 + HIPAA); Groq and Cerebras for open-weight fast inference; local MLX on your own hardware; LiteLLM and Portkey self-hosted; the `claude --bare -p` CLI with API key; `codex exec --json` with API key; Aider with per-vendor keys; ccusage for monitoring; claude-code-router for rule-based routing to multiple vendor APIs.

**Grey zone, avoid:** Codex CLI with ChatGPT login for non-coding backend workloads (not forbidden by ToS but architecturally swimming upstream and rate-limited); personal-use Claude Max for your own IDE work (fine, but orthogonal to BFA).

**Prohibited, do not deploy:** Claude Max or Pro OAuth tokens in any third-party product, service, tool, or SDK, **explicitly including the Anthropic Agent SDK** per the February 2026 policy; GitHub Copilot's `api.githubcopilot.com` endpoint via copilot-api, copilot-proxy, or LiteLLM's `github_copilot` provider, per GitHub's written ToS statement in community discussion #178117; DeepSeek direct API for any sensitive or regulated data; Alibaba DashScope direct for the same reason; any "multi-Max round-robin" scheme.

### 9.4 Concrete next steps for Herman

First, **turn on Anthropic prompt caching in the existing BFA codebase today**. If it is not already in use, this is a one-afternoon change that recoups the largest single saving and requires no architectural churn. Second, **stand up LiteLLM self-hosted in-VPC** as the unified gateway, virtual-keyed per BFA agent role, with Redis cache and Langfuse observability. Third, **migrate the research-loop agents from Sonnet to Gemini 2.5 Flash on Vertex AI** behind a FallbackModel that escalates to Sonnet on quality-check failure; keep planning and synthesis on Sonnet with full caching. Fourth, **add a local MLX endpoint** (LM Studio on the M4 Max exposing Qwen3-Coder-30B-A3B and Qwen3-8B over the OpenAI API) for reranking and compaction sub-tasks, routed by LiteLLM rules. Fifth, **adopt the Anthropic context-editing and memory tool** (beta header `context-management-2025-06-27`) — on web-search agents this alone cuts token consumption by 84 percent. Sixth, **run any nightly eval, digest, or corpus-enrichment workload through the Batch API** for the compounding 50 percent discount.

Every element of this plan is contractually sanctioned, operationally stable, and empirically shown to stack for 80–90 percent reductions in Anthropic spend without sacrificing the quality Mission Control's users expect.
