# Agentic AI Harness for Continuous Web Application Security Assurance: BFA Reference Architecture

This document is the foundational technical research for an agentic AI harness intended to run as a `horizontal.{name}.agent` family on the Mission Control platform, implemented on the BFA stack (FastAPI, FastStream/NATS, PydanticAI, PostgreSQL/TimescaleDB, Apache AGE, pgvector, multi-provider LLM routing, Tavily). It leads with white-box assessment of internal Group web applications, adds black-box as a secondary mode, and is constrained to continuous assurance: find, triage, feed to Jira. Humans handle exploitation. SARIF is the canonical interchange format. Ephemeral containers are the execution primitive.

---

## 1.0 Executive recommendations

1. **Topology**: a deterministic Python coordinator dispatching seven role-specialised PydanticAI agents over NATS, with white-box static and graph analysis as the lead path and dynamic probing as the secondary path. Naming: `horizontal.coordinator.agent`, `horizontal.recon.agent`, `horizontal.sast.agent`, `horizontal.dast.agent`, `horizontal.auth.agent`, `horizontal.triage.agent`, `horizontal.reporter.agent`.
2. **Template strategy**: a generic core agent loop with versioned per-stack knowledge packs (.NET, Python, Node, Java, Go, Ruby, plus a generic fallback) selected by deterministic repo fingerprinting. This mirrors Semgrep rulesets, CodeQL packs, ZeroPath's investigation-first pipeline, and DryRun's per-stack accuracy investments.
3. **Authentication**: a pluggable `AuthStrategy` Protocol with concrete strategies for OIDC code/PKCE, OIDC client credentials, SAML POST, JWT bearer, session cookie, mTLS, HMAC SigV4, generic HMAC, and GraphQL persisted queries; composable through a `CompositeStrategy`; secrets resolved from Vault at tool-call time, never written into LLM context.
4. **Application mapping**: triple-source (OpenAPI/Swagger ground truth, Katana plus ZAP Client Spider observed reality, source-derived routes from framework reflection) reconciled into an Apache AGE knowledge graph; coverage tracked as `endpoint × vuln_class × auth_zone × payload_class` in TimescaleDB with continuous aggregates.
5. **Tool inventory**: SARIF-native where possible (Semgrep, CodeQL, Bandit, Trivy, Grype, OSV-Scanner, govulncheck, Nuclei, ZAP via report add-on, Snyk Code, Gitleaks, Nosey Parker). Wrap as ephemeral containers behind typed PydanticAI tools; do not wrap w3af, Arachni, Astra (unmaintained or archived); do not wrap AutoGPT-style frameworks.
6. **Verification**: every candidate finding is verified by an agent that did not produce it (often a different model entirely). Producer-as-verifier is forbidden by policy.
7. **Triage**: CVSS v4.0 base from the producer, threat and environmental enrichment from EPSS v4 plus the Group CMDB, deterministic business-risk weighting, SSVC outcome stored alongside, then mapped to Jira priority with cluster-batched ticketing.
8. **Safety rails**: deterministic egress proxy with per-target allowlist, kill switch over NATS, per-engagement tenant isolation in pgvector, append-only audit trail, write-operation block by default, untrusted-content tagging on every byte read from a target.

---

## 2.0 Question 1: Template strategy — generic core, per-stack knowledge packs

### 2.1 What every mature SAST already does

Every production SAST splits work along a per-language parser/extractor, a per-language taint or dataflow library with framework models, per-language rule or query packs, and a language-agnostic orchestration and reporting layer. Semgrep ships per-language YAML rules grouped into rulesets, with a tree-sitter parser per language and a generic core matching engine; the public Registry holds about 2,000 community rules and about 20,000 Pro rules. CodeQL ships explicitly per-language packs (`codeql/python-queries`, `codeql/java-queries`, `codeql/csharp-queries`, `codeql/javascript-queries`, `codeql/go-queries`, `codeql/ruby-queries`, `codeql/cpp-queries`, `codeql/rust-queries`, `codeql/actions-queries`) with their own database schemas and extractors, plus query suites that aggregate queries across packs by metadata. Snyk Code combines symbolic AI with ML over per-language analysers across roughly 19 languages. SonarQube splits each language analyser into a separate plugin. None ship a single generic template.

### 2.2 What agentic SAST/DAST tools do in late 2025/early 2026

**XBOW** runs a generic agentic loop with knowledge of historical CVE families as context, alternating static reading of source with live dynamic execution. XBOW reached the top US position on HackerOne in Q2 2025 with about 1,060 submissions; all submissions were human-reviewed before sending, per HackerOne's automation policy. XBOW open-sourced a 104-task web validation benchmark (PortSwigger and PentesterLab style); ZeroPath forked it and seeded false positives for fairer SAST comparison.

**ZeroPath** explicitly rejects rule-based engines and per-language sinks lists, and runs a pipeline of trigger → AST generation → enriched graph → AI investigation → multi-agent vulnerability validation per class (SSTI agent, SQLi agent, XSS agent, business-logic agent) → patch generation. The pre-step is a repo investigation that identifies application boundaries, generates application descriptions and metadata, and notes auth procedure and tech stack. That is per-repo fingerprinting in everything but name.

**Pixee** is codemod-centric: an open-source `codemodder` framework executes deterministic code transformations as per-language packs (Java, Python, JS/TS), with optional LLM-assisted codemods for transformations infeasible with deterministic AST rewrites. **Corgea BLAST** combines LLMs with AST static analysis and adds organisation-specific PolicyIQ rules in plain English; their public reporting cites a false-positive rate below 5% versus traditional SAST above 20%. **DryRun Security** runs Contextual Security Analysis (SLIDE: Surface, Language, Intent, Detection, Environment) with Natural Language Code Policies, and their 2025 SAST Accuracy Report shows per-stack investment (RailsGoat, Vulnerable Task Manager, Damn Vulnerable C# API, Spring Boot demo) with 23/26 detection versus Semgrep at 12/26.

The pattern is consistent across vendors: **agent loop and reasoning are language-agnostic; the knowledge that varies by stack is the routing/endpoint discovery, the auth idioms, the ORM and SQL escape conventions, the templating engine sinks, the deserialisation primitives, and the common CVE families per ecosystem**.

### 2.3 Repo fingerprinting algorithm for the harness

Stage 1 is deterministic and parallel. Walk the repo respecting `.gitignore` and `.semgrepignore`; do a Linguist-style extension count to estimate language proportions; parse all manifests in parallel: `package.json`/`package-lock`/`yarn.lock`/`pnpm-lock`, `pyproject.toml`/`requirements*.txt`/`Pipfile.lock`/`poetry.lock`, `pom.xml`/`build.gradle(.kts)`/`settings.gradle`, `go.mod`/`go.sum`, `*.csproj`/`Directory.Packages.props`/`global.json`, `Gemfile`/`Gemfile.lock`, `composer.json`/`composer.lock`, `Cargo.toml`/`Cargo.lock`. Detect monorepo boundaries via workspaces, `lerna.json`, `nx.json`, `turbo.json`, and `/apps/*`, `/services/*` conventions.

Stage 2 is LLM-assisted and runs only for ambiguous repos: sample the top ten entry-point files (by import fan-in plus filename heuristics) and one-shot classify the stack, auth model, and data layer. Stage 3 emits a `RepoFingerprint` Pydantic object: `{language[], framework[], orm[], auth[], deploy_targets[], monorepo_units[]}`. Stage 4 loads the matching knowledge packs; multiple packs may be active at once for polyglot mono-repos (Next.js BFF plus FastAPI service is common).

### 2.4 Recommendation

Adopt the **generic core, per-stack knowledge pack** pattern. The generic core is a single Python codebase implementing the planner, scout, executor, verifier, triage, and reporter agents, with stack-agnostic prompts and tool definitions. Versioned per-stack knowledge packs ship as plug-ins for at minimum:

- C#/.NET (ASP.NET Core, MVC, Web API, EF Core, BinaryFormatter risks)
- Python (FastAPI, Django, Flask, SQLAlchemy, Jinja2, `pickle`, `yaml.unsafe_load`)
- Node (Express, NestJS, Next.js including App Router and RSC quirks)
- Java (Spring MVC/WebFlux/Boot, Spring Security, Hibernate, Jackson polymorphic typing)
- Go (`net/http`, Gin, Fiber, GORM, `html/template` autoescape behaviour)
- Ruby (Rails, Sinatra, ActiveRecord, ERB)

Each pack contains routing and endpoint discovery rules, auth idioms, ORM and SQL escape conventions, template sink lists, deserialisation primitives, framework-specific CVE family priors, recommended dynamic probes, and prompt fragments injected into the planner and verifier system prompts. A generic fallback pack covers YAML, Dockerfile, and IaC checks for unsupported stacks.

```python
# horizontal/knowledge/pack.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Stack = Literal[
    "dotnet", "python_fastapi", "python_django", "python_flask",
    "node_express", "node_nestjs", "node_next", "java_spring",
    "go_net_http", "go_gin", "ruby_rails", "generic",
]

class RepoFingerprint(BaseModel):
    languages: dict[str, float]              # share 0..1
    frameworks: list[Stack]
    orms: list[str]
    auth_hints: list[str]                    # "oidc", "saml", "jwt", "mtls", "hmac"
    monorepo_units: list[str] = Field(default_factory=list)
    package_managers: list[str]
    has_openapi: bool
    has_graphql: bool

class KnowledgePack(BaseModel):
    stack: Stack
    version: str
    route_extractor: str                     # entry point id of an importable function
    auth_idioms: list[str]
    sql_escape_apis: list[str]
    template_sinks: list[str]
    deserialisation_primitives: list[str]
    cve_priors: list[str]
    dynamic_probes: list[str]
    planner_prompt_fragment: str
    verifier_prompt_fragment: str
```

Packs are loaded via Python entry points so Group business-line teams can ship internal extensions (mainframe SSO, bespoke RBAC, in-house ORM) without forking the harness.

---

## 3.0 Question 2: Pluggable authentication subsystem

### 3.1 What modern scanners do

OWASP ZAP separates authentication method, session management method, and verification strategy, all bound to a context. Methods include `manual`, `httpAuthentication` (Basic, Digest, NTLM), `form`, `json`, `script`, `autodetect`, `browser` (Selenium-driven multi-step browser auth for SSO and MFA), and the newer `client` script auth using Zest scripts recorded in browser. Session methods are cookie, header, autodetect, HTTP. Verification uses `loggedInRegex` and `loggedOutRegex` polled at a configurable frequency. The Automation Framework drives this from YAML.

Burp Suite Enterprise uses three primitives: Recorded Login Sequences (JSON scripts captured by the Login Recorder Chrome extension, replayable in fresh browser sessions, supporting SSO, multi-step, AI-generated sequences), Macros (HTTP request sequences with parameter derivation), and Session Handling Rules (scoped to tools or URLs, with actions to add cookies, set headers, run macros, check session validity, prompt for in-browser recovery). The cookie jar is shared across tools. Anti-CSRF tokens are handled by a macro fetching the issuing page plus a derivation rule mapping the response token into the next request parameter.

Caido replaces Burp's macro and session-rule model with Workflows backed by a JS SDK and an Environment service. A Refresh Authentication Workflow runs on every intercepted response, extracts cookies, JWT, or access tokens via JS, and writes them to scoped environment variables. Replay tabs and Automate sessions reference these as placeholders.

Nuclei uses a `-secret-file` YAML with static or dynamic modes; in dynamic mode, a referenced template runs first, its extractors populate placeholders in static fields, with `-prefetch-secrets` forcing eager loading. Wapiti supports `--auth-method`, `--form-script`, `-c` for cookie jars, `-sf` for Selenium IDE side files, and `--headless` running a real browser via Playwright/Selenium for SPA and SSO logins. w3af exposes `auth.generic` and `auth.detailed` plugins re-validated every five seconds during a scan; CSRF and 2FA are handled via Netscape-format cookie jars. Astra (Flipkart OSS) is effectively static; the commercial Astra DAST handles TOTP MFA via login scripts.

### 3.2 Pluggable auth subsystem (PydanticAI)

```python
# horizontal/auth/strategy.py
from __future__ import annotations
from typing import Protocol, Literal, runtime_checkable, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, SecretStr, AnyHttpUrl
import httpx

AuthMethod = Literal[
    "oidc_code", "oidc_client_credentials", "saml_post",
    "jwt_bearer", "session_cookie", "mtls",
    "hmac_sigv4", "hmac_generic", "graphql_persisted",
    "basic", "ntlm",
]

class AuthCredential(BaseModel):
    method: AuthMethod
    username: str | None = None
    password: SecretStr | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    private_key_pem: SecretStr | None = None
    cert_pem: SecretStr | None = None
    api_key: SecretStr | None = None
    totp_secret: SecretStr | None = None
    backup_codes: list[SecretStr] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

class AuthContext(BaseModel):
    target: AnyHttpUrl
    login_url: AnyHttpUrl | None = None
    token_url: AnyHttpUrl | None = None
    issuer: AnyHttpUrl | None = None
    scopes: list[str] = Field(default_factory=list)
    audience: str | None = None
    role: str = "user"            # admin/user/anonymous for Autorize-style mutations
    csrf_param: str | None = None
    csrf_header: str | None = None
    logged_in_regex: str | None = None
    logged_out_regex: str | None = None
    response_indicators: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

class SessionState(BaseModel):
    method: AuthMethod
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    bearer: SecretStr | None = None
    refresh: SecretStr | None = None
    expires_at: datetime | None = None
    csrf_token: str | None = None
    fingerprint: str = ""
    issued_at: datetime = Field(default_factory=datetime.utcnow)

    def expired(self, skew: int = 30) -> bool:
        return bool(self.expires_at
                    and datetime.utcnow() + timedelta(seconds=skew) >= self.expires_at)

@runtime_checkable
class AuthStrategy(Protocol):
    method: AuthMethod
    async def login(self, ctx: AuthContext, cred: AuthCredential,
                    client: httpx.AsyncClient) -> SessionState: ...
    async def refresh(self, ctx: AuthContext, state: SessionState,
                      client: httpx.AsyncClient) -> SessionState: ...
    async def apply(self, request: httpx.Request,
                    state: SessionState) -> httpx.Request: ...
    async def detect_logout(self, response: httpx.Response,
                            ctx: AuthContext) -> bool: ...
```

Concrete strategies follow this shape: `OIDCAuthCodeStrategy` drives Playwright for SSO and MFA (using `pyotp` for TOTP), `SAMLPostStrategy` captures `SAMLResponse` via Playwright and POSTs to ACS, `JWTBearerStrategy` accepts a static or vended token, `SessionCookieStrategy` does form POST with optional CSRF prefetch, `MTLSStrategy` configures `httpx.AsyncClient(verify=ca, cert=(cert_pem, key_pem))` at transport level, `HMACSigV4Strategy` signs each outgoing request with the AWS SigV4 algorithm via `botocore.auth.SigV4Auth`, `HMACGenericStrategy` computes `HMAC(secret, METHOD\npath\nbody_sha256\ntimestamp)` set in `X-Signature` and `X-Timestamp`, and `GraphQLPersistedStrategy` replaces the body with `{"id": "<sha256>", "variables": {...}}` while preserving auth from another strategy via composition.

A `CompositeStrategy` chains transport (mTLS) → identity (OIDC/JWT) → request signing (HMAC) → CSRF (per-request) so the harness models real Group middlewares (mTLS to the API gateway plus JWT plus HMAC). The strategy registry is exposed as a single PydanticAI tool to the planner; the LLM picks among registered strategies and explains its choice, but does not implement the protocol.

### 3.3 Logout detection and recovery

Combine signals: HTTP 401 or 407, sometimes 403 with auth challenge; 30x to `/login`, `/sso`, `/oauth2/authorize`, IdP host; logged-out regex on body or absence of logged-in regex; missing or rejected CSRF (`INVALID_CSRF`, `csrf_token mismatch`, missing `XSRF-TOKEN` cookie); GraphQL `{"errors":[{"extensions":{"code":"UNAUTHENTICATED"}}]}`; sudden latency drop indicating gateway short-circuit; WAF challenge headers (`x-amzn-waf-action`, `cf-ray` with 403). State machine: `OK → SOFT_EXPIRED (refresh) → HARD_LOGGED_OUT (full re-login) → BLOCKED (back-off and alert)`. Per-target single-flight on `(target, role)` via `asyncio.Lock` plus `pg_advisory_xact_lock(hashtext(target||role))` for cross-pod coordination. After recovery, replay the failed request with the new state.

### 3.4 CSRF, dynamic headers, request signing

Prefetch a known authenticated page; extract token from `<meta name="csrf-token">`, hidden form field, or `Set-Cookie: XSRF-TOKEN`; store on `SessionState.csrf_token`; refresh on 419/403-csrf, on TTL, or per request for double-submit cookies. Dynamic header providers compute `X-Request-ID = uuid4`, `X-Idempotency-Key = sha256(plan)`, `X-Trace-Id = otel context` at request time. AWS SigV4 uses canonical request → string-to-sign → derived signing key; non-AWS HMAC schemes (Stripe, Shopify, Adyen) compute `HMAC_SHA256(secret, body)` over the canonical body and set `Stripe-Signature: t=<ts>,v1=<sig>` style headers.

### 3.5 Architecture

The Auth Service is a separate FastAPI module fronted by the BFA control plane and consumed by FastStream/NATS workers. The strategy registry ships in `horizontal.auth` discovered via entry points so Group business lines can add bespoke strategies. Vault integration uses HashiCorp Vault dynamic secrets engine for service accounts, KV2 for static credentials, and Transit for TOTP seed encryption. The session store is `auth_sessions(target, role, state JSONB encrypted, expires_at, fingerprint)` with `pgcrypto.pgp_sym_encrypt` and Vault Transit keys. A dedicated FastStream worker issues validity probes every N requests or on response heuristic match, emitting `auth.session.invalid` to NATS so all workers drop and re-attach. Per-request middleware in the HTTP client applies `apply()`, short-circuits on `detect_logout()`, enqueues refresh, and retries.

---

## 4.0 Question 3: Application mapping and coverage tracking

### 4.1 Mapping pipeline

Three sources are reconciled into one graph.

**Source A, ground truth (white-box first):** OpenAPI 2.0/3.0/3.1 documents from `/openapi.json`, `/swagger.json`, repo files. Validate with `prance` or `openapi-core`, then convert each operation into testable cases via Schemathesis (Python SDK in-process). For GraphQL, run introspection; if disabled, run `clairvoyance` against a wordlist exploiting Apollo "Did you mean" suggestions.

**Source B, source-derived routes (white-box):** Django via `python manage.py show_urls` (django-extensions) or `django.urls.get_resolver().reverse_dict`; FastAPI via `app.routes` iteration on `APIRoute` instances or `app.openapi()`; Flask via `app.url_map.iter_rules()`; Express via `express-list-endpoints`; Spring Boot via `/actuator/mappings` or `RequestMappingHandlerMapping.getHandlerMethods()`; .NET via `EndpointDataSource.Endpoints` enumeration or Swashbuckle CLI; Rails via `bundle exec rails routes --json`; Next.js by walking `app/` and `pages/` for route files. For polyglot mono-repos, run `tree-sitter` over the AST.

**Source C, observed reality (black-box):** Katana with `-jc -jsl -kf all -d 5 -hl -xhr -aff -fx`, ZAP Client Spider for SPAs, GoSpider as fallback, sitemap.xml and robots.txt parsing, and SPA route discovery via LinkFinder, JSluice, getJS, hakrawler.

The diff between A∪B (declared) and C (observed) exposes shadow APIs and undocumented endpoints; this diff is itself a finding class.

### 4.2 Apache AGE knowledge graph

AGE supports one label per node or edge by design. Use a `kind` property when multi-role semantics are needed. Vertex labels: `Application`, `Route`, `Endpoint`, `Parameter`, `AuthZone`, `Role`, `Session`, `DataStore`, `ExternalService`, `Finding`, `TestCase`, `Package`. Edge labels: `ROUTES_TO`, `REQUIRES_AUTH`, `ACCEPTS_PARAM`, `READS_FROM`, `WRITES_TO`, `REDIRECTS_TO`, `CALLS`, `TAINTED_BY`, `FOUND_AT`, `COVERED_BY`, `GRANTED_TO`, `DEPENDS_ON`, `LIKELY_SAME_AS`.

```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('appsec');

SELECT create_vlabel('appsec','Application');
SELECT create_vlabel('appsec','Route');
SELECT create_vlabel('appsec','Endpoint');
SELECT create_vlabel('appsec','Parameter');
SELECT create_vlabel('appsec','AuthZone');
SELECT create_vlabel('appsec','Role');
SELECT create_vlabel('appsec','Session');
SELECT create_vlabel('appsec','DataStore');
SELECT create_vlabel('appsec','ExternalService');
SELECT create_vlabel('appsec','Finding');
SELECT create_vlabel('appsec','TestCase');
SELECT create_vlabel('appsec','Package');

SELECT create_elabel('appsec','ROUTES_TO');
SELECT create_elabel('appsec','REQUIRES_AUTH');
SELECT create_elabel('appsec','ACCEPTS_PARAM');
SELECT create_elabel('appsec','READS_FROM');
SELECT create_elabel('appsec','WRITES_TO');
SELECT create_elabel('appsec','REDIRECTS_TO');
SELECT create_elabel('appsec','CALLS');
SELECT create_elabel('appsec','TAINTED_BY');
SELECT create_elabel('appsec','FOUND_AT');
SELECT create_elabel('appsec','COVERED_BY');
SELECT create_elabel('appsec','GRANTED_TO');
SELECT create_elabel('appsec','DEPENDS_ON');
SELECT create_elabel('appsec','LIKELY_SAME_AS');
```

Property conventions: `Application{name, version, repo_url, sbom_id, language, framework}`; `Route{pattern, method, controller, file, line, source}`; `Endpoint{url, http_method, content_type, status_codes_observed, hash}`; `Parameter{name, in, schema, required, sensitive, taint_class}`; `AuthZone{name, requires_role, auth_method, mfa}`; `DataStore{type, classification}`; `Finding{cwe, cve, severity, owasp_top10, confidence, evidence_id, dedup_hash}`. Insert example:

```sql
SELECT * FROM cypher('appsec', $$
  MERGE (a:Application {name:'corebank-api'})
  MERGE (r:Route {pattern:'/v1/accounts/{id}/transfers', method:'POST'})
  MERGE (a)-[:ROUTES_TO]->(r)
  MERGE (z:AuthZone {name:'authenticated_customer', mfa:true})
  MERGE (r)-[:REQUIRES_AUTH]->(z)
$$) AS (v agtype);
```

### 4.3 White-box artefacts

SBOM: `syft packages dir:./repo -o cyclonedx-json > sbom.json` and `trivy fs --format cyclonedx ./repo`. Dependency graph ingested as `(Application)-[:DEPENDS_ON]->(Package{ecosystem,version,license,cves})`. Call graph via `joern-parse repo; joern-export --repr cpg14 --format dot` or Semgrep `--dataflow-traces` or CodeQL databases. Taint analysis via CodeQL global taint config (`module Flow = TaintTracking::Global<Cfg>`), Semgrep `mode: taint` rules with `pattern-sources`, `pattern-sinks`, `pattern-sanitizers`, `pattern-propagators`, or Joern `cpg.method.name("input").reachableBy(cpg.call.name("exec"))`. Each taint pair becomes `(Parameter)-[:TAINTED_BY]->(Parameter){evidence:"codeql"}` joining DAST endpoint discovery with SAST data flow.

### 4.4 TimescaleDB schema

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

CREATE TABLE scan_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id  UUID NOT NULL,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at        TIMESTAMPTZ,
  status          TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
  scope           JSONB NOT NULL,
  config          JSONB NOT NULL,
  initiator       TEXT NOT NULL,
  llm_router_log  JSONB,
  CONSTRAINT scan_runs_status_dates CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX ON scan_runs (application_id, started_at DESC);

CREATE TABLE findings (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id   UUID NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  endpoint_hash TEXT NOT NULL,
  vuln_class    TEXT NOT NULL,
  cwe           TEXT,
  owasp         TEXT,
  severity      TEXT NOT NULL CHECK (severity IN ('info','low','medium','high','critical')),
  confidence    NUMERIC(3,2) NOT NULL,
  cvss_vector   TEXT,
  epss          NUMERIC(5,4),
  ssvc_outcome  TEXT,
  title         TEXT NOT NULL,
  description   TEXT NOT NULL,
  evidence      JSONB NOT NULL,
  sarif         JSONB,
  dedup_hash    TEXT NOT NULL,
  match_based_id TEXT,
  embedding     vector(1024),
  first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
  triage_state  TEXT NOT NULL DEFAULT 'new',
  jira_key      TEXT,
  UNIQUE (dedup_hash)
);
CREATE INDEX findings_emb_hnsw
  ON findings USING hnsw (embedding vector_cosine_ops)
  WITH (m=16, ef_construction=64);
CREATE INDEX ON findings (scan_run_id, severity);

CREATE TABLE tool_executions (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_run_id      UUID NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  tool             TEXT NOT NULL,
  tool_version     TEXT,
  args             JSONB NOT NULL,
  idempotency_key  TEXT NOT NULL,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at         TIMESTAMPTZ,
  exit_code        INT,
  stdout_ref       TEXT,
  stderr_ref       TEXT,
  cost_tokens      JSONB,
  UNIQUE (idempotency_key)
);

CREATE TABLE coverage_state (
  application_id   UUID NOT NULL,
  endpoint_hash    TEXT NOT NULL,
  vuln_class       TEXT NOT NULL,
  auth_zone        TEXT NOT NULL,
  payload_class    TEXT NOT NULL,
  attempts         INT  NOT NULL DEFAULT 0,
  successes        INT  NOT NULL DEFAULT 0,
  last_attempt_at  TIMESTAMPTZ,
  bloom            BYTEA,
  PRIMARY KEY (application_id, endpoint_hash, vuln_class, auth_zone, payload_class)
);

CREATE TABLE http_traces (
  ts                TIMESTAMPTZ NOT NULL,
  scan_run_id       UUID NOT NULL,
  tool_execution_id UUID,
  endpoint_hash     TEXT NOT NULL,
  method            TEXT NOT NULL,
  url               TEXT NOT NULL,
  status            INT,
  req_headers       JSONB,
  req_body_ref      TEXT,
  res_headers       JSONB,
  res_body_ref      TEXT,
  res_size          INT,
  duration_ms       INT,
  auth_zone         TEXT,
  role              TEXT,
  payload_class     TEXT,
  finding_id        UUID
);
SELECT create_hypertable('http_traces', by_range('ts', INTERVAL '1 day'));
CREATE INDEX ON http_traces (scan_run_id, ts DESC);
CREATE INDEX ON http_traces (endpoint_hash, ts DESC);
ALTER TABLE http_traces SET (timescaledb.compress,
  timescaledb.compress_segmentby='scan_run_id',
  timescaledb.compress_orderby='ts DESC');
SELECT add_compression_policy('http_traces', INTERVAL '7 days');
SELECT add_retention_policy('http_traces', INTERVAL '180 days');

CREATE MATERIALIZED VIEW coverage_1h
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS bucket, scan_run_id, endpoint_hash,
       payload_class, count(*) AS attempts,
       count(*) FILTER (WHERE finding_id IS NOT NULL) AS hits
FROM http_traces
GROUP BY bucket, scan_run_id, endpoint_hash, payload_class;
SELECT add_continuous_aggregate_policy('coverage_1h',
  start_offset=>INTERVAL '7 days', end_offset=>INTERVAL '1 hour',
  schedule_interval=>INTERVAL '5 minutes');
```

### 4.5 Coverage and idempotency

Coverage matrix is `endpoint × vuln_class × auth_zone × payload_class`, persisted as a per-attempt row in `http_traces` with the current matrix as a continuous aggregate. Fuzzing state per parameter is a bitmap of payload classes attempted (sql, xss, ssrf, xxe, idor, ssti, deserialisation, path-traversal, command-injection, open-redirect, csrf, jwt-attacks, race-conditions, mass-assignment) plus a Bloom filter of payload hashes already sent. Idempotency keys are `sha256(canonical_json({tool, target_endpoint, payload_class, payload_hash, auth_zone, role, scan_run_id}))` stored on `tool_executions`; duplicate enqueues short-circuit.

### 4.6 pgvector strategy

| Collection | Source | Model | Dim | Index |
|---|---|---|---|---|
| `code_chunks` | repo files chunked by function/class | voyage-code-3 (or Qwen3-Embedding-8B air-gapped) | 1024 | HNSW cosine `(m=16, ef_construction=64)` |
| `owasp_test_cases` | WSTG, ASVS 5.0, MITRE CWE | text-embedding-3-large truncated | 1024 | HNSW cosine |
| `historical_findings` | normalised title+description+evidence | text-embedding-3-large truncated | 1024 | HNSW cosine |
| `route_descriptions` | controller docstrings + AI summary | text-embedding-3-large | 1024 | HNSW cosine |
| `payload_library` | OWASP cheat sheets, SecLists | text-embedding-3-small | 1536 | IVFFlat |

Chunking: AST-aware via tree-sitter (never split a function body); sliding window with header retention (file imports plus class signature in every chunk prefix); two-resolution indexing (per-function plus per-file LLM summary); contextual retrieval (Anthropic 2024 pattern) prepending a short LLM-written description of where this chunk fits the project. Per-language indexes routed by repo fingerprint. Use `halfvec(1024)` to halve storage when memory is tight.

### 4.7 Deduplication

Primary hash: `sha256(cwe || normalised_endpoint || sink_param || canonical_payload_class || method || auth_state)`. Normalise UUIDs, integer IDs, and date stamps in path segments to `{id}` before hashing. Keep severity out of the hash. Secondary structural hash for SAST: Semgrep `match_based_id` (rule plus AST shape, stable across line moves and benign edits). Fuzzy match for stack traces and log lines: MinHash plus LSH over shingled tokens with Jaccard threshold around 0.85, or SimHash with 64-bit fingerprints and Hamming distance ≤ 3. pgvector cosine similarity above 0.92 over `(title + description + evidence_excerpt)` is a ranking aid for candidate clusters, never the sole dedup key. Cross-finding correlation runs in AGE: matching CWE on the same Endpoint across different scan runs becomes a `LIKELY_SAME_AS` edge.

---

## 5.0 Question 4: Open source tooling inventory

All tools are wrapped as ephemeral containers behind typed PydanticAI tools. Subprocess execution uses `asyncio.create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE, cwd=workspace)` with `asyncio.wait_for(proc.communicate(), timeout=TOOL_TIMEOUT)`. Non-zero exit codes mean "findings present" for security tools, distinguished from real errors via stderr inspection. Every container image is pinned by digest and verified via cosign attestations. Trivy was compromised twice in early 2026; pin the image and the GitHub Action by SHA.

### 5.1 SAST

| Tool | Version 2026 | Invocation | Output | SARIF | Agent role | Notes |
|---|---|---|---|---|---|---|
| Semgrep CE | 1.161.x | `semgrep scan --config=auto --sarif -o out.sarif <path>` | SARIF/JSON | Yes | sast | Pin ruleset for air-gapped; CE is intra-file only, cross-file is Pro |
| CodeQL CLI | 2.x | `codeql database create db --language=<l> && codeql database analyze db --format=sarifv2.1.0 --output=out.sarif <queries>` | SARIF | Yes | sast | License limits commercial use; database build is RAM-heavy |
| Bandit | 1.8.x | `bandit -r <path> -f sarif -o out.sarif` | SARIF/JSON | Yes | sast | High FP rate on `subprocess`; AST only, no taint |
| Brakeman | 7.1.2+ | `brakeman -f sarif -o out.sarif <path>` | SARIF/JSON | Yes | sast | Rails-only; ignore via `config/brakeman.ignore` |
| gosec | 2.21+ | `gosec -fmt sarif -out out.sarif ./...` | SARIF | Yes | sast | Use `-confidence high -severity medium` |
| ESLint security plugins | eslint-plugin-security 3.x | `eslint -f @microsoft/eslint-formatter-sarif -o out.sarif` | SARIF (via formatter) | Via formatter | sast | ESLint v9 flat config; dedupe by `(file,line,ruleId)` |
| Snyk Code | 1.1300+ | `snyk code test --sarif` | SARIF | Yes | sast | Licensing precludes embedding without paid plan |
| Joern | 4.x | `joern-parse <path> && joern --script q.sc` | JSON via script | No | sast (deep) | Reserved for "is this Semgrep finding reachable?" queries |
| njsscan | 0.4.x | `njsscan --sarif -o out.sarif <path>` | SARIF | Yes | sast | Bundles Semgrep internally |
| Psalm | 5.x | `psalm --taint-analysis --output-format=sarif > out.sarif` | SARIF | Yes | sast | PHP only |

### 5.2 DAST

| Tool | Version 2026 | Invocation | Output | SARIF | Agent role |
|---|---|---|---|---|---|
| OWASP ZAP | 2.17.0 | `zap.sh -daemon -port 8090 -config api.key=$KEY` plus `python-owasp-zap-v2.4` SDK | XML/JSON/SARIF (via report add-on) | Yes | dast/auth |
| Nuclei | v3.x, templates v10.4.2 | `nuclei -u https://t -severity high,critical -sarif-export out.sarif` | JSONL/SARIF | Yes | dast/recon |
| Wapiti | 3.2+ | `wapiti -u https://t -f json -o out.json --flush-session` | JSON | No | dast |
| sqlmap | 1.10.4+ | `sqlmapapi -s` then JSON-RPC | Session/CSV | No | dast (gated) |
| Nikto | 2.5.x | `nikto -h https://t -Format json -o out.json` | JSON | No | recon |
| sslyze | 6.x | `import sslyze` (use SDK, not subprocess) | JSON | No | recon |
| testssl.sh | 3.2 | `testssl.sh --jsonfile-pretty=out.json` | JSON | No | recon (compliance) |

w3af, Arachni, and Astra (Flipkart OSS) are unmaintained or archived; do not wrap.

### 5.3 Recon and crawling

| Tool | Invocation | Output |
|---|---|---|
| Katana | `katana -u https://t -jc -jsl -kf all -d 5 -o out.jsonl -j` | JSONL |
| Subfinder | `subfinder -d t -all -silent -oJ -o subs.json` | JSONL |
| Amass | `amass enum -active -d t -json out.jsonl` | JSONL |
| httpx (PD) | `httpx -l hosts.txt -json -tech-detect -tls-grab -o probe.jsonl` | JSONL |
| Arjun | `arjun -u https://t/api -oJ out.json` | JSON |
| ParamSpider | `paramspider -d t` | text |
| gau | `gau t.com --json --o gau.jsonl` | JSONL |
| waybackurls | `echo t \| waybackurls > urls.txt` | text |

GoSpider is a fallback for sitemap-driven discovery; Hakrawler and Photon are diminishing returns once Katana is in the stack.

### 5.4 Fuzzing

| Tool | Invocation | Output | Notes |
|---|---|---|---|
| ffuf | `ffuf -w wl.txt -u https://t/FUZZ -of json -o out.json -rate 50` | JSON | Use `-request raw.txt` for accurate auth replay |
| feroxbuster | `feroxbuster -u https://t -w wl.txt --json -o out.jsonl --auto-tune` | JSONL | `--auto-tune --auto-bail` essential to avoid DoS |
| dirsearch | `dirsearch -u https://t --format json -o out.json` | JSON | Curated wordlist |
| RESTler | `dotnet Restler.dll compile --api_spec spec.json && dotnet Restler.dll fuzz ...` | bug_buckets/, runSummary.json | Three modes: `test`, `fuzz-lean`, `fuzz`; only `fuzz` is aggressive |
| fuzz-lightyear | `fuzz-lightyear --schema schema.json --output out.json` | JSON | Useful for IDOR; expect to fork |

### 5.5 API and GraphQL

Schemathesis is the primary API tool, used as a Python SDK in-process for direct access to request and response objects. RESTler is the strongest open-source stateful API fuzzer and slots in after Schemathesis. Postman/Newman replays curated regression tests. For GraphQL: introspect via httpx, fall back to clairvoyance, drive GraphQL Cop for standard checks (introspection, batching, depth, field suggestions, alias overloading), batchql for batching DoS, graphql-path-enum for authorisation pivots. InQL adds depth in Burp-integrated workflows. Dredd is superseded.

### 5.6 Supply chain

| Tool | Invocation | Output | SARIF |
|---|---|---|---|
| Trivy | `trivy fs --format sarif -o out.sarif <path>` | SARIF/CycloneDX | Yes |
| Syft | `syft <target> -o cyclonedx-json > sbom.json` | CycloneDX/SPDX | n/a |
| Grype | `grype sbom:sbom.json -o sarif > out.sarif` | SARIF | Yes |
| OSV-Scanner | `osv-scanner --recursive --format sarif --output out.sarif <path>` | SARIF | Yes |
| pip-audit | `pip-audit -r requirements.txt --format json -o audit.json` | JSON | No |
| npm audit | `npm audit --json` | JSON | No |
| govulncheck | `govulncheck -format sarif ./... > vuln.sarif` | SARIF | Yes |
| cargo audit | `cargo audit --json` | JSON | No |
| Retire.js | `retire --path . --outputformat json --outputpath retire.json` | JSON | No |

Dependency-Track (Postgres-backed, fits the BFA stack) is the system of record; cdxgen generates SBOMs across 25+ ecosystems and is preferable to Syft for polyglot projects when CycloneDX is the target.

### 5.7 Secrets

| Tool | Invocation | Output | SARIF |
|---|---|---|---|
| Gitleaks | `gitleaks dir -s <path> --report-format sarif --report-path out.sarif` | SARIF | Yes |
| TruffleHog v3 | `trufflehog git file://<path> --json --results=verified,unknown > tf.jsonl` | JSONL | No |
| detect-secrets | `detect-secrets scan --baseline .secrets.baseline > out.json` | JSON | No |
| Nosey Parker | `noseyparker scan --datastore np.ds <path> && noseyparker report --format json` | JSON/SARIF | Yes (recent) |

TruffleHog v3's active credential verification is decisive; the `Verified` boolean overrides the criticality score from other scanners. Run all four with results unioned and deduplicated by `(file, start_offset, secret_hash)`.

### 5.8 IAST and runtime

Contrast Community Edition is no longer offered for new sign-ups. The pragmatic substitute is OpenTelemetry instrumentation in the application under test, with the agent treating spans as a structured runtime feed (parameterised vs interpolated SQL, request body hashes, exception classes by endpoint). Tetragon and Falco are runtime detection rather than scanning; out of scope for pre-prod, but worth modelling the data shape.

### 5.9 Browser automation

Playwright (Python async API, 1.58+) is the default. Run in disposable containers with no host volume mounts; route traffic through the ZAP daemon for automatic capture. Microsoft Playwright MCP exposes navigate/click/fill/screenshot as discrete tools and pairs cleanly with PydanticAI when the LLM-driven exploration agent needs browser tools.

### 5.10 Headless reasoning frameworks (do not wrap)

PentestGPT informs the design (Reasoning + Generation + Parsing modules, Pentest Task Tree) but is wrapped by no one in production. AutoGPT-style frameworks must be avoided: no state discipline, unbounded tool execution, no separation of trusted instructions from untrusted scanner output. AutoGen and CrewAI duplicate what NATS and FastStream already provide. LangGraph is a useful design reference but PydanticAI suffices.

### 5.11 LLM-native security (for securing the Group's own LLM apps)

Garak (NVIDIA, 0.14.0) for nightly scans, Promptfoo for OWASP/MITRE/EU AI Act mapping per pull request, PyRIT (Microsoft) for bi-weekly multi-turn campaigns. Vigil and Rebuff sit at runtime as request-time guards. None emit SARIF; standardise on a wrapper `LLMFinding` Pydantic model keyed on `probe_id`, `attack_class`, `verified`, `severity`.

---

## 6.0 Question 5: Cutting-edge agentic security techniques

### 6.1 LLM-driven discovery

XBOW's reproducible techniques are: machine-readable scope ingestion; relentless iteration after failed payloads; variant analysis (probably-similar-bug pattern); hybrid alternation between source reading and live execution; human pre-submission triage. Open-source replications include MAPTA (arXiv:2508.20816, 80/104 on the XBOW benchmark), Cyber-AutoAgent (84.6% on the XBOW Validation Benchmark with a meta-agent architecture), Excalibur (arXiv:2602.17622, difficulty-aware planning), Red-MIRROR (arXiv:2603.27127, dual-phase reflection plus RAG over CAPEC/NVD), and CAI/alias1 (Alias Robotics, EU-funded, 100% on Base benchmark with G-CTR augmentation, 31% on Cybench).

### 6.2 AI-augmented fuzzing

OSS-Fuzz-Gen generates fuzz harnesses for C/C++/Java/Python with up to 31% line-coverage gain and 30+ new bugs reported. Fuzz4All (ICSE 2024, arXiv:2308.04748) is universal across six languages with +36.8% average coverage and 47 unknown bugs. ChatAFL (NDSS 2024) drives LLM-guided protocol fuzzing with +5.8% branch coverage on RTSP. MultiFuzz (arXiv:2508.14300) and ChatFuMe (arXiv:2508.01750) extend with RAG and reduce token cost 36×. Project Naptime/Big Sleep (Google) found the first AI-discovered real-world memory-safety zero day (SQLite, October 2024) and five WebKit CVEs in November 2025.

The harness pattern: LLM proposes payload candidates, deterministic mutator (AFL/libFuzzer-style) executes, coverage feedback feeds the LLM next round. For HTTP fuzzing, LLM extracts schema or grammar from OpenAPI ingestion or sample traffic, produces typed mutations, classical fuzzer iterates. Token economy follows ChatFuMe: rare LLM, frequent mutator, LLM only when classical fuzzer plateaus.

### 6.3 Exploit chain reasoning for prioritisation only

The harness does not execute exploit chains. It produces a chained-finding score: reachability from public ingress, auth-bypass present, data-class touched, blast radius from AGE traversal. ZeroPath's per-class verification agents compute CVSS 4.0 heuristics before patch generation; the Group uses the same logic with patch generation disabled.

### 6.4 RAG over codebase

Default embeddings: voyage-code-3 at 1024 dims with int8 quantisation (Voyage outperforms OpenAI text-embedding-3-large by 13.80% and CodeSage-large by 16.81% across 32 code retrieval datasets). Air-gapped fallback: Qwen3-Embedding-8B (Apache 2.0, top of MTEB-Code) or CodeSage-Large-v2. Chunking: AST-aware via tree-sitter; sliding window with header retention; two-resolution (per-function plus per-file LLM summary); contextual retrieval prefix (Anthropic 2024). Per-language indexes routed by repo fingerprint.

### 6.5 Multi-agent topology

What works: modular role separation (planner/scout/executor/fuzzer/verifier/reporter/triage); dual-phase reflection (intra-reflection per action, inter-reflection across iterations) per Red-MIRROR; shared structured memory with access control and deterministic retrieval; hierarchical planning plus task-specific agents plus in-context learning (empirically 6×/2×/2× multipliers); peer-to-peer agent messaging (AutoGen 52.3% refusal vs CrewAI hierarchical 30.8% on adversarial pentest); difficulty-aware planning per Excalibur.

What fails: monolithic ReAct agents (long-horizon coherence loss); pure LLM planning without structured memory (logically inconsistent plans); centralised LLM orchestrators (single point of prompt injection failure); naive in-context CTF training (poor generalisation to bug bounty diversity).

For the Group harness:

```
Coordinator (deterministic Python, not an LLM)
  scope, kill switch, rate limits, fingerprint, knowledge-pack loader
        │
   ┌────┼─────────────┬──────────┬────────────┬───────────┬────────┐
   ▼    ▼             ▼          ▼            ▼           ▼        ▼
 Recon  Auth        SAST       DAST        Triage     Reporter
                  Analyser    Probe       Verifier   (SARIF +
                                          per-class    Jira)
        ▲           ▲           ▲            ▲           ▲
        └───────────┴───────────┴────────────┴───────────┘
              Shared structured memory (NATS subjects + AGE + pgvector)
              with access control and deterministic retrieval
```

### 6.6 Reflection and verification

Reflexion (NeurIPS 2023, arXiv:2303.11366) stores verbal feedback in an experience memory used to revise the next attempt. Self-RAG (ICLR 2024, arXiv:2310.11511) does adaptive retrieval plus reflection tokens with per-segment self-critique and citations. Chain-of-Verification generates, derives verification questions, answers independently, revises. SelfCheckGPT does zero-resource hallucination detection via sample variance.

For SAST FP reduction, ZeroPath, Corgea, Pixee, and Semgrep Assistant all run a second-pass per-class verifier agent that re-reads surrounding code with the candidate finding as input and produces a structured judgement (exploitable, blocked-by-control, false-positive) plus reasoning. Corgea claims roughly 90% noise reduction; Semgrep Assistant claims 95–96% expert agreement on auto-triage; HackerOne's Hai validation agent reports 56% reduction in validation time on early-adopter sets. Concrete pipeline:

```
finding → (1) rule-based reachability filter
        → (2) per-class verifier LLM call (sees: source code chunk,
              data-flow path, executed probe response, framework knowledge pack)
        → output schema {is_real, confidence, exploitability, evidence,
                         attack_path, blockers}
        → (3) only confidence ≥ θ AND is_real=true reaches reporter
        → (4) if downstream patch agent disagrees, re-open for human review
```

### 6.7 Prompt injection defence

The lethal trifecta (Simon Willison, June 2025): any agent with private data access, exposure to untrusted content, and ability to communicate externally is structurally vulnerable. Filters reach roughly 97% accuracy on known patterns, leaving 3% unacceptable for a bank. OWASP LLM Top 10 (2025): LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM10 Unbounded Consumption. OWASP also released the Top 10 for Agentic AI Applications in late 2025.

Concrete defences:

1. **CaMeL pattern (Google DeepMind, April 2025)**: a privileged controller LLM never sees untrusted content; an isolated LLM processes untrusted content but cannot call tools.
2. **Avoid the lethal trifecta**: the scanner agent has no Group-private data while processing untrusted web responses.
3. **Tool-call gating**: every tool call requires a structured Pydantic schema; free text from web responses cannot directly become a tool argument.
4. **Untrusted-content tagging**: tag every byte from the target as `untrusted=true`; the planner is instructed never to follow instructions from untrusted content.
5. **Output filtering**: scrub Markdown links and images and HTML in agent context to prevent exfiltration via image-bait.
6. **Human-in-the-loop** for irreversible actions and scope-extending HTTP requests.
7. **Indirect-prompt-injection fuzzing** of the harness itself before deployment, using Promptfoo's lethal-trifecta tests and HackerOne's Agentic Prompt Injection Testing.

### 6.8 Safety rails

Scope enforcement is deterministic, not LLM-policed: an HTTP egress proxy (mitmproxy or Envoy) with a per-target host and port allowlist; off-scope attempts are blocked at the network level, logged, and themselves become a finding. Rate limits per target via token bucket on the proxy. Kill switch: the coordinator publishes `STOP` to a NATS subject; all agents poll on each tool-call boundary and abort. Blast radius: write operations forbidden by default; mutating verbs require explicit per-endpoint allowlist or shadow mode (request constructed but not sent, recorded for review). Resource budgets: per-job token cap, wall-clock cap, per-tool-call latency cap. Sandboxed execution: code the agent writes runs in gVisor or Firecracker with no outbound network except to the target via the proxy. Credential isolation: secrets never enter LLM context. Append-only audit log with cryptographic chaining for EU AI Act high-risk records. Tenant isolation: each engagement runs in a fresh container, vector-DB indexes per-engagement and destroyed at completion.

### 6.9 Recent academic research (2024–2026)

| Paper | ID | Finding |
|---|---|---|
| PentestGPT | arXiv:2308.06782, USENIX Security 2024 | Three-module design; 228.6% task completion gain |
| AutoAttacker | arXiv:2403.01038 | Three-agent navigator/planner/summariser with RAG |
| PenHeal | Huang & Zhu 2024 | Two-stage (Pentest + Remediation) with counterfactual prompting |
| Cybench | arXiv:2408.08926 | 40-CTF benchmark, standard for model-card evaluation |
| Big Sleep / Naptime | Project Zero 2024 | First AI-discovered real-world memory-safety zero day |
| Fuzz4All | arXiv:2308.04748 | +36.8% coverage, 47 unknown bugs |
| ChatAFL | NDSS 2024 | LLM-guided protocol fuzzing |
| MAPTA | arXiv:2508.20816 | Open-source multi-agent pentest, 80/104 XBOW |
| Excalibur | arXiv:2602.17622 | Difficulty-aware planning fixes Type B failures |
| Red-MIRROR | arXiv:2603.27127 | Reflective dual-phase plus RAG over CAPEC/NVD |
| CAI | arXiv:2510.24317 | 100% Base, 31% Cybench with G-CTR |
| MultiFuzz | arXiv:2508.14300 | RAG plus multi-agent ChatAFL |
| PentestEval | arXiv:2512.14233 | Six-stage decomposed benchmark; autonomous agents fail catastrophically (3–6%) vs manual PentestGPT (39%) |
| Penetration Testing of Agentic AI | arXiv:2512.14860 | AutoGen 52.3% vs CrewAI 30.8% refusal under attack |
| RuleLLM | arXiv:2504.17198 | LLM-driven YARA/Semgrep rule generation |

The PentestEval result drives a hard requirement: keep humans in the loop for verification of high-impact findings. Autonomous end-to-end pentesting at ~31% success is unsuitable for a regulated bank.

---

## 7.0 Question 6: Triage, deduplication, and Jira integration

### 7.1 CVSS v4.0

Published by FIRST on 1 November 2023. Four metric groups: Base (CVSS-B), Threat (CVSS-BT), Environmental (CVSS-BE), Supplemental (CVSS-BTE). Material changes from v3.1: AC split into AC and Attack Requirements (AT); UI distinguishes Passive vs Active; Scope removed and replaced by separate impact metrics for the Vulnerable System (VC/VI/VA) and the Subsequent System (SC/SI/SA); a Supplemental group covers Safety, Automatable, Recovery, Value Density, Vulnerability Response Effort, Provider Urgency. Scoring is no longer a closed-form formula; vectors map into equivalency sets (over fifteen million permutations compress into 101 score values) using expert-derived ranking.

Computation pattern in the harness:

1. The producer agent emits a Base vector only.
2. A separate enrichment service overlays Threat metrics from EPSS and CISA KEV, then Environmental metrics from the Group CMDB.
3. The final stored score is CVSS-BTE; persist the full vector string, not just the numeric.

### 7.2 EPSS v4

Current model is EPSS v4 (v2025.03.14), publishing since 17 March 2025. v4 expands exploitation telemetry to over 10,000 CVEs observed monthly, ingests RSS and web mentions, adds Shodan and HackerOne Hacktivity signals, normalises CWE to 22 categories, and excludes REJECTED CVEs. Refresh: daily for both score and percentile via FIRST. API base: `https://api.first.org/data/v1/epss`. NIST has now published Likely Exploited Vulnerabilities (LEV) which back-propagates EPSS to estimate past exploitation.

For the Group, an EPSS percentile of 0.90 to 0.95 combined with KEV listing is a defensible expedite trigger. A daily NATS-driven job pulls CVEs intersecting the asset inventory, joins to existing findings, and recomputes risk.

### 7.3 SSVC

CISA's SSVC is a decision table producing four outcomes for the deployer/coordinator role: Track, Track*, Attend, Act. Inputs: Exploitation status, Technical Impact, Automatable, Mission Prevalence, Public Well-being Impact. Store the SSVC outcome alongside the score; map to SLA targets.

### 7.4 Business risk weighting

```
BusinessRisk = w1 * f(CVSS-BTE)
             + w2 * g(EPSS_percentile, KEV_flag)
             + w3 * h(asset_criticality)        # 1..5 from CMDB
             + w4 * i(data_classification)      # public/internal/confidential/restricted
             + w5 * j(internet_exposure)        # internet/partner/internal
             + w6 * k(blast_radius)             # downstream service count via AGE
```

Weights and functions f..k are stored in a versioned policy file under change control. Agents cannot mutate them. This mirrors Snyk's Risk Score 0–1000.

### 7.5 Deduplication

Primary fingerprint:

```python
import hashlib, json
def finding_fingerprint(f) -> str:
    fields = {
        "vuln_class_id": f.cwe,
        "endpoint":      normalise_url(f.url),    # lowercase host, strip session ids,
                                                  # normalise numeric path segments to {id}
        "parameter":     f.parameter_name or "",
        "sink":          f.sink_location or "",
        "method":        (f.http_method or "").upper(),
        "auth_state":    f.auth_state,
    }
    blob = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

For SAST, use Semgrep's `match_based_id` (rule plus AST shape) so unchanged vulnerabilities do not re-open as new findings whenever code is reformatted. Fuzzy matching at scale: MinHash+LSH for stack traces (Jaccard ~0.85), SimHash for log lines (Hamming ≤ 3), Levenshtein only for short titles. pgvector cosine above 0.92 ranks candidate clusters but never decides them.

Cross-finding correlation in AGE produces `LIKELY_SAME_AS` edges where weighted by match strength. Mirror DefectDojo's `HASHCODE_FIELDS_PER_SCANNER` configurability per parser.

### 7.6 False-positive reduction

Verification chain (each stage must pass before promotion to a Jira ticket): payload variance (two or more semantically equivalent payloads); response invariants; differential testing (auth vs unauth, privilege-elevated vs reduced); sanitised control test (benign payload that should not trigger); independent verifier agent (different system prompt, ideally different model). The verifier never sees the producer's chain of thought, only structured evidence (request, response, diff, sink reference). ZeroPath routes by class to specialised verifiers (SSTI, SQLi, XSS, business logic). Persist verifier decision, prompt hash, model id, and evidence references in TimescaleDB for audit.

A Semgrep study found 88% of IDORs identified by Claude Code without static-analysis grounding were false positives; Sean Heelan's o3 evaluation showed 8 true positives, 66 false negatives, 28 false positives on a Kerberos benchmark. Treat any single agent verdict as a hypothesis.

### 7.7 Jira integration

Title schema: `[SEC-{class}] {short_desc} on {endpoint}`, e.g. `[SEC-SQLI] Boolean-based SQLi via 'q' parameter on /search` or `[SEC-IDOR] Cross-tenant account read on /api/v2/users/{id}`.

Severity to priority mapping (final business risk band, not raw CVSS):

| Internal severity | Jira priority |
|---|---|
| Critical | Highest |
| High | High |
| Medium | Medium |
| Low | Low |
| Info | Lowest |

Labels are flat strings encoded with prefixes:

```
component:payments-api
owasp:A03-2021-Injection
cwe:CWE-89
found-by:dast-agent-v2.4
scan-id:run-2026-04-26-7af3
cvss:CVSS_4_0_AV_N_AC_L_AT_N_PR_N_UI_N_VC_H_VI_H_VA_H_SC_N_SI_N_SA_N
epss:0.97
epss-pct:99
kev:true
business-criticality:tier-1
```

Attachments via `POST /rest/api/3/issue/{key}/attachments`, in order: redacted HTTP request and response (`.http`), sink trace, code snippet (±20 lines), SARIF excerpt for the specific result, idempotent reproduction script, verifier evidence bundle JSON.

Custom fields (IDs discovered per tenant via `GET /rest/api/3/field`):

```json
{
  "fields": {
    "project":      {"key": "SEC"},
    "summary":      "[SEC-SQLI] Boolean-based SQLi via `q` on /search",
    "issuetype":    {"name": "Vulnerability"},
    "priority":     {"name": "High"},
    "labels":       ["component:payments-api","owasp:A03-2021-Injection","cwe:CWE-89"],
    "customfield_10101": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",
    "customfield_10102": "CWE-89",
    "customfield_10103": "run-2026-04-26-7af3",
    "customfield_10104": "github.com/example-org/payments-api",
    "customfield_10105": "9f8e7d6c5b4a",
    "customfield_10106": 0.97,
    "customfield_10107": "Act"
  }
}
```

Linking: one Epic per scan run; finding tickets linked via `parent` or `is part of`; duplicate-cluster members linked via `duplicates` to the canonical ticket; cross-finding correlations via `relates to`; rediscovery re-opens the original ticket rather than creating a new one.

### 7.8 Avoiding ticket spam

The curl bug bounty terminated effective 31 January 2026 because only ~5% of submissions were genuine; HackerOne paused the Internet Bug Bounty in March 2026 because remediation capacity could not match AI-driven discovery. The internal harness applies equivalent discipline:

- **Cluster-batched ticketing**: one ticket per dedup cluster, canonical example in the description, member fingerprints listed; new members append a comment.
- **Suppression file** in repo root `.security-suppress.yml` with mandatory expiry; permanent suppressions require an exception register entry:
  ```yaml
  suppressions:
    - fingerprint: 7c3e...d9a1
      reason: "Internal admin endpoint, network ACL enforced at L3"
      expires: 2026-09-30
      approved_by: app-sec-lead@example.com
  ```
- **Recurrence**: re-open canonical tickets when a `Done` ticket re-matches within a window; comment the new scan id and evidence delta.
- **SLAs** (calendar days, paused during change freezes): Critical 7, High 30, Medium 90, Low 180, Info best-effort. SSVC `Act` overrides to 7 regardless of CVSS.
- **Quiet hours and freezes**: outside business hours only Critical/Act pages on call; during declared freezes (year-end, regulatory submissions), suspend non-critical ticket creation, persist in NATS dead-letter, replay post-freeze.

---

## 8.0 Question 7: Reference architecture for BFA integration

### 8.1 Agent topology

| Agent | NATS subject | Role |
|---|---|---|
| `horizontal.coordinator.agent` | `horizontal.coord.*` | Deterministic dispatch loop, scope and kill switch enforcement, fingerprint, knowledge-pack loader, budget controller |
| `horizontal.recon.agent` | `horizontal.recon.{cmd,result}` | Subfinder, Amass, httpx, Katana, gau, Arjun; emits routes and observed endpoints |
| `horizontal.sast.agent` | `horizontal.sast.{cmd,result}` | Semgrep, CodeQL, Bandit/Brakeman/gosec/njsscan/Psalm; emits SARIF |
| `horizontal.dast.agent` | `horizontal.dast.{cmd,result}` | ZAP, Nuclei, Wapiti, Schemathesis, RESTler, ffuf, feroxbuster |
| `horizontal.auth.agent` | `horizontal.auth.{cmd,session}` | Strategy registry; emits and refreshes `SessionState` |
| `horizontal.triage.agent` | `horizontal.triage.{cmd,result}` | CVSS v4.0 enrichment, EPSS lookup, SSVC mapping, dedup, business-risk weighting, per-class verifier orchestration |
| `horizontal.reporter.agent` | `horizontal.reporter.{cmd,result}` | SARIF aggregation, Jira ticketing, Slack notifications, Markdown report |

The coordinator is **not an LLM**. It is a Python state machine driven by FastStream subscribers. PydanticAI agents are invoked from worker subscribers via typed `Tool` invocations.

### 8.2 NATS subjects and message contracts

```python
# horizontal/contracts.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal
from uuid import UUID

class ScanRequest(BaseModel):
    scan_run_id: UUID
    application_id: UUID
    repo_url: str | None = None
    repo_ref: str | None = None
    targets: list[str]                          # https://app.example.com
    scope: dict                                 # allowlist, ratelimits, exclusions
    auth_refs: list[str]                        # credential handles (vault refs)
    knowledge_packs: list[str]                  # populated post-fingerprint
    budget: dict                                # tokens, wallclock_s, max_findings
    initiator: str

class ReconResult(BaseModel):
    scan_run_id: UUID
    routes_declared: list[dict]                 # from OpenAPI, source extraction
    routes_observed: list[dict]                 # from crawlers
    sbom_ref: str | None = None
    fingerprint: dict                           # RepoFingerprint serialised

class FindingCandidate(BaseModel):
    scan_run_id: UUID
    producer: Literal["sast","dast","secrets","supply_chain"]
    tool: str
    rule_id: str
    cwe: str | None = None
    title: str
    description: str
    location: dict                              # {url|file, line?, parameter?}
    evidence: dict                              # {request, response, snippet, taint_path}
    severity_proposed: Literal["info","low","medium","high","critical"]
    cvss_base_vector: str | None = None
    raw: dict                                   # original tool output
    sarif: dict | None = None
    dedup_hash: str
    match_based_id: str | None = None

class VerifiedFinding(FindingCandidate):
    is_real: bool
    confidence: float
    exploitability: Literal["confirmed","plausible","blocked","false_positive"]
    cvss_bte_vector: str
    epss: float | None = None
    ssvc: Literal["Track","Track*","Attend","Act"]
    business_risk: float
    verifier_model: str
    verifier_prompt_hash: str

class JiraTicket(BaseModel):
    scan_run_id: UUID
    finding_ids: list[UUID]
    issue_key: str | None = None
    cluster_canonical: UUID | None = None
    action: Literal["create","update","reopen","comment","skip_suppressed"]
```

NATS subjects (JetStream, durable consumers):

```
horizontal.coord.scan.start            ScanRequest
horizontal.coord.scan.cancel           {scan_run_id, reason}
horizontal.coord.scan.kill             {scan_run_id}            # global kill switch
horizontal.recon.cmd                   {scan_run_id, ...}
horizontal.recon.result                ReconResult
horizontal.auth.cmd                    {scan_run_id, target, role, method, credential_ref}
horizontal.auth.session                {scan_run_id, target, role, fingerprint}
horizontal.auth.session.invalid        {scan_run_id, target, role}
horizontal.sast.cmd                    {scan_run_id, repo_path, tools[], packs[]}
horizontal.sast.result                 FindingCandidate
horizontal.dast.cmd                    {scan_run_id, endpoint, payload_class, auth_zone}
horizontal.dast.result                 FindingCandidate
horizontal.triage.cmd                  FindingCandidate
horizontal.triage.result               VerifiedFinding
horizontal.reporter.cmd                VerifiedFinding[]
horizontal.reporter.result             JiraTicket
```

All consumers are idempotent on `idempotency_key`. Dead-letter queue for messages exceeding retry budget.

### 8.3 PydanticAI agent definitions

```python
# horizontal/agents/triage.py
from pydantic_ai import Agent, RunContext
from horizontal.contracts import FindingCandidate, VerifiedFinding

class TriageDeps:
    epss_client: "EPSSClient"
    cmdb: "CMDBClient"
    age: "AGEClient"
    pgvector: "VectorClient"
    policy: "BusinessRiskPolicy"
    knowledge_pack: "KnowledgePack"

triage_agent = Agent(
    model="anthropic:claude-sonnet-4-6",        # router selects per task
    deps_type=TriageDeps,
    output_type=VerifiedFinding,
    instructions=(
        "You verify candidate web vulnerabilities. You do not produce findings; "
        "you confirm or reject those produced by other agents. You only see "
        "structured evidence: request, response, code snippet, taint path. "
        "You return strict JSON conforming to VerifiedFinding."
    ),
)

@triage_agent.tool
async def epss_score(ctx: RunContext[TriageDeps], cve: str) -> dict:
    return await ctx.deps.epss_client.lookup(cve)

@triage_agent.tool
async def asset_context(ctx: RunContext[TriageDeps], application_id: str) -> dict:
    return await ctx.deps.cmdb.get(application_id)

@triage_agent.tool
async def similar_historical(ctx: RunContext[TriageDeps],
                             dedup_hash: str, embedding: list[float]) -> list[dict]:
    return await ctx.deps.pgvector.similar("historical_findings", embedding, k=5)

@triage_agent.tool
async def reachable_endpoint(ctx: RunContext[TriageDeps],
                             endpoint_hash: str) -> bool:
    return await ctx.deps.age.reachable_from_internet(endpoint_hash)
```

The verifier model is selected by the multi-provider LLM router with a constraint: it must not be the model that produced the candidate. The Mission Control router records the producer's model on the candidate and excludes it from the verifier pool.

### 8.4 FastAPI control plane endpoints

```
POST /v1/scans                          create scan run, returns scan_run_id
GET  /v1/scans/{id}                     scan status
POST /v1/scans/{id}:cancel              cooperative cancel
POST /v1/scans/{id}:kill                hard kill via NATS
GET  /v1/scans/{id}/findings            paginated findings
GET  /v1/scans/{id}/coverage            coverage matrix snapshot
GET  /v1/scans/{id}/sarif               aggregated SARIF (canonical interchange)
GET  /v1/applications/{id}/graph        AGE export (Cypher result)
POST /v1/auth/strategies/test           dry-run a strategy against a target
POST /v1/policies/business-risk         versioned policy update (RBAC-gated)
GET  /v1/health                         liveness and dependency checks
```

All endpoints emit OTel spans onto NATS with the BFA standard tracecontext propagation.

### 8.5 Ephemeral container execution model

Apply the existing Mission Control pattern: git worktrees plus ephemeral containers.

For white-box scanning, the coordinator creates a git worktree at the requested ref and mounts it read-only into a tool container. Each tool runs in a dedicated container image pinned by digest, with: no host volume mounts beyond the worktree; outbound network restricted to the egress proxy via a `scoped-net` Docker network; CPU and memory caps; a five-minute default wall-clock; SARIF or JSON output written to a tmpfs and slurped into the parent process before tear-down.

For black-box scanning, the egress proxy enforces the per-target allowlist. ZAP runs as a long-lived daemon inside its own container, fed targets and configurations via the Python SDK. Browser automation containers receive the active `SessionState` at start, never the raw credential.

Container teardown is unconditional: even on exception, the container is removed within 30 seconds via a coordinator-side timer. Containers carry an OTel tag of the `tool_executions.id` so traces and logs can be reconstructed post-mortem.

### 8.6 SARIF as canonical interchange

Every tool output is normalised to SARIF 2.1.0 before persistence. Tools with native SARIF (Semgrep, CodeQL, Bandit, Trivy, Grype, OSV-Scanner, govulncheck, Nuclei, ZAP via report add-on, Snyk Code, Gitleaks, Nosey Parker recent versions) feed a shared parser. Tools without SARIF go through tool-specific adapters that emit equivalent SARIF, with the original output preserved verbatim in the `findings.evidence` jsonb. The `findings.sarif` jsonb stores the SARIF result object for the specific finding; the full run-level SARIF is persisted in object storage and referenced from `scan_runs.config.sarif_ref`. The `/v1/scans/{id}/sarif` endpoint produces the merged SARIF for downstream consumers (GitHub Advanced Security, Defectdojo, internal dashboards).

`partialFingerprints` populated by tools (especially CodeQL) and `match_based_id` from Semgrep are preserved into `findings.match_based_id` for stable structural dedup.

---

## 9.0 Question 8: Anti-patterns

These are forbidden by policy.

**Letting the LLM execute arbitrary tools without sandboxing.** Prompt injection has documented attack success rates of 66.9% to 84.1% in agent systems with auto-execution; OWASP LLM Top 10 #1 for 2025; even hardened models record ~1% adversarial success against browser injection. Every tool call goes through a typed PydanticAI Tool with strict input schemas. No `shell=True`, no `eval`, no `exec`, no dynamic import. Containerise per scan target with Linux user namespaces (bubblewrap or gVisor) plus an egress allowlist.

**Trusting LLM-generated payloads without static validation.** Every payload passes a Pydantic validator with length cap (≤ 4096 bytes), character-class allowlist by injection context, and a regex-tested safe set per vulnerability class. Reject silently and re-prompt with the violation reason.

**No scope enforcement.** Out-of-scope testing is a contractual breach for a regulated bank. Domain allowlist enforced at the HTTP client layer (not via system prompt), egress controls at the network namespace, sub-agent scope inheritance via Pydantic-frozen scope object that cannot be widened.

**Mock-heavy integration tests.** The most common failures (TLS handshake, redirect handling, cookie jar bugs, body streaming) only manifest against real servers. CI runs ephemeral containers of OWASP Juice Shop, OWASP WebGoat, DVWA, NodeGoat, OWASP crAPI, OWASP vAPI, OWASP Benchmark, BodgeIt, bWAPP. Juice Shop's gamified design is an inadequate sole DAST benchmark; use multiple targets.

**Self-evaluation by the producing agent.** Confirmation bias and sycophancy are documented; Semgrep's Autotriage explicitly separates TP-reasoning from FP-reasoning chains because a single classifier produces "mediocre at both" results. The verifier sees only structured evidence, never the producer's chain of thought, and ideally runs a different base model.

**Using LLMs for tasks deterministic tools do better.** Sorting findings, parsing Python ASTs, hashing payloads, port-scanning a CIDR, regex matching: use `nmap`, `tree-sitter`/`ast`, `re`, `hashlib`, `sorted()`. Reserve the LLM for natural-language reasoning (interpreting an error, deciding semantic equivalence, drafting remediation notes).

**Storing secrets in agent context windows.** API tokens, basic-auth credentials, session cookies, and full request headers leak into traces, logs, and any vector DB. Secrets resolve at tool-call time from Vault using opaque handles. Strip `Authorization`, `Cookie`, `Set-Cookie`, and bearer tokens from anything written to logs, traces, or vector storage.

**Unbounded agent loops.** OWASP LLM10:2025 (Unbounded Consumption). Enforce all of: `max_iterations` (e.g. 25); wall-clock budget (e.g. 600 s per finding); token budget (e.g. 200,000 per scan); finding budget (e.g. 50 before forced flush); novelty-stalled detector (no new fingerprint in N iterations).

**Ungoverned tool sprawl.** Each agent role has a versioned tool registry; PydanticAI agents receive only the tool subset their role needs.

**Conflating recon, exploitation, and triage in one agent.** Separate agents (separate prompts, tool grants, processes) connected by NATS subjects. Producer of a finding must not be its verifier.

**Persisting raw web responses in pgvector without sanitisation.** Indirect prompt injection persists; OWASP LLM08:2025 was added in response. Before embedding, strip HTML to text, remove invisible Unicode (zero-width joiners, tag chars), strip oversized base64 blobs, neutralise instruction-like phrases (`ignore previous`, `system:`), tag every chunk with `untrusted=true`. Wrap untrusted chunks in spotlighted delimiters at retrieval time.

**Sharing one LLM context across multiple targets.** A fresh agent context per `(tenant, target, scan_run)`. Memory keyed by `(tenant_id, target_id)`. No cross-tenant retrieval.

**No deterministic replay.** Log per finding the model id and version, full prompt (templated with version hash), tool inventory hashes, payload set, RNG seed, target snapshot (commit SHA for static, response capture for DAST). NATS JetStream retention matches the regulatory record period.

**Treating LLM scores as ground truth without calibration.** Maintain a held-out labelled finding set; periodically score the agent against it; fit a Platt or isotonic calibration curve; apply before mapping confidence to severity. Track precision, recall, and effort metrics per scan run; alert on drift.

---

## 10.0 Conclusion: what changes in operational reality

This harness inverts the failure mode of first-generation agentic security tooling. First-generation tools either let one LLM agent do everything (producing high-confidence garbage that the curl and HackerOne post-mortems demonstrate is unworkable at any scale) or wrapped existing scanners as a thin LLM front-end (producing slower scans with no quality gain). This design is different in three structural ways.

First, **the LLM is the smallest possible part of the loop**. The coordinator is deterministic Python. Scope, kill switches, rate limits, and idempotency are enforced in code, not prompts. PydanticAI agents are invoked as typed functions inside FastStream consumers, never as autonomous loops. This matches what XBOW, ZeroPath, and Semgrep have all converged on after their public failure modes.

Second, **white-box leads, black-box follows**. Source code reading plus AGE-modelled application graphs plus SAST and SCA produce the dense, low-noise candidate set. Black-box DAST and fuzzing then verify and extend. This ordering, which DryRun's per-stack accuracy data and ZeroPath's investigation-first pipeline both validate, produces an order of magnitude lower false-positive rate than DAST-led approaches at equivalent coverage.

Third, **producer and verifier are separated by policy**. Every candidate finding is verified by an agent that did not produce it, on evidence-only inputs, using a different model where possible. The triage agent's output schema is strict; only `is_real=true` and `confidence ≥ θ` reach the reporter. This is how Corgea, Semgrep Assistant, and HackerOne Hai close the FP gap, and it is what separates findings worth opening a Jira ticket on from findings worth deleting.

Three operational outcomes follow. The harness produces fewer Jira tickets per scan than legacy DAST, with higher actionability per ticket. Engineering trust scales because every ticket carries a SARIF excerpt, a reproduction script, an audit trail of model id and prompt hash, and a verifier evidence bundle. Regulatory defensibility is intrinsic because deterministic replay, append-only audit, and CVSS v4.0 plus EPSS plus SSVC plus business-risk weighting are first-class properties of the data model rather than retrofitted. The right metric to track from day one is not findings per scan, it is the ratio of accepted-by-engineer to opened tickets per quarter. If that ratio is not above 0.7 within six months of go-live, the verifier or the calibration is wrong, not the producers.
