import { Button } from '@/components/ui/button'
import { DialogFrame } from '@/components/ui/dialog-frame'

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
  return (
    <DialogFrame title={title} onCancel={onCancel}>
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
    </DialogFrame>
  )
}
