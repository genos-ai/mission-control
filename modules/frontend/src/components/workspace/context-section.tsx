import { useId, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

export interface ContextSectionProps {
  title: string
  /** How many items the section holds, when it is a list. */
  count?: number
  defaultOpen?: boolean
  children: ReactNode
}

/** One collapsible block of the Mission Context Document. */
export function ContextSection({ title, count, defaultOpen = false, children }: ContextSectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const Chevron = open ? ChevronDown : ChevronRight

  return (
    <div className="shrink-0 rounded-card bg-raised">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 rounded-card px-3.5 py-[11px] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/40"
      >
        <Chevron className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="text-base font-medium">{title}</span>
        {count !== undefined && <span className="font-mono text-xs text-subtle">{count}</span>}
      </button>
      {open && (
        <div id={bodyId} className="space-y-2.5 pb-3.5 pl-[38px] pr-3.5 text-base text-text-2">
          {children}
        </div>
      )}
    </div>
  )
}
