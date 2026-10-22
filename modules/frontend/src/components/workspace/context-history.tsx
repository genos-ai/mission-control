import { Archive, Minus, Plus, Repeat2, Scissors } from 'lucide-react'

import { IconTile } from '@/components/ui/icon-tile'
import { Panel, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import type { ContextChange } from '@/hooks/use-context'
import { agentShortName } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import { styleFor, type StatusStyle } from '@/lib/status-tone'

// The backend's ChangeType values (models/mission_context.py).
type ChangeType = 'add' | 'replace' | 'remove' | 'prune' | 'archive'

const CHANGE_STYLE: Record<ChangeType, StatusStyle> = {
  add: { tone: 'success', icon: Plus },
  replace: { tone: 'info', icon: Repeat2 },
  remove: { tone: 'danger', icon: Minus },
  prune: { tone: 'warning', icon: Scissors },
  archive: { tone: 'neutral', icon: Archive },
}

const CHANGE_VERB: Record<ChangeType, string> = {
  add: 'added',
  replace: 'replaced',
  remove: 'removed',
  prune: 'pruned',
  archive: 'archived',
}

function ChangeRow({ change }: { change: ContextChange }) {
  const { tone, icon } = styleFor(CHANGE_STYLE, change.change_type, 'context change')
  const verb = CHANGE_VERB[change.change_type as ChangeType]

  return (
    <li className="flex gap-2.5 rounded-chip p-2">
      <IconTile icon={icon} tone={tone} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm text-text-2">
          {change.agent_id ? (
            <>
              <span className="font-medium text-foreground">{agentShortName(change.agent_id)}</span> {verb}
            </>
          ) : (
            <span className="capitalize">{verb}</span>
          )}{' '}
          <code className="break-words font-mono text-xs text-muted-foreground">{change.path}</code>
        </p>
        {change.reason && <p className="mt-0.5 text-xs text-subtle">{change.reason}</p>}
        <p className="mt-0.5 font-mono text-2xs text-subtle">
          v{change.version} · {formatUtc(change.created_at)}
        </p>
      </div>
    </li>
  )
}

interface ChangeListProps {
  changes: ContextChange[]
  isLoading: boolean
}

/** The edits themselves, newest first, with their loading and empty states. */
export function ChangeList({ changes, isLoading }: ChangeListProps) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner className="h-4 w-4" />
      </div>
    )
  }
  if (changes.length === 0) return <p className="px-2 text-xs text-subtle">No changes recorded yet.</p>
  return (
    <ul className="flex flex-col gap-0.5">
      {changes.map((change) => (
        <ChangeRow key={change.id} change={change} />
      ))}
    </ul>
  )
}

/** Side panel of recent edits. Below 960px it would crowd the document, so the panel gives way to a section under it. */
export function ContextHistory({ changes, isLoading }: ChangeListProps) {
  return (
    <Panel className="hidden w-[300px] shrink-0 flex-col overflow-hidden min-[960px]:flex">
      <PanelHeader title="Change history" />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <ChangeList changes={changes} isLoading={isLoading} />
      </div>
    </Panel>
  )
}
