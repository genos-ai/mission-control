import { useState, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, RefreshCw, GitBranch } from 'lucide-react'
import { useConsoleStore } from '@/stores/console'
import { useSessions, useCreateSession } from '@/hooks/use-sessions'
import { workflowKeys } from '@/hooks/use-workflows'
import { Conversation } from '@/pages/mission/tabs/chat-conversation'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'

const ARCHITECT_AGENT = 'mission.workflow.architect'

export function ArchitectChat({
  missionId,
  workflowId,
  workflowName,
  onClose,
}: {
  missionId: string
  workflowId?: string
  workflowName?: string
  onClose?: () => void
}) {
  const qc = useQueryClient()
  const { data: sessions, isLoading: sessionsLoading } = useSessions({
    mission_id: missionId,
    status: 'active',
  })
  const createSession = useCreateSession()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [graphUpdated, setGraphUpdated] = useState(false)
  const initRef = useRef(false)

  // Find an existing architect session for this workflow, or create one.
  useEffect(() => {
    if (sessionsLoading || initRef.current) return
    initRef.current = true

    const existing = sessions?.find(
      (s) =>
        s.agent_id === ARCHITECT_AGENT &&
        (!workflowId || s.goal?.includes(workflowId)),
    )

    if (existing) {
      setSessionId(existing.id)
      return
    }

    createSession
      .mutateAsync({
        goal: workflowId
          ? `Workflow ${workflowId}${workflowName ? ': ' + workflowName : ''}`
          : 'Workflow Design',
        mission_id: missionId,
        agent_id: ARCHITECT_AGENT,
      })
      .then((s) => setSessionId(s.id))
      .catch(() => {})
  }, [sessions, sessionsLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  // Show reload banner when the architect saves the workflow via its tools.
  const events = useConsoleStore((s) => s.events)
  useEffect(() => {
    const updated = events.some(
      (e) =>
        e.event_type === 'workflow.graph.updated' &&
        (!workflowId || String(e.data.workflow_id ?? '') === workflowId),
    )
    if (updated) setGraphUpdated(true)
  }, [events, workflowId])

  const handleReload = () => {
    qc.invalidateQueries({ queryKey: workflowKeys.missionWorkflows(missionId) })
    setGraphUpdated(false)
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5">
          <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-medium">Architect</span>
          {workflowName && (
            <span className="max-w-[120px] truncate text-[10px] text-muted-foreground/50">
              {workflowName}
            </span>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Graph updated banner */}
      {graphUpdated && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          <span>Workflow updated by architect</span>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 gap-1 text-xs text-emerald-300 hover:text-emerald-200"
            onClick={handleReload}
          >
            <RefreshCw className="h-3 w-3" />
            Reload
          </Button>
        </div>
      )}

      {/* Conversation */}
      {sessionsLoading || createSession.isPending || !sessionId ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <Conversation
            sessionId={sessionId}
            missionId={missionId}
            targetAgent={ARCHITECT_AGENT}
          />
        </div>
      )}
    </div>
  )
}
