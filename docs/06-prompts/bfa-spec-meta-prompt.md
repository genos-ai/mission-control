# BFA Specification Meta-Prompt

**Purpose:** System-level instructions for generating production specifications on the BFA framework (FastAPI, FastStream/NATS, PydanticAI, PostgreSQL/TimescaleDB). Use as a `CLAUDE.md` rule file, a Claude Code project instruction, or a system prompt prefix when generating specs.

**Version:** 1.0
**Last updated:** April 2026

---

## Who you are writing for

Every spec you produce has two audiences who read it differently.

**The AI coding agent** (Claude Code, Cursor, Copilot) will treat the spec as its primary instruction set. It reads literally. If the spec says "use asyncio.gather for sub-agents" in one section and "distribute sub-agents via NATS workers" in another, the agent will implement whichever it encounters last, or worse, both. Contradictions in specs become contradictions in code. Ambiguity in specs becomes invented behaviour in code.

**The human reviewer** (Herman, or a senior engineer) reads for intent, gaps, and risk. They scan section headers to verify coverage, read invariants to verify testability, and check anti-pattern sections to verify you've thought about failure modes. They will spend 5-10 minutes reviewing a spec and 30 seconds per section. Front-load the important decisions.

Write for both. Be precise enough for the agent. Be structured enough for the reviewer.

---

## What a good BFA spec looks like

A good spec answers five questions, in order:

1. **What does this system do?** (Summary, 3-5 sentences. A senior engineer should understand the system's purpose and boundaries after reading this paragraph alone.)

2. **What are the boundaries?** (Technology stack with version pins and rationale. API contracts with request/response schemas. Configuration with defaults and valid ranges. Out of scope, stated explicitly.)

3. **How does it work?** (Architecture diagram. Request lifecycle. Module dependency map showing which module imports which and what data types flow between them. Agent prompts with tool definitions.)

4. **How do we know it works?** (Behavioural invariants: verifiable assertions about system behaviour. Error taxonomy: every failure mode with recovery behaviour. Test matrix with fixture requirements.)

5. **What can go wrong?** (Anti-patterns per section. Security boundaries covering all four trust boundaries: user→API, agent→external services, external content→agent context, agent output→data stores and users. Known limitations, stated honestly.)

6. **What are the security implications?** (Threat model with trust boundaries. Agent-specific threats: indirect prompt injection, tool-based data exfiltration, knowledge graph poisoning, cost exhaustion. Supply chain and NHI management. Audit trail. Compliance hooks. See the BFA Agent Security Specification for the full framework.)

Most specs answer questions 1 and 3. Good specs answer all five. The difference between a spec that produces correct code and one that produces plausible code is questions 2, 4, and 5.

---

## BFA framework conventions

These conventions apply to every BFA spec. Do not restate them in individual specs unless overriding a default.

### Stack defaults

- **API:** FastAPI >= 0.115. Pydantic v2 for all models. Async handlers only.
- **Agents:** PydanticAI with structured output types. FallbackModel for multi-provider routing. Agents return Pydantic models, never raw strings.
- **Messaging:** NATS JetStream via FastStream. Pull consumers for work distribution. Durable subscriptions for reliability.
- **Database:** PostgreSQL 16. asyncpg for connections. Alembic for migrations. TimescaleDB hypertables for time-series metrics.
- **Extensions:** Apache AGE for graph queries (via AGEClient wrapper, never raw cypher() calls). pgvector for embeddings (HNSW indexes).

### Code conventions

- Python 3.12+. Type hints on all function signatures. `from __future__ import annotations` not needed.
- Configuration via `pydantic-settings` with `env_prefix`. No `os.environ` calls. No magic numbers in code.
- Logging via `logging.getLogger(__name__)`. Structured log fields for task_id, agent_type, error_code.
- Error handling: catch specific exceptions, log with context, re-raise as typed errors from the error taxonomy.
- No `except Exception: pass`. No `except Exception: return None` without logging.

### Architectural principles

- **Orchestrators are plain Python, not LLM agents.** Concurrency, error handling, timeouts, and state management are code. LLMs handle understanding and generation.
- **Agents get clean context windows.** Do not share context between parallel agents. Each agent receives only its specific input and tools.
- **The spec is the source of truth.** Pydantic models in the codebase are the executable form of the spec's output model section. If they diverge, the spec is authoritative.
- **Graph write-backs are eventually consistent.** Never block the primary deliverable (report, response, result) on graph persistence.

---

## How to write each section type

### Summary

3-5 sentences. First sentence names the system and states its purpose. Second sentence names the architectural pattern. Remaining sentences identify the primary technology choices and data flow. No marketing language. No adjectives that don't carry information.

**Good:** "Build a citation verification pipeline that checks research report claims against source documents using NLI cross-encoders."

**Bad:** "Build a cutting-edge, AI-powered verification system that leverages state-of-the-art natural language inference."

### Technology Decision Matrix

Table format. Columns: Component, Technology, Version (pinned), Role (one phrase), Rationale (one sentence, real reason). Version pins prevent the AI agent from guessing. Rationale prevents the next human from replacing the technology without understanding why it was chosen.

### Configuration (AppConfig)

Single `pydantic-settings` model. Every parameter must have: a type with `Field(ge=..., le=...)` constraints, a default value, and a comment starting with "Rationale:" explaining why the default was chosen. Group parameters by subsystem with `# ── Section Name ──` comments.

If you find yourself hardcoding a number anywhere in the spec (timeout, batch size, threshold, limit), stop and add it to AppConfig instead.

### API Contracts

Define request/response models as Pydantic classes with `Field(description=...)`. Define an endpoint table mapping Method + Path to request body, success response, error responses, and notes. Define an `ErrorResponse` model used by all error status codes.

Every endpoint must specify what HTTP status code it returns for success and for each error condition. "Returns an error" is not a spec; "returns 429 with ErrorResponse containing retry_after_seconds" is a spec.

### Pydantic Output Models (for agents)

These are the most important section for AI coding quality. Output models are executable contracts: the agent literally cannot produce output that violates the schema. Use this to your advantage.

- Use `Literal` or `Enum` for constrained string fields. Never use bare `str` for a field with known valid values.
- Use `Field(min_length=1)` on lists that must not be empty (e.g., source references on claims).
- Use `Field(ge=0.0, le=1.0)` on confidence scores.
- Add `field_validator` with `mode="before"` for fields where LLMs may produce close-but-not-exact values (e.g., enum values with wrong casing).
- Add comments referencing the invariant ID that the field constraint enforces.

### Agent Prompts

System prompts must include, in order:

1. **Role statement.** One sentence. What this agent is. What it is not.
2. **Input description.** What the agent receives. What it does not receive (important for preventing hallucinated context).
3. **Protocol.** Numbered steps the agent must follow. "Do not skip steps."
4. **Error handling.** What to do when tools fail, when budget is exhausted, when results are empty.
5. **Negative constraints.** "What NOT to do" section. LLMs respond better to explicit prohibitions than to hoping they infer boundaries.
6. **Output constraints.** Reference the Pydantic model. State any field-level rules that the model enforces structurally but the agent should understand semantically.

Tool docstrings must include: what the tool does, when to use it, when NOT to use it, and the expected argument format. Short is better. The agent reads tool docstrings on every invocation.

### Behavioural Invariants

These are the single most important section for spec-driven development. They define what "correct" means beyond structural schema validation.

Each invariant must be:

- **Verifiable:** You can write a test that asserts it. If you cannot describe the test, the invariant is too vague.
- **Behavioural:** It describes what the system does, not what the data looks like. "Every claim must have a source" is structural (Pydantic handles it). "Claims with confidence < 0.3 must not appear in the report without an uncertainty qualifier" is behavioural.
- **Identified:** Give each invariant an ID (P-01, R-01, S-01, O-01, G-01) so test files can reference them.
- **Testable:** Include the test method column. A test name like "test_low_confidence_claims_qualified" is more useful than "unit test".

Aim for 15-25 invariants per spec. Fewer means you're under-specifying. More means you're over-constraining and the spec will become brittle.

### Error Taxonomy

Enumerate every error condition the system can encounter. For each:

- **Error code:** Machine-readable string (e.g., `LLM_ALL_PROVIDERS_FAILED`).
- **HTTP status:** The correct status code (not 500 for everything).
- **Message template:** Human-readable, with `{variable}` placeholders.
- **Retryable:** Boolean. If true, include `retry_after_seconds`.
- **Recovery action:** What the system does automatically. One sentence.

The error taxonomy is exhaustive. If a new error condition is discovered during implementation, it must be added to the taxonomy before the error handling code is written. This prevents ad-hoc error handling that diverges from spec.

### Anti-patterns

Every section that describes "how to do something" should also describe "how NOT to do it." Anti-patterns are the most cost-effective content in a spec because they prevent the single most common AI coding failure: producing structurally valid code that makes plausible-but-wrong architectural decisions.

Format: bold imperative statement, then one sentence explaining why.

**Good:** "**Do not use AGE for shallow lookups.** Single-hop property lookups on <10K nodes are faster with standard SQL."

**Bad:** "It might be better to consider using standard SQL for simple queries." (Too tentative. An AI agent will ignore this.)

### Security Specification

Every BFA spec MUST include a security section that addresses the four trust boundaries of agent systems. This is not optional, even for internal tools.

**The four trust boundaries:**

1. **User → API.** Input validation, rate limiting, prompt injection screening.
2. **Agent → External Services.** Egress controls (SSRF prevention), credential scoping, data classification of outbound requests, request logging.
3. **External Content → Agent Context.** Content sanitisation for fetched web pages, indirect prompt injection defences, output schema enforcement as a guardrail.
4. **Agent Output → Data Stores & Users.** Output validation, NLI verification, content safety, graph write validation, audit trail.

Traditional web application security covers boundaries 1 and parts of 2. Agent systems introduce boundaries 3 and 4, which have no equivalent in conventional architectures. A spec that covers only secrets management and input validation is incomplete.

**Agent-specific threats to address in every spec:**

- **Indirect prompt injection:** External content (search results, extracted pages) contains instructions that override agent behaviour. Primary control: output schema enforcement via Pydantic models. Defence-in-depth: content stripping, prompt reinforcement, cross-agent isolation.
- **Data exfiltration via tools:** Agent constructs tool calls (search queries, HTTP requests) that leak sensitive context to external APIs. Control: search query logging, context scoping, query content validation.
- **Knowledge graph / data store poisoning:** Agent-generated content persists across sessions and influences future tasks. Control: confidence gating on reads, NLI verification before writes, provenance tracking, human approval option.
- **Cost exhaustion:** Malicious queries trigger excessive LLM consumption. Control: token budget enforcement (structural), cost hard limits (operational), rate limiting.
- **SSRF via tool calls:** Agent fetches internal network resources. Control: URL validation blocking private IP ranges.

**What to include in the security section:**

- Threat catalogue with likelihood × impact ratings.
- Trust boundary diagram showing where controls apply.
- Specific controls for each agent-specific threat, with code samples.
- Secret management table (what, where, rotation policy).
- NHI (non-human identity) inventory with compromise impact analysis.
- Model provider data handling policies (retention, training, regional processing).
- Audit trail schema with auditable events table.
- Compliance mapping hooks (which controls map to which regulatory requirements).
- Security-specific testing requirements.

See the template's Section 2.7 for the full structural scaffold with reference implementations.

### Testing Section

Must include:

- **Test matrix:** Table mapping each testable layer to test type, tool, assertions, and file path.
- **Shared fixtures:** `conftest.py` with typed fixture functions that load known-good test data from JSON files.
- **Fixture data requirements:** Table listing every fixture file, its path, and what it contains.
- **Mock boundaries:** Table defining which external services are mocked, how, and what is NOT mocked.

Do not say "write tests." Say "assert that when the planner receives a complexity-2 query, it produces no more than 4 sub-questions (invariant P-01)."

### Out of Scope

Explicit, not implicit. If something is out of scope, say so and say why. If it has a configuration threshold that prepares for future implementation (e.g., `graph_edge_max_age_days`), note that the threshold exists even though the logic is deferred.

---

## What NOT to do in specs

- **Do not contradict yourself.** If Section 2.1 says sub-agents are distributed via NATS and Section 6.2 uses `asyncio.gather`, you have two architectures. Pick one. This is the single most common spec defect.
- **Do not reference functions without defining them.** If you import `execute_cypher` from `age_client.py`, define its signature, parameter binding approach, and return type. An AI agent will invent the interface if you don't specify it.
- **Do not list dependencies in prose without adding them to requirements.txt.** If a section says "use spaCy for NER," `spacy>=3.8.0` must appear in the requirements section and the model download must appear in infrastructure setup.
- **Do not use free-text strings for constrained fields.** If `synthesis_strategy` can only be one of five values, use an `Enum`, not `str`.
- **Do not assume the AI agent will infer error handling.** It will not. Or worse, it will infer `except Exception: pass`. Define every error path explicitly.
- **Do not write empty anti-pattern sections.** If you cannot think of at least 3 anti-patterns for a section, you have not thought about it enough. The anti-patterns are where your experience as an engineer lives.
- **Do not skip the "Files involved" line at the end of each section.** This tells the AI agent exactly which files to create or modify. Without it, the agent guesses file paths.

---

## Language and formatting

- UK English spelling throughout (organisation, colour, defence, programme, prioritise).
- Numbered sections (0.1, 1.0, 1.1, 2.3.1) for navigation. Flat bullet lists for anti-patterns only.
- Bold labels for anchoring concepts (**Why:** , **Rule:** , **Rationale:**).
- Code blocks with file path comments (`# src/agents/planner.py`) so the AI agent knows where to create the file.
- Tables for structured comparisons (technology matrix, error taxonomy, invariants, test matrix).
- Short paragraphs: 2-4 sentences maximum. Context before detail.
- No em dashes. No "Additionally," / "Furthermore," / "Moreover," / "Notably,". No "it's worth noting."

---

## Spec review checklist

Before finalising any spec, verify:

- [ ] Every `import` in code samples references a module defined elsewhere in the spec or in requirements.
- [ ] Every function called is defined somewhere in the spec with its signature and return type.
- [ ] Every configuration value used in code samples exists in AppConfig with type, default, and rationale.
- [ ] Every external service has an entry in the error taxonomy for at least: unavailable, rate limited, malformed response.
- [ ] Every Pydantic output model field with constrained values uses `Literal`, `Enum`, or `Field(ge/le)`.
- [ ] The architecture diagram, module dependency map, and code samples all describe the same architecture. No contradictions.
- [ ] The directory structure lists every file referenced in code samples.
- [ ] At least 15 behavioural invariants are defined, each with a test method.
- [ ] Anti-patterns exist for every section that describes implementation.
- [ ] Out of Scope explicitly lists at least 3 things that might be assumed in-scope but are not.
- [ ] All four trust boundaries are addressed: user→API, agent→external, external→agent, agent→datastore/user.
- [ ] Agent-specific threats are enumerated: indirect injection, data exfiltration via tools, data store poisoning, cost exhaustion, SSRF.
- [ ] Every external API the agent calls is listed in the NHI inventory with compromise impact and rotation policy.
- [ ] Secret management specifies storage, access method, and rotation for every credential.
- [ ] SSRF prevention is applied to every tool that makes outbound HTTP requests.
- [ ] An audit trail schema exists with at least one auditable event per trust boundary crossing.
- [ ] Model provider data handling policies are documented (retention, training opt-out, regional processing).
- [ ] Security-specific test cases exist for injection patterns, SSRF, output schema enforcement, and cost limits.
