import { useState } from 'react'
import { Plus, ChevronDown, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'
import { useCatalog, useCatalogAgent } from '@/hooks/use-catalog'
import { useAddToTeam } from '@/hooks/use-team'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
  const { open: openDrawer } = useDrawerStore()

  if (isLoading) return <Spinner />

  if (!agents?.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No agents in catalog yet.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Select an agent to add to your mission team.
      </p>
      {agents
        .filter((a) => a.enabled)
        .map((agent) => (
          <CatalogPickCard
            key={agent.id}
            agent={agent}
            onClick={() =>
              openDrawer('agent-detail', {
                agentName: agent.agent_name,
                missionId,
              })
            }
          />
        ))}
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
}: {
  agent: AgentCatalogItem
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="w-full rounded-lg border bg-card p-3 text-left transition-colors hover:bg-accent"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{agent.agent_name}</span>
        <Badge variant="secondary" className="text-[10px]">
          {agent.agent_type}
        </Badge>
      </div>
      <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
        {agent.description}
      </p>
    </button>
  )
}
