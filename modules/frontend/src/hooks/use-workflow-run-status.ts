/**
 * Hook that derives per-node workflow execution state from the mission's
 * event log (historical narrative + live SSE). State is computed by a
 * pure reducer over the event list, so opening the editor mid-run
 * reconstructs the overlay correctly — no replay logic, no live-only blind
 * spot.
 */

import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'

export type NodeStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'awaiting_input'

export interface NodeMetrics {
  cost_usd?: number
  duration_seconds?: number
}

/** A pending human input request from a human_input or decision (human resolver) node. */
export interface PendingHumanInput {
  requestId: string
  stepId: string
  promptMessage: string
  choices: string[]        // empty = free-text response
  timeoutAt: string | null // ISO timestamp, or null if no timeout
}

export interface WorkflowRunOverlay {
  /** Per-node status keyed by step_id */
  nodeStatuses: Record<string, NodeStatus>
  /** Per-node cost/duration keyed by step_id */
  nodeMetrics: Record<string, NodeMetrics>
  /** Pending human input requests keyed by step_id */
  pendingHumanInputs: Record<string, PendingHumanInput>
  /** Is a workflow currently running? */
  isActive: boolean
  /** The active workflow_run_id (if any) */
  activeRunId: string | null
  /** Progress: [completed, total] */
  progress: [number, number]
  /** Reset all status (call before starting a new run) */
  reset: () => void
}

const WORKFLOW_EVENT_TYPES = new Set([
  'workflow.run.started',
  'workflow.execution.started',
  'workflow.execution.completed',
  'workflow.step.skipped',
  'workflow.condition.evaluated',
  'workflow.notification.sent',
  'workflow.tool_call.completed',
  'workflow.llm_call.completed',
  'workflow.branch.passed',
  'workflow.merge.completed',
  'workflow.sub_workflow.completed',
  'workflow.decision.resolved',
  'workflow.human_input.requested',
  'workflow.human_input.responded',
  'workflow.run.completed',
  'workflow.run.failed',
])

// ── Pure reducer ──────────────────────────────────────────────────────────

interface ReducerState {
  nodeStatuses: Record<string, NodeStatus>
  nodeMetrics: Record<string, NodeMetrics>
  pendingHumanInputs: Record<string, PendingHumanInput>
  activeRunId: string | null
  progress: [number, number]
}

const EMPTY_STATE: ReducerState = {
  nodeStatuses: {},
  nodeMetrics: {},
  pendingHumanInputs: {},
  activeRunId: null,
  progress: [0, 0],
}

function withStatus(state: ReducerState, stepId: string, status: NodeStatus): ReducerState {
  return { ...state, nodeStatuses: { ...state.nodeStatuses, [stepId]: status } }
}

function withMetrics(
  state: ReducerState,
  stepId: string,
  d: Record<string, unknown>,
): ReducerState {
  const m: NodeMetrics = {}
  if (typeof d.cost_usd === 'number') m.cost_usd = d.cost_usd
  if (typeof d.duration_seconds === 'number') m.duration_seconds = d.duration_seconds
  if (typeof d.child_cost_usd === 'number') m.cost_usd = d.child_cost_usd
  if (m.cost_usd === undefined && m.duration_seconds === undefined) return state
  return { ...state, nodeMetrics: { ...state.nodeMetrics, [stepId]: m } }
}

function incProgress(state: ReducerState): ReducerState {
  return { ...state, progress: [state.progress[0] + 1, state.progress[1]] }
}

function applyEvent(state: ReducerState, ev: ConsoleEvent): ReducerState {
  if (!WORKFLOW_EVENT_TYPES.has(ev.event_type)) return state
  const d = ev.data as Record<string, unknown>
  const stepId = String(d.step_id ?? '')

  switch (ev.event_type) {
    case 'workflow.run.started':
      return {
        ...EMPTY_STATE,
        activeRunId: String(d.workflow_run_id ?? ''),
        progress: [0, Number(d.step_count ?? 0)],
      }

    case 'workflow.execution.started':
      return withStatus(state, stepId, 'running')

    case 'workflow.execution.completed':
    case 'workflow.notification.sent':
    case 'workflow.tool_call.completed':
    case 'workflow.llm_call.completed':
    case 'workflow.sub_workflow.completed': {
      const next = withStatus(state, stepId, d.success ? 'completed' : 'failed')
      return incProgress(withMetrics(next, stepId, d))
    }

    case 'workflow.step.skipped':
      return incProgress(withStatus(state, stepId, 'skipped'))

    case 'workflow.condition.evaluated':
    case 'workflow.decision.resolved':
    case 'workflow.branch.passed':
    case 'workflow.merge.completed':
      return incProgress(withStatus(state, stepId, 'completed'))

    case 'workflow.human_input.requested': {
      const next = withStatus(state, stepId, 'awaiting_input')
      return {
        ...next,
        pendingHumanInputs: {
          ...next.pendingHumanInputs,
          [stepId]: {
            requestId: String(d.request_id ?? ''),
            stepId,
            promptMessage: String(d.prompt_message ?? ''),
            choices: Array.isArray(d.choices) ? (d.choices as unknown[]).map(String) : [],
            timeoutAt: d.timeout_at ? String(d.timeout_at) : null,
          },
        },
      }
    }

    case 'workflow.human_input.responded': {
      const { [stepId]: _omit, ...rest } = state.pendingHumanInputs
      const next = withStatus(state, stepId, 'completed')
      return incProgress({ ...next, pendingHumanInputs: rest })
    }

    case 'workflow.run.completed':
    case 'workflow.run.failed':
      return { ...state, activeRunId: null }

    default:
      return state
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useWorkflowRunStatus(): WorkflowRunOverlay {
  const { id: missionId } = useParams<{ id: string }>()
  // Live events come from the console store, which is fed by the mission
  // SSE stream in MissionLayout and normalizes events to ConsoleEvent shape.
  const liveEvents = useConsoleStore((s) => s.events)
  // Reset cursor — events with timestamp older than this are ignored. Set
  // by reset() before starting a new run so the previous run's overlay
  // clears immediately instead of waiting for the next workflow.run.started.
  const [resetAt, setResetAt] = useState<number>(0)

  // Historical narrative events for this mission. Shares the same query
  // key as the chat narrative consumer — only one request per mission.
  const { data: narrativeData } = useQuery({
    queryKey: ['narrative', missionId],
    queryFn: () =>
      api.get<{ events: ConsoleEvent[]; count: number }>(
        `/missions/${missionId}/narrative`,
      ),
    enabled: !!missionId,
    staleTime: 30_000,
  })

  // Combined, deduplicated, chronologically sorted workflow event list.
  const events = useMemo(() => {
    const all = [
      ...(narrativeData?.events ?? []),
      ...liveEvents,
    ]
    const seen = new Set<string>()
    const out: ConsoleEvent[] = []
    for (const ev of all) {
      if (!WORKFLOW_EVENT_TYPES.has(ev.event_type)) continue
      if (seen.has(ev.event_id)) continue
      const tsMs = new Date(ev.timestamp).getTime()
      if (resetAt > 0 && tsMs < resetAt) continue
      seen.add(ev.event_id)
      out.push(ev)
    }
    out.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    return out
  }, [narrativeData, liveEvents, resetAt])

  // Replay through the pure reducer — same code path for historical and live.
  const state = useMemo(() => events.reduce(applyEvent, EMPTY_STATE), [events])

  const reset = useCallback(() => {
    // Drop everything older than now; the next workflow.run.started event
    // will land after this cursor and rebuild the overlay from scratch.
    setResetAt(Date.now())
  }, [])

  return {
    nodeStatuses: state.nodeStatuses,
    nodeMetrics: state.nodeMetrics,
    pendingHumanInputs: state.pendingHumanInputs,
    activeRunId: state.activeRunId,
    progress: state.progress,
    isActive: state.activeRunId !== null,
    reset,
  }
}
