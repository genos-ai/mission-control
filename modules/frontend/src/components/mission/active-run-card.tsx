import { useState } from 'react'
import { Activity, CheckCircle, XCircle, Circle, Pause } from 'lucide-react'
import { useRunStream } from '@/hooks/use-sse'
import { useDrawerStore } from '@/stores/drawer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { GateApproval } from '@/components/mission/gate-approval'
import type { ExecutionRecord } from '@/types'

interface ActiveRunCardProps {
  execution: ExecutionRecord
  onClick?: () => void
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  running: <Activity className="h-3.5 w-3.5 text-amber-500 animate-pulse" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
  pending: <Circle className="h-3.5 w-3.5 text-muted-foreground" />,
  gate: <Pause className="h-3.5 w-3.5 text-amber-500" />,
}

export function ActiveRunCard({ execution, onClick }: ActiveRunCardProps) {
  const { events, connected } = useRunStream(execution.session_id)
  const { open: openDrawer } = useDrawerStore()
  const [gateResolved, setGateResolved] = useState(false)

  // Detect gate approval requests from SSE events
  const latestGate = [...events].reverse().find(
    (e: { event_type: string }) => e.event_type === 'agent.approval.requested',
  )

  const showGate = latestGate && !gateResolved

  return (
    <Card
      className="border-amber-500/30 bg-amber-500/5 cursor-pointer"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-amber-500 animate-pulse" />
            <CardTitle className="text-base">Active Run</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {connected && (
              <Badge variant="success" className="text-[10px]">
                Live
              </Badge>
            )}
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
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Run info */}
        <div className="flex items-center justify-between text-sm">
          <span className="font-mono text-xs text-muted-foreground">
            {execution.id.slice(0, 8)}
          </span>
          <span className="text-xs text-muted-foreground">
            ${execution.total_cost_usd.toFixed(4)}
          </span>
        </div>

        {/* Recent agent events */}
        <div className="space-y-1">
          {events.slice(-5).map((ev, i) => (
            <div
              key={i}
              className="flex items-center gap-2 text-xs text-muted-foreground"
            >
              {STATUS_ICONS[String(ev.data.status ?? '')] ??
                STATUS_ICONS.running}
              <span className="truncate">
                {ev.event_type.replace(/\./g, ' ')}
              </span>
            </div>
          ))}
        </div>

        {/* Gate approval UI */}
        {showGate && (
          <div onClick={(e) => e.stopPropagation()}>
            <GateApproval
              executionId={execution.id}
              gateMessage={String(latestGate.data.message ?? '')}
              onResolved={() => setGateResolved(true)}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
