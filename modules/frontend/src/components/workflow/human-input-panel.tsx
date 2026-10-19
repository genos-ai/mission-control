/**
 * Response forms for the workflow editor's pending human_input nodes.
 */

import { useState } from 'react'
import toast from 'react-hot-toast'
import { UserRound, Clock, Send, Loader2 } from 'lucide-react'
import type { PendingHumanInput } from '@/hooks/use-workflow-run-status'
import { useRespondToHumanInput } from '@/hooks/use-workflows'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/cn'
import { TONE_BOX } from '@/lib/tone-class'

/**
 * Renders a response form for each pending human_input node.
 * Sits below the toolbar — non-blocking, dismisses automatically when
 * the Temporal Signal is acknowledged and the SSE response event fires.
 */
export function HumanInputPanel({
  pending,
  missionId,
}: {
  pending: Record<string, PendingHumanInput>
  missionId: string
}) {
  const respond = useRespondToHumanInput(missionId)
  const [freeText, setFreeText] = useState<Record<string, string>>({})

  const requests = Object.values(pending)
  if (requests.length === 0) return null

  return (
    <div className={cn('shrink-0 space-y-2 rounded-panel border p-3', TONE_BOX.warning)}>
      {requests.map((req) => (
        <HumanInputRequest
          key={req.requestId}
          req={req}
          freeText={freeText[req.stepId] ?? ''}
          onFreeTextChange={(v) => setFreeText((prev) => ({ ...prev, [req.stepId]: v }))}
          isPending={respond.isPending}
          onSubmit={(response) => {
            respond.mutate(
              { requestId: req.requestId, response },
              { onError: (err) => toast.error(err instanceof Error ? err.message : 'Failed to submit') },
            )
          }}
        />
      ))}
    </div>
  )
}

function HumanInputRequest({
  req,
  freeText,
  onFreeTextChange,
  isPending,
  onSubmit,
}: {
  req: PendingHumanInput
  freeText: string
  onFreeTextChange: (v: string) => void
  isPending: boolean
  onSubmit: (response: string) => void
}) {
  const hasChoices = req.choices.length > 0

  return (
    <div className="rounded-card bg-raised p-3">
      <div className="mb-2 flex items-start gap-2">
        <UserRound className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-warning">Input required</span>
            <span className="text-2xs text-subtle">step: {req.stepId}</span>
            {req.timeoutAt && (
              <span className="ml-auto flex items-center gap-1 text-2xs text-subtle">
                <Clock className="h-3 w-3" />
                expires {new Date(req.timeoutAt).toLocaleTimeString()}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{req.promptMessage}</p>
        </div>
      </div>

      {hasChoices ? (
        <div className="flex flex-wrap gap-2">
          {req.choices.map((choice) => (
            <Button
              key={choice}
              variant="secondary"
              size="sm"
              disabled={isPending}
              onClick={() => onSubmit(choice)}
            >
              {isPending ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" /> : choice}
            </Button>
          ))}
        </div>
      ) : (
        <div className="flex gap-2">
          <Textarea
            value={freeText}
            onChange={(e) => onFreeTextChange(e.target.value)}
            placeholder="Type your response…"
            rows={2}
            className="resize-none text-sm"
            disabled={isPending}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && freeText.trim()) {
                e.preventDefault()
                onSubmit(freeText.trim())
              }
            }}
          />
          <Button
            size="icon"
            variant="secondary"
            disabled={!freeText.trim() || isPending}
            onClick={() => onSubmit(freeText.trim())}
            className="h-auto"
          >
            {isPending
              ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
              : <Send className="h-4 w-4" />}
          </Button>
        </div>
      )}
    </div>
  )
}
