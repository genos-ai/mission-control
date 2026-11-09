import { useState } from 'react'
import { Pause } from 'lucide-react'
import toast from 'react-hot-toast'
import { useDecideGate, useGateRequest } from '@/hooks/use-gates'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/cn'
import { TONE_BOX } from '@/lib/tone-class'

interface GateApprovalProps {
  missionId: string
  requestId: string
  gateMessage?: string
  onResolved: () => void
}

/** Decides a pending manual gate: one button per action the backend allows for its type. */
export function GateApproval({
  missionId,
  requestId,
  gateMessage,
  onResolved,
}: GateApprovalProps) {
  const [reason, setReason] = useState('')
  const gate = useGateRequest(missionId, requestId)
  const decide = useDecideGate(missionId)

  const submit = async (action: string) => {
    try {
      await decide.mutateAsync({ requestId, action, reason: reason || undefined })
      toast.success(`Gate: ${action.replace(/_/g, ' ')}`)
      onResolved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }

  const actions = gate.data?.allowed_actions ?? []

  return (
    <div className={cn('space-y-2 rounded-card border p-3', TONE_BOX.warning)}>
      <div className="flex items-center gap-2">
        <Pause className="h-4 w-4 text-warning" />
        <span className="text-sm font-medium">Gate Approval Required</span>
        {gate.data && (
          <span className="font-mono text-xs text-muted-foreground">{gate.data.gate_type}</span>
        )}
      </div>

      {gateMessage && (
        <p className="text-xs text-muted-foreground">{gateMessage}</p>
      )}

      <Textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        placeholder="Reason (optional)"
        className="text-xs"
      />

      {gate.isError && (
        <p className="text-xs text-danger">Could not load this gate.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {actions.map((action) => (
          <Button
            key={action}
            size="sm"
            variant={action === 'abort' ? 'destructive' : 'secondary'}
            onClick={() => submit(action)}
            disabled={decide.isPending}
          >
            {action.replace(/_/g, ' ')}
          </Button>
        ))}
      </div>
    </div>
  )
}
