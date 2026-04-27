# Plan 45 — Rich Workflow Model + Visual Editor

| Field | Value |
|-------|-------|
| **Status** | Done |
| **Created** | 2026-04-24 |
| **Depends on** | Plan 53 (Workflow DB + Plan Integration — done), Plan 52 (Temporal Backbone — done), Plan 42 (Mission Backlog Model — done) |
| **Coordinates** | Plan 44 (Plan Tasks Invoke Workflows — TODO candidate), Plan 46 (Autonomous Mission Roadmap — Phase 5) |
| **Target** | Backend node schema + executor rewrite, frontend visual editor |

---

## 1  Problem

The workflow system today has two crippling gaps:

1. **Flat step model.** Every step is an `AgentStepNode` — invoke an agent, get output.
   There is no way to express conditionals ("if the quality score is below 0.7, re-run
   the analysis"), human pauses ("wait for the user to approve this report before
   publishing"), notifications, or sub-workflow composition. Users who need these
   patterns must either hardcode them in agent prompts (brittle, invisible to the
   platform) or give up and do it manually.

2. **No visual editor.** The Workflows tab is a flat list with Run/Delete buttons
   and an amber "coming soon" banner. Users cannot see the shape of a workflow,
   cannot drag nodes to rearrange them, cannot click a node to configure it, and
   cannot design new workflows visually. The only way to create a workflow is via
   the Workflow Architect agent in chat (which produces YAML) or by editing YAML
   files directly.

Together, these make the workflow system a second-class citizen — powerful on paper,
but invisible and inflexible in practice.

### What this plan delivers

A visual workflow designer that is:

- **Intuitive** — drag nodes from a palette, connect them with edges, click to
  configure. No YAML knowledge required.
- **Functional** — 8 node types covering agents, tools, LLM calls, conditionals,
  human input, notifications, branching, and sub-workflows.
- **Beautiful** — dark-mode-first, color-coded by node type, with smooth animations,
  a minimap for large workflows, and execution status overlays that show a workflow
  running in real-time.
- **AI-assisted** — the Workflow Architect can propose workflows in chat, and the
  graph renders live as the AI describes steps. The user refines visually, then
  locks the workflow in.

---

## 2  Design Principles

Drawn from competitor analysis (n8n, Windmill, Langflow, Rivet, ComfyUI) and our
own platform conventions:

1. **Progressive disclosure.** The simplest workflow (2 agent steps with a
   dependency) should be creatable in under 30 seconds with zero configuration
   beyond naming the steps and picking agents. Advanced features (variable binding,
   conditionals, timeouts, cost ceilings) are accessible but never in the way.

2. **Canvas is king.** The DAG graph is the primary interaction surface — not a
   sidebar list, not a form, not a table. Everything radiates from the canvas.
   Inspired by n8n's uncluttered workspace and ComfyUI's node-centric design.

3. **Inline configuration.** Clicking a node opens a config panel (slide-in from
   right, same as our existing drawer pattern — not a modal). The node stays
   visible on the canvas with a highlight ring. Inspired by n8n's contextual
   property panels.

4. **Live execution overlay.** The same canvas that designs workflows also shows
   execution state. Nodes light up green/amber/red as they run. Cost and duration
   appear on completed nodes. Inspired by Temporal's timeline view color coding.

5. **Keyboard-first.** `Space` to open the node palette (like Spotlight), `Delete`
   to remove selected, `Cmd+Z`/`Cmd+Shift+Z` for undo/redo, `Cmd+S` to save.
   Power users never need the mouse for common operations.

6. **Consistent with Mission Control.** Same Tailwind design tokens, same dark
   mode, same Lucide icons, same drawer/panel patterns, same React Query data
   fetching. A user who knows the Plan board knows the Workflow editor.

---

## 3  Node Type Schema

### 3.1  Discriminated union

Every node in a workflow is one of these types. The `node_type` field is the
discriminator.

```typescript
type WorkflowNode =
  | AgentStepNode       // Invoke a registered agent
  | ToolCallNode        // Call a tool directly (no agent wrapping)
  | LlmCallNode         // Raw LLM prompt (no agent, no tools)
  | ConditionNode       // If/else branch on a prior output
  | HumanInputNode      // Pause and wait for human response
  | NotificationNode    // Send a message (Telegram, Slack, email)
  | BranchNode          // Fork: one input, multiple outputs (parallel)
  | MergeNode           // Join: multiple inputs, one output (sync barrier)
  | SubWorkflowNode     // Invoke another workflow as a single node
```

### 3.2  Base fields (all node types)

```typescript
interface WorkflowNodeBase {
  id: string                    // Unique within workflow, e.g. "research-1"
  node_type: string             // Discriminator
  label: string                 // Human-readable name shown on canvas
  description: string | null    // Optional tooltip / help text
  position: { x: number; y: number }  // Canvas position (persisted)

  // Execution constraints
  timeout_seconds: number | null       // Per-node timeout (null = workflow default)
  cost_ceiling_usd: number | null      // Per-node budget cap
  retry_policy: {
    max_attempts: number               // Default: 1 (no retry)
    backoff_seconds: number            // Delay between retries
  }

  // Data flow
  inputs: Record<string, VariableBinding>    // Named input slots
  outputs: Record<string, OutputDefinition>  // Named output slots
}
```

### 3.3  Variable binding language

Extends the existing `@context.field` convention from YAML templates:

```
@context.query              — Read from workflow-level context
@node.research-1.summary    — Read from a specific node's output
@node.research-1.*          — Forward all outputs from a node
@input.articles             — Read from the current node's input slot
@env.ANTHROPIC_API_KEY      — Read from environment (restricted)
```

**Resolution order:** `@node.*` references are resolved at execution time from
the upstream node's completed output. The executor validates that all `@node.*`
references point to nodes that are upstream (transitively reachable via edges)
at save time — broken references are a validation error, not a runtime surprise.

### 3.4  Node type details

#### AgentStepNode

The workhorse. Invokes a registered agent from the catalog.

```typescript
interface AgentStepNode extends WorkflowNodeBase {
  node_type: "agent_step"
  agent_name: string              // e.g. "research.strategist.agent"
  agent_prompt: string | null     // Optional override of the agent's system prompt
  environment: "local" | "container"
  complexity_tier: "simple" | "complex"
  termination: "natural" | "criteria_met"
  max_refinement_rounds: number   // Default: 0
}
```

**Canvas appearance:** Rounded rectangle, agent domain color (blue for code,
violet for research, rose for security — same palette as plan board task cards).
Shows agent icon + label + cost ceiling badge.

#### ToolCallNode

Calls a tool directly without wrapping in an agent. For deterministic operations
like "send HTTP request", "write file", "run SQL query".

```typescript
interface ToolCallNode extends WorkflowNodeBase {
  node_type: "tool_call"
  tool_name: string               // Registered tool name
  tool_args: Record<string, VariableBinding>  // Static or bound arguments
}
```

**Canvas appearance:** Smaller rectangle with wrench icon, slate/gray color.

#### LlmCallNode

Raw LLM invocation — a prompt template with variable substitution. No agent
framework, no tools, no history. For simple transformations like "summarize this
text" or "extract entities from this JSON".

```typescript
interface LlmCallNode extends WorkflowNodeBase {
  node_type: "llm_call"
  model: string                   // e.g. "claude-haiku-4-5"
  system_prompt: string | null
  user_prompt_template: string    // Template with {{variable}} substitution
  temperature: number             // Default: 0.0
  max_tokens: number | null
  structured_output: object | null  // Optional JSON schema for output
}
```

**Canvas appearance:** Rounded rectangle with sparkle icon, amber/gold color.

#### ConditionNode

Evaluates a boolean expression on upstream output and routes to one of two
outgoing edges (true/false). The expression language is deliberately simple —
JSONPath-style field access + comparison operators.

```typescript
interface ConditionNode extends WorkflowNodeBase {
  node_type: "condition"
  expression: string              // e.g. "@node.check.score >= 0.7"
  true_label: string              // Label for the "true" edge (default: "Yes")
  false_label: string             // Label for the "false" edge (default: "No")
}
```

**Expression syntax:**
```
<variable> <operator> <literal>

Operators: ==, !=, >, >=, <, <=, contains, not_contains, is_empty, is_not_empty
Literals:  "string", 123, 45.6, true, false, null
Compound:  <expr> AND <expr>, <expr> OR <expr>, NOT <expr>
```

**Canvas appearance:** Diamond shape (classic flowchart conditional), cyan color.
Two outgoing handles labeled with true_label/false_label.

#### HumanInputNode

Pauses the workflow and waits for a human response. Can pause for minutes, hours,
or days. The pause is durable — survives backend restarts via Temporal timer.

```typescript
interface HumanInputNode extends WorkflowNodeBase {
  node_type: "human_input"
  prompt_message: string          // What to ask the human
  channel: "chat" | "telegram" | "slack" | "email"  // Where to ask
  timeout_hours: number | null    // Auto-fail after N hours (null = wait forever)
  choices: string[] | null        // Optional: constrain to specific choices
}
```

**Canvas appearance:** Rounded rectangle with user icon, orange color, dashed
border (visually distinct as "this step involves a human").

#### NotificationNode

Fire-and-forget message to a channel. Does not wait for a response (use
HumanInputNode for that). For alerts, status updates, and report delivery.

```typescript
interface NotificationNode extends WorkflowNodeBase {
  node_type: "notification"
  channel: "telegram" | "slack" | "email" | "webhook"
  message_template: string       // Template with {{variable}} substitution
  recipient: string | null       // Channel-specific (chat_id, email, URL)
}
```

**Canvas appearance:** Small rectangle with bell icon, teal color.

#### BranchNode (Fork)

Splits execution into parallel paths. One input, multiple outputs. All downstream
paths execute concurrently. Typically paired with a MergeNode.

```typescript
interface BranchNode extends WorkflowNodeBase {
  node_type: "branch"
  // No additional fields — the fork is defined by outgoing edges
}
```

**Canvas appearance:** Narrow vertical bar with split-arrow icon, gray. Multiple
outgoing handles.

#### MergeNode (Join)

Synchronization barrier. Waits for all incoming edges to complete before
continuing. Collects outputs from all incoming paths into a combined object.

```typescript
interface MergeNode extends WorkflowNodeBase {
  node_type: "merge"
  merge_strategy: "wait_all" | "wait_any"  // Default: "wait_all"
}
```

**Canvas appearance:** Narrow vertical bar with merge-arrow icon, gray. Multiple
incoming handles, one outgoing.

#### SubWorkflowNode

Invokes another saved workflow as a single node. Enables composition and reuse.
The sub-workflow's context is populated from this node's inputs; its final outputs
become this node's outputs.

```typescript
interface SubWorkflowNode extends WorkflowNodeBase {
  node_type: "sub_workflow"
  workflow_id: string             // Reference to another workflow_definition
  workflow_name: string           // Denormalized for display
  input_mapping: Record<string, VariableBinding>   // Map parent vars → child context
  output_mapping: Record<string, string>           // Map child outputs → parent outputs
}
```

**Canvas appearance:** Double-bordered rectangle with nested-workflow icon,
indigo color. Click to drill into the sub-workflow (opens in a new canvas tab).

---

## 4  Backend Changes

### 4.1  Migration: workflow node storage

The current `workflow_definitions.steps_json` stores a flat array of
`WorkflowStep` objects. Replace with a richer structure:

```python
# workflow_definitions table — existing columns preserved
# Changed column:
steps_json = Column(JSON, nullable=False, default=list)
# New: stores the full node graph instead of flat steps

# New column:
edges_json = Column(JSON, nullable=False, default=list)
# Stores: [{ "id": "e1", "source": "node-1", "target": "node-2",
#            "source_handle": "output", "target_handle": "input",
#            "label": "Yes" }]

canvas_state = Column(JSON, nullable=True)
# Stores viewport position, zoom level for editor restore
```

**Migration strategy:** The migration reads existing `steps_json` arrays,
converts each `WorkflowStep` to an `AgentStepNode` (the only type that existed),
computes edges from `depends_on` arrays, and writes back the new format. Fully
reversible — the rollback reconstructs `depends_on` from edges.

### 4.2  Node executor rewrite

Replace the current `WorkflowRunService._execute_step()` with a node-type
dispatcher:

```python
class NodeExecutor:
    """Dispatch execution to the handler for each node type."""

    _handlers: dict[str, Callable] = {
        "agent_step":    _execute_agent_step,
        "tool_call":     _execute_tool_call,
        "llm_call":      _execute_llm_call,
        "condition":     _execute_condition,
        "human_input":   _execute_human_input,
        "notification":  _execute_notification,
        "branch":        _execute_branch,
        "merge":         _execute_merge,
        "sub_workflow":  _execute_sub_workflow,
    }

    async def execute(self, node: WorkflowNodeBase, context: ExecutionContext):
        handler = self._handlers[node.node_type]
        return await handler(node, context)
```

**Key design:** Each handler is a standalone async function that:
1. Resolves `@node.*` and `@context.*` variable bindings from `ExecutionContext`
2. Executes the node's logic
3. Returns a `NodeResult` with typed outputs
4. Emits SSE events for live status

The executor walks the DAG topologically (same Kahn's algorithm as the current
`layoutSteps` in `dag-graph.tsx`), running parallel-ready nodes concurrently
via `asyncio.gather()`.

### 4.3  Condition expression evaluator

A minimal safe expression evaluator. No `eval()`, no arbitrary code.

```python
def evaluate_condition(expression: str, context: dict) -> bool:
    """Evaluate a condition expression against node outputs.

    Supports:
      @node.check.score >= 0.7
      @node.review.status == "approved" AND @node.review.confidence > 0.8
      @node.scan.findings is_empty

    Returns True or False. Raises ConditionError on parse failure.
    """
```

Implementation: tokenize → parse into AST → evaluate against context dict.
No third-party expression library needed — the grammar is small enough for a
hand-written recursive descent parser (~200 lines).

### 4.4  HumanInputNode execution (Temporal timer)

When the executor reaches a `HumanInputNode`:

1. Emit a `workflow.human_input.requested` SSE event with the prompt message
2. Send the prompt via the configured channel (Telegram, Slack, etc.)
3. Start a Temporal timer for `timeout_hours`
4. The workflow is now **paused** — the Temporal workflow is sleeping on a signal
5. When the human responds (via channel adapter or the Chat tab), the adapter
   calls a Temporal signal `human_input_received` with the response
6. The executor resumes, stores the response as the node's output, continues

This is the key differentiator — a workflow can pause for **days** and resume
exactly where it left off, surviving backend restarts.

### 4.5  Validation service

```python
class WorkflowValidator:
    """Validate a workflow graph before save or execution."""

    def validate(self, nodes: list[dict], edges: list[dict]) -> list[str]:
        errors = []
        errors += self._check_no_cycles(nodes, edges)
        errors += self._check_connected_graph(nodes, edges)
        errors += self._check_variable_references(nodes, edges)
        errors += self._check_condition_expressions(nodes)
        errors += self._check_agent_names_exist(nodes)
        errors += self._check_handle_compatibility(nodes, edges)
        return errors
```

Runs on every save. The frontend also runs a client-side subset (cycle detection,
connectivity) for instant feedback, but the backend is authoritative.

### 4.6  API endpoints

New and modified endpoints:

```
# Existing (unchanged)
GET    /missions/:id/workflows              — List workflows
GET    /missions/:id/workflows/:name        — Get workflow detail
POST   /missions/:id/workflows/import       — Clone template
POST   /missions/:id/workflows/:name/run    — Run workflow
DELETE /missions/:id/workflows/:id          — Delete workflow

# New
POST   /missions/:id/workflows              — Create workflow (from editor)
PUT    /missions/:id/workflows/:id/graph    — Save node graph + edges
POST   /missions/:id/workflows/:id/validate — Validate graph (returns errors)
GET    /missions/:id/workflows/:id/runs     — List runs for a workflow
GET    /missions/:id/workflows/:id/runs/:runId — Run detail with per-node status
```

**Request body for `PUT .../graph`:**
```json
{
  "nodes": [ { "id": "...", "node_type": "agent_step", ... } ],
  "edges": [ { "source": "node-1", "target": "node-2", ... } ],
  "canvas_state": { "viewport": { "x": 0, "y": 0, "zoom": 1 } }
}
```

---

## 5  Frontend — Visual Editor

### 5.1  Technology

| Library | Purpose | Notes |
|---------|---------|-------|
| @xyflow/react v12 | Canvas, nodes, edges, handles, minimap, controls | Already in package.json |
| @dagrejs/dagre | Auto-layout (left-to-right DAG) | ~15KB, integrates well with React Flow |
| zustand | Editor state (undo/redo stack, selection, clipboard) | Already used |

No new major dependencies. React Flow is already installed. Dagre is the standard
auto-layout library for React Flow — used by n8n, Langflow, and Windmill.

### 5.2  Page layout

The Workflows tab transforms from the current flat list into a split layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  Toolbar: [+ New] [Save] [Validate] [Auto-layout] [Run] [···] │
├──────────┬──────────────────────────────────────┬───────────────┤
│          │                                      │               │
│  Sidebar │         Canvas (React Flow)          │  Config Panel │
│  240px   │         flex-1                       │  360px        │
│          │                                      │  (optional)   │
│ Workflow │  ┌─────┐    ┌─────┐    ┌─────┐      │               │
│ List     │  │ Src │───▶│ LLM │───▶│Agent│      │  Node config  │
│ ──────── │  └─────┘    └─────┘    └─────┘      │  when a node  │
│ Node     │       ╲                              │  is selected  │
│ Palette  │        ╲   ┌─────┐                   │               │
│          │         └──▶│ If? │──▶ ...           │               │
│          │             └─────┘                   │               │
│          │                                      │               │
│          │  ┌──────────┐                        │               │
│          │  │ Minimap  │                        │               │
│          │  └──────────┘                        │               │
├──────────┴──────────────────────────────────────┴───────────────┤
│  Status: 8 nodes · 7 edges · Valid ✓ · Last saved 2m ago       │
└─────────────────────────────────────────────────────────────────┘
```

**Three regions:**

1. **Left sidebar (240px, collapsible):** Two sections — workflow list (top) and
   node palette (bottom). The workflow list replaces the current `WorkflowsPanel`
   list view. The node palette shows draggable node type tiles.

2. **Canvas (flex-1):** React Flow instance. This is where users drag, connect,
   and arrange nodes. Includes minimap (bottom-right), controls (bottom-left),
   and a background grid.

3. **Config panel (360px, slides in from right):** Opens when a node is selected
   on the canvas. Shows the node's configuration form — fields vary by node type.
   Same slide-in pattern as the existing right drawer. Closes on deselect or Escape.

### 5.3  Left sidebar — Node Palette

The node palette is the primary way to add nodes. Each node type is a tile
that can be dragged onto the canvas.

```
┌────────────────────┐
│ WORKFLOWS          │
│                    │
│ ● health-check  ▶ │  ← Click to load into canvas
│ ○ deep-research    │
│ ○ arch-review      │
│                    │
│ [+ New Workflow]   │
│                    │
│ ─────────────────  │
│ NODE PALETTE       │
│                    │
│ ┌──────┐ ┌──────┐ │
│ │ 🤖   │ │ 🔧   │ │
│ │Agent │ │Tool  │ │
│ └──────┘ └──────┘ │
│ ┌──────┐ ┌──────┐ │
│ │ ✨   │ │ ◇    │ │
│ │ LLM  │ │ If   │ │
│ └──────┘ └──────┘ │
│ ┌──────┐ ┌──────┐ │
│ │ 👤   │ │ 🔔   │ │
│ │Human │ │Notify│ │
│ └──────┘ └──────┘ │
│ ┌──────┐ ┌──────┐ │
│ │ ⑃    │ │ ⑂    │ │
│ │Fork  │ │Join  │ │
│ └──────┘ └──────┘ │
│ ┌──────────────┐  │
│ │ 📦 Workflow  │  │
│ └──────────────┘  │
└────────────────────┘
```

**Interaction:** Drag a tile from the palette and drop it on the canvas. The node
appears at the drop position with default configuration. A `ConditionNode` starts
with the expression `@node.prev.result == true`; an `AgentStepNode` starts with
no agent selected (the config panel opens automatically).

**Quick add (keyboard):** Press `Space` anywhere on the canvas to open a
command-palette-style search. Type "agent", "condition", "human" etc. to filter.
Press Enter to place the node at the cursor position. Inspired by n8n's node
picker and VS Code's command palette.

### 5.4  Canvas — Custom node components

Each node type has a distinct visual appearance. All nodes share a consistent
structure:

```
┌─ handle(s) ──────────────────────── handle(s) ─┐
│  [icon]  Label                        $0.50     │
│  Agent: research.strategist.agent               │
│  ● Running · 3.2s                               │
└─────────────────────────────────────────────────┘
```

**Common visual rules:**

| Element | Design |
|---------|--------|
| Shape | Rounded rectangle (12px radius) for most types. Diamond for ConditionNode. Narrow bar for Branch/Merge. |
| Width | 220px standard, 160px for Branch/Merge/Notification |
| Border | 1px solid, color varies by node type. Selected: 2px ring in primary color |
| Background | `bg-card` with node-type tint at 5% opacity |
| Icon | Lucide icon, node-type color, top-left |
| Label | 13px semibold, truncated with ellipsis |
| Subtitle | 11px muted, shows agent name / tool name / expression preview |
| Handles | Source (right), Target (left). Color matches node type. Glow on hover. |
| Status overlay | When running: amber pulse border. Done: green border. Failed: red border + error icon. |

**Node type color palette** (dark mode optimized):

| Node Type | Color | Tailwind | Rationale |
|-----------|-------|----------|-----------|
| AgentStep | Domain-specific | Same as plan board | Consistency with existing agent colors |
| ToolCall | Slate | `slate-400` | Neutral — tools are infrastructure |
| LlmCall | Amber | `amber-400` | Sparkle/AI connotation |
| Condition | Cyan | `cyan-400` | Decision/logic connotation |
| HumanInput | Orange | `orange-400` | Warm — human warmth |
| Notification | Teal | `teal-400` | Communication connotation |
| Branch/Merge | Gray | `zinc-500` | Structural — not a "step" |
| SubWorkflow | Indigo | `indigo-400` | Composition/nesting connotation |

### 5.5  Config panel (right slide-in)

When a node is selected, the config panel slides in from the right (360px).
Structure varies by node type but follows a consistent pattern:

```
┌────────────────────────────────────┐
│  [×]  Agent Step: research-1       │
│                                    │
│  Label ____________________________│
│  Description ______________________│
│                                    │
│  ── AGENT ──────────────────────── │
│  Agent  [research.strategist ▼]    │
│  Environment  [local ▼]           │
│  Complexity   [simple ▼]          │
│                                    │
│  ── INPUTS ─────────────────────── │
│  query    [@context.query      ]   │
│  depth    [comprehensive       ]   │
│                                    │
│  ── EXECUTION ──────────────────── │
│  Timeout (s)   [3600           ]   │
│  Cost ceiling  [$5.00          ]   │
│  Max retries   [1              ]   │
│                                    │
│  ── OUTPUTS ────────────────────── │
│  summary    string                 │
│  findings   object                 │
│                                    │
│  [Delete Node]                     │
└────────────────────────────────────┘
```

**Variable binding inputs:** Input fields that accept `@node.*` or `@context.*`
references show a special inline editor with autocomplete. Typing `@` triggers
a dropdown showing available upstream node outputs and context keys. The dropdown
is filtered as the user types. Selecting an item inserts the full reference.

**Agent picker:** The agent dropdown loads from `useCatalog()` (existing hook).
Shows agent name, description, and domain color. Grouped by domain.

### 5.6  Toolbar

Persistent horizontal bar above the canvas:

```
[+ New] [Save ⌘S] [Validate] [Auto-layout] [|] [Undo ⌘Z] [Redo ⌘⇧Z] [|] [▶ Run] [···]
```

| Button | Action |
|--------|--------|
| + New | Create a new empty workflow (prompts for name) |
| Save | Persist current graph to backend (`PUT .../graph`) |
| Validate | Run backend validation, show errors inline on nodes |
| Auto-layout | Run dagre layout (left-to-right), animate nodes to new positions |
| Undo / Redo | Local undo/redo stack (node add/remove/move, edge add/remove, config changes) |
| Run | Execute the current workflow (same as existing `useRunWorkflow`) |
| More (···) | Export as YAML, Duplicate, Delete, Version history |

### 5.7  Auto-layout

Uses `@dagrejs/dagre` to compute a left-to-right DAG layout:

```typescript
function autoLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
  g.setDefaultEdgeLabel(() => ({}))

  nodes.forEach(n => g.setNode(n.id, { width: 220, height: 80 }))
  edges.forEach(e => g.setEdge(e.source, e.target))

  dagre.layout(g)

  return nodes.map(n => {
    const pos = g.node(n.id)
    return { ...n, position: { x: pos.x - 110, y: pos.y - 40 } }
  })
}
```

Triggered by:
- The "Auto-layout" toolbar button
- After AI-assisted workflow generation (auto-layout the proposed graph)
- After importing a template (auto-layout once)

Nodes animate to their new positions via React Flow's built-in transition support
(~300ms ease-out).

### 5.8  Undo / Redo

A Zustand store tracks a stack of graph snapshots:

```typescript
interface EditorStore {
  // Graph state
  nodes: Node[]
  edges: Edge[]

  // Undo/redo
  undoStack: GraphSnapshot[]
  redoStack: GraphSnapshot[]
  pushSnapshot: () => void   // Call before any mutation
  undo: () => void
  redo: () => void

  // Selection
  selectedNodeId: string | null

  // Dirty tracking
  isDirty: boolean
  lastSavedAt: Date | null
}
```

Every mutation (add node, delete node, move node, add edge, delete edge, change
config) calls `pushSnapshot()` first. Capped at 50 snapshots. Keyboard shortcuts
`Cmd+Z` and `Cmd+Shift+Z` are wired via React Flow's `onKeyDown`.

### 5.9  Edge validation

Not all connections are valid. The editor enforces:

| Rule | Example |
|------|---------|
| No self-loops | A node cannot connect to itself |
| No cycles | A → B → C → A is rejected |
| Type compatibility | ConditionNode must have exactly 2 outgoing edges (true/false) |
| Handle direction | Source handles (right) → Target handles (left) only |
| BranchNode | Must have ≥2 outgoing edges |
| MergeNode | Must have ≥2 incoming edges |
| SubWorkflowNode | Cannot reference itself (no recursion) |

React Flow's `isValidConnection` callback enforces these in real-time. Invalid
connections show a red indicator on the target handle (same pattern as n8n).

### 5.10  Execution visualization

When a workflow is running, the canvas shows live status:

| Node State | Visual |
|------------|--------|
| Pending | Default appearance, muted opacity (60%) |
| Running | Amber pulse border (2px, animated), spinner icon replaces type icon |
| Completed | Green border, checkmark icon, cost + duration badge |
| Failed | Red border, X icon, error message tooltip |
| Skipped | Gray, strikethrough label |
| Waiting (HumanInput) | Orange pulse border, hourglass icon, "Waiting for response" subtitle |

Edges animate too: a flowing dash pattern on the edge between a completed node
and a running node (shows data flowing). Completed edges are solid green.
Pending edges are dashed gray.

The execution overlay is read-only — users cannot edit the graph while a workflow
is running. The "Run" button changes to "Running..." (disabled) with a cancel
button.

### 5.11  AI-assisted workflow design

The Workflow Architect integration bridges the chat drawer and the canvas:

**Flow:**
1. User clicks "+ New Workflow" or opens the Architect drawer
2. The chat drawer opens on the right (replaces the config panel)
3. User describes what they want: "Design a workflow that researches a topic,
   validates the findings, and sends a Telegram notification"
4. The Architect responds with a structured workflow proposal (JSON alongside
   the chat message)
5. The frontend parses the proposal and **renders nodes on the canvas in
   real-time** as the chat streams
6. User can then:
   - Refine via chat: "Add a condition after the validation step"
   - Edit visually: drag nodes, reconfigure, add edges
   - Mix both: visual edits are reflected in the next Architect round
7. When satisfied, user clicks "Save" — the graph persists to the backend

**Architect response format:**

```json
{
  "response": "Here's a workflow that...",
  "workflow_proposal": {
    "nodes": [ ... ],
    "edges": [ ... ]
  }
}
```

The existing `useArchitectChat` hook is extended to parse `workflow_proposal`
from the response. When present, the editor store replaces the current graph
with the proposal and runs auto-layout.

---

## 6  Phases

### Phase 1 — Node schema + migration (backend)

**Goal:** The backend understands the new node types and can store/retrieve
workflow graphs with the new schema.

**Work:**
1. Define Pydantic models for all 9 node types + edges
2. Write the migration to convert existing `steps_json` → new format
3. Update `WorkflowDefinitionService` to validate and store the new format
4. Update `GET /missions/:id/workflows/:name` to return nodes + edges
5. Add `PUT /missions/:id/workflows/:id/graph` endpoint
6. Add `POST /missions/:id/workflows/:id/validate` endpoint

**Exit criteria:**
- Existing workflows load correctly after migration
- New workflows with mixed node types can be saved and retrieved
- Validation catches cycles, broken references, and invalid connections

### Phase 2 — Node executor (backend)

**Goal:** The executor can run workflows with all 9 node types.

**Work:**
1. Implement `NodeExecutor` with type-dispatched handlers
2. Implement condition expression evaluator
3. Implement Branch/Merge parallel execution
4. Implement NotificationNode (Telegram adapter exists)
5. Wire SSE events for per-node status updates
6. Update `WorkflowRunService.run_workflow_from_definition()` to use `NodeExecutor`

**Exit criteria:**
- A workflow with Agent + Condition + Notification nodes runs end-to-end
- Branch/Merge parallel execution works with 3+ parallel paths
- Per-node SSE events appear in the Console tab
- Existing agent-only workflows still run correctly (no regression)

### Phase 3 — Visual editor foundation (frontend)

**Goal:** The Workflows tab shows a working canvas with drag-and-drop node
creation, edge connections, and node configuration.

**Work:**
1. Replace `WorkflowsPanel` list view with the split layout (sidebar + canvas + config panel)
2. Implement custom React Flow node components for all 9 types
3. Implement the node palette (sidebar, drag-to-canvas)
4. Implement the config panel (right slide-in, per-node-type forms)
5. Implement edge validation (`isValidConnection`)
6. Wire save/load to backend (`useMissionWorkflow` + `PUT .../graph`)
7. Add auto-layout with dagre
8. Add undo/redo store
9. Add keyboard shortcuts (Space for palette search, Delete, Cmd+Z/Shift+Z, Cmd+S)

**Exit criteria:**
- User can create a workflow with 5+ nodes visually (no YAML)
- User can connect nodes, configure them, save, and reload
- Auto-layout produces a clean left-to-right arrangement
- Undo/redo works for all operations
- The workflow runs via the existing Run button

### Phase 4 — HumanInputNode + execution overlay (frontend + backend)

**Goal:** Workflows can pause for human input, and the canvas shows live
execution status.

**Work:**
1. Implement HumanInputNode execution via Temporal timer + signal
2. Wire channel adapters (Telegram first, chat tab second)
3. Implement execution visualization on the canvas (node status overlays)
4. Implement edge animation (data flow visualization)
5. Add run history view (list of runs per workflow with per-node status)

**Exit criteria:**
- A workflow with a HumanInputNode pauses, sends a Telegram message, waits
  for the response, and resumes
- The canvas shows live node status while a workflow runs
- A returning user can see the run history with per-node outcomes

### Phase 5 — SubWorkflowNode + AI-assisted design

**Goal:** Workflows can compose other workflows, and the Architect can propose
workflows that render live on the canvas.

**Work:**
1. Implement SubWorkflowNode execution (recursive workflow invocation)
2. Implement drill-into UX (click sub-workflow → open child canvas)
3. Extend Architect agent to return `workflow_proposal` JSON
4. Wire Architect chat drawer → canvas live rendering
5. Implement "Save as template" (promote mission workflow to system template)

**Exit criteria:**
- A workflow containing a SubWorkflowNode runs end-to-end
- Clicking a SubWorkflowNode opens the child workflow in a nested canvas
- The Architect can propose a 5-node workflow from a natural language description
  and it renders correctly on the canvas
- User can refine the AI proposal both visually and via chat

---

## 7  Migration path from current state

The current `WorkflowStep` model maps 1:1 to `AgentStepNode`:

| Current field | New field | Notes |
|---------------|-----------|-------|
| `id` | `id` | Unchanged |
| `description` | `description` | Unchanged |
| `capability` | `agent_name` | Resolved via catalog lookup |
| `roster` | (dropped) | Roster concept subsumed by mission team |
| `complexity_tier` | `complexity_tier` | Unchanged |
| `cost_ceiling_usd` | `cost_ceiling_usd` | Unchanged |
| `environment` | `environment` | Unchanged |
| `input` | `inputs` | Flatten `@context.*` refs into `VariableBinding` |
| `output_mapping` | `outputs` | Convert field_mappings to `OutputDefinition` |
| `depends_on` | (edges) | Moved to `edges_json` — no longer on the node |
| `timeout_seconds` | `timeout_seconds` | Unchanged |
| `max_refinement_rounds` | `max_refinement_rounds` | Unchanged |
| `termination` | `termination` | Unchanged |
| `max_iterations` | (dropped) | Superseded by `retry_policy.max_attempts` |

The migration is **non-destructive** — old workflows become valid `AgentStepNode`
graphs. No workflow is lost or broken.

---

## 8  Performance considerations

| Concern | Mitigation |
|---------|-----------|
| Large graphs (50+ nodes) | React Flow handles 100+ nodes natively. Minimap for navigation. Dagre layout runs in <50ms for 100 nodes. |
| Canvas rerenders | React Flow uses internal virtualization — only visible nodes render. Node components are memoized with `React.memo`. |
| Save frequency | Debounced auto-save (2s after last change) + explicit Save button. Dirty indicator in status bar. |
| Undo stack memory | Capped at 50 snapshots. Each snapshot is a shallow copy of nodes + edges arrays (~KB each). |
| SSE event volume during execution | Reuse existing mission SSE stream. Per-node status events are low volume (~1 per node per state change). |

---

## 9  Out of scope

- **Workflow versioning UI.** The backend already stores `version` on
  `workflow_definitions`. A visual diff between versions is deferred.
- **Collaborative editing.** One user edits at a time. The `locked_at` column
  on `workflow_definitions` prevents concurrent edits.
- **Custom node types.** The 9 node types cover all planned use cases. A plugin
  system for user-defined node types is out of scope.
- **Mobile / tablet.** The editor is desktop-only (1440px+ screens), consistent
  with the rest of Mission Control.
- **Import/export to external formats.** No BPMN, no Temporal DSL, no n8n JSON.
  YAML export is the only external format (via the toolbar "Export" option).

---

## 10  References

### Plans

- [Plan 29 — Frontend Design Specification](29-plan-frontend-design-[X].md) §5.7 (Workflows Tab wireframe)
- [Plan 42 — Mission Backlog Model](42-plan-mission-backlog-model.md) (plan task dispatch)
- [Plan 44 — Plan Tasks Invoke Workflows](TODO candidate) (discriminated task types)
- [Plan 46 — Autonomous Mission Roadmap](46-plan-autonomous-mission-roadmap.md) §4 Phase 5
- [Plan 53 — Workflow DB + Plan Integration](53-plan-workflow-db-and-plan-integration-[X].md)

### Competitor analysis (informing UX decisions)

| Product | Key takeaway adopted |
|---------|---------------------|
| n8n | Node palette as categorized sidebar, contextual config panels, uncluttered canvas |
| Windmill | Flow groups, drag-drop reordering with ghost previews, collapsible subflows |
| Langflow | Component-based node system, dark mode with vibrant node colors |
| ComfyUI | Node-centric design, minimal chrome, inputs/outputs as typed handles |
| Rivet | AI-specific node types (LLM call, prompt template), variable binding visualization |
| Temporal | Execution timeline color coding (green/amber/red), duration visualization |

### Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| @xyflow/react | ^12.10 | Canvas, nodes, edges, handles, minimap, controls |
| @dagrejs/dagre | ^1.1 | Auto-layout (left-to-right DAG) |
| zustand | ^4.4 | Editor state (undo/redo, selection, dirty tracking) |
