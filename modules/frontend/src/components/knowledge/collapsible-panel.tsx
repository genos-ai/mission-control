import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

import { Panel, PanelContent } from '@/components/ui/panel'
import { cn } from '@/lib/cn'

interface CollapsiblePanelProps {
  title: string
  /** Quiet text after the title, e.g. a count. */
  meta?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}

/** A Panel whose header toggles its body. The toggle holds only the title, so controls in the body never sit inside a button. */
export function CollapsiblePanel({ title, meta, defaultOpen = true, children }: CollapsiblePanelProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <Panel>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="group flex w-full items-center gap-2 rounded-panel px-4 pb-2 pt-3.5 text-left"
      >
        <span className="text-base font-medium">{title}</span>
        {meta !== undefined && <span className="text-xs text-subtle">{meta}</span>}
        <ChevronDown
          className={cn(
            'ml-auto h-3.5 w-3.5 shrink-0 text-subtle transition-transform duration-150 group-hover:text-foreground motion-reduce:transition-none',
            !open && '-rotate-90',
          )}
        />
      </button>
      {open && <PanelContent className="px-2.5 pb-2.5">{children}</PanelContent>}
    </Panel>
  )
}
