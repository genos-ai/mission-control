/**
 * PlanBoard — shared types, constants, and pure utility functions.
 */

import type { PlanTaskStatus, PlanTask } from '@/hooks/use-mission-plan'

// ── Types ─────────────────────────────────────────────────────────────────

export type ColumnId = 'proposed' | 'approved' | 'running' | 'done'

export interface ColumnDef {
  id: ColumnId
  label: string
  statuses: PlanTaskStatus[]
}

/** A unified task with live-overlay status applied. */
export interface JoinedTask {
  task: PlanTask
  /** Overlay status wins over durable status when present. */
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

// ── Constants ─────────────────────────────────────────────────────────────

export const COLUMN_DEFS: ColumnDef[] = [
  { id: 'proposed', label: 'Proposed', statuses: ['proposed'] },
  { id: 'approved', label: 'Approved', statuses: ['approved', 'queued'] },
  { id: 'running', label: 'Running', statuses: ['running'] },
  { id: 'done', label: 'Done', statuses: ['completed', 'failed', 'skipped', 'cancelled'] },
]

export const PRE_RUN_GATE_KEY = (missionId: string) => `prerun_gate_dismissed:${missionId}`

// ── Pure utility functions ────────────────────────────────────────────────

export function columnFor(status: PlanTaskStatus): ColumnId {
  for (const def of COLUMN_DEFS) {
    if (def.statuses.includes(status)) return def.id
  }
  return 'proposed'
}

/** Dependency-curve colour for an edge state, from the theme tokens. */
export function edgeColor(state: Edge['state']): string {
  switch (state) {
    case 'amber':
      return 'hsl(var(--warning) / 0.75)'
    case 'green':
      return 'hsl(var(--success) / 0.35)'
    case 'failed':
      return 'hsl(var(--danger) / 0.45)'
    default:
      return 'hsl(var(--subtle) / 0.35)'
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
  const byId = new Map(joined.map((j) => [j.task.id, j]))
  const edges: Edge[] = []
  for (const j of joined) {
    for (const depId of j.task.dependencies) {
      const blocker = byId.get(depId)
      if (!blocker) continue
      const bs = blocker.effectiveStatus
      let state: Edge['state'] = 'grey'
      if (bs === 'running') state = 'amber'
      else if (bs === 'completed' || bs === 'skipped') state = 'green'
      else if (bs === 'failed' || bs === 'cancelled') state = 'failed'
      edges.push({ from: depId, to: j.task.id, state })
    }
  }
  return edges
}
