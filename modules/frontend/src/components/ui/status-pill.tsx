import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'
import type { Tone } from '@/lib/status-tone'

// Whole class literals per tone: Tailwind (and the no-custom-classname lint
// rule) can only see classes written out in full.
const TONE_CLASS: Record<Tone, string> = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  info: 'bg-info/10 text-info',
  brand: 'bg-brand/10 text-brand-text',
  violet: 'bg-violet/10 text-violet',
  neutral: 'bg-raised text-muted-foreground',
}

export interface StatusPillProps {
  tone?: Tone
  /** Leading dot in the pill's text colour. */
  dot?: boolean
  /** Pulse the dot, for work that is in progress. */
  pulse?: boolean
  className?: string
  children: ReactNode
}

export function StatusPill({
  tone = 'neutral',
  dot = true,
  pulse = false,
  className,
  children,
}: StatusPillProps) {
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-medium',
        TONE_CLASS[tone],
        className,
      )}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full bg-current',
            pulse && 'animate-pulse-dot motion-reduce:animate-none',
          )}
        />
      )}
      {children}
    </span>
  )
}
