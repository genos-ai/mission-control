/**
 * IntentStrip — compact current-intent display for the mission header.
 *
 * Used in Overview tab and above the Chat input. Shows the one-line
 * intent summary with source badge. Collapsible to show full text.
 */

import { useState } from 'react'
import { Target, ChevronDown, ChevronRight } from 'lucide-react'
import { intentSourceLabel } from '@/components/knowledge/intent-source'
import { Badge } from '@/components/ui/badge'
import { useCurrentIntent } from '@/hooks/use-mission-intent'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'
import { TONE_BOX } from '@/lib/tone-class'

export function IntentStrip({ missionId }: { missionId: string }) {
  const { data: intent, isLoading } = useCurrentIntent(missionId)
  const [expanded, setExpanded] = useState(false)

  if (isLoading || !intent) {
    return null
  }

  const sourceLabel = intentSourceLabel(intent.source)
  const scopeIn = intent.scope?.in ?? []
  const scopeOut = intent.scope?.out ?? []

  return (
    <div className={cn('rounded-card border px-3 py-2 text-sm', TONE_BOX.brand)}>
      <button
        type="button"
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-brand-text shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-brand-text shrink-0" />
        )}
        <Target className="h-3.5 w-3.5 text-brand-text shrink-0" />
        <span className="font-medium truncate">
          {intent.intent_summary}
        </span>
        <Badge className="ml-auto shrink-0">
          {sourceLabel}
        </Badge>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1 pl-9 text-xs text-muted-foreground">
          <p className="whitespace-pre-wrap">{intent.intent}</p>
          {scopeIn.length > 0 && (
            <p>
              <span className="font-medium text-success">In scope:</span>{' '}
              {scopeIn.join(', ')}
            </p>
          )}
          {scopeOut.length > 0 && (
            <p>
              <span className="font-medium text-danger">Out of scope:</span>{' '}
              {scopeOut.join(', ')}
            </p>
          )}
          <p className="text-subtle">
            {intent.reason} &middot; {formatUtc(intent.created_at)}
          </p>
        </div>
      )}
    </div>
  )
}
