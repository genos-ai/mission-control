import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { DialogFrame } from '@/components/ui/dialog-frame'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { PASSWORD_MIN_LENGTH } from '@/lib/constants'

/** Asks an admin for a user's new password. The field is masked; the server's refusal shows in the dialog. */
export function ResetPasswordDialog({
  userName,
  onSubmit,
  onCancel,
}: {
  userName: string
  /** Resolves when the password was reset. A rejection's message is shown and the dialog stays open. */
  onSubmit: (password: string) => Promise<void>
  onCancel: () => void
}) {
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tooShort = password.length > 0 && password.length < PASSWORD_MIN_LENGTH

  const submit = async () => {
    if (password.length < PASSWORD_MIN_LENGTH || pending) return
    setPending(true)
    setError(null)
    try {
      await onSubmit(password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
      setPending(false)
    }
  }

  return (
    // The backdrop does not close it: a stray click would throw away a typed password.
    <DialogFrame title={`Reset password for ${userName}`} onCancel={onCancel} closeOnBackdrop={false}>
      <h3 className="text-base font-medium">Reset password</h3>
      <p className="mt-2 text-sm text-muted-foreground">
        Set a new password for {userName}. They are signed out on every device.
      </p>
      <form
        className="mt-4 flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <Field
          label="New password"
          htmlFor="reset-password-input"
          describedById="reset-password-message"
          hint={`At least ${PASSWORD_MIN_LENGTH} characters`}
          error={error ?? (tooShort ? `At least ${PASSWORD_MIN_LENGTH} characters` : undefined)}
        >
          <Input
            id="reset-password-input"
            type="password"
            autoComplete="new-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="reset-password-message"
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={password.length < PASSWORD_MIN_LENGTH || pending}>
            {pending && <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />}
            Reset password
          </Button>
        </div>
      </form>
    </DialogFrame>
  )
}
