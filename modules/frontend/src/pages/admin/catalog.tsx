import { useState } from 'react'
import { Plus, Search, Sprout, Users } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import {
  useAdminCatalog,
  useCreateAgent,
  useUpdateAgent,
  useDeleteAgent,
  useUpdateSystemPrompt,
  useSeedCatalog,
} from '@/hooks/use-admin'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { CatalogAgentEditor } from '@/components/admin/catalog-agent-editor'
import { CATALOG_ROW_GRID, CatalogAgentRow } from '@/components/admin/catalog-agent-row'
import { CatalogCreateForm } from '@/components/admin/catalog-create-form'
import { EMPTY_NEW_AGENT } from '@/components/admin/catalog-new-agent'
import { CatalogPromptEditor } from '@/components/admin/catalog-prompt-editor'
import { cn } from '@/lib/cn'
import type { AgentCatalogItem } from '@/types'

export default function AdminCatalogPage() {
  const { data: agents, isLoading } = useAdminCatalog()
  const createAgent = useCreateAgent()
  const updateAgent = useUpdateAgent()
  const deleteAgent = useDeleteAgent()
  const updatePrompt = useUpdateSystemPrompt()
  const seedCatalog = useSeedCatalog()
  const { user } = useAuthStore()

  const [search, setSearch] = useState('')
  const [promptEditor, setPromptEditor] = useState<{
    agentName: string
    content: string
  } | null>(null)
  const [editingAgent, setEditingAgent] = useState<AgentCatalogItem | null>(null)
  const [creating, setCreating] = useState(false)
  const [newAgent, setNewAgent] = useState(EMPTY_NEW_AGENT)

  const filtered = agents?.filter(
    (a) =>
      a.agent_name.toLowerCase().includes(search.toLowerCase()) ||
      a.description.toLowerCase().includes(search.toLowerCase()),
  )

  const handleCreate = async () => {
    try {
      await createAgent.mutateAsync(newAgent)
      toast.success('Agent created')
      setCreating(false)
      setNewAgent(EMPTY_NEW_AGENT)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Create failed')
    }
  }

  const handleToggle = async (agent: AgentCatalogItem) => {
    try {
      await updateAgent.mutateAsync({
        agentName: agent.agent_name,
        data: { enabled: !agent.enabled },
      })
      toast.success(`${agent.agent_name} ${agent.enabled ? 'disabled' : 'enabled'}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    }
  }

  const handleDelete = async (agentName: string) => {
    try {
      await deleteAgent.mutateAsync(agentName)
      toast.success(`${agentName} deleted`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const handleSeed = async () => {
    try {
      await seedCatalog.mutateAsync()
      toast.success('Catalog seeded from YAML configs')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Seed failed')
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    )
  }

  const enabledCount = agents?.filter((a) => a.enabled).length ?? 0

  return (
    <>
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">Agent catalog</h2>
          <p className="text-sm text-muted-foreground">
            {agents?.length ?? 0} {agents?.length === 1 ? 'agent' : 'agents'} · {enabledCount} enabled
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={handleSeed} disabled={seedCatalog.isPending}>
            {seedCatalog.isPending ? <Spinner className="h-3.5 w-3.5 text-current" /> : <Sprout className="h-3.5 w-3.5" />}
            Seed
          </Button>
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" />
            New Agent
          </Button>
        </div>
      </div>

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
        <Input
          aria-label="Search agents"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agents..."
          className="h-[34px] pl-9"
        />
      </div>

      {creating && (
        <CatalogCreateForm
          draft={newAgent}
          onChange={setNewAgent}
          onCreate={handleCreate}
          onCancel={() => setCreating(false)}
          creating={createAgent.isPending}
        />
      )}

      {promptEditor && (
        <CatalogPromptEditor
          agentName={promptEditor.agentName}
          onSave={async (content) => {
            try {
              await updatePrompt.mutateAsync({
                agentName: promptEditor.agentName,
                content,
                changedBy: user?.id ?? 'admin',
                changeReason: 'Updated via admin UI',
              })
              toast.success('System prompt updated')
              setPromptEditor(null)
            } catch (err) {
              toast.error(err instanceof Error ? err.message : 'Update failed')
            }
          }}
          saving={updatePrompt.isPending}
          onClose={() => setPromptEditor(null)}
        />
      )}

      {editingAgent && (
        <CatalogAgentEditor
          agent={editingAgent}
          onSave={async (data) => {
            try {
              await updateAgent.mutateAsync({
                agentName: editingAgent.agent_name,
                data,
              })
              toast.success(`${editingAgent.agent_name} updated`)
              setEditingAgent(null)
            } catch (err) {
              toast.error(err instanceof Error ? err.message : 'Update failed')
            }
          }}
          saving={updateAgent.isPending}
          onClose={() => setEditingAgent(null)}
        />
      )}

      {!agents?.length ? (
        <Panel>
          <EmptyState
            icon={<Users className="h-4 w-4" />}
            title="No agents in the catalog"
            description="Seed the catalog from the YAML configs, or create an agent."
            action={{ label: 'Seed', onClick: handleSeed }}
          />
        </Panel>
      ) : (
        <Panel className="overflow-x-auto">
          <div className="min-w-[620px]">
            <div className={cn(CATALOG_ROW_GRID, 'py-2.5 text-2xs text-subtle')}>
              <span>
                <span className="sr-only">Enabled</span>
              </span>
              <span>Agent</span>
              <span>Type</span>
              <span>Version</span>
              <span>Model</span>
              <span>
                <span className="sr-only">Actions</span>
              </span>
            </div>
            {filtered?.length === 0 ? (
              <p className="border-t border-line px-4 py-6 text-center text-sm text-subtle">
                No agents match "{search}".
              </p>
            ) : (
              filtered?.map((agent) => (
                <CatalogAgentRow
                  key={agent.id}
                  agent={agent}
                  onToggle={() => handleToggle(agent)}
                  onEditPrompt={() => setPromptEditor({ agentName: agent.agent_name, content: '' })}
                  onEdit={() => setEditingAgent(agent)}
                  onDelete={() => handleDelete(agent.agent_name)}
                />
              ))
            )}
          </div>
        </Panel>
      )}
    </>
  )
}
