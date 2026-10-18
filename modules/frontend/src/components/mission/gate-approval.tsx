import { useState } from 'react'
import { Pause } from 'lucide-react'
import toast from 'react-hot-toast'
import { useSubmitApproval } from '@/hooks/use-executions'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface GateApprovalProps {
  executionId: string
  gateMessage?: string
  onResolved: () => void
}

export function GateApproval({
  executionId,
  gateMessage,
  onResolved,
}: GateApprovalProps) {
  const [feedback, setFeedback] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)
  const approval = useSubmitApproval()

  const submit = async (decision: 'approve' | 'reject' | 'retry') => {
    try {
      await approval.mutateAsync({
        executionId,
        decision,
        reason: feedback || undefined,
      })
      toast.success(`Gate ${decision}`)
      onResolved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }

  return (
    <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Pause className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium">Gate Approval Required</span>
      </div>

      {gateMessage && (
        <p className="text-xs text-muted-foreground">{gateMessage}</p>
      )}

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
          disabled={approval.isPending}
        >
          Approve
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            if (!showFeedback) {
              setShowFeedback(true)
            } else {
              submit('retry')
            }
          }}
          disabled={approval.isPending}
        >
          {showFeedback ? 'Retry' : 'Retry with Feedback'}
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => submit('reject')}
          disabled={approval.isPending}
        >
          Reject
        </Button>
      </div>
    </div>
  )
}
