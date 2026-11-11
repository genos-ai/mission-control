import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useExecution, useCancelExecution } from '@/hooks/use-executions'
import { useRunStream } from '@/hooks/use-sse'
import { useLiveRunStore } from '@/stores/live-run'
import { useResearchStore } from '@/stores/research'
import { EmptyState } from '@/components/ui/empty-state'
import { Spinner } from '@/components/ui/spinner'
import { ROUTES } from '@/lib/constants'
import { LiveActivityPanel } from '@/components/live/live-activity-panel'
import { LiveResultsPanel } from '@/components/live/live-results-panel'
import { LiveSummary } from '@/components/live/live-summary'
import { ResearchLiveView } from '@/components/research/research-live-view'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'timed_out'])

// TODO: Run detail page shows very little when navigating into an already-running
//       or completed run. The UI is entirely SSE-driven — if you missed earlier
//       events (late join, page refresh, reconnect), the store starts empty and
//       panels show "Waiting for events..." / "No results yet...".
//       Fix: hydrate the live-run store from the polled execution record
//       (task_executions, decisions, cost) so the page is useful even without SSE
//       history. Show execution metadata (objective, agent roster, plan steps,
//       created_at, duration), backfill taskResults from task_executions, and
//       display the final output for completed runs.
export default function RunLivePage() {
  const { id: missionId, runId } = useParams<{ id: string; runId: string }>()
  const navigate = useNavigate()

  // Fetch execution detail — poll while running
  const { data: execution, isLoading, isError, error } = useExecution(runId)
  const isTerminal = execution
    ? TERMINAL_STATUSES.has(execution.status)
    : false

  // SSE stream
  const sessionId = execution?.session_id ?? null
  const { events, connected } = useRunStream(isTerminal ? null : sessionId)

  // Store init + reset
  const init = useLiveRunStore((s) => s.init)
  const handleEvent = useLiveRunStore((s) => s.handleEvent)
  const setDone = useLiveRunStore((s) => s.setDone)
  const reset = useLiveRunStore((s) => s.reset)
  const storeExecId = useLiveRunStore((s) => s.executionId)

  // Initialize store when execution loads
  useEffect(() => {
    if (execution && storeExecId !== execution.id) {
      init(execution.id, execution.session_id)
      processedCount.current = 0
    }
  }, [execution, storeExecId, init])

  // Research store reactive state
  const researchActive = useResearchStore((s) => s.isActive)
  const researchComplete = useResearchStore((s) => s.reportComplete)

  // Forward SSE events to both live-run store and research store
  const handleResearchEvent = useResearchStore((s) => s.handleEvent)
  const processedCount = useRef(0)
  useEffect(() => {
    if (events.length > processedCount.current) {
      const newEvents = events.slice(processedCount.current)
      processedCount.current = events.length
      newEvents.forEach((event) => {
        handleEvent(event)
        handleResearchEvent(event)
      })
    }
  }, [events.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Detect terminal status from polling
  useEffect(() => {
    if (isTerminal && execution) {
      const s = execution.status === 'completed' ? 'success' : 'failed'
      setDone(s)
    }
  }, [isTerminal, execution, setDone])

  const cancelMutation = useCancelExecution()
  const [activityOpen, setActivityOpen] = useState(true)
  const [resultsOpen, setResultsOpen] = useState(true)

  // Cleanup on unmount
  const resetResearch = useResearchStore((s) => s.reset)
  useEffect(() => () => { reset(); resetResearch() }, [reset, resetResearch])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  const handleCancel = () => {
    cancelMutation.mutate(execution!.id, {
      onSuccess: () => toast.success('Run cancelled'),
      onError: (err) => toast.error(err.message),
    })
  }

  if (isError || !execution || !missionId) {
    return (
      <EmptyState
        title="Run not found"
        description={error?.message ?? 'This run does not exist or you cannot see it.'}
        action={missionId ? { label: 'Back to runs', onClick: () => navigate(ROUTES.MISSION_RUNS(missionId)) } : undefined}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-gutter px-2 pb-2">
      <LiveSummary
        execution={execution}
        inFlight={!isTerminal}
        connected={connected}
        activityOpen={activityOpen}
        resultsOpen={resultsOpen}
        onToggleActivity={() => setActivityOpen((v) => !v)}
        onToggleResults={() => setResultsOpen((v) => !v)}
        onCancel={handleCancel}
        cancelling={cancelMutation.isPending}
      />

      {/* Research runs get their own three-panel view; everything else gets activity + results. */}
      {researchActive || researchComplete ? (
        <ResearchLiveView />
      ) : (
        <div className="flex min-h-0 flex-1 gap-gutter">
          {activityOpen && <LiveActivityPanel recorded={execution.task_executions} />}
          {resultsOpen && <LiveResultsPanel outcome={execution.execution_outcome_json} />}
        </div>
      )}
    </div>
  )
}
