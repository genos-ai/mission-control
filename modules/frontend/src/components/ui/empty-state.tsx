import type { ReactNode } from 'react'
import { Button } from './button'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description: string
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
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
      {action && (
        <Button variant="secondary" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  )
}
