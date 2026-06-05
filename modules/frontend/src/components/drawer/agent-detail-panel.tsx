import { useState } from 'react'
import { Plus, ChevronDown, ChevronRight, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { useCatalog, useCatalogAgent } from '@/hooks/use-catalog'
import { useAddToTeam, useTeam } from '@/hooks/use-team'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import type { AgentCatalogItem } from '@/types'

export function AgentDetailPanel() {
  const { context } = useDrawerStore()
  const mode = context.mode as string | undefined
  const missionId = context.missionId as string | undefined
  const agentName = context.agentName as string | undefined

  if (mode === 'add-from-catalog' && missionId) {
    return <AddFromCatalog missionId={missionId} />
  }

  if (agentName) {
    return <AgentDetail agentName={agentName} missionId={missionId} />
  }

  return <p className="text-sm text-muted-foreground">No agent selected.</p>
}

function AgentDetail({
  agentName,
  missionId,
}: {
  agentName: string
  missionId?: string
}) {
  const { data: agent, isLoading } = useCatalogAgent(agentName)
  const addToTeam = useAddToTeam(missionId ?? '')
  const addMutation = missionId ? addToTeam : null
  const { close } = useDrawerStore()
  const [prompt, setPrompt] = useState('')

  if (isLoading) return <Spinner />
  if (!agent) return <p className="text-sm text-muted-foreground">Agent not found.</p>

  const handleAdd = () => {
    if (!addMutation) return
    addMutation.mutate(
      {
        agent_catalog_id: agent.id,
        user_prompt: prompt.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success(`${agent.agent_name} added to team`)
          close()
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">{agent.agent_name}</h3>
        <div className="mt-1 flex items-center gap-2">
          <Badge variant="secondary">{agent.agent_type}</Badge>
          <span className="text-xs text-muted-foreground">v{agent.version}</span>
        </div>
      </div>

      <p className="text-sm text-muted-foreground">{agent.description}</p>

      {agent.tools.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Tools
          </h4>
          <div className="flex flex-wrap gap-1">
            {agent.tools.map((t) => (
              <Badge key={t} variant="outline" className="text-[10px]">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {agent.keywords.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Keywords
          </h4>
          <div className="flex flex-wrap gap-1">
            {agent.keywords.map((k) => (
              <Badge key={k} variant="outline" className="text-[10px]">
                {k}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {agent.system_prompt && <SystemPromptSection prompt={agent.system_prompt} />}

      {missionId && (
        <div className="border-t pt-4">
          <h4 className="mb-2 text-sm font-medium">
            Add to Mission
          </h4>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="Optional mission-specific instructions..."
            className="mb-3"
          />
          <Button
            onClick={handleAdd}
            disabled={addMutation?.isPending}
            className="w-full"
          >
            <Plus className="mr-1 h-4 w-4" />
            Add to Team
          </Button>
        </div>
      )}
    </div>
  )
}

function AddFromCatalog({ missionId }: { missionId: string }) {
  const { data: agents, isLoading } = useCatalog()
  const { data: team } = useTeam(missionId)
  const { open: openDrawer } = useDrawerStore()
  const [query, setQuery] = useState('')

  if (isLoading) return <Spinner />

  if (!agents?.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No agents in catalog yet.
      </p>
    )
  }

  const addedIds = new Set((team ?? []).map((m) => m.agent_catalog_id))

  const q = query.toLowerCase().trim()
  const filtered = agents.filter((a) => {
    if (!a.enabled) return false
    if (!q) return true
    return (
      a.agent_name.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q) ||
      a.agent_type.toLowerCase().includes(q) ||
      a.keywords.some((k) => k.toLowerCase().includes(q))
    )
  })

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search agents..."
          className="pl-8 h-8 text-sm"
        />
      </div>
      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">
          No agents match &quot;{query}&quot;
        </p>
      ) : (
        filtered.map((agent) => (
          <CatalogPickCard
            key={agent.id}
            agent={agent}
            alreadyAdded={addedIds.has(agent.id)}
            onClick={() =>
              openDrawer('agent-detail', {
                agentName: agent.agent_name,
                missionId,
              })
            }
          />
        ))
      )}
    </div>
  )
}

function SystemPromptSection({ prompt }: { prompt: string }) {
  const { user } = useAuthStore()
  const [open, setOpen] = useState(false)

  // Only visible to sysadmin
  if (user?.system_role !== 'sysadmin') return null

  return (
    <div className="border-t pt-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 text-left"
      >
        {open
          ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        }
        <h4 className="text-xs font-semibold uppercase text-muted-foreground">System Prompt</h4>
      </button>
      {open && (
        <pre className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap rounded border bg-muted/30 p-3 font-mono text-[11px] text-muted-foreground">
          {prompt}
        </pre>
      )}
    </div>
  )
}

function CatalogPickCard({
  agent,
  onClick,
  alreadyAdded = false,
}: {
  agent: AgentCatalogItem
  onClick: () => void
  alreadyAdded?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={alreadyAdded}
      title={alreadyAdded ? 'Already on this team' : undefined}
      className={
        alreadyAdded
          ? 'w-full cursor-not-allowed rounded-lg border bg-muted/30 p-3 text-left opacity-50'
          : 'w-full rounded-lg border bg-card p-3 text-left transition-colors hover:bg-accent'
      }
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{agent.agent_name}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          {alreadyAdded && (
            <Badge variant="outline" className="text-[10px]">
              Added
            </Badge>
          )}
          <Badge variant="secondary" className="text-[10px]">
            {agent.agent_type}
          </Badge>
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
        {agent.description}
      </p>
    </button>
  )
}
