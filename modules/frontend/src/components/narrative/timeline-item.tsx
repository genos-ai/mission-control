import type { ReactNode } from 'react'
import { ChevronDown, type LucideIcon } from 'lucide-react'

import { IconTile } from '@/components/ui/icon-tile'
import type { Tone } from '@/lib/status-tone'

export interface TimelineItemProps {
  icon: LucideIcon
  tone: Tone
  time: string
  /** Expandable body (an excerpt, arguments, a result). Omit for a plain row. */
  detail?: ReactNode
  defaultOpen?: boolean
  /** The sentence; emphasise the actor with `font-medium text-foreground`. */
  children: ReactNode
}

/** One entry on a run's timeline: a round icon on a connector line, a sentence and a time. */
export function TimelineItem({ icon, tone, time, detail, defaultOpen, children }: TimelineItemProps) {
  const row = (
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1 py-0.5 text-md text-text-2">{children}</div>
      {detail !== undefined && (
        <ChevronDown className="mt-1.5 h-3 w-3 shrink-0 text-subtle transition-transform group-open/detail:rotate-180" />
      )}
      <span className="shrink-0 pt-1 font-mono text-2xs text-subtle">{time}</span>
    </div>
  )

  return (
    <li className="group/item relative flex gap-3 pb-3.5 last:pb-0">
      <span
        aria-hidden
        className="absolute bottom-0 left-3 top-6 w-px -translate-x-1/2 bg-line group-last/item:hidden"
      />
      <IconTile icon={icon} tone={tone} size="sm" />
      <div className="min-w-0 flex-1">
        {detail === undefined ? (
          row
        ) : (
          <details open={defaultOpen} className="group/detail">
            {/* The native summary is keyboard reachable and toggles on Enter and Space. */}
            <summary className="cursor-pointer list-none rounded-chip focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
              {row}
            </summary>
            <div className="mt-2 rounded-card bg-raised px-3 py-2.5 text-sm text-muted-foreground">
              {detail}
            </div>
          </details>
        )}
      </div>
    </li>
  )
}
