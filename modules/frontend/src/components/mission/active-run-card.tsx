import { useState } from 'react'
import { Activity, CheckCircle, XCircle, Circle, Pause } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/lib/api'
import { useRunStream } from '@/hooks/use-sse'
import { useDrawerStore } from '@/stores/drawer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { ExecutionRecord } from '@/types'

interface ActiveRunCardProps {
  execution: ExecutionRecord
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  running: <Activity className="h-3.5 w-3.5 text-amber-500 animate-pulse" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
  pending: <Circle className="h-3.5 w-3.5 text-muted-foreground" />,
  gate: <Pause className="h-3.5 w-3.5 text-amber-500" />,
}

export function ActiveRunCard({ execution }: ActiveRunCardProps) {
  const { events, connected } = useRunStream(execution.session_id)
  const { open: openDrawer } = useDrawerStore()
  const [gateState, setGateState] = useState<{
    executionId: string
    visible: boolean
  } | null>(null)

  // Detect gate approval requests from SSE events
  const latestGate = [...events].reverse().find(
    (e: { event_type: string }) => e.event_type === 'agent.approval.requested',
  )

  const showGate = latestGate && !gateState?.visible

  return (
    <Card className="border-amber-500/30 bg-amber-500/5">
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
              onClick={() =>
                openDrawer('run-events', {
                  sessionId: execution.session_id,
                })
              }
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
          <GateApproval
            executionId={execution.id}
            gateData={latestGate.data}
            onResolved={() => setGateState({ executionId: execution.id, visible: true })}
          />
        )}
      </CardContent>
    </Card>
  )
}

function GateApproval({
  executionId,
  gateData,
  onResolved,
}: {
  executionId: string
  gateData: Record<string, unknown>
  onResolved: () => void
}) {
  const [feedback, setFeedback] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (decision: string) => {
    setSubmitting(true)
    try {
      await api.post(
        `/executions/${executionId}/approve?decision=${decision}&responder_id=user:web${feedback ? `&reason=${encodeURIComponent(feedback)}` : ''}`,
      )
      toast.success(`Gate ${decision}`)
      onResolved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Pause className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium">Gate Approval Required</span>
      </div>

      {gateData.message != null ? (
        <p className="text-xs text-muted-foreground">
          {String(gateData.message)}
        </p>
      ) : null}

      {showFeedback && (
        <Textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={2}
          placeholder="Feedback for retry..."
          className="text-xs"
        />
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => submit('approve')}
          disabled={submitting}
        >
          Approve
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            if (!showFeedback) {
              setShowFeedback(true)
            } else {
              submit('retry')
            }
          }}
          disabled={submitting}
        >
          {showFeedback ? 'Retry' : 'Retry with Feedback'}
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => submit('reject')}
          disabled={submitting}
        >
          Reject
        </Button>
      </div>
    </div>
  )
}
