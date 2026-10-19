import { cn } from '@/lib/cn'
import type { Tone } from '@/lib/status-tone'
import { TONE_DOT } from '@/lib/tone-class'

export interface ProgressProps {
  /** Percent complete; values outside 0-100 are clamped for display. */
  value: number
  tone?: Tone
  /** `sm` is 3px (inside cards), `md` is 4px (toolbars, tables). */
  size?: 'sm' | 'md'
  /** Accessible name. */
  label: string
  className?: string
}

export function Progress({ value, tone = 'brand', size = 'md', label, className }: ProgressProps) {
  const percent = Math.min(100, Math.max(0, value))
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(percent)}
      className={cn('overflow-hidden rounded-full bg-raised-2', size === 'sm' ? 'h-[3px]' : 'h-1', className)}
    >
      <div className={cn('h-full rounded-full transition-all', TONE_DOT[tone])} style={{ width: `${percent}%` }} />
    </div>
  )
}
