import { Loader2 } from 'lucide-react'

import { cn } from '@/lib/cn'
import type { StatusStyle } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'

export interface StatusIconProps extends StatusStyle {
  className?: string
}

/** The icon for a status, in its tone colour. Spread a `status-tone` entry into it. */
export function StatusIcon({ tone, icon: Icon, className }: StatusIconProps) {
  return (
    <Icon
      className={cn(
        'h-3 w-3 shrink-0',
        TONE_TEXT[tone],
        Icon === Loader2 && 'animate-spin motion-reduce:animate-none',
        className,
      )}
    />
  )
}
