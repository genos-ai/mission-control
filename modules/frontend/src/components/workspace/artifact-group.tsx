/**
 * ArtifactGroup — one collapsible type group in the artifact list.
 */

import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Code,
  Database,
  File,
  FileText,
  MessageSquare,
  Package,
  Search,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'
import { agentShortName } from '@/lib/format'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'

const TYPE_META: Record<string, { icon: LucideIcon; label: string }> = {
  report:   { icon: FileText,      label: 'Reports' },
  finding:  { icon: Search,        label: 'Findings' },
  response: { icon: MessageSquare, label: 'Responses' },
  code:     { icon: Code,          label: 'Code' },
  data:     { icon: Database,      label: 'Data' },
  file:     { icon: File,          label: 'Files' },
}

// Stable display order for groups
export const TYPE_ORDER = Object.keys(TYPE_META)

export function ArtifactGroup({
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
  const Chevron = open ? ChevronDown : ChevronRight

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-2xs text-subtle transition-colors hover:text-foreground"
      >
        <Chevron className="h-3 w-3" />
        <Icon className="h-3 w-3" />
        <span>{meta.label}</span>
        <span className="ml-auto font-mono">{items.length}</span>
      </button>

      {open && (
        <div className="flex flex-col gap-0.5">
          {items.map((a) => (
            <button
              type="button"
              key={a.id}
              onClick={() => onSelect(a.id)}
              aria-current={a.id === selectedId || undefined}
              className={cn(
                'flex w-full flex-col gap-0.5 rounded-[9px] px-2.5 py-2 text-left transition-colors',
                a.id === selectedId ? 'bg-sidebar-active' : 'hover:bg-raised',
              )}
            >
              <span className="truncate text-sm text-foreground">{a.title}</span>
              <span className="truncate text-2xs text-subtle">
                {agentShortName(a.agent_id)} · {formatUtc(a.created_at)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
