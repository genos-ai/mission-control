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
    <div className="absolute inset-x-0 bottom-full z-50 mb-1 overflow-hidden rounded-card border border-panel-border bg-popover shadow-lg">
      <div className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-xs text-subtle">
        <Zap className="h-3 w-3 text-brand-text" />
        Commands
      </div>

      <div className="max-h-52 overflow-y-auto pb-1">
        {tools.map((tool, i) => {
          const isActive = i === activeIndex
          return (
            <button
              key={tool}
              ref={isActive ? activeRef : null}
              // mousedown instead of click so it fires before the textarea loses focus
              onMouseDown={(e) => { e.preventDefault(); onSelect(tool) }}
              className={cn(
                'flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors duration-150',
                isActive ? 'bg-raised text-foreground' : 'text-text-3 hover:bg-hover',
              )}
            >
              <span className="shrink-0 font-mono text-xs text-brand-text">/</span>
              <span className="text-sm">{tool}</span>
            </button>
          )
        })}
      </div>

      <div className="px-3 pb-2 text-2xs text-subtle">↑↓ navigate · Enter select · Esc close</div>
    </div>
  )
}
