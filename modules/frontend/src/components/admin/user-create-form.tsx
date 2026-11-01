import { useId, useState } from 'react'
import toast from 'react-hot-toast'

import { useCreateUser } from '@/hooks/use-admin'
import { UserRoleSelect } from '@/components/admin/user-role'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'

const EMPTY_USER = { email: '', password: '', display_name: '', system_role: 'user' }

/** The new-user form. Closes itself through `onClose` once the account exists, or on Cancel. */
export function UserCreateForm({ onClose }: { onClose: () => void }) {
  const createUser = useCreateUser()
  const ids = useId()
  const [newUser, setNewUser] = useState(EMPTY_USER)

  const handleCreate = async () => {
    try {
      await createUser.mutateAsync(newUser)
      toast.success('User created')
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Create failed')
    }
  }

  return (
    <Panel>
      <PanelHeader title="Create user" />
      <PanelContent className="flex flex-col gap-4">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
          <Field label="Email" htmlFor={`${ids}-email`}>
            <Input
              id={`${ids}-email`}
              type="email"
              value={newUser.email}
              onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))}
            />
          </Field>
          <Field label="Display name" htmlFor={`${ids}-name`}>
            <Input
              id={`${ids}-name`}
              value={newUser.display_name}
              onChange={(e) => setNewUser((p) => ({ ...p, display_name: e.target.value }))}
            />
          </Field>
          <Field label="Password" htmlFor={`${ids}-password`}>
            <Input
              id={`${ids}-password`}
              type="password"
              autoComplete="new-password"
              value={newUser.password}
              onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))}
            />
          </Field>
          <Field label="Role" htmlFor={`${ids}-role`}>
            <UserRoleSelect
              id={`${ids}-role`}
              value={newUser.system_role}
              onChange={(role) => setNewUser((p) => ({ ...p, system_role: role }))}
            />
          </Field>
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!newUser.email || !newUser.password || createUser.isPending}>
            Create
          </Button>
        </div>
      </PanelContent>
    </Panel>
  )
}
