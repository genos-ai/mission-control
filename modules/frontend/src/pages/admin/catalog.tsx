import { useState, useEffect } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  Loader2,
  FileCode,
  Sprout,
  Search,
} from 'lucide-react'
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
import { useCatalogAgent } from '@/hooks/use-catalog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
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
  const [creating, setCreating] = useState(false)
  const [newAgent, setNewAgent] = useState({
    agent_name: '',
    agent_type: 'vertical' as 'vertical' | 'horizontal' | 'system',
    description: '',
    version: '1.0.0',
  })

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
      setNewAgent({
        agent_name: '',
        agent_type: 'vertical',
        description: '',
        version: '1.0.0',
      })
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
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Agent Catalog</h2>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleSeed}
            disabled={seedCatalog.isPending}
          >
            {seedCatalog.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Sprout className="h-3.5 w-3.5 mr-1" />
            )}
            Seed
          </Button>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            New Agent
          </Button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agents..."
          className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm"
        />
      </div>

      {/* Create form */}
      {creating && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Create Agent</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              value={newAgent.agent_name}
              onChange={(e) =>
                setNewAgent((p) => ({ ...p, agent_name: e.target.value }))
              }
              placeholder="Agent name"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            <select
              value={newAgent.agent_type}
              onChange={(e) =>
                setNewAgent((p) => ({
                  ...p,
                  agent_type: e.target.value as 'vertical' | 'horizontal' | 'system',
                }))
              }
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="vertical">Vertical</option>
              <option value="horizontal">Horizontal</option>
              <option value="system">System</option>
            </select>
            <Textarea
              value={newAgent.description}
              onChange={(e) =>
                setNewAgent((p) => ({ ...p, description: e.target.value }))
              }
              placeholder="Description"
              rows={2}
              className="text-sm"
            />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={
                  !newAgent.agent_name.trim() || createAgent.isPending
                }
              >
                Create
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setCreating(false)}
              >
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Prompt editor modal */}
      {promptEditor && (
        <PromptEditor
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

      {/* Agent list */}
      <div className="space-y-2">
        {filtered?.map((agent) => (
          <Card key={agent.id}>
            <CardContent className="flex items-center justify-between py-3 px-4">
              <div className="flex items-center gap-3 min-w-0">
                <button
                  onClick={() => handleToggle(agent)}
                  className={cn(
                    'h-2.5 w-2.5 rounded-full flex-shrink-0 transition-colors',
                    agent.enabled ? 'bg-emerald-500' : 'bg-muted-foreground/30',
                  )}
                  title={agent.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {agent.agent_name}
                    </span>
                    <Badge variant="secondary" className="text-[9px]">
                      {agent.agent_type}
                    </Badge>
                    <Badge variant="outline" className="text-[9px]">
                      v{agent.version}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {agent.description}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0 ml-4">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() =>
                    setPromptEditor({
                      agentName: agent.agent_name,
                      content: '',
                    })
                  }
                  title="Edit system prompt"
                >
                  <FileCode className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  title="Edit agent"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-destructive"
                  onClick={() => handleDelete(agent.agent_name)}
                  title="Delete agent"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

function PromptEditor({
  agentName,
  onSave,
  saving,
  onClose,
}: {
  agentName: string
  onSave: (content: string) => void
  saving: boolean
  onClose: () => void
}) {
  const { data: agentDetail, isLoading } = useCatalogAgent(agentName)
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)

  // Populate with existing prompt once loaded
  useEffect(() => {
    if (agentDetail && !loaded) {
      setContent(agentDetail.system_prompt ?? '')
      setLoaded(true)
    }
  }, [agentDetail, loaded])

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">
            System Prompt — {agentName}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => onSave(content)}
              disabled={saving || isLoading}
            >
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
            className="font-mono text-xs"
          />
        )}
      </CardContent>
    </Card>
  )
}
