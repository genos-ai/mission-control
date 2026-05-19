import { useEffect, useRef } from 'react'
import { Zap } from 'lucide-react'
import { cn } from '@/lib/cn'

interface Props {
  /** Pre-filtered tool list — caller owns the filter computation. */
  tools: string[]
  activeIndex: number
  onSelect: (tool: string) => void
}

/**
 * Slash-command autocomplete popover.
 * Rendered above the chat input when the user types / .
 * Receives an already-filtered tool list from the parent.
 */
export function SlashCommandPopover({ tools, activeIndex, onSelect }: Props) {
  const activeRef = useRef<HTMLButtonElement | null>(null)

  // Keep the highlighted item scrolled into view
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (tools.length === 0) return null

  return (
    <div className="absolute bottom-full left-0 right-0 mb-1 z-50 rounded-lg border bg-popover shadow-lg overflow-hidden">
      <div className="flex items-center gap-1.5 border-b px-3 py-1.5">
        <Zap className="h-3 w-3 text-primary" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Commands
        </span>
      </div>

      <div className="max-h-52 overflow-y-auto py-1">
        {tools.map((tool, i) => {
          const isActive = i === activeIndex
          return (
            <button
              key={tool}
              ref={isActive ? activeRef : null}
              // mousedown instead of click so it fires before the textarea loses focus
              onMouseDown={(e) => { e.preventDefault(); onSelect(tool) }}
              className={cn(
                'flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors',
                isActive
                  ? 'bg-accent text-accent-foreground'
                  : 'text-foreground hover:bg-accent/50',
              )}
            >
              <span className="shrink-0 font-mono text-[11px] text-primary">/</span>
              <span className="text-sm">{tool}</span>
            </button>
          )
        })}
      </div>

      <div className="border-t px-3 py-1 text-[10px] text-muted-foreground/50">
        ↑↓ navigate · Enter select · Esc close
      </div>
    </div>
  )
}
