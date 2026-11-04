import { useState } from 'react'
import { Check, Copy, Key, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import { useOwnApiKeys, useCreateOwnApiKey, useRevokeOwnApiKey } from '@/hooks/use-profile'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { StatusPill } from '@/components/ui/status-pill'
import type { ApiKeyCreateResponse } from '@/types'

export function ApiKeysPanel() {
  const { data: keys, isLoading } = useOwnApiKeys()
  const createKey = useCreateOwnApiKey()
  const revokeKey = useRevokeOwnApiKey()

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
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }

  const handleRevoke = async (keyId: string) => {
    setRevoking(null)
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
    <Panel>
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            <Key className="h-4 w-4 text-muted-foreground" />
            API keys
          </span>
        }
      />
      <PanelContent className="flex flex-col gap-3">
        {createdKey && (
          <div className="flex flex-col gap-2 rounded-card border border-warning/30 bg-warning/10 p-3">
            <p className="text-sm font-medium">Copy your key now, it won't be shown again.</p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-chip bg-well px-2 py-1 font-mono text-xs">
                {createdKey.key}
              </code>
              <Button variant="ghost" size="icon-sm" aria-label="Copy key" onClick={copyKey}>
                {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            <div>
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
          />
          <Button
            size="xl"
            variant="secondary"
            onClick={handleCreate}
            disabled={!newKeyName.trim() || createKey.isPending}
          >
            Create
          </Button>
        </div>

        {isLoading ? (
          <Spinner />
        ) : (
          <div className="flex flex-col gap-1.5">
            {keys?.map((k) => (
              <div key={k.id} className="flex items-center justify-between gap-2 rounded-card bg-well px-3 py-1.5 text-sm">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-medium">{k.name}</span>
                  <code className="font-mono text-xs text-subtle">{k.key_prefix}...</code>
                  {k.revoked_at && <StatusPill tone="danger">revoked</StatusPill>}
                </div>
                {!k.revoked_at && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-danger hover:text-danger"
                    aria-label={`Revoke ${k.name}`}
                    onClick={() => setRevoking({ id: k.id, name: k.name })}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            ))}
            {!keys?.length && <p className="text-xs text-subtle">No API keys yet.</p>}
          </div>
        )}
      </PanelContent>
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
    </Panel>
  )
}
