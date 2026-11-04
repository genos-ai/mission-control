import { useState } from 'react'
import { ChevronDown, ChevronRight, RotateCcw, UserX } from 'lucide-react'
import toast from 'react-hot-toast'

import { useDeactivateUser, useResetPassword, useUpdateUser } from '@/hooks/use-admin'
import { ResetPasswordDialog } from '@/components/admin/reset-password-dialog'
import { UserApiKeys } from '@/components/admin/user-api-keys'
import { UserRolePill, UserRoleSelect } from '@/components/admin/user-role'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import type { UserResponse } from '@/types'

// User · Role · Status · Actions
export const USER_ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_96px_92px_160px] items-center gap-3 px-4'

/** One user in the table. Opening it shows their API keys. */
export function UserRow({
  user,
  expanded,
  onToggle,
}: {
  user: UserResponse
  expanded: boolean
  onToggle: () => void
}) {
  const updateUser = useUpdateUser()
  const deactivateUser = useDeactivateUser()
  const resetPassword = useResetPassword()
  const [confirmingDeactivate, setConfirmingDeactivate] = useState(false)
  const [resettingPassword, setResettingPassword] = useState(false)

  const handleRoleChange = async (role: string) => {
    try {
      await updateUser.mutateAsync({ userId: user.id, data: { system_role: role } })
      toast.success(`Role updated to ${role}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    }
  }

  const handleDeactivate = async () => {
    setConfirmingDeactivate(false)
    try {
      await deactivateUser.mutateAsync(user.id)
      toast.success('User deactivated')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Deactivate failed')
    }
  }

  // Throws on failure so the dialog can show the server's reason and stay open.
  const handleResetPassword = async (newPassword: string) => {
    await resetPassword.mutateAsync({ userId: user.id, newPassword })
    setResettingPassword(false)
    toast.success('Password reset')
  }

  const Chevron = expanded ? ChevronDown : ChevronRight

  return (
    <div className="transition-colors hover:bg-hover">
      <div className={cn(USER_ROW_GRID, 'py-2.5')}>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className={cn('flex min-w-0 items-center gap-2 text-left', !user.is_active && 'opacity-60')}
        >
          <Chevron className="h-3.5 w-3.5 shrink-0 text-subtle" />
          <span className="min-w-0">
            <span className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">{user.display_name}</span>
              {user.is_service_account && <Badge variant="outline">service</Badge>}
            </span>
            <span className="block truncate text-xs text-subtle">{user.email}</span>
            <span className="sr-only">Toggle API keys</span>
          </span>
        </button>
        <span>
          <UserRolePill role={user.system_role} />
        </span>
        <span>
          <StatusPill tone={user.is_active ? 'success' : 'neutral'}>
            {user.is_active ? 'Active' : 'Inactive'}
          </StatusPill>
        </span>
        <div className="flex items-center justify-end gap-1">
          <UserRoleSelect
            size="sm"
            value={user.system_role}
            label={`Role for ${user.display_name}`}
            onChange={handleRoleChange}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setResettingPassword(true)}
            title="Reset password"
            aria-label={`Reset password for ${user.display_name}`}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-danger hover:text-danger"
            onClick={() => setConfirmingDeactivate(true)}
            title="Deactivate user"
            aria-label={`Deactivate ${user.display_name}`}
            disabled={!user.is_active}
          >
            <UserX className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-3">
          <UserApiKeys userId={user.id} />
        </div>
      )}
      {confirmingDeactivate && (
        <ConfirmDialog
          title="Deactivate user"
          message={`Deactivate ${user.display_name}? They are signed out on every device, their API keys are revoked, and they cannot sign in until the account is reactivated.`}
          confirmLabel="Deactivate"
          variant="danger"
          onConfirm={handleDeactivate}
          onCancel={() => setConfirmingDeactivate(false)}
        />
      )}
      {resettingPassword && (
        <ResetPasswordDialog
          userName={user.display_name}
          onSubmit={handleResetPassword}
          onCancel={() => setResettingPassword(false)}
        />
      )}
    </div>
  )
}
