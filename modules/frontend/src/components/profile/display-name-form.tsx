import { useState } from 'react'
import { Loader2, Save } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'

export function DisplayNameForm() {
  const { user, setUser } = useAuthStore()
  const [name, setName] = useState(user?.display_name ?? '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await api.patch<typeof user>('/auth/me', {
        display_name: name,
      })
      if (updated) setUser(updated)
      toast.success('Display name updated')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Field label="Display name" htmlFor="profile-display-name">
      <div className="flex items-center gap-2">
        <Input id="profile-display-name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button size="xl" onClick={handleSave} disabled={saving || name === user?.display_name}>
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Save
        </Button>
      </div>
    </Field>
  )
}
