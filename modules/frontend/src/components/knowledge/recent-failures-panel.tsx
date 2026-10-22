import { CollapsiblePanel } from '@/components/knowledge/collapsible-panel'
import { StatusIcon } from '@/components/ui/status-icon'
import { taskTone } from '@/lib/status-tone'

/** A failed task attempt, as the mission knowledge endpoint returns it. */
export interface RecentFailure {
  task_id: string
  agent_name: string
  failure_reason?: unknown
}

// Long provider errors are cut here so one failure cannot fill the panel.
const REASON_MAX_CHARS = 150

/** The latest failed attempts, so nobody repeats them. */
export function RecentFailuresPanel({ failures }: { failures: RecentFailure[] }) {
  return (
    <CollapsiblePanel title="Recent failures" meta={failures.length}>
      <div className="flex flex-col">
        {failures.map((f, i) => (
          <div key={`${f.task_id}:${i}`} className="flex items-start gap-3 rounded-card p-2.5">
            <StatusIcon {...taskTone.failed} className="mt-1" />
            <div className="min-w-0 flex-1">
              <p className="text-sm">{f.agent_name}</p>
              {typeof f.failure_reason === 'string' && (
                <p className="mt-0.5 line-clamp-2 break-words text-xs text-subtle">
                  {f.failure_reason.slice(0, REASON_MAX_CHARS)}
                </p>
              )}
              <p className="mt-0.5 truncate font-mono text-2xs text-subtle">{f.task_id}</p>
            </div>
          </div>
        ))}
      </div>
    </CollapsiblePanel>
  )
}
