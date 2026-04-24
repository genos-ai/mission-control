/**
 * ArtifactListPanel — left panel listing artifacts grouped by type.
 *
 * Follows the RunsPanel pattern: fixed-width panel with a header bar,
 * grouped collapsible sections, and per-row click handler.
 * All groups are expanded by default.
 */

import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Code,
  Database,
  File,
  FileText,
  Loader2,
  Package,
  Search,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'
import { agentShortName } from '@/lib/format'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'
import { useWorkspaceStore } from '@/stores/workspace'
import { StreamingArtifactCard } from '@/components/workspace/streaming-artifact-card'

const TYPE_META: Record<string, { icon: typeof FileText; label: string }> = {
  report:  { icon: FileText, label: 'Reports' },
  finding: { icon: Search,   label: 'Findings' },
  code:    { icon: Code,     label: 'Code' },
  data:    { icon: Database,  label: 'Data' },
  file:    { icon: File,     label: 'Files' },
}

// Stable display order for groups
const TYPE_ORDER = ['report', 'finding', 'code', 'data', 'file']

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

  const groups = useMemo(() => {
    const map = new Map<string, MissionArtifact[]>()
    for (const a of artifacts) {
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
  }, [artifacts])

  return (
    <div className="flex w-[260px] shrink-0 flex-col border-r">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center border-b px-3">
        <span className="text-xs font-medium">Artifacts</span>
        {artifacts.length > 0 && (
          <span className="ml-1.5 text-[10px] text-muted-foreground/60">
            {artifacts.length}
          </span>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground/50" />
          </div>
        ) : !artifacts.length && !streaming ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 py-8">
            <Package className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs leading-relaxed text-muted-foreground/70">
              No artifacts yet.
            </p>
            <p className="max-w-[200px] text-center text-[11px] leading-relaxed text-muted-foreground/50">
              Artifacts appear when agents produce reports, findings, or code during a run.
            </p>
          </div>
        ) : (
          <div className="py-1">
            {streaming && (
              <div className="px-2 pb-1">
                <StreamingArtifactCard streaming={streaming} />
              </div>
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
    </div>
  )
}

function ArtifactGroup({
  type,
  items,
  selectedId,
  onSelect,
}: {
  type: string
  items: MissionArtifact[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(true)
  const meta = TYPE_META[type] ?? { icon: Package, label: type }
  const Icon = meta.icon

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <Icon className="h-3 w-3" />
        <span>{meta.label}</span>
        <span className="text-[10px] text-muted-foreground/50">{items.length}</span>
      </button>

      {open && (
        <div className="space-y-px px-1.5">
          {items.map((a) => {
            const agentShort = agentShortName(a.agent_id)
            const active = a.id === selectedId

            return (
              <button
                key={a.id}
                onClick={() => onSelect(a.id)}
                className={cn(
                  'flex w-full flex-col rounded px-2.5 py-1.5 text-left text-xs transition-colors',
                  active
                    ? 'bg-primary/10 text-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                <span className="truncate font-medium leading-snug">{a.title}</span>
                <span className="truncate text-[10px] text-muted-foreground/60">
                  {agentShort} · {formatUtc(a.created_at)}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
