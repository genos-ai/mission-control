import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Radio, StopCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useExecution,
  useCancelExecution,
  useStartExecution,
} from '@/hooks/use-executions'
import { useRunStream } from '@/hooks/use-sse'
import { useLiveRunStore } from '@/stores/live-run'
import { useResearchStore } from '@/stores/research'
import { ROUTES } from '@/lib/constants'
import { StatusPill } from '@/components/ui/status-pill'
import { runTone, styleFor } from '@/lib/status-tone'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { LiveActivityPanel } from '@/components/live/live-activity-panel'
import { LiveResultsPanel } from '@/components/live/live-results-panel'
import { LiveFooter } from '@/components/live/live-footer'
import { ResearchLiveView } from '@/components/research/research-live-view'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'timed_out'])
const PENDING_STATUSES = new Set(['pending', 'created'])

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
  const { data: execution, isLoading } = useExecution(runId)
  const isTerminal = execution
    ? TERMINAL_STATUSES.has(execution.status)
    : false
  const isPending = execution
    ? PENDING_STATUSES.has(execution.status)
    : false

  // SSE stream
  const sessionId = execution?.session_id ?? null
  const { events, connected } = useRunStream(isTerminal ? null : sessionId)

  // Start execution once SSE is connected (only for pending runs)
  const startExecution = useStartExecution()
  const startedRef = useRef(false)
  useEffect(() => {
    if (connected && isPending && execution && !startedRef.current) {
      startedRef.current = true
      startExecution.mutate(execution.id, {
        onError: (err) => toast.error(err.message),
      })
    }
  }, [connected, isPending, execution]) // eslint-disable-line react-hooks/exhaustive-deps

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

  if (!execution || !missionId) return null

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => navigate(ROUTES.MISSION_RUNS(missionId))}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <span className="font-mono text-sm text-muted-foreground">
            {execution.id.slice(0, 8)}
          </span>
          {execution.objective_statement && (
            <span className="text-sm truncate max-w-md">
              {execution.objective_statement}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!isTerminal && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCancel}
              disabled={cancelMutation.isPending}
              className="text-destructive hover:text-destructive"
            >
              <StopCircle className="mr-1.5 h-3.5 w-3.5" />
              {cancelMutation.isPending ? 'Cancelling...' : 'Cancel'}
            </Button>
          )}
          {connected && (
            <StatusPill tone="success" pulse>
              <Radio className="mr-1 h-3 w-3" />
              Live
            </StatusPill>
          )}
          {isTerminal && (
            <StatusPill tone={styleFor(runTone, execution.status, 'run').tone}>
              {execution.status}
            </StatusPill>
          )}
        </div>
      </div>

      {/* Main content: research three-panel view or standard two-panel */}
      {researchActive || researchComplete ? (
        <ResearchLiveView />
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {activityOpen ? (
            <LiveActivityPanel onCollapse={() => setActivityOpen(false)} />
          ) : (
            <button
              onClick={() => setActivityOpen(true)}
              className="flex w-5 shrink-0 items-center justify-center border-r text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
              title="Open activity panel"
            >
              <ChevronRight className="h-3 w-3" />
            </button>
          )}
          {resultsOpen ? (
            <LiveResultsPanel onCollapse={() => setResultsOpen(false)} />
          ) : (
            <button
              onClick={() => setResultsOpen(true)}
              className="flex w-5 shrink-0 items-center justify-center border-l text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
              title="Open results panel"
            >
              <ChevronLeft className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {/* Footer */}
      <LiveFooter />
    </div>
  )
}
