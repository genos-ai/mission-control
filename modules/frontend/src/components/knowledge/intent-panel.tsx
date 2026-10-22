import { useState } from 'react'
import { ChevronDown, History, Target } from 'lucide-react'

import { intentSourceLabel } from '@/components/knowledge/intent-source'
import { Badge } from '@/components/ui/badge'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import type { MissionIntent } from '@/hooks/use-mission-intent'
import { cn } from '@/lib/cn'
import { formatRelative, formatUtc } from '@/lib/format-date'

interface IntentPanelProps {
  intent: MissionIntent | null | undefined
  /** Every revision, newest first. */
  revisions: MissionIntent[]
}

/** The mission's current intent, with its scope and the history of how it changed. */
export function IntentPanel({ intent, revisions }: IntentPanelProps) {
  const [open, setOpen] = useState(true)
  const scopeIn = intent?.scope?.in ?? []
  const scopeOut = intent?.scope?.out ?? []

  return (
    <Panel className="flex gap-3.5 px-5 py-[18px]">
      <IconTile icon={Target} tone="brand" size="lg" />
      <div className="min-w-0 flex-1">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="group flex w-full items-center gap-2 text-left"
        >
          <span className="text-sm text-text-2">Mission intent</span>
          {intent && (
            <span className="text-xs text-subtle">
              set by {intentSourceLabel(intent.source)} &middot; {formatRelative(intent.created_at)}
            </span>
          )}
          {revisions.length > 0 && (
            <Badge>{revisions.length} {revisions.length === 1 ? 'revision' : 'revisions'}</Badge>
          )}
          <ChevronDown
            className={cn(
              'ml-auto h-3.5 w-3.5 shrink-0 text-subtle transition-transform duration-150 group-hover:text-foreground motion-reduce:transition-none',
              !open && '-rotate-90',
            )}
          />
        </button>

        {open && (
          <div className="mt-1.5 flex flex-col gap-3">
            {intent ? (
              <div className="flex flex-col gap-1.5">
                <p className="whitespace-pre-wrap text-lg leading-[23px]">{intent.intent}</p>
                {(scopeIn.length > 0 || scopeOut.length > 0) && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {scopeIn.length > 0 && (
                      <span>
                        <span className="font-medium text-success">In:</span> {scopeIn.join(', ')}
                      </span>
                    )}
                    {scopeOut.length > 0 && (
                      <span>
                        <span className="font-medium text-danger">Out:</span> {scopeOut.join(', ')}
                      </span>
                    )}
                  </div>
                )}
                <p className="text-xs text-subtle">{intent.reason}</p>
              </div>
            ) : (
              <p className="text-sm text-subtle">No intent set.</p>
            )}

            {revisions.length > 1 && (
              <div className="flex flex-col gap-0.5">
                <p className="mb-1 flex items-center gap-1.5 text-xs text-subtle">
                  <History className="h-3 w-3" /> Revision history
                </p>
                {revisions.map((rev, i) => (
                  <div
                    key={rev.id}
                    className={cn('flex items-start gap-2 rounded-card px-2.5 py-1.5 text-xs', i === 0 && 'bg-raised')}
                  >
                    <span className="w-4 shrink-0 text-right font-mono text-subtle">{revisions.length - i}</span>
                    <span className="min-w-0 flex-1 truncate">{rev.intent_summary}</span>
                    <Badge className="shrink-0">{intentSourceLabel(rev.source)}</Badge>
                    <span className="shrink-0 font-mono text-subtle">{formatUtc(rev.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}
