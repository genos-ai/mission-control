import { useState, useMemo } from 'react'
import { Search, BookOpen, Cpu, FolderOpen } from 'lucide-react'
import { useCatalog } from '@/hooks/use-catalog'
import { useDrawerStore } from '@/stores/drawer'
import { Panel, PanelHeader, PanelContent } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'
import type { AgentCatalogItem } from '@/types'

function modelLabel(name: string | undefined): string {
  if (!name) return 'Unknown'
  const bare = name.includes(':') ? name.split(':')[1] : name
  if (bare.includes('opus')) return 'Opus 4'
  if (bare.includes('sonnet-4-6')) return 'Sonnet 4.6'
  if (bare.includes('sonnet-4')) return 'Sonnet 4'
  if (bare.includes('haiku')) return 'Haiku 4.5'
  return bare
}

const TYPE_COLORS: Record<string, 'default' | 'secondary' | 'warning'> = {
  vertical: 'default',
  horizontal: 'secondary',
  system: 'warning',
}

export default function CatalogPage() {
  const { data: agents, isLoading } = useCatalog()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const { open: openDrawer } = useDrawerStore()

  const filtered = useMemo(() => {
    if (!agents) return []
    let list = agents
    if (typeFilter) {
      list = list.filter((a) => a.agent_type === typeFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(
        (a) =>
          a.agent_name.toLowerCase().includes(q) ||
          a.description.toLowerCase().includes(q) ||
          a.keywords.some((k) => k.toLowerCase().includes(q)),
      )
    }
    return list
  }, [agents, search, typeFilter])

  const types = useMemo(() => {
    if (!agents) return []
    return [...new Set(agents.map((a) => a.agent_type))]
  }, [agents])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Agent Catalog</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Browse available agents to add to your missions.
        </p>
      </div>

      {/* Filters */}
      <div className="mb-6 flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search agents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant={typeFilter === null ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTypeFilter(null)}
          >
            All
          </Button>
          {types.map((t) => (
            <Button
              key={t}
              variant={typeFilter === t ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setTypeFilter(t)}
            >
              {t}
            </Button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="h-6 w-6 text-muted-foreground" />}
          title="No agents found"
          description={
            search || typeFilter
              ? 'Try adjusting your search or filters.'
              : 'The catalog is empty.'
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((agent) => (
            <CatalogCard
              key={agent.id}
              agent={agent}
              onViewDetails={() =>
                openDrawer('agent-detail', { agentName: agent.agent_name })
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CatalogCard({
  agent,
  onViewDetails,
}: {
  agent: AgentCatalogItem
  onViewDetails: () => void
}) {
  return (
    <Panel className="flex flex-col">
      <PanelHeader
        title={agent.agent_name}
        actions={
          <Badge variant={TYPE_COLORS[agent.agent_type] ?? 'secondary'}>
            {agent.agent_type}
          </Badge>
        }
      />
      <PanelContent className="flex flex-1 flex-col">
        <p className="flex-1 text-sm text-muted-foreground line-clamp-2">
          {agent.description}
        </p>

        {/* Model & scope */}
        <div className="mt-3 space-y-1.5">
          {agent.model_config_json?.name && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Cpu className="h-3 w-3 flex-shrink-0" />
              <span>{modelLabel(agent.model_config_json.name)}</span>
            </div>
          )}
          {agent.scope?.read && agent.scope.read.length > 0 && (
            <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <FolderOpen className="h-3 w-3 flex-shrink-0 mt-0.5" />
              <div className="flex flex-wrap gap-1">
                {agent.scope.read.map((p) => (
                  <span key={p} className="font-mono text-[10px] rounded bg-muted px-1 py-0.5">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {agent.keywords.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {agent.keywords.slice(0, 4).map((kw) => (
              <Badge key={kw} variant="outline" className="text-[10px]">
                {kw}
              </Badge>
            ))}
            {agent.keywords.length > 4 && (
              <span className="text-[10px] text-muted-foreground">
                +{agent.keywords.length - 4}
              </span>
            )}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">v{agent.version}</span>
          <Button variant="secondary" size="sm" onClick={onViewDetails}>
            Details
          </Button>
        </div>
      </PanelContent>
    </Panel>
  )
}
