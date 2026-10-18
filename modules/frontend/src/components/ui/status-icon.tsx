import { Loader2 } from 'lucide-react'

import { cn } from '@/lib/cn'
import type { StatusStyle, Tone } from '@/lib/status-tone'

const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
  brand: 'text-brand-text',
  violet: 'text-violet',
  neutral: 'text-subtle',
}

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
