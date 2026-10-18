import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

export interface FilterChipProps {
  active: boolean
  onClick: () => void
  /** Optional count shown after the label. */
  count?: number
  children: ReactNode
}

export function FilterChip({ active, onClick, count, children }: FilterChipProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs transition-colors duration-150',
        active
          ? 'border-border-hover bg-raised text-foreground'
          : 'border-panel-border text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
      {count !== undefined && <span className="font-mono text-2xs text-subtle">{count}</span>}
    </button>
  )
}
