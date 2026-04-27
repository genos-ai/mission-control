/**
 * Workflow Editor — types, constants, and layout utilities.
 */

import { Graph, layout } from '@dagrejs/dagre'
import type { Node, Edge } from '@xyflow/react'
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
  context: Record<string, unknown>
}

// ── Constants ─────────────────────────────────────────────────────────────

export const NODE_WIDTH = 220
export const NODE_HEIGHT = 80

/** Domain → border color class for node outlines. */
export const DOMAIN_BORDER_COLORS: Record<string, string> = {
  code: 'border-blue-500/50',
  software: 'border-blue-500/50',
  dev: 'border-blue-500/50',
  engineer: 'border-blue-500/50',
  research: 'border-violet-500/50',
  analyst: 'border-violet-500/50',
  analysis: 'border-violet-500/50',
  security: 'border-rose-500/50',
  audit: 'border-rose-500/50',
  writer: 'border-emerald-500/50',
  content: 'border-emerald-500/50',
  data: 'border-cyan-500/50',
  mission: 'border-orange-500/50',
  director: 'border-orange-500/50',
  planning: 'border-orange-500/50',
  system: 'border-zinc-500/50',
  ops: 'border-zinc-500/50',
}

/** Domain → subtle background tint. */
export const DOMAIN_BG_COLORS: Record<string, string> = {
  code: 'bg-blue-500/5',
  software: 'bg-blue-500/5',
  dev: 'bg-blue-500/5',
  engineer: 'bg-blue-500/5',
  research: 'bg-violet-500/5',
  analyst: 'bg-violet-500/5',
  analysis: 'bg-violet-500/5',
  security: 'bg-rose-500/5',
  audit: 'bg-rose-500/5',
  writer: 'bg-emerald-500/5',
  content: 'bg-emerald-500/5',
  data: 'bg-cyan-500/5',
  mission: 'bg-orange-500/5',
  director: 'bg-orange-500/5',
  planning: 'bg-orange-500/5',
  system: 'bg-zinc-500/5',
  ops: 'bg-zinc-500/5',
}

export function getDomain(capability: string | null): string {
  if (!capability) return 'system'
  return capability.split('.')[0].toLowerCase()
}

export function getDomainBorder(capability: string | null): string {
  const domain = getDomain(capability)
  return DOMAIN_BORDER_COLORS[domain] ?? 'border-border'
}

export function getDomainBg(capability: string | null): string {
  const domain = getDomain(capability)
  return DOMAIN_BG_COLORS[domain] ?? 'bg-card'
}

/** Fixed colors for non-agent node types. */
export const NODE_TYPE_STYLES = {
  condition: {
    border: 'border-amber-500/60',
    bg: 'bg-amber-500/5',
  },
  notification: {
    border: 'border-sky-500/60',
    bg: 'bg-sky-500/5',
  },
  human_input: {
    border: 'border-orange-500/60 border-dashed',
    bg: 'bg-orange-500/5',
  },
  tool_call: {
    border: 'border-slate-500/60',
    bg: 'bg-slate-500/5',
  },
  llm_call: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-400/5',
  },
  branch: {
    border: 'border-zinc-500/60',
    bg: 'bg-zinc-500/5',
  },
  merge: {
    border: 'border-zinc-500/60',
    bg: 'bg-zinc-500/5',
  },
  sub_workflow: {
    border: 'border-indigo-500/60',
    bg: 'bg-indigo-500/5',
  },
} as const

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
