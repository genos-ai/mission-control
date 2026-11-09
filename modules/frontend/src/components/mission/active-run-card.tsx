import { useState } from 'react'
import { ChevronRight, Wrench } from 'lucide-react'
import { useRunStream } from '@/hooks/use-sse'
import { useNow } from '@/hooks/use-now'
import { useDrawerStore } from '@/stores/drawer'
import { useWorkspaceStore } from '@/stores/workspace'
import { Panel } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
import { Button } from '@/components/ui/button'
import { GateApproval } from '@/components/mission/gate-approval'
import { agentShortName, fmtCost } from '@/lib/format'
import { formatElapsed, parseUtc } from '@/lib/format-date'
import type { ExecutionRecord } from '@/types'

interface ActiveRunCardProps {
  execution: ExecutionRecord
  onClick?: () => void
}

export function ActiveRunCard({ execution, onClick }: ActiveRunCardProps) {
  const { events, connected } = useRunStream(execution.session_id)
  const { open: openDrawer } = useDrawerStore()
  const [resolvedGateId, setResolvedGateId] = useState<string | null>(null)
  const agentStatuses = useWorkspaceStore((s) => s.agentStatuses)
  const now = useNow(true)

  // The latest manual gate opened on this run with no later decision for the same request.
  let latestGateIndex = -1
  events.forEach((e, i) => {
    if (e.event_type === 'gate.request.opened') latestGateIndex = i
  })
  const latestGate = latestGateIndex >= 0 ? events[latestGateIndex] : undefined
  const latestGateRequestId = String(latestGate?.data.request_id ?? '')
  const gateDecided = events
    .slice(latestGateIndex + 1)
    .some(
      (e) =>
        e.event_type === 'gate.request.decided' &&
        String(e.data.request_id ?? '') === latestGateRequestId,
    )

  const showGate = latestGate && !gateDecided && resolvedGateId !== latestGateRequestId
  const working = Object.values(agentStatuses).filter(
    (a) => a.status === 'running' || a.status === 'thinking',
  )
  const lastEvent = events[events.length - 1]

  return (
    <Panel
      className="flex cursor-pointer flex-col gap-3.5 border-warning/25 bg-warning/[0.03] p-4"
      onClick={onClick}
    >
      <div className="flex items-center gap-2.5">
        <span className="h-2 w-2 shrink-0 rounded-full bg-warning animate-pulse-dot motion-reduce:animate-none" />
        <span className="text-md font-medium">Run in progress</span>
        {connected && (
          <StatusPill tone="success" pulse>
            Live
          </StatusPill>
        )}
        <span className="font-mono text-xs text-text-3">{execution.id.slice(0, 8)}</span>
        <div className="ml-auto flex items-center gap-3">
          {execution.started_at && (
            <span className="font-mono text-xs text-muted-foreground">
              {formatElapsed(Math.max(0, now - parseUtc(execution.started_at).getTime()))}
            </span>
          )}
          <span className="font-mono text-xs text-muted-foreground">{fmtCost(execution.total_cost_usd)}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              openDrawer('run-events', {
                sessionId: execution.session_id,
              })
            }}
          >
            View Events
          </Button>
          <ChevronRight className="h-4 w-4 text-subtle" />
        </div>
      </div>

      <div
        role="progressbar"
        aria-label="Run in progress"
        className="h-[3px] overflow-hidden rounded-full bg-warning/10"
      >
        <div className="h-full w-2/5 animate-shimmer-x bg-warning motion-reduce:animate-none" />
      </div>

      {(working.length > 0 || lastEvent) && (
        <div className="flex flex-col gap-1">
          {working.map((a) => (
            <div key={a.agentId} className="flex items-center gap-2 text-sm">
              <Wrench className="h-3.5 w-3.5 shrink-0 text-warning" />
              <span>{agentShortName(a.agentId)}</span>
              {a.currentTool && <span className="font-mono text-warning">{a.currentTool}</span>}
            </div>
          ))}
          {lastEvent && (
            <span className="truncate text-xs text-subtle">
              Last event: {lastEvent.event_type.replace(/\./g, ' ')}
            </span>
          )}
        </div>
      )}

      {/* Gate approval UI */}
      {showGate && (
        <div onClick={(e) => e.stopPropagation()}>
          <GateApproval
            missionId={String(latestGate.data.mission_id ?? '')}
            requestId={latestGateRequestId}
            onResolved={() => setResolvedGateId(latestGateRequestId)}
          />
        </div>
      )}
    </Panel>
  )
}
