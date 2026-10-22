/**
 * ArtifactListPanel — left panel listing a mission's artifacts, filtered by
 * title or agent and grouped by type. Every group starts expanded.
 */

import { useMemo, useState } from 'react'
import { Package, Search } from 'lucide-react'
import { agentShortName } from '@/lib/format'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'
import { useWorkspaceStore } from '@/stores/workspace'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Panel, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { ArtifactGroup, TYPE_ORDER } from '@/components/workspace/artifact-group'
import { StreamingArtifactCard } from '@/components/workspace/streaming-artifact-card'

export function ArtifactListPanel({
  artifacts,
  isLoading,
  selectedId,
  onSelect,
}: {
  artifacts: MissionArtifact[]
  isLoading: boolean
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const streaming = useWorkspaceStore((s) => s.streamingArtifact)
  const [query, setQuery] = useState('')

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const map = new Map<string, MissionArtifact[]>()
    for (const a of artifacts) {
      if (
        needle &&
        !a.title.toLowerCase().includes(needle) &&
        !agentShortName(a.agent_id).toLowerCase().includes(needle)
      ) {
        continue
      }
      const type = a.artifact_type
      const list = map.get(type)
      if (list) list.push(a)
      else map.set(type, [a])
    }
    // Return in stable order, only types that have items
    return TYPE_ORDER
      .filter((t) => map.has(t))
      .map((t) => ({ type: t, items: map.get(t)! }))
      // Append any unknown types at the end
      .concat(
        [...map.entries()]
          .filter(([t]) => !TYPE_ORDER.includes(t))
          .map(([type, items]) => ({ type, items })),
      )
  }, [artifacts, query])

  const hasArtifacts = artifacts.length > 0

  return (
    <Panel className="flex w-[300px] shrink-0 flex-col overflow-hidden">
      <PanelHeader title="Artifacts" meta={hasArtifacts ? `· ${artifacts.length}` : undefined} />

      {hasArtifacts && (
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
            <Input
              aria-label="Filter artifacts"
              placeholder="Filter artifacts"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-[30px] rounded-card pl-8 text-sm"
            />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : !hasArtifacts && !streaming ? (
          <EmptyState
            icon={<Package className="h-4 w-4" />}
            title="No artifacts yet"
            description="Artifacts appear when agents produce reports, findings, or code during a run."
          />
        ) : (
          <div className="flex flex-col gap-1">
            {streaming && <StreamingArtifactCard streaming={streaming} />}
            {hasArtifacts && groups.length === 0 && (
              <p className="px-2.5 py-6 text-center text-xs text-subtle">No artifacts match “{query.trim()}”.</p>
            )}
            {groups.map(({ type, items }) => (
              <ArtifactGroup
                key={type}
                type={type}
                items={items}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    </Panel>
  )
}
