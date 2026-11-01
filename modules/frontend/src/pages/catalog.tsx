import { useState, useMemo } from 'react'
import { Search, BookOpen } from 'lucide-react'
import { useCatalog } from '@/hooks/use-catalog'
import { useDrawerStore } from '@/stores/drawer'
import { AgentCard } from '@/components/catalog/agent-card'
import { DocumentPage } from '@/components/layout/document-page'
import { TopBar } from '@/components/layout/top-bar'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'

/** The "no type chosen" segment; agent types are the catalogue's own values, so it must not be one of them. */
const ALL_TYPES = '*'

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

  const typeOptions = useMemo(() => {
    if (!agents) return []
    const types = [...new Set(agents.map((a) => a.agent_type))]
    return [
      { value: ALL_TYPES, label: 'All', count: agents.length },
      ...types.map((t) => ({ value: t, label: t, count: agents.filter((a) => a.agent_type === t).length })),
    ]
  }, [agents])

  const topBar = <TopBar segments={[{ label: 'Catalog' }]} />

  if (isLoading) {
    return (
      <>
        {topBar}
        <div className="flex items-center justify-center py-24">
          <Spinner />
        </div>
      </>
    )
  }

  return (
    <>
      {topBar}
      <DocumentPage className="gap-4">
        <div className="flex flex-col gap-1.5 pt-4">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">Agent catalog</h1>
          <p className="text-sm text-muted-foreground">Browse available agents to add to your missions.</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-sm flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
            <Input
              aria-label="Search agents"
              placeholder="Search agents..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-[34px] rounded-card pl-9 text-base"
            />
          </div>
          <Segmented
            label="Filter by agent type"
            value={typeFilter ?? ALL_TYPES}
            onChange={(t) => setTypeFilter(t === ALL_TYPES ? null : t)}
            options={typeOptions}
          />
        </div>

        {filtered.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="h-4 w-4" />}
            title="No agents found"
            description={search || typeFilter ? 'Try adjusting your search or filters.' : 'The catalog is empty.'}
          />
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-gutter">
            {filtered.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onViewDetails={() => openDrawer('agent-detail', { agentName: agent.agent_name })}
              />
            ))}
          </div>
        )}
      </DocumentPage>
    </>
  )
}
