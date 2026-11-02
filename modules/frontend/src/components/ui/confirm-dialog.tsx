import { useEscapeKey } from '@/hooks/use-escape-key'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'

export interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel: string
  /** `danger` for destructive actions (delete); `warning` for reversible ones (archive). */
  variant: 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  variant,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEscapeKey(onCancel)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-sm p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-medium">{title}</h3>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={variant === 'danger' ? 'destructive' : 'default'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </Panel>
    </div>
  )
}
