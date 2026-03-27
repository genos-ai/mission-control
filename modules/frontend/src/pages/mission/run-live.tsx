import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Radio } from 'lucide-react'
import { useExecution } from '@/hooks/use-executions'
import { useRunStream } from '@/hooks/use-sse'
import { useLiveRunStore } from '@/stores/live-run'
import { ROUTES } from '@/lib/constants'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { LiveActivityPanel } from '@/components/live/live-activity-panel'
import { LiveResultsPanel } from '@/components/live/live-results-panel'
import { LiveFooter } from '@/components/live/live-footer'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'timed_out'])

export default function RunLivePage() {
  const { id: missionId, runId } = useParams<{ id: string; runId: string }>()
  const navigate = useNavigate()

  // Fetch execution detail — poll while running
  const { data: execution, isLoading } = useExecution(runId)
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
    }
  }, [execution, storeExecId, init])

  // Forward SSE events to store
  const lastProcessed = useLiveRunStore((s) => s.eventLog.length)
  useEffect(() => {
    if (events.length > 0) {
      // Process only new events since last forward
      const newEvents = events.slice(lastProcessed)
      newEvents.forEach(handleEvent)
    }
  }, [events.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Detect terminal status from polling
  useEffect(() => {
    if (isTerminal && execution) {
      const s = execution.status === 'completed' ? 'success' : 'failed'
      setDone(s)
    }
  }, [isTerminal, execution, setDone])

  // Cleanup on unmount
  useEffect(() => reset, [reset])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
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
          {connected && (
            <Badge variant="success" className="text-[10px]">
              <Radio className="mr-1 h-3 w-3 animate-pulse" />
              Live
            </Badge>
          )}
          {isTerminal && (
            <Badge
              variant={
                execution.status === 'completed' ? 'success' : 'destructive'
              }
            >
              {execution.status}
            </Badge>
          )}
        </div>
      </div>

      {/* Main content: two-panel layout */}
      <div className="flex flex-1 overflow-hidden">
        <div className="w-[70%]">
          <LiveActivityPanel />
        </div>
        <div className="w-[30%]">
          <LiveResultsPanel />
        </div>
      </div>

      {/* Footer */}
      <LiveFooter />
    </div>
  )
}
