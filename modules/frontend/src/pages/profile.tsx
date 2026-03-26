import { useState } from 'react'
import { Loader2, Save, Key, Copy, Check, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { useOwnApiKeys, useCreateOwnApiKey, useRevokeOwnApiKey } from '@/hooks/use-profile'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { ApiKeyCreateResponse, ChangePasswordRequest } from '@/types'

export default function ProfilePage() {
  const { user } = useAuthStore()

  if (!user) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl p-6 space-y-6">
      <h1 className="text-xl font-semibold">Profile</h1>

      <DisplayNameCard />
      <ChangePasswordCard />
      <ApiKeysCard userId={user.id} />
    </div>
  )
}

function DisplayNameCard() {
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
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Display Name</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{user?.email}</span>
          <Badge variant="secondary" className="text-[9px]">
            {user?.system_role}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
          />
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving || name === user?.display_name}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function ChangePasswordCard() {
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
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Change Password</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <input
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          placeholder="Current password"
          type="password"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <input
          value={newPw}
          onChange={(e) => setNewPw(e.target.value)}
          placeholder="New password"
          type="password"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <input
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="Confirm new password"
          type="password"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <Button
          size="sm"
          onClick={handleChange}
          disabled={saving || !current || !newPw || !confirm}
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : null}
          Change Password
        </Button>
      </CardContent>
    </Card>
  )
}

function ApiKeysCard({ userId: _userId }: { userId: string }) {
  const { data: keys, isLoading } = useOwnApiKeys()
  const createKey = useCreateOwnApiKey()
  const revokeKey = useRevokeOwnApiKey()

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
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }

  const handleRevoke = async (keyId: string) => {
    try {
      await revokeKey.mutateAsync(keyId)
      toast.success('Key revoked')
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
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Key className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm">API Keys</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Created key banner */}
        {createdKey && (
          <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3 space-y-1">
            <p className="text-xs font-medium">
              Copy your key now — it won't be shown again.
            </p>
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

        {/* Create new */}
        <div className="flex items-center gap-2">
          <input
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="Key name"
            className="flex-1 rounded-md border bg-background px-2 py-1.5 text-sm"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={handleCreate}
            disabled={!newKeyName.trim() || createKey.isPending}
          >
            Create
          </Button>
        </div>

        {/* Key list */}
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : (
          <div className="space-y-2">
            {keys?.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between text-sm"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-medium">{k.name}</span>
                  <code className="text-xs text-muted-foreground">
                    {k.key_prefix}...
                  </code>
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
                    className="h-7 w-7 text-destructive"
                    onClick={() => handleRevoke(k.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            ))}
            {!keys?.length && (
              <p className="text-xs text-muted-foreground">No API keys yet.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
