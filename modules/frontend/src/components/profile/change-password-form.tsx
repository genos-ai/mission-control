import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import type { ChangePasswordRequest } from '@/types'

export function ChangePasswordForm() {
  const [current, setCurrent] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)

  const handleChange = async () => {
    if (newPw !== confirm) {
      toast.error('Passwords do not match')
      return
    }
    setSaving(true)
    try {
      await api.post('/auth/change-password', {
        current_password: current,
        new_password: newPw,
      } satisfies ChangePasswordRequest)
      toast.success('Password changed')
      setCurrent('')
      setNewPw('')
      setConfirm('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Change failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Field label="Current password" htmlFor="profile-current-password">
        <Input
          id="profile-current-password"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </Field>
      <Field label="New password" htmlFor="profile-new-password">
        <Input id="profile-new-password" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
      </Field>
      <Field label="Confirm new password" htmlFor="profile-confirm-password">
        <Input
          id="profile-confirm-password"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </Field>
      <div>
        <Button onClick={handleChange} disabled={saving || !current || !newPw || !confirm}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />}
          Change password
        </Button>
      </div>
    </div>
  )
}
