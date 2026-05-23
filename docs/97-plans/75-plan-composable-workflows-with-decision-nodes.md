# Plan 75: Composable Workflows with Decision Nodes

## Status: Closed (2026-05-21)

**Priority:** High
**Dependencies:** Plan 45 (Rich Workflow Model), Plan 53 (Workflow DB), Plan 72 (Task First-Class)
**Branch:** `feature/75-composable-workflows`

**Implementation notes:**
- All 7 phases shipped. Phase 3 (edge-option coverage) lives in `services/workflow_validator.py:158` (`_check_decision_edges`, called from `save_graph`) rather than `workflow_definition.py` — equivalent validation, different home.
- Follow-up after MVP: added `edges` field to `WorkflowSchema` so YAML-seeded templates can declare labeled decision-routing edges (derived edges are unlabeled). First template: `config/workflow_templates/general.decision-routing.workflow.yaml`.
- Follow-up: `condition_evaluator._REF_RE` extended to allow hyphens in node IDs (e.g. `@node.check-mcd.output`).

---

## Problem Statement

Mission Control has two execution paths today:

1. **Plans** — the Director calls the Planning Agent, which decomposes a novel
   objective into a task DAG. Flexible but expensive (LLM planning + supervisor
   loop).
2. **Workflows** — pre-designed step graphs executed deterministically. Cheap and
   predictable, but isolated: once a workflow completes, nothing happens next.

The gap: **there is no way to chain workflows with intelligent routing between
them.** After a deep research workflow completes, there's no mechanism for an
agent to decide "curate these findings into the knowledge platform" or "distribute
this report via email." The user must manually trigger the next workflow.

### Consequences

- Workflows are one-shot — no post-completion routing
- Complex multi-phase processes (research → curate → distribute) require manual
  intervention or fall back to the expensive plan-based path
- The `condition` node type handles simple boolean branching but cannot invoke
  an LLM to reason about which path to take
- The `sub_workflow` node type exists but only supports static references — no
  dynamic selection based on upstream output
- The Director's `run_workflow()` tool returns immediately; there's no mechanism
  for "run workflow A, then decide what to do next"

### Design Principle

**Run as deterministic as possible. The non-deterministic part is only the
decision-making.**

Each workflow remains a deterministic, pre-designed step graph. The new
`decision` node type is the only place where an LLM (or human) evaluates
outputs and picks the next path. This maximizes predictability, auditability,
and cost efficiency.

---

## Design

### New Node Type: `decision`

A `decision` node is a routing junction in the workflow graph. It evaluates
the outputs of upstream steps and selects which downstream path to take.

Three resolver types:

| Resolver | How it decides | Cost | Latency |
|----------|---------------|------|---------|
| `agent` | LLM evaluates upstream outputs + prompt, returns one of the declared option keys | ~$0.001 (Haiku) | 1-3s |
| `human` | Presents options to the user via chat/Telegram, waits for selection | $0 | Minutes-hours |
| `rule` | Evaluates a deterministic expression (same engine as `condition` nodes) | $0 | <1ms |

**Relationship to existing `condition` node:**

The `condition` node evaluates a boolean expression and branches to Yes/No
paths. It stays as-is — it's the right tool for simple if/else guards.

The `decision` node handles **N-way routing with optional LLM reasoning**. It
declares named options, each mapping to a downstream node. The resolver picks
one. This is a superset of `condition` in capability but serves a different
purpose: orchestrating workflow composition, not guarding a single step.

### How Decisions Route via Edges

Decision routing reuses the existing edge-label mechanism that `condition`
nodes already use. When a `condition` node runs, it sets `_branch` to the
chosen label (e.g., "Yes" or "No"). The wave engine's `_should_skip()` method
then skips downstream nodes whose incoming edge label doesn't match.

`decision` nodes work identically:

1. The decision resolver returns one of the declared option keys (e.g., `"curate"`)
2. The node sets `_branch` to that key
3. Each outgoing edge has a label matching an option key
4. `_should_skip()` skips nodes whose edge label doesn't match `_branch`

**One-line change to `_should_skip()` is needed.** The existing `_branch`
routing logic (line 1046-1058 in `workflow_run_waves.py`) checks edge labels
against the chosen branch — but it's gated behind `dep_type == "condition"`
at line 1038. We extend that guard to also match `"decision"`:

```python
# Before:
if dep_type != "condition":
# After:
if dep_type not in ("condition", "decision"):
```

This makes the existing edge-label routing logic apply to decision nodes
identically to how it works for condition nodes. The `_branch` key in
decision outputs is checked against edge labels, and non-matching downstream
nodes are skipped.

### Architectural Diagram

```
┌─────────────────┐
│  Deep Research   │  (agent_step: research.deep_research.searcher)
│   Workflow Steps │
└────────┬────────┘
         │ output: {findings: [...], coverage_score: 0.87}
         ▼
┌─────────────────┐
│    decision      │  resolver: agent
│  "route_findings"│  model: anthropic:claude-haiku-4-5
│                  │  prompt: "Given findings, pick next action..."
│  options:        │  options:
│    curate ───────│──→ knowledge_curation (sub_workflow)
│    distribute ───│──→ report_distribution (sub_workflow)
│    deepen ───────│──→ refine_query (agent_step, loops back)
└─────────────────┘
```

### Schema: `DecisionConfig`

```python
class DecisionOption(BaseModel):
    """A single option the resolver can choose."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Unique option key used as edge label for routing",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable description of when to pick this option",
    )


class DecisionConfig(BaseModel):
    """Configuration for a decision node — N-way routing with resolver."""

    model_config = ConfigDict(extra="forbid")

    resolver: str = Field(
        ...,
        pattern=r"^(agent|human|rule)$",
        description="How the decision is made: agent (LLM), human (approval gate), rule (expression)",
    )

    # ── Agent resolver fields ──
    model: str | None = Field(
        None,
        max_length=100,
        description="Model for agent resolver (default: anthropic:claude-haiku-4-5)",
    )
    prompt: str | None = Field(
        None,
        max_length=5000,
        description="Prompt template for agent resolver. "
        "Has access to @node.<id>.output variables.",
    )
    temperature: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Temperature for agent resolver",
    )

    # ── Human resolver fields ──
    prompt_message: str | None = Field(
        None,
        max_length=2000,
        description="Message shown to human when presenting options",
    )
    channel: str | None = Field(
        None,
        pattern=r"^(telegram|sse|chat)$",
        description="Channel for human resolver",
    )
    timeout_hours: float | None = Field(
        None, ge=0.1, le=720,
        description="Timeout for human decision",
    )
    default_option: str | None = Field(
        None,
        max_length=50,
        description="Option key to use on timeout (human resolver only)",
    )

    # ── Rule resolver fields ──
    expression: str | None = Field(
        None,
        max_length=500,
        description="Expression for rule resolver. Must evaluate to an option key string.",
    )

    # ── Options (all resolvers) ──
    options: list[DecisionOption] = Field(
        ...,
        min_length=2,
        description="Available routing options. Each key becomes an edge label.",
    )
```

### Validation Rules

Add to `WorkflowStepSchema._validate_node_type_config()`:

```python
if self.node_type == "decision" and self.decision_config is None:
    raise ValueError("decision_config is required for decision nodes")
```

Add cross-validation in `DecisionConfig`:

```python
@model_validator(mode="after")
def _validate_resolver_fields(self) -> "DecisionConfig":
    if self.resolver == "agent" and not self.prompt:
        raise ValueError("prompt is required for agent resolver")
    if self.resolver == "rule" and not self.expression:
        raise ValueError("expression is required for rule resolver")
    if self.resolver == "human" and not self.prompt_message:
        raise ValueError("prompt_message is required for human resolver")
    if self.default_option and self.default_option not in {o.key for o in self.options}:
        raise ValueError(f"default_option '{self.default_option}' not in options")
    return self
```

### Validation: Edges Must Cover All Options

Add to `WorkflowSchema.validate_steps()` — for every decision node, verify
that each declared option key appears as an edge label on at least one
outgoing edge:

```python
# Decision node option coverage
for step in steps:
    if step.node_type == "decision" and step.decision_config:
        option_keys = {o.key for o in step.decision_config.options}
        # Edge labels targeting downstream steps from this decision
        # are validated at save time when edges_json is available.
        # At schema level, just ensure options are non-empty (min_length=2).
```

Full edge-option coverage validation belongs in
`WorkflowDefinitionService.save_graph()` where `edges_json` is available:

```python
# For each decision node, every option key must appear as a label on
# at least one outgoing edge.
for step_dict in steps:
    if step_dict.get("node_type") == "decision":
        config = step_dict.get("decision_config", {})
        option_keys = {o["key"] for o in config.get("options", [])}
        outgoing_labels = {
            e.get("label") for e in edges
            if e.get("source") == step_dict["id"] and e.get("label")
        }
        missing = option_keys - outgoing_labels
        if missing:
            errors.append(
                f"Decision node '{step_dict['id']}' has options "
                f"{sorted(missing)} with no matching edge labels"
            )
```

---

## Data Flow

### Decision Node Execution Flow

```
1. Upstream step(s) complete → outputs in completed_outcomes
2. Wave engine reaches decision node
3. _execute_decision_step() called
4. Resolver invoked:
   a. agent: LLM call with prompt + upstream context → returns option key
   b. human: Present options via HumanInputWorkflow → returns option key
   c. rule:  Evaluate expression → returns option key
5. Validate returned key is in options
6. Set _branch = chosen_key in outputs
7. Wave engine continues → _should_skip() skips non-matching paths
```

### Agent Resolver Detail

Uses the same `_build_model()` + `PydanticAgent` pattern as the existing
`_execute_llm_call_step()` (line ~672 of `workflow_run_waves.py`). Import
path: `modules.backend.core.model_builder` (NOT `mission_control.helpers` —
consistency with the workflow engine).

LLM output is aggressively sanitized with `re.sub(r"[^a-z0-9_]", "", ...)`
to strip quotes, backticks, periods, and markdown artifacts that LLMs
commonly wrap around short responses. See full implementation in Phase 2.3.

### Human Resolver Detail

Reuses the existing `HumanInputWorkflow` Temporal workflow (same as
`human_input` nodes). The `choices` parameter maps to option keys.
On timeout, uses `default_option` if set, otherwise raises.

### Rule Resolver Detail

Reuses the existing condition evaluator's tokenizer, parser, and `_eval()`
AST evaluator. The expression must evaluate to a string value matching an
option key (not a boolean).

**Important:** The expression language does NOT support ternary syntax
(`? :`). It supports references (`@node.x.output.field`), comparisons, and
boolean logic. For the `rule` resolver, the expression should resolve to a
reference whose value IS the option key. Examples:

```
@node.classifier.output.next_action
@node.research.output.route
```

Where upstream agent output contains `{"next_action": "curate"}` or
`{"route": "distribute"}`. For boolean-guarded routing, use a `condition`
node instead — that's the right tool for if/else.

**Note:** The current `evaluate_condition()` returns a boolean (coerces via
`bool(result)`). For `rule` resolver, we need `evaluate_expression()` that
returns the raw string result. This mirrors `evaluate_condition()` exactly
but skips the `bool()` coercion.

The internal evaluation function is `_eval()` (NOT `_eval_safe` — that
doesn't exist). The correct flow matches `evaluate_condition()` at line 379:

```python
def evaluate_expression(
    expression: str,
    completed_outcomes: dict[str, dict],
    workflow_context: dict[str, Any] | None = None,
) -> str:
    """Evaluate an expression and return its string result.

    Unlike evaluate_condition() which coerces to bool, this returns the
    raw expression result as a string — used by decision node rule resolver.

    Raises ConditionEvaluationError on failure.
    """
    tokens = tokenize(expression)
    ast = _Parser(tokens).parse()
    result = _eval(ast, completed_outcomes, workflow_context or {})
    return str(result).strip()
```

---

## Blast Radius

### Files to Create

| File | Description |
|------|-------------|
| `modules/backend/migrations/versions/plan75_001_add_decision_node_type.py` | Alembic migration: no schema change needed (node_type is a string field validated by Pydantic, not a DB enum) |

No migration is actually needed. `node_type` is a `String` column validated
by Pydantic regex — adding `decision` to the regex is a schema-only change.
`decision_config` is stored in the `steps` JSON column alongside other
`*_config` fields.

### Files to Modify

| File | Change |
|------|--------|
| `modules/backend/schemas/workflow.py` | Add `DecisionOption`, `DecisionConfig`. Add `decision_config` field to `WorkflowStepSchema`. Extend `node_type` regex. Add validation. |
| `modules/backend/services/workflow_run_waves.py` | Add `_execute_decision_step()`. Add `_resolve_agent_decision()`, `_resolve_human_decision()`, `_resolve_rule_decision()`. Extend `_execute_step()` dispatch. Fix `_should_skip()` to handle decision nodes. |
| `modules/backend/services/workflow_definition.py` | Extend `save_graph()` validation for decision option-edge coverage. |
| `modules/backend/services/condition_evaluator.py` | Add `evaluate_expression()` for rule resolver. |
| `modules/backend/events/types.py` | Add `WorkflowDecisionResolvedEvent`. |
| `modules/frontend/src/types/workflow.ts` | Add `decision` to `WorkflowStep.node_type` union. Add `decision_config` field. |
| `modules/frontend/src/components/workflow/workflow-editor-node.tsx` | Add `DecisionNode` component (diamond/hexagon shape, option list). |
| `modules/frontend/src/components/workflow/workflow-editor-types.ts` | Add `decision` to `NODE_TYPE_STYLES`. |
| `modules/frontend/src/components/workflow/workflow-editor-toolbar.tsx` | Add decision node button to toolbar. |
| `modules/frontend/src/components/workflow/node-palette.tsx` | Add decision entry to palette. |
| `modules/frontend/src/components/workflow/step-detail.tsx` | Add decision config editor (resolver type, prompt, options list, model selector). |
| `modules/frontend/src/components/workflow/workflow-editor.tsx` | Register `DecisionNode` in `nodeTypes`. Add connection validation for decision outgoing edges (must have label). |
| `modules/frontend/src/hooks/use-workflow-run-status.ts` | Handle `workflow.decision.resolved` SSE event. |

### Files Unchanged

| File | Why |
|------|-----|
| `modules/backend/models/workflow_definition.py` | `steps` is a JSON column — no schema change needed |
| `modules/backend/models/workflow_run.py` | No model changes |
| `modules/backend/services/workflow_run.py` | Orchestrator unchanged — wave engine handles new node type |
| `modules/backend/services/workflow.py` | YAML loader unchanged |
| `modules/backend/temporal/` | No Temporal changes (human resolver reuses existing HumanInputWorkflow) |
| `modules/backend/agents/mission/director/agent.py` | `run_workflow()` tool unchanged — decision nodes are internal to workflows |

---

## Implementation Phases

### Phase 1: Backend Schema (decision_config + validation)

**File: `modules/backend/schemas/workflow.py`**

**1.1 Add DecisionOption and DecisionConfig classes**

Insert after `BranchConfig` (line ~161):

```python
class DecisionOption(BaseModel):
    """A single option the resolver can choose."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Unique option key used as edge label for routing",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable description of when to pick this option",
    )


class DecisionConfig(BaseModel):
    """Configuration for a decision node — N-way routing with resolver."""

    model_config = ConfigDict(extra="forbid")

    resolver: str = Field(
        ...,
        pattern=r"^(agent|human|rule)$",
    )
    model: str | None = Field(None, max_length=100)
    prompt: str | None = Field(None, max_length=5000)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    prompt_message: str | None = Field(None, max_length=2000)
    channel: str | None = Field(None, pattern=r"^(telegram|sse|chat)$")
    timeout_hours: float | None = Field(None, ge=0.1, le=720)
    default_option: str | None = Field(None, max_length=50)
    expression: str | None = Field(None, max_length=500)
    options: list[DecisionOption] = Field(..., min_length=2)

    @model_validator(mode="after")
    def _validate_resolver_fields(self) -> "DecisionConfig":
        if self.resolver == "agent" and not self.prompt:
            raise ValueError("prompt is required for agent resolver")
        if self.resolver == "rule" and not self.expression:
            raise ValueError("expression is required for rule resolver")
        if self.resolver == "human" and not self.prompt_message:
            raise ValueError("prompt_message is required for human resolver")
        if self.default_option and self.default_option not in {o.key for o in self.options}:
            raise ValueError(f"default_option '{self.default_option}' not in options")
        return self
```

**1.2 Add decision_config to WorkflowStepSchema**

In `WorkflowStepSchema` (line ~185), add after `branch_config`:

```python
decision_config: DecisionConfig | None = None
```

**1.3 Extend node_type regex**

Change line ~204 from:

```python
pattern=r"^(agent_step|condition|notification|human_input|tool_call|llm_call|branch|merge|sub_workflow)$",
```

To:

```python
pattern=r"^(agent_step|condition|notification|human_input|tool_call|llm_call|branch|merge|sub_workflow|decision)$",
```

**1.4 Add validation in _validate_node_type_config**

Add after the `sub_workflow` check (line ~293):

```python
if self.node_type == "decision" and self.decision_config is None:
    raise ValueError("decision_config is required for decision nodes")
```

**Exit criteria:** `DecisionConfig` validates correctly. Existing workflow
schemas still pass validation. New workflows with `decision` nodes validate
per resolver type.

---

### Phase 2: Backend Execution (wave engine + resolvers)

**File: `modules/backend/services/condition_evaluator.py`**

**2.1 Add evaluate_expression()**

Add alongside existing `evaluate_condition()` (line ~393). The implementation
mirrors `evaluate_condition()` exactly (tokenize → parse → _eval) but returns
`str(result)` instead of `bool(result)`:

```python
def evaluate_expression(
    expression: str,
    completed_outcomes: dict[str, dict],
    workflow_context: dict[str, Any] | None = None,
) -> str:
    """Evaluate an expression and return its string result.

    Unlike evaluate_condition() which coerces to bool, this returns the
    raw expression result as a string. Used by decision node rule resolver.

    Raises ConditionEvaluationError on failure.
    """
    tokens = tokenize(expression)
    ast = _Parser(tokens).parse()
    result = _eval(ast, completed_outcomes, workflow_context or {})
    return str(result).strip()
```

Note: `_eval()` is the internal AST evaluator (line ~307). `tokenize()` and
`_Parser` are already used by `evaluate_condition()`. All three are
module-private — `evaluate_expression()` is the new public API alongside
`evaluate_condition()` and `resolve_template()`.

**File: `modules/backend/services/workflow_run_waves.py`**

**2.2 Add _execute_decision_step()**

Add after `_execute_condition_step()` (line ~554):

```python
async def _execute_decision_step(
    self,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> tuple[VirtualExecution, dict]:
    """Resolve a decision and return the chosen option as _branch.

    Follows the same signature pattern as _execute_condition_step
    (lightweight routing — no session_id needed, extracted from run).
    """
    config = step.decision_config
    if not config:
        raise RuntimeError(f"decision_config missing for step '{step.id}'")

    valid_keys = {o.key for o in config.options}

    if config.resolver == "agent":
        chosen = await self._resolve_agent_decision(
            step, completed_outcomes, run.context or {},
        )
    elif config.resolver == "human":
        chosen = await self._resolve_human_decision(
            run, step, completed_outcomes,
        )
    elif config.resolver == "rule":
        chosen = await self._resolve_rule_decision(
            step, completed_outcomes, run.context or {},
        )
    else:
        raise RuntimeError(f"Unknown resolver '{config.resolver}' in step '{step.id}'")

    if chosen not in valid_keys:
        raise RuntimeError(
            f"Decision '{step.id}' resolver returned '{chosen}' "
            f"which is not in options: {sorted(valid_keys)}"
        )

    logger.info(
        "Decision resolved",
        extra={
            "step_id": step.id,
            "run_id": run.id,
            "resolver": config.resolver,
            "chosen": chosen,
        },
    )

    # Emit SSE event
    await self._publish_workflow_event(
        run.mission_id,
        WorkflowDecisionResolvedEvent(
            session_id=_uuid.UUID(str(run.session_id)),
            source="workflow_run_service",
            workflow_run_id=run.id,
            step_id=step.id,
            resolver=config.resolver,
            chosen_option=chosen,
            options=[o.key for o in config.options],
        ),
    )

    outputs = {"chosen": chosen, "_branch": chosen}
    return VirtualExecution(id=step.id), outputs
```

**2.3 Add resolver methods**

```python
async def _resolve_agent_decision(
    self,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
    workflow_context: dict,
) -> str:
    """LLM picks an option key."""
    config = step.decision_config
    model_name = config.model or "anthropic:claude-haiku-4-5"

    from modules.backend.services.condition_evaluator import resolve_template

    prompt = resolve_template(config.prompt, completed_outcomes, workflow_context)
    options_desc = "\n".join(f"- {o.key}: {o.label}" for o in config.options)

    full_prompt = (
        f"{prompt}\n\n"
        f"Available options:\n{options_desc}\n\n"
        f"Respond with ONLY the option key. No explanation."
    )

    from modules.backend.core.model_builder import _build_model
    from pydantic_ai import Agent as PydanticAgent

    model = _build_model(model_name)
    agent = PydanticAgent(
        model, output_type=str,
        instructions="You are a routing decision agent. Return only the option key.",
    )
    result = await agent.run(full_prompt)

    # Aggressively sanitize LLM output: strip whitespace, quotes,
    # backticks, periods, and other markdown artifacts that LLMs
    # commonly add around short responses.
    import re
    chosen = re.sub(r"[^a-z0-9_]", "", result.output.strip().lower())
    return chosen


async def _resolve_human_decision(
    self,
    run: WorkflowRun,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
) -> str:
    """Present options to human and wait for selection.

    Reuses _execute_human_input_step by constructing a temporary
    human_input-shaped step. Template resolution of prompt_message
    happens inside _execute_human_input_step (line 840) — do NOT
    resolve here or the template gets resolved twice.
    """
    config = step.decision_config
    choices = [o.key for o in config.options]

    # Reuse the existing HumanInputWorkflow via _execute_human_input_step
    # by building a temporary human_input-shaped step.
    # NOTE: pass raw prompt_message — _execute_human_input_step resolves
    # {{@node.*}} templates internally.
    from modules.backend.schemas.workflow import HumanInputConfig, WorkflowStepSchema as StepSchema

    hi_config = HumanInputConfig(
        prompt_message=config.prompt_message,
        channel=config.channel or "chat",
        timeout_hours=config.timeout_hours,
        default_response=config.default_option,
        choices=choices,
    )

    # Create a minimal step for the human input handler
    temp_step = StepSchema(
        id=step.id,
        node_type="human_input",
        human_input_config=hi_config,
        depends_on=step.depends_on,
    )

    _, outputs = await self._execute_human_input_step(
        run, temp_step, completed_outcomes,
    )

    response = outputs.get("response", "")
    # If response matches an option key, use it directly
    if response in {o.key for o in config.options}:
        return response
    # If timed out and default_option set, use that
    if outputs.get("timed_out") and config.default_option:
        return config.default_option

    raise RuntimeError(
        f"Decision '{step.id}' human response '{response}' "
        f"does not match any option key"
    )


async def _resolve_rule_decision(
    self,
    step: WorkflowStepSchema,
    completed_outcomes: dict[str, dict],
    workflow_context: dict,
) -> str:
    """Evaluate expression to get option key."""
    config = step.decision_config

    from modules.backend.services.condition_evaluator import (
        ConditionEvaluationError,
        evaluate_expression,
    )

    try:
        return evaluate_expression(
            config.expression, completed_outcomes, workflow_context,
        )
    except ConditionEvaluationError as e:
        raise RuntimeError(
            f"Decision '{step.id}' rule evaluation failed: {e}"
        ) from e
```

**2.4 Extend _execute_step() dispatch**

In `_execute_step()` (line ~358), add before the `agent_step` default:

```python
if node_type == "decision":
    return await self._execute_decision_step(run, step, completed_outcomes)
```

This follows the same dispatch pattern as `_execute_condition_step` — lightweight
routing nodes that don't need `session_id` or `ctx` (unlike `sub_workflow`).
The `run.session_id` attribute is available if needed internally.

**2.5 Fix _should_skip() for decision nodes**

In `_should_skip()` (line ~1038), change:

```python
if dep_type != "condition":
```

To:

```python
if dep_type not in ("condition", "decision"):
```

This makes the existing edge-label routing logic apply to both condition
and decision node types. The `_branch` output from decision nodes is checked
against edge labels on the outgoing edges, and non-matching downstream nodes
are skipped — identical behavior to condition nodes.

**File: `modules/backend/events/types.py`**

**2.6 Add WorkflowDecisionResolvedEvent**

Add alongside other workflow events (after `WorkflowSubWorkflowCompletedEvent`,
line ~324). Must inherit from `SessionEvent` (the base class for all session
events), NOT `BaseModel`:

```python
class WorkflowDecisionResolvedEvent(SessionEvent):
    """Emitted when a decision node resolves its routing choice."""

    event_type: str = "workflow.decision.resolved"
    workflow_run_id: str
    step_id: str
    resolver: str          # "agent" | "human" | "rule"
    chosen_option: str     # The selected option key
    options: list[str]     # All available option keys
```

`SessionEvent` provides: `event_id`, `session_id`, `timestamp`, `source`,
`correlation_id`, `trace_id`, `metadata`. Do NOT redeclare these.

**2.7 Register in EVENT_TYPE_MAP**

Add to the `EVENT_TYPE_MAP` dict (line ~781) alongside other workflow entries:

```python
"workflow.decision.resolved": WorkflowDecisionResolvedEvent,
```

Without this, the event cannot be deserialized from the SSE stream and will
be silently dropped.

**Exit criteria:** Decision nodes execute correctly for all three resolver
types. Agent resolver makes a Haiku call and returns an option key. Human
resolver delegates to HumanInputWorkflow. Rule resolver evaluates an
expression. `_should_skip()` routes downstream nodes correctly based on
`_branch`. SSE events emitted.

---

### Phase 3: Backend Validation (save_graph edge coverage)

**File: `modules/backend/services/workflow_definition.py`**

**3.1 Extend save_graph() validation**

In `_validate_steps()` or wherever step/edge validation happens in
`save_graph()`, add:

```python
# Decision node: every option key must have a matching edge label
for step_dict in steps_data:
    if step_dict.get("node_type") == "decision":
        config = step_dict.get("decision_config") or {}
        option_keys = {o["key"] for o in config.get("options", [])}
        outgoing_labels = {
            e.get("label") for e in edges_data
            if e.get("source") == step_dict["id"] and e.get("label")
        }
        missing = option_keys - outgoing_labels
        if missing:
            errors.append(
                f"Decision '{step_dict['id']}': options {sorted(missing)} "
                f"have no matching outgoing edge labels"
            )
```

**3.2 Connection constraint: decision outgoing edges must have labels**

When the frontend saves edges, validate that every edge originating from a
decision node has a non-empty label:

```python
# Decision nodes: outgoing edges must have labels
decision_ids = {
    s["id"] for s in steps_data if s.get("node_type") == "decision"
}
for e in edges_data:
    if e.get("source") in decision_ids and not e.get("label"):
        errors.append(
            f"Edge from decision node '{e['source']}' to "
            f"'{e['target']}' must have a label matching an option key"
        )
```

**Exit criteria:** Saving a workflow with a decision node that has uncovered
options fails with a clear validation error. Saving a valid workflow succeeds.

---

### Phase 4: Frontend Types + Node Component

**File: `modules/frontend/src/types/workflow.ts`**

**4.1 Add decision to WorkflowStep**

Update the `node_type` union (line ~23):

```typescript
node_type?: 'agent_step' | 'condition' | 'notification' | 'human_input' | 'tool_call' | 'llm_call' | 'branch' | 'merge' | 'sub_workflow' | 'decision'
```

Add `decision_config` field after `branch_config`:

```typescript
decision_config?: {
  resolver: 'agent' | 'human' | 'rule'
  model: string | null
  prompt: string | null
  temperature: number
  prompt_message: string | null
  channel: string | null
  timeout_hours: number | null
  default_option: string | null
  expression: string | null
  options: { key: string; label: string }[]
} | null
```

**File: `modules/frontend/src/components/workflow/workflow-editor-types.ts`**

**4.2 Add decision to NODE_TYPE_STYLES**

```typescript
decision: { bg: 'bg-purple-500/10', border: 'border-purple-500/40', text: 'text-purple-400' },
```

Purple distinguishes it from condition (which uses the default node styling).

**File: `modules/frontend/src/components/workflow/workflow-editor-node.tsx`**

**4.3 Add DecisionNode component**

Add after `SubWorkflowNode`:

```tsx
import { Signpost } from 'lucide-react'

export const DecisionNode = memo(function DecisionNode({ data, selected }: NodeProps<StepNodeData>) {
  const step = data.step
  const config = step.decision_config
  const style = NODE_TYPE_STYLES.decision
  const ring = selected ? selectedRing : STATUS_RING[data.status ?? 'idle']

  return (
    <div
      className={`relative rounded-lg border-2 px-3 py-2 shadow-sm ${style.border} ${style.bg} ${ring}`}
      style={{ width: NODE_WIDTH }}
    >
      <TargetHandle />
      {/* Multiple source handles — one per option */}
      {config?.options?.map((opt, i) => (
        <Handle
          key={opt.key}
          type="source"
          id={opt.key}
          position={Position.Right}
          style={{ top: `${((i + 1) / ((config?.options?.length ?? 1) + 1)) * 100}%` }}
          className="!h-3 !w-3 !rounded-full !border-2 !border-background !bg-purple-400"
        />
      ))}
      <div className="flex items-center gap-1.5">
        <Signpost className={`h-4 w-4 ${style.text}`} />
        <span className="truncate text-xs font-medium">{step.label || step.id}</span>
        {data.status && data.status !== 'idle' && <StatusIcon status={data.status} />}
      </div>
      {config && (
        <div className="mt-1 text-[10px] text-muted-foreground">
          {config.resolver} · {config.options?.length ?? 0} options
        </div>
      )}
      <MetricsBadge metrics={data.metrics} />
    </div>
  )
})
```

**File: `modules/frontend/src/components/workflow/workflow-editor.tsx`**

**4.4 Register DecisionNode in nodeTypes**

Add to the `nodeTypes` object:

```typescript
decision: DecisionNode,
```

**4.5 Connection validation for decision nodes**

In the `onConnect` or edge validation callback, when the source node is a
decision node, enforce that the edge gets a label from the node's options.
The simplest UX: when connecting from a decision node, auto-prompt for which
option this edge represents (dropdown of available option keys).

Alternative (simpler): require users to set edge labels manually in the
step-detail panel. Decision outgoing edges without labels will fail
save_graph() validation with a clear error message.

Recommend the simpler approach for Phase 4. Auto-prompt can be a follow-up.

**File: `modules/frontend/src/components/workflow/workflow-editor-toolbar.tsx`**

**4.6 Add decision button to toolbar**

Add a `Signpost` icon button in the toolbar alongside the other node-type
buttons:

```tsx
<ToolbarButton
  icon={Signpost}
  label="Decision"
  onClick={() => onAddNode('decision')}
/>
```

**File: `modules/frontend/src/components/workflow/node-palette.tsx`**

**4.7 Add decision entry to palette**

Add to the palette items array:

```typescript
{
  type: 'decision',
  label: 'Decision',
  description: 'Route to different paths based on agent, human, or rule evaluation',
  icon: Signpost,
}
```

**Exit criteria:** Decision node renders on the canvas with purple styling
and a Signpost icon. Multiple source handles shown (one per option). Node
appears in toolbar and palette. Node type appears in the step-detail panel
badge.

---

### Phase 5: Frontend Config Editor (step-detail panel)

**File: `modules/frontend/src/components/workflow/step-detail.tsx`**

**5.1 Add decision config editor section**

When `nodeType === 'decision'`, render:

1. **Resolver type** — dropdown: `agent`, `human`, `rule`
2. **Options list** — dynamic list of `{key, label}` pairs with add/remove buttons
3. **Conditional fields based on resolver:**
   - `agent`: model selector (text input, default `anthropic:claude-haiku-4-5`),
     prompt (VariableAutocomplete textarea), temperature slider
   - `human`: prompt_message (VariableAutocomplete textarea), channel dropdown,
     timeout_hours input, default_option dropdown (from options list)
   - `rule`: expression (VariableAutocomplete textarea)

```tsx
{nodeType === 'decision' && (
  <>
    {/* Resolver type */}
    <label className="text-xs text-muted-foreground">Resolver</label>
    <select
      value={draft.decision_config?.resolver ?? 'agent'}
      onChange={e => update({
        decision_config: {
          ...draft.decision_config!,
          resolver: e.target.value as 'agent' | 'human' | 'rule',
        },
      })}
      className="rounded border bg-background px-2 py-1 text-sm"
    >
      <option value="agent">Agent (LLM)</option>
      <option value="human">Human</option>
      <option value="rule">Rule</option>
    </select>

    {/* Options list */}
    <label className="text-xs text-muted-foreground">Options</label>
    {(draft.decision_config?.options ?? []).map((opt, i) => (
      <div key={i} className="flex gap-1">
        <Input
          placeholder="key"
          value={opt.key}
          onChange={e => {
            const opts = [...(draft.decision_config?.options ?? [])]
            opts[i] = { ...opts[i], key: e.target.value }
            update({ decision_config: { ...draft.decision_config!, options: opts } })
          }}
          className="w-1/3"
        />
        <Input
          placeholder="description"
          value={opt.label}
          onChange={e => {
            const opts = [...(draft.decision_config?.options ?? [])]
            opts[i] = { ...opts[i], label: e.target.value }
            update({ decision_config: { ...draft.decision_config!, options: opts } })
          }}
        />
        <Button
          variant="ghost" size="icon"
          onClick={() => {
            const opts = (draft.decision_config?.options ?? []).filter((_, j) => j !== i)
            update({ decision_config: { ...draft.decision_config!, options: opts } })
          }}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
    ))}
    <Button
      variant="outline" size="sm"
      onClick={() => {
        const opts = [...(draft.decision_config?.options ?? []), { key: '', label: '' }]
        update({ decision_config: { ...draft.decision_config!, options: opts } })
      }}
    >
      + Add option
    </Button>

    {/* Resolver-specific fields */}
    {draft.decision_config?.resolver === 'agent' && (
      <>
        <label className="text-xs text-muted-foreground">Model</label>
        <Input
          value={draft.decision_config?.model ?? 'anthropic:claude-haiku-4-5'}
          onChange={e => update({
            decision_config: { ...draft.decision_config!, model: e.target.value },
          })}
        />
        <label className="text-xs text-muted-foreground">Prompt</label>
        <VariableAutocomplete
          value={draft.decision_config?.prompt ?? ''}
          onChange={v => update({
            decision_config: { ...draft.decision_config!, prompt: v },
          })}
          upstreamNodeIds={upstreamNodeIds}
          mode="template"
        />
      </>
    )}

    {draft.decision_config?.resolver === 'human' && (
      <>
        <label className="text-xs text-muted-foreground">Prompt message</label>
        <VariableAutocomplete
          value={draft.decision_config?.prompt_message ?? ''}
          onChange={v => update({
            decision_config: { ...draft.decision_config!, prompt_message: v },
          })}
          upstreamNodeIds={upstreamNodeIds}
          mode="template"
        />
        <label className="text-xs text-muted-foreground">Channel</label>
        <select
          value={draft.decision_config?.channel ?? 'chat'}
          onChange={e => update({
            decision_config: { ...draft.decision_config!, channel: e.target.value },
          })}
          className="rounded border bg-background px-2 py-1 text-sm"
        >
          <option value="chat">Chat</option>
          <option value="telegram">Telegram</option>
          <option value="sse">SSE</option>
        </select>
        <label className="text-xs text-muted-foreground">Timeout (hours)</label>
        <Input
          type="number"
          value={draft.decision_config?.timeout_hours ?? ''}
          onChange={e => update({
            decision_config: { ...draft.decision_config!, timeout_hours: parseFloat(e.target.value) || null },
          })}
        />
        <label className="text-xs text-muted-foreground">Default option (on timeout)</label>
        <select
          value={draft.decision_config?.default_option ?? ''}
          onChange={e => update({
            decision_config: { ...draft.decision_config!, default_option: e.target.value || null },
          })}
          className="rounded border bg-background px-2 py-1 text-sm"
        >
          <option value="">None</option>
          {(draft.decision_config?.options ?? []).map(o => (
            <option key={o.key} value={o.key}>{o.key}</option>
          ))}
        </select>
      </>
    )}

    {draft.decision_config?.resolver === 'rule' && (
      <>
        <label className="text-xs text-muted-foreground">Expression</label>
        <VariableAutocomplete
          value={draft.decision_config?.expression ?? ''}
          onChange={v => update({
            decision_config: { ...draft.decision_config!, expression: v },
          })}
          upstreamNodeIds={upstreamNodeIds}
          mode="template"
        />
      </>
    )}
  </>
)}
```

**Exit criteria:** Selecting a decision node opens the step-detail panel with
resolver selector, options editor, and resolver-specific fields. Changes sync
to canvas in real-time. Save persists to DB.

---

### Phase 6: Frontend SSE Event Handling

**File: `modules/frontend/src/hooks/use-workflow-run-status.ts`**

**6.1 Add to WORKFLOW_EVENT_TYPES filter set**

The hook filters events through a `WORKFLOW_EVENT_TYPES` Set (line ~37).
Without adding the new event type, it will be silently ignored:

```typescript
// Add to the WORKFLOW_EVENT_TYPES Set:
'workflow.decision.resolved',
```

**6.2 Handle workflow.decision.resolved event**

Add to the event handler switch (alongside `workflow.condition.evaluated`):

```typescript
case 'workflow.decision.resolved':
  setNodeStatuses(prev => ({
    ...prev,
    [event.step_id]: 'completed',
  }))
  // Increment progress counter (decision step completed)
  setProgress(prev => [prev[0] + 1, prev[1]])
  break
```

The decision node transitions from `running` to `completed` when the resolver
returns. The chosen option label could optionally be shown on the node, but
that's a polish item — the status ring is sufficient for Phase 6.

**Exit criteria:** Decision nodes show running → completed status transitions
during live workflow execution. The SSE event stream includes decision.resolved
events. Progress counter increments when decision resolves.

---

### Phase 7: Edge Label UX for Decision Nodes

**File: `modules/frontend/src/components/workflow/workflow-editor.tsx`**

**7.1 Auto-label edges from decision nodes**

When a new edge is created from a decision node, auto-assign the first
unused option key as the edge label. The user can change it in the edge
properties or step-detail panel.

In the `onConnect` handler:

```typescript
if (sourceNode?.data?.step?.node_type === 'decision') {
  const config = sourceNode.data.step.decision_config
  const usedLabels = new Set(
    edges.filter(e => e.source === connection.source).map(e => e.label)
  )
  const availableOption = config?.options?.find(o => !usedLabels.has(o.key))
  if (availableOption) {
    newEdge.label = availableOption.key
    // Use the option key as the source handle ID
    newEdge.sourceHandle = availableOption.key
  }
}
```

**7.2 Edge label rendering**

Decision edges should render with their option key as a label, using
the same styling as condition edges (colored by option). Add to the
edge style logic:

```typescript
// Decision edges: purple tint with option key label
if (sourceNode?.data?.step?.node_type === 'decision' && edge.label) {
  return {
    ...baseStyle,
    stroke: 'hsl(270 60% 60% / 0.6)',
    label: edge.label,
  }
}
```

**Exit criteria:** Creating an edge from a decision node auto-assigns the
next unused option key. Edges render with purple-tinted labels showing the
option key.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Agent resolver returns invalid option key | Medium | Low | Validate against options set; raise clear error with valid keys listed |
| LLM returns option key with extra whitespace/casing/quotes | High | Low | `re.sub(r"[^a-z0-9_]", "", ...)` strips all non-key chars; option keys are lowercase by regex |
| Human resolver timeout with no default | Low | Medium | Validation warns at design time; runtime raises clear error |
| Circular workflows (decision loops back infinitely) | Medium | High | Budget enforcement per workflow run; add max_iterations on decision nodes as follow-up |
| Edge labels out of sync with options | Medium | Medium | save_graph() validates edge-option coverage; frontend auto-labels |
| Expression evaluator returns non-string for rule resolver | Low | Low | `str(result).strip()` coercion + validation against option keys |
| Rule resolver expression uses unsupported syntax (ternary) | Medium | Low | Expression language supports references and comparisons only — no `?:` ternary. Document that rule expressions must resolve to a value, not a conditional. For conditional routing, use a `condition` node upstream |

---

## Testing Strategy

### Unit Tests

1. `DecisionConfig` validation — all three resolver types, missing fields, invalid options
2. `WorkflowStepSchema` — decision node requires decision_config
3. `evaluate_expression()` — returns string result (not bool)
4. `_should_skip()` — decision nodes route correctly (matches existing condition tests)

### Integration Tests

1. Agent resolver: mock PydanticAgent to return option key → verify _branch set correctly
2. Human resolver: mock HumanInputWorkflow → verify option selection flows through
3. Rule resolver: expression returns option key → verify routing
4. Full workflow: agent_step → decision → two sub_workflows → only chosen one executes
5. Edge validation: save workflow with uncovered options → validation error

### Frontend Smoke Tests

1. Add decision node via palette → renders with purple styling
2. Configure agent resolver with prompt and options → saves correctly
3. Run workflow with decision node → status transitions correctly via SSE
4. Edge auto-labeling from decision source → correct option key assigned

---

## Success Criteria

1. Decision nodes execute correctly for all three resolver types
2. Only the chosen downstream path executes; other paths are skipped
3. SSE events surface decision outcomes in the workflow editor
4. Workflow editor supports full decision node CRUD (add, configure, connect, save)
5. save_graph() rejects workflows with uncovered decision options
6. Agent resolver costs < $0.005 per decision (Haiku-tier)
7. No regressions in existing node types (condition, sub_workflow, etc.)

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `modules/backend/schemas/workflow.py` | Modify | Add `DecisionOption`, `DecisionConfig`, extend `WorkflowStepSchema` |
| `modules/backend/services/workflow_run_waves.py` | Modify | Add `_execute_decision_step()` + 3 resolver methods, extend `_execute_step()`, fix `_should_skip()` |
| `modules/backend/services/condition_evaluator.py` | Modify | Add `evaluate_expression()` |
| `modules/backend/services/workflow_definition.py` | Modify | Add decision edge-option validation in `save_graph()` |
| `modules/backend/events/types.py` | Modify | Add `WorkflowDecisionResolvedEvent` |
| `modules/frontend/src/types/workflow.ts` | Modify | Add `decision` to node_type, add `decision_config` |
| `modules/frontend/src/components/workflow/workflow-editor-node.tsx` | Modify | Add `DecisionNode` component |
| `modules/frontend/src/components/workflow/workflow-editor-types.ts` | Modify | Add `decision` to `NODE_TYPE_STYLES` |
| `modules/frontend/src/components/workflow/workflow-editor-toolbar.tsx` | Modify | Add decision button |
| `modules/frontend/src/components/workflow/node-palette.tsx` | Modify | Add decision palette entry |
| `modules/frontend/src/components/workflow/step-detail.tsx` | Modify | Add decision config editor |
| `modules/frontend/src/components/workflow/workflow-editor.tsx` | Modify | Register `DecisionNode`, add edge auto-labeling |
| `modules/frontend/src/hooks/use-workflow-run-status.ts` | Modify | Handle `workflow.decision.resolved` event |

**No migrations needed.** `node_type` is a Pydantic-validated string, not a
DB enum. `decision_config` lives inside the `steps` JSON column.

---

## Cleanup Checklist

- [ ] Verify `condition` nodes still work correctly after `_should_skip()` change
- [ ] Remove any TODO comments added during implementation
- [ ] Confirm existing workflow templates (YAML seeds) still validate
- [ ] Run full workflow editor smoke test (create, edit, run, delete)

---

## Future Work (Not in Scope)

1. **Decision node max_iterations** — prevent infinite loops in workflows with
   decision nodes that loop back. Currently protected by budget enforcement;
   explicit iteration cap is a hardening follow-up.
2. **Director smart routing** — `run_objective()` checks for matching workflows
   before falling back to the Planning Agent. This is a Director-layer
   optimization, not a workflow-layer change.
3. **Plan tasks referencing workflows** — a planned task could execute via a
   workflow instead of a single agent. Requires Planning Agent awareness.
4. **Workflow templates with decision nodes** — seed YAML templates for common
   patterns (research → curate, security → remediate).
5. **Decision audit trail** — log all decision inputs/outputs to the knowledge
   platform for cross-mission learning.
6. **Architect agent awareness** — the workflow editor's architect chat
   (`useArchitectChat`) generates `ArchitectGraphProposal` with nodes and
   edges. Its prompt should be updated to know about `decision` nodes so it
   can propose workflows with intelligent routing. Not required for MVP.
