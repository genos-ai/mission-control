import { NarrativeEvent } from '@/components/narrative/narrative-event'
import type { NarrativeGroup } from '@/components/narrative/narrative-groups'
import { Panel } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
import { fmtCost, statusLabel } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import { runTone, type Tone } from '@/lib/status-tone'
import type { RunStatus } from '@/types'

// Run-completed events report the dispatcher's own outcomes beside the run
// statuses, so a status is looked up in both rather than assumed to be one.
const DISPATCH_TONE: Record<string, Tone> = { success: 'success', partial: 'warning' }

function outcomeTone(status: string): Tone {
  if (Object.prototype.hasOwnProperty.call(DISPATCH_TONE, status)) return DISPATCH_TONE[status]
  if (Object.prototype.hasOwnProperty.call(runTone, status)) return runTone[status as RunStatus].tone
  return 'neutral'
}

function runTitle(group: NarrativeGroup): string {
  if (group.objective) return group.objective
  if (!group.key) return 'Events'
  return group.executionId ? 'Run' : 'Session'
}

/** One run or session: its header, then its events on a timeline. */
export function NarrativeRun({ group }: { group: NarrativeGroup }) {
  const meta = [
    (group.executionId || group.key).slice(0, 8),
    // Only a created event proves a start; the history window can cut a session's beginning off.
    group.startedAt ? `started ${formatUtc(group.startedAt)}` : `first event ${formatUtc(group.firstSeenAt)}`,
    group.durationSeconds !== null ? `${group.durationSeconds.toFixed(1)}s` : '',
    group.costUsd !== null ? fmtCost(group.costUsd) : '',
    `${group.events.length} event${group.events.length === 1 ? '' : 's'}`,
  ].filter(Boolean)

  return (
    <Panel className="px-5 py-[18px]">
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h2 className="truncate text-base font-medium">{runTitle(group)}</h2>
          <span className="font-mono text-2xs text-subtle">{meta.join(' · ')}</span>
        </div>
        {group.status && <StatusPill tone={outcomeTone(group.status)}>{statusLabel(group.status)}</StatusPill>}
      </div>
      <ul className="mt-4 flex flex-col">
        {group.events.map((event) => (
          <NarrativeEvent key={event.event_id} event={event} />
        ))}
      </ul>
    </Panel>
  )
}
