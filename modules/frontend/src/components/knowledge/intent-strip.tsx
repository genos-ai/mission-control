/**
 * IntentStrip — compact current-intent display for the mission header.
 *
 * Used in Overview tab and above the Chat input. Shows the one-line
 * intent summary with source badge. Collapsible to show full text.
 */

import { useState } from 'react'
import { Target, ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useCurrentIntent } from '@/hooks/use-mission-intent'
import { formatUtc } from '@/lib/format-date'

const SOURCE_LABELS: Record<string, string> = {
  user_chat: 'User',
  user_cli: 'CLI',
  director_inferred: 'Director',
  system: 'System',
}

export function IntentStrip({ missionId }: { missionId: string }) {
  const { data: intent, isLoading } = useCurrentIntent(missionId)
  const [expanded, setExpanded] = useState(false)

  if (isLoading || !intent) {
    return null
  }

  const sourceLabel = SOURCE_LABELS[intent.source] ?? intent.source
  const scopeIn = intent.scope?.in ?? []
  const scopeOut = intent.scope?.out ?? []

  return (
    <div
      className="rounded-md border border-amber-200/50 bg-amber-50/30 px-3 py-2 text-sm dark:border-amber-800/30 dark:bg-amber-950/20"
    >
      <button
        className="flex w-full items-center gap-2 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-amber-600 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-amber-600 shrink-0" />
        )}
        <Target className="h-3.5 w-3.5 text-amber-600 shrink-0" />
        <span className="font-medium text-amber-800 dark:text-amber-300 truncate">
          {intent.intent_summary}
        </span>
        <Badge variant="secondary" className="ml-auto shrink-0 text-xs">
          {sourceLabel}
        </Badge>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1 pl-9 text-xs text-muted-foreground">
          <p className="whitespace-pre-wrap">{intent.intent}</p>
          {scopeIn.length > 0 && (
            <p>
              <span className="font-medium text-green-700 dark:text-green-400">In scope:</span>{' '}
              {scopeIn.join(', ')}
            </p>
          )}
          {scopeOut.length > 0 && (
            <p>
              <span className="font-medium text-red-700 dark:text-red-400">Out of scope:</span>{' '}
              {scopeOut.join(', ')}
            </p>
          )}
          <p className="text-muted-foreground/60">
            {intent.reason} &middot; {formatUtc(intent.created_at)}
          </p>
        </div>
      )}
    </div>
  )
}
