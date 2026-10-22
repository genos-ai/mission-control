import { useState, type KeyboardEvent } from 'react'

import { ConsoleDetail } from '@/components/console/console-detail'
import { cn } from '@/lib/cn'
import { consoleRowView, formatTime } from '@/lib/console-event'
import { consoleCategoryTone } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import type { ConsoleEvent } from '@/stores/console'

// Time, category, event type, source, message. Fixed widths keep the columns
// aligned from row to row; the message takes what is left. Below lg the
// category column drops out (the segmented control already says which
// category is showing) so the message keeps a readable width.
const GRID =
  'grid grid-cols-[76px_minmax(130px,190px)_minmax(100px,140px)_minmax(0,1fr)] gap-3 lg:grid-cols-[76px_74px_minmax(150px,210px)_minmax(110px,150px)_minmax(0,1fr)]'

/** One event as a line in the log. Opens on click or Enter/Space to show the rest of the event. */
export function ConsoleRow({ event }: { event: ConsoleEvent }) {
  const [open, setOpen] = useState(false)
  const view = consoleRowView(event)
  // A plain log line with no message has nothing more to show.
  const expandable = view.kind !== 'log' || view.message !== ''

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setOpen((v) => !v)
    }
  }

  return (
    <div>
      <div
        {...(expandable && {
          role: 'button',
          tabIndex: 0,
          'aria-expanded': open,
          onClick: () => setOpen((v) => !v),
          onKeyDown,
        })}
        className={cn(
          GRID,
          'rounded-control px-2 py-1.5 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
          expandable && 'cursor-pointer',
          view.error
            ? 'bg-danger/5 hover:bg-danger/10'
            : view.warning
              ? 'bg-warning/5 hover:bg-warning/10'
              : 'hover:bg-raised',
        )}
      >
        <span className="truncate tabular-nums text-subtle">{formatTime(event.timestamp)}</span>
        <span className={cn('hidden truncate lg:block', TONE_TEXT[consoleCategoryTone[event.category].tone])}>
          {event.category}
        </span>
        <span
          className={cn(
            'truncate',
            view.error ? 'text-danger' : view.warning ? 'text-warning' : 'text-foreground',
          )}
          title={event.event_type}
        >
          {event.event_type}
        </span>
        <span className="truncate text-muted-foreground" title={view.source}>
          {view.source}
        </span>
        <span className="truncate font-sans text-sm text-text-3" title={view.message}>
          {view.message}
        </span>
      </div>
      {open && expandable && <ConsoleDetail event={event} view={view} />}
    </div>
  )
}
