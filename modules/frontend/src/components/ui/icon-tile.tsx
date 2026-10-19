import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/cn'
import type { Tone } from '@/lib/status-tone'
import { TONE_DOT } from '@/lib/tone-class'

const TONE_TILE: Record<Tone, string> = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  info: 'bg-info/10 text-info',
  brand: 'bg-brand/10 text-brand-text',
  violet: 'bg-violet/10 text-violet',
  neutral: 'bg-raised text-muted-foreground',
}

const SIZE: Record<'sm' | 'md' | 'lg', { box: string; icon: string }> = {
  sm: { box: 'h-6 w-6', icon: 'h-3 w-3' },
  md: { box: 'h-7 w-7', icon: 'h-3.5 w-3.5' },
  lg: { box: 'h-8 w-8', icon: 'h-[15px] w-[15px]' },
}

export interface IconTileProps {
  icon: LucideIcon
  tone?: Tone
  size?: 'sm' | 'md' | 'lg'
  /** `round` for agents, `square` for step types. */
  shape?: 'round' | 'square'
  /** A dot in the tone colour at the corner, for something that is working right now. */
  live?: boolean
}

/** A small tinted tile holding an icon: the avatar for an agent or a step type. */
export function IconTile({ icon: Icon, tone = 'neutral', size = 'md', shape = 'round', live = false }: IconTileProps) {
  return (
    <span
      className={cn(
        'relative flex shrink-0 items-center justify-center',
        SIZE[size].box,
        shape === 'round' ? 'rounded-full' : 'rounded-md',
        TONE_TILE[tone],
      )}
    >
      <Icon className={SIZE[size].icon} />
      {live && (
        <span
          className={cn(
            'absolute -bottom-px -right-px h-2 w-2 rounded-full ring-2 ring-panel',
            TONE_DOT[tone],
            'animate-pulse-dot motion-reduce:animate-none',
          )}
        />
      )}
    </span>
  )
}
