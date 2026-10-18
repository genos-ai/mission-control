import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

/** A floating surface: rounded, on the well, with a faint edge in the light theme. */
export const Panel = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('rounded-panel border border-panel-border bg-panel text-foreground', className)}
      {...props}
    />
  ),
)
Panel.displayName = 'Panel'

export interface PanelHeaderProps {
  title: ReactNode
  /** Quiet text after the title, e.g. a count. */
  meta?: ReactNode
  /** Controls pushed to the right edge. */
  actions?: ReactNode
  className?: string
}

export function PanelHeader({ title, meta, actions, className }: PanelHeaderProps) {
  return (
    <div className={cn('flex items-center gap-2 px-4 pb-2 pt-3.5', className)}>
      <span className="text-base font-medium">{title}</span>
      {meta && <span className="text-xs text-subtle">{meta}</span>}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export const PanelContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('px-4 pb-4', className)} {...props} />
  ),
)
PanelContent.displayName = 'PanelContent'
