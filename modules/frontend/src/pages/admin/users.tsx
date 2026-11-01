import { useState } from 'react'
import { AlertTriangle, Plus, Users } from 'lucide-react'

import { useAdminUsers } from '@/hooks/use-admin'
import { UserCreateForm } from '@/components/admin/user-create-form'
import { USER_ROW_GRID, UserRow } from '@/components/admin/user-row'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/cn'

export default function AdminUsersPage() {
  const { data: users, isLoading, error } = useAdminUsers()

  const [creating, setCreating] = useState(false)
  const [expandedUser, setExpandedUser] = useState<string | null>(null)

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-medium">
          Users
          {users && <span className="ml-2 text-xs font-normal text-subtle">{users.length}</span>}
        </h2>
        <Button variant="secondary" onClick={() => setCreating(true)}>
          <Plus className="h-[13px] w-[13px]" />
          New user
        </Button>
      </div>

      {creating && <UserCreateForm onClose={() => setCreating(false)} />}

      {isLoading ? (
        <Panel className="flex justify-center py-12">
          <Spinner className="h-5 w-5" />
        </Panel>
      ) : !users ? (
        <Panel>
          <EmptyState
            icon={<AlertTriangle className="h-4 w-4" />}
            title="Could not load users"
            description={error?.message ?? 'The user list did not load.'}
          />
        </Panel>
      ) : !users.length ? (
        <Panel>
          <EmptyState
            icon={<Users className="h-4 w-4" />}
            title="No users yet"
            description="Accounts created here can sign in to Mission Control."
          />
        </Panel>
      ) : (
        <Panel className="overflow-x-auto">
          <div className="min-w-[680px]">
            <div className={cn(USER_ROW_GRID, 'py-2.5 text-2xs text-subtle')}>
              <span>User</span>
              <span>Role</span>
              <span>Status</span>
              <span className="sr-only">Actions</span>
            </div>
            <div className="divide-y divide-line">
              {users.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  expanded={expandedUser === u.id}
                  onToggle={() => setExpandedUser((prev) => (prev === u.id ? null : u.id))}
                />
              ))}
            </div>
          </div>
        </Panel>
      )}
    </>
  )
}
