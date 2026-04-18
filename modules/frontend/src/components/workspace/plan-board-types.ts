/**
 * PlanBoard — shared types, constants, and pure utility functions.
 */

import type { PlanTaskStatus } from '@/hooks/use-mission-plan'

// ── Types ─────────────────────────────────────────────────────────────────

export type ColumnId = 'proposed' | 'approved' | 'running' | 'done'

export interface ColumnDef {
  id: ColumnId
  label: string
  statuses: PlanTaskStatus[]
}

/** One task body + its persistent state, with live-overlay applied. */
export interface JoinedTask {
  body: import('@/hooks/use-mission-plan').PlanTaskBody
  state: import('@/hooks/use-mission-plan').PlanTaskState | null
  /** Overlay status wins over durable state when present. */
  effectiveStatus: PlanTaskStatus
}

/** JoinedTask with computed blocked-by-dependency info. */
export interface AnnotatedTask extends JoinedTask {
  blocked: boolean
  blockingDeps: string[]
}

export interface Rect {
  left: number
  top: number
  right: number
  bottom: number
  width: number
  height: number
}

export interface Edge {
  from: string
  to: string
  state: 'grey' | 'amber' | 'green' | 'failed'
}

export interface VetoState {
  /** Whole seconds remaining until the window expires. 0 when expired. */
  remainingSec: number
  /** True once the timestamp has passed — veto is no longer available. */
  expired: boolean
}

// ── Constants ─────────────────────────────────────────────────────────────

export const COLUMN_DEFS: ColumnDef[] = [
  { id: 'proposed', label: 'Proposed', statuses: ['proposed'] },
  { id: 'approved', label: 'Approved', statuses: ['approved', 'queued'] },
  { id: 'running', label: 'Running', statuses: ['running'] },
  { id: 'done', label: 'Done', statuses: ['completed', 'failed', 'skipped', 'cancelled'] },
]

export const AGENT_DOMAIN_COLORS: Record<string, string> = {
  code: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  software: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  dev: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  engineer: 'bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/30',
  research: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  analyst: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  analysis: 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30',
  security: 'bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/30',
  audit: 'bg-rose-500/10 text-rose-400 ring-1 ring-inset ring-rose-500/30',
  writer: 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30',
  content: 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30',
  data: 'bg-cyan-500/10 text-cyan-400 ring-1 ring-inset ring-cyan-500/30',
  mission: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
  director: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
  planning: 'bg-orange-500/10 text-orange-400 ring-1 ring-inset ring-orange-500/30',
}

export const PRE_RUN_GATE_KEY = (missionId: string) => `prerun_gate_dismissed:${missionId}`

// ── Pure utility functions ────────────────────────────────────────────────

export function columnFor(status: PlanTaskStatus): ColumnId {
  for (const def of COLUMN_DEFS) {
    if (def.statuses.includes(status)) return def.id
  }
  return 'proposed'
}

export function getBorderClass(status: PlanTaskStatus): string {
  switch (status) {
    case 'running':
      return 'border-amber-500/40'
    case 'completed':
      return 'border-emerald-500/25'
    case 'failed':
      return 'border-destructive/40'
    case 'cancelled':
    case 'skipped':
      return 'border-border/30'
    case 'approved':
    case 'queued':
      return 'border-primary/30'
    default:
      return 'border-border'
  }
}

export function getAgentDomainClass(agentName: string): string {
  const domain = agentName.split('.')[0].toLowerCase()
  return AGENT_DOMAIN_COLORS[domain] ?? 'bg-muted text-muted-foreground ring-1 ring-inset ring-border/50'
}

export function getAgentBadgeClass(status: PlanTaskStatus, agentName: string): string {
  switch (status) {
    case 'running':
      return 'bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/30'
    case 'completed':
      return 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/30'
    case 'failed':
      return 'bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30'
    default:
      // For proposed/approved/queued/cancelled/skipped: use domain color
      return getAgentDomainClass(agentName)
  }
}

export function edgeColor(state: Edge['state']): string {
  switch (state) {
    case 'amber':
      return 'rgb(251 191 36 / 0.75)' // amber-400
    case 'green':
      return 'rgb(52 211 153 / 0.35)' // emerald-400, faded
    case 'failed':
      return 'rgb(239 68 68 / 0.45)' // red-500, muted
    default:
      return 'rgb(148 163 184 / 0.35)' // slate-400, muted
  }
}

export function bezierPath(from: Rect, to: Rect): string {
  const x1 = from.right
  const y1 = from.top + from.height / 2
  const x2 = to.left
  const y2 = to.top + to.height / 2
  // Control-point offset: minimum 60px, scale with horizontal distance so
  // curves don't look collapsed when cards are right next to each other.
  const dx = Math.max(60, Math.abs(x2 - x1) * 0.35)
  return `M ${x1},${y1} C ${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
}

export function computeEdges(joined: JoinedTask[]): Edge[] {
  const byId = new Map(joined.map((j) => [j.body.task_id, j]))
  const edges: Edge[] = []
  for (const j of joined) {
    for (const depId of j.body.dependencies) {
      const blocker = byId.get(depId)
      if (!blocker) continue
      const bs = blocker.effectiveStatus
      let state: Edge['state'] = 'grey'
      if (bs === 'running') state = 'amber'
      else if (bs === 'completed' || bs === 'skipped') state = 'green'
      else if (bs === 'failed' || bs === 'cancelled') state = 'failed'
      edges.push({ from: depId, to: j.body.task_id, state })
    }
  }
  return edges
}
