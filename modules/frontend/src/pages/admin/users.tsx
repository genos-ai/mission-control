import { useState } from 'react'
import {
  Plus,
  Loader2,
  Key,
  Trash2,
  RotateCcw,
  UserX,
  Copy,
  Check,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useAdminUsers,
  useCreateUser,
  useUpdateUser,
  useDeactivateUser,
  useResetPassword,
  useUserApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
} from '@/hooks/use-admin'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import type { UserResponse, ApiKeyCreateResponse } from '@/types'

export default function AdminUsersPage() {
  const { data: users, isLoading } = useAdminUsers()
  const createUser = useCreateUser()

  const [creating, setCreating] = useState(false)
  const [newUser, setNewUser] = useState({
    email: '',
    password: '',
    display_name: '',
    system_role: 'user',
  })
  const [expandedUser, setExpandedUser] = useState<string | null>(null)

  const handleCreate = async () => {
    try {
      await createUser.mutateAsync(newUser)
      toast.success('User created')
      setCreating(false)
      setNewUser({ email: '', password: '', display_name: '', system_role: 'user' })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Create failed')
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Users</h2>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          New User
        </Button>
      </div>

      {/* Create form */}
      {creating && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Create User</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              value={newUser.email}
              onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))}
              placeholder="Email"
              type="email"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            <input
              value={newUser.display_name}
              onChange={(e) => setNewUser((p) => ({ ...p, display_name: e.target.value }))}
              placeholder="Display name"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            <input
              value={newUser.password}
              onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))}
              placeholder="Password"
              type="password"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            <select
              value={newUser.system_role}
              onChange={(e) => setNewUser((p) => ({ ...p, system_role: e.target.value }))}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="viewer">Viewer</option>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={!newUser.email || !newUser.password || createUser.isPending}
              >
                Create
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* User list */}
      <div className="space-y-2">
        {users?.map((u) => (
          <div key={u.id}>
            <UserRow
              user={u}
              expanded={expandedUser === u.id}
              onToggle={() =>
                setExpandedUser((prev) => (prev === u.id ? null : u.id))
              }
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function UserRow({
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

  const handleRoleChange = async (role: string) => {
    try {
      await updateUser.mutateAsync({ userId: user.id, data: { system_role: role } })
      toast.success(`Role updated to ${role}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    }
  }

  const handleDeactivate = async () => {
    try {
      await deactivateUser.mutateAsync(user.id)
      toast.success('User deactivated')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Deactivate failed')
    }
  }

  const handleResetPassword = async () => {
    const pw = prompt('Enter new password:')
    if (!pw) return
    try {
      await resetPassword.mutateAsync({ userId: user.id, newPassword: pw })
      toast.success('Password reset')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Reset failed')
    }
  }

  return (
    <Card className={cn(!user.is_active && 'opacity-50')}>
      <CardContent className="py-3 px-4">
        <div className="flex items-center justify-between">
          <button
            onClick={onToggle}
            className="flex items-center gap-3 min-w-0 text-left"
          >
            <span
              className={cn(
                'h-2.5 w-2.5 rounded-full flex-shrink-0',
                user.is_active ? 'bg-emerald-500' : 'bg-muted-foreground/30',
              )}
            />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  {user.display_name}
                </span>
                <Badge variant="secondary" className="text-[9px]">
                  {user.system_role}
                </Badge>
                {user.is_service_account && (
                  <Badge variant="outline" className="text-[9px]">
                    service
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{user.email}</p>
            </div>
          </button>
          <div className="flex items-center gap-1 flex-shrink-0 ml-4">
            <select
              value={user.system_role}
              onChange={(e) => handleRoleChange(e.target.value)}
              className="rounded border bg-background px-2 py-1 text-xs"
            >
              <option value="viewer">Viewer</option>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handleResetPassword}
              title="Reset password"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-destructive"
              onClick={handleDeactivate}
              title="Deactivate user"
              disabled={!user.is_active}
            >
              <UserX className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {expanded && (
          <div className="mt-3 pt-3 border-t">
            <ApiKeySection userId={user.id} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ApiKeySection({ userId }: { userId: string }) {
  const { data: keys, isLoading } = useUserApiKeys(userId)
  const createKey = useCreateApiKey(userId)
  const revokeKey = useRevokeApiKey(userId)

  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResponse | null>(null)
  const [copied, setCopied] = useState(false)

  const handleCreate = async () => {
    if (!newKeyName.trim()) return
    try {
      const result = await createKey.mutateAsync({ name: newKeyName })
      setCreatedKey(result)
      setNewKeyName('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create key')
    }
  }

  const handleRevoke = async (keyId: string) => {
    try {
      await revokeKey.mutateAsync(keyId)
      toast.success('API key revoked')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Revoke failed')
    }
  }

  const copyKey = () => {
    if (!createdKey) return
    navigator.clipboard.writeText(createdKey.key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Key className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium">API Keys</span>
      </div>

      {/* Created key display */}
      {createdKey && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3 space-y-1">
          <p className="text-xs font-medium">Key created — copy it now!</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs font-mono bg-background rounded px-2 py-1 truncate">
              {createdKey.key}
            </code>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={copyKey}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => setCreatedKey(null)}
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* Create new key */}
      <div className="flex items-center gap-2">
        <input
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          placeholder="Key name"
          className="flex-1 rounded-md border bg-background px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={handleCreate}
          disabled={!newKeyName.trim() || createKey.isPending}
          className="text-xs h-7"
        >
          Create
        </Button>
      </div>

      {/* Key list */}
      {isLoading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
      ) : (
        <div className="space-y-1">
          {keys?.map((k) => (
            <div
              key={k.id}
              className="flex items-center justify-between text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium">{k.name}</span>
                <code className="text-muted-foreground">{k.key_prefix}...</code>
                {k.revoked_at && (
                  <Badge variant="destructive" className="text-[9px]">
                    revoked
                  </Badge>
                )}
              </div>
              {!k.revoked_at && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-destructive"
                  onClick={() => handleRevoke(k.id)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
            </div>
          ))}
          {!keys?.length && (
            <p className="text-xs text-muted-foreground">No API keys.</p>
          )}
        </div>
      )}
    </div>
  )
}
