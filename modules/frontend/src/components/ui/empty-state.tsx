import type { ReactNode } from 'react'
import { Button } from './button'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description: string
  action?: { label: string; onClick: () => void }
  /** A quieter alternative route, shown under the main action. */
  secondaryAction?: { label: string; onClick: () => void }
}

export function EmptyState({ icon, title, description, action, secondaryAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      {icon && (
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-raised text-muted-foreground">
          {icon}
        </div>
      )}
      <div>
        <h3 className="text-md text-muted-foreground">{title}</h3>
        <p className="mt-1 text-sm text-subtle">{description}</p>
      </div>
      {(action || secondaryAction) && (
        <div className="flex flex-col items-center gap-1">
          {action && (
            <Button variant="secondary" onClick={action.onClick}>
              {action.label}
            </Button>
          )}
          {secondaryAction && (
            <Button variant="link" size="sm" onClick={secondaryAction.onClick}>
              {secondaryAction.label}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
