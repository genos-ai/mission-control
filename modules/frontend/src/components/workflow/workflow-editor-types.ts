/**
 * Workflow Editor — types, constants, and layout utilities.
 */

import { Graph, layout } from '@dagrejs/dagre'
import type { Node, Edge } from '@xyflow/react'
import { Bell, Bot, GitBranch, Layers, Merge, Signpost, Sparkles, Split, UserRound, Wrench, type LucideIcon } from 'lucide-react'
import type { Tone } from '@/lib/status-tone'
import type { WorkflowStep } from '@/types'

// ── Types ─────────────────────────────────────────────────────────────────

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  source_handle?: string
  target_handle?: string
  label?: string | null
}

export interface CanvasState {
  viewport?: { x: number; y: number; zoom: number }
  node_positions?: Record<string, { x: number; y: number }>
}

export interface WorkflowParameter {
  key: string
  label: string
  type: 'string' | 'text' | 'number' | 'boolean' | 'enum'
  required: boolean
  default?: unknown
  description?: string | null
  placeholder?: string | null
  options?: string[] | null
  min?: number | null
  max?: number | null
}

export interface WorkflowDetailFull {
  id: string
  name: string
  description: string
  version: number
  enabled: boolean
  trigger_type: string
  step_count: number
  designed_by: string
  locked_at: string | null
  steps: WorkflowStep[]
  edges_json: WorkflowEdge[]
  canvas_state: CanvasState
  objective: Record<string, unknown>
  budget_config: Record<string, unknown>
  trigger_config: Record<string, unknown>
  parameters: WorkflowParameter[]
  context: Record<string, unknown>
}

// ── Constants ─────────────────────────────────────────────────────────────

export const NODE_WIDTH = 220
export const NODE_HEIGHT = 56

/** Every kind of step a workflow can hold. */
export type StepType = NonNullable<WorkflowStep['node_type']>

export interface StepTypeInfo {
  label: string
  description: string
  icon: LucideIcon
  /** An agent step is toned by its agent's domain instead (`agentStyle`). */
  tone: Tone
}

/**
 * The one description of each step type: its name, icon and tone. The palette,
 * the toolbar, the nodes and the inspector all read it. Insertion order is the
 * order the types are offered in.
 */
export const STEP_TYPES: Record<StepType, StepTypeInfo> = {
  agent_step: { label: 'Agent step', description: 'Invoke a registered agent', icon: Bot, tone: 'neutral' },
  condition: { label: 'Condition', description: 'If/else branch on an expression', icon: GitBranch, tone: 'info' },
  notification: { label: 'Notification', description: 'Send a message (Telegram, SSE)', icon: Bell, tone: 'success' },
  human_input: { label: 'Human input', description: 'Pause and wait for a response', icon: UserRound, tone: 'warning' },
  tool_call: { label: 'Tool call', description: 'Call a tool directly', icon: Wrench, tone: 'neutral' },
  llm_call: { label: 'LLM call', description: 'Raw LLM prompt, no agent', icon: Sparkles, tone: 'brand' },
  branch: { label: 'Fork', description: 'Split into parallel paths', icon: Split, tone: 'neutral' },
  merge: { label: 'Join', description: 'Sync barrier for parallel paths', icon: Merge, tone: 'neutral' },
  sub_workflow: { label: 'Sub-workflow', description: 'Invoke another saved workflow', icon: Layers, tone: 'violet' },
  decision: { label: 'Decision', description: 'Route to different paths (agent, human or rule)', icon: Signpost, tone: 'violet' },
}

export const STEP_TYPE_ORDER = Object.keys(STEP_TYPES) as StepType[]

// ── Layout ────────────────────────────────────────────────────────────────

/**
 * Apply dagre auto-layout to a set of React Flow nodes and edges.
 * Returns new node array with updated positions.
 */
export function dagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new Graph()
  g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target)
  }

  layout(g)

  return nodes.map((node) => {
    const pos = g.node(node.id)
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    }
  })
}
