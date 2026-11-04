import { useState } from 'react'
import { Check, Copy, Key, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { useCreateApiKey, useRevokeApiKey, useUserApiKeys } from '@/hooks/use-admin'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { TONE_BOX } from '@/lib/tone-class'
import type { ApiKeyCreateResponse } from '@/types'

/** One user's API keys: the list, a revoke button per live key, and a create box. */
export function UserApiKeys({ userId }: { userId: string }) {
  const { data: keys, isLoading } = useUserApiKeys(userId)
  const createKey = useCreateApiKey(userId)
  const revokeKey = useRevokeApiKey(userId)

  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [revoking, setRevoking] = useState<{ id: string; name: string } | null>(null)

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
    setRevoking(null)
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
    <div className="flex flex-col gap-3 rounded-card bg-well p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-text-3">
        <Key className="h-3.5 w-3.5 text-subtle" />
        API keys
      </div>

      {createdKey && (
        <div role="status" className={cn('flex flex-col gap-2 rounded-card border p-3', TONE_BOX.warning)}>
          <p className="text-xs font-medium">Key created. Copy it now.</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-chip bg-field px-2 py-1 font-mono text-xs">
              {createdKey.key}
            </code>
            <Button variant="ghost" size="icon-sm" aria-label="Copy key" onClick={copyKey}>
              {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCreatedKey(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Input
          aria-label="Key name"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          placeholder="Key name"
          className="h-[30px] flex-1 text-sm"
        />
        <Button
          variant="secondary"
          onClick={handleCreate}
          disabled={!newKeyName.trim() || createKey.isPending}
        >
          Create
        </Button>
      </div>

      {isLoading ? (
        <Spinner className="h-3.5 w-3.5" />
      ) : (
        <ul className="flex flex-col gap-1">
          {keys?.map((k) => (
            <li key={k.id} className="flex items-center justify-between gap-2 text-sm">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate font-medium">{k.name}</span>
                <code className="font-mono text-xs text-subtle">{k.key_prefix}...</code>
                {k.revoked_at && <StatusPill tone="danger">Revoked</StatusPill>}
              </div>
              {!k.revoked_at && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="text-danger hover:text-danger"
                  aria-label={`Revoke key ${k.name}`}
                  onClick={() => setRevoking({ id: k.id, name: k.name })}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
            </li>
          ))}
          {!keys?.length && <li className="text-xs text-subtle">No API keys.</li>}
        </ul>
      )}

      {revoking && (
        <ConfirmDialog
          title="Revoke API key"
          message={`Revoke ${revoking.name}? Anything using it stops working at once. This cannot be undone.`}
          confirmLabel="Revoke"
          variant="danger"
          onConfirm={() => handleRevoke(revoking.id)}
          onCancel={() => setRevoking(null)}
        />
      )}
    </div>
  )
}
