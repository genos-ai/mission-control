/**
 * Hook that consumes mission SSE events and tracks per-node execution status
 * for the workflow editor overlay.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useMissionStreamContext } from '@/context/mission-stream'

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

export function useWorkflowRunStatus(): WorkflowRunOverlay {
  const stream = useMissionStreamContext()
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatus>>({})
  const [nodeMetrics, setNodeMetrics] = useState<Record<string, NodeMetrics>>({})
  const [pendingHumanInputs, setPendingHumanInputs] = useState<Record<string, PendingHumanInput>>({})
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [progress, setProgress] = useState<[number, number]>([0, 0])
  const processedRef = useRef(0)

  useEffect(() => {
    if (!stream) return
    const events = stream.events
    if (events.length <= processedRef.current) return

    const newEvents = events.slice(processedRef.current)
    processedRef.current = events.length

    const captureMetrics = (stepId: string, d: Record<string, unknown>) => {
      const m: NodeMetrics = {}
      if (typeof d.cost_usd === 'number') m.cost_usd = d.cost_usd
      if (typeof d.duration_seconds === 'number') m.duration_seconds = d.duration_seconds
      if (typeof d.child_cost_usd === 'number') m.cost_usd = d.child_cost_usd
      if (m.cost_usd !== undefined || m.duration_seconds !== undefined) {
        setNodeMetrics((prev) => ({ ...prev, [stepId]: m }))
      }
    }

    for (const ev of newEvents) {
      if (!WORKFLOW_EVENT_TYPES.has(ev.event_type)) continue
      // SSE wire format: event_type at top level, event-specific fields in ev.data
      const d = ev.data as Record<string, unknown>

      switch (ev.event_type) {
        case 'workflow.run.started':
          setActiveRunId(String(d.workflow_run_id ?? ''))
          setProgress([0, Number(d.step_count ?? 0)])
          setNodeStatuses({})
          setNodeMetrics({})
          setPendingHumanInputs({})
          break

        case 'workflow.execution.started':
          setNodeStatuses((prev) => ({ ...prev, [String(d.step_id)]: 'running' }))
          break

        case 'workflow.execution.completed':
          setNodeStatuses((prev) => ({
            ...prev,
            [String(d.step_id)]: d.success ? 'completed' : 'failed',
          }))
          captureMetrics(String(d.step_id), d)
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.step.skipped':
          setNodeStatuses((prev) => ({ ...prev, [String(d.step_id)]: 'skipped' }))
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.condition.evaluated':
        case 'workflow.decision.resolved':
          setNodeStatuses((prev) => ({ ...prev, [String(d.step_id)]: 'completed' }))
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.notification.sent':
        case 'workflow.tool_call.completed':
        case 'workflow.llm_call.completed':
          setNodeStatuses((prev) => ({
            ...prev,
            [String(d.step_id)]: d.success ? 'completed' : 'failed',
          }))
          captureMetrics(String(d.step_id), d)
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.branch.passed':
        case 'workflow.merge.completed':
          setNodeStatuses((prev) => ({ ...prev, [String(d.step_id)]: 'completed' }))
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.sub_workflow.completed':
          setNodeStatuses((prev) => ({
            ...prev,
            [String(d.step_id)]: d.success ? 'completed' : 'failed',
          }))
          captureMetrics(String(d.step_id), d)
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break

        case 'workflow.human_input.requested': {
          const stepId = String(d.step_id ?? '')
          setNodeStatuses((prev) => ({ ...prev, [stepId]: 'awaiting_input' }))
          setPendingHumanInputs((prev) => ({
            ...prev,
            [stepId]: {
              requestId: String(d.request_id ?? ''),
              stepId,
              promptMessage: String(d.prompt_message ?? ''),
              choices: Array.isArray(d.choices) ? (d.choices as unknown[]).map(String) : [],
              timeoutAt: d.timeout_at ? String(d.timeout_at) : null,
            },
          }))
          break
        }

        case 'workflow.human_input.responded': {
          const stepId = String(d.step_id ?? '')
          setNodeStatuses((prev) => ({ ...prev, [stepId]: 'completed' }))
          setPendingHumanInputs((prev) => {
            const next = { ...prev }
            delete next[stepId]
            return next
          })
          setProgress((prev) => [prev[0] + 1, prev[1]])
          break
        }

        case 'workflow.run.completed':
        case 'workflow.run.failed':
          setActiveRunId(null)
          break
      }
    }
  }, [stream?.events.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const reset = useCallback(() => {
    setNodeStatuses({})
    setNodeMetrics({})
    setPendingHumanInputs({})
    setActiveRunId(null)
    setProgress([0, 0])
    processedRef.current = stream?.events.length ?? 0
  }, [stream?.events.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const isActive = activeRunId !== null

  return { nodeStatuses, nodeMetrics, pendingHumanInputs, isActive, activeRunId, progress, reset }
}
