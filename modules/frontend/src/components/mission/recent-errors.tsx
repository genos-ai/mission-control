import { AlertTriangle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useExecution } from '@/hooks/use-executions'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { StatusIcon } from '@/components/ui/status-icon'
import { ROUTES } from '@/lib/constants'
import { formatUtc } from '@/lib/format-date'
import { taskTone } from '@/lib/status-tone'
import { TONE_BOX } from '@/lib/tone-class'

interface RecentErrorsProps {
  failedRunIds: string[]
  missionId: string
}

/** The task-level errors of up to three recent failed runs. */
export function RecentErrors({ failedRunIds, missionId }: RecentErrorsProps) {
  const navigate = useNavigate()
  // Fetch details for up to 3 recent failed runs
  const q0 = useExecution(failedRunIds[0])
  const q1 = useExecution(failedRunIds[1])
  const q2 = useExecution(failedRunIds[2])
  const details = [q0.data, q1.data, q2.data].filter(Boolean)

  // Extract all task-level errors across runs
  const errors: { runId: string; agent: string; error: string; when: string }[] = []
  for (const detail of details) {
    if (!detail) continue
    for (const task of detail.task_executions) {
      if (task.status !== 'failed') continue
      const output = task.output_data as Record<string, unknown> | null
      const msg =
        String(output?.error ?? output?.message ?? '') ||
        `${task.agent_name} failed`
      errors.push({
        runId: detail.id,
        agent: task.agent_name,
        error: msg,
        when: task.completed_at ?? task.started_at ?? detail.created_at,
      })
    }
  }

  if (errors.length === 0) return null

  return (
    <Panel className={TONE_BOX.danger}>
      <PanelHeader
        title={
          <span className="flex items-center gap-2 text-danger">
            <AlertTriangle className="h-4 w-4" />
            Recent errors
          </span>
        }
        meta={errors.length}
      />
      <PanelContent className="flex flex-col gap-1">
        {errors.slice(0, 5).map((err, i) => (
          <button
            key={i}
            onClick={() => navigate(ROUTES.MISSION_RUN_LIVE(missionId, err.runId))}
            className="flex w-full items-start gap-3 rounded-card px-3 py-2 text-left transition-colors hover:bg-danger/10"
          >
            <StatusIcon {...taskTone.failed} className="mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{err.agent}</span>
                <span className="text-2xs text-subtle">{formatUtc(err.when)}</span>
              </div>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">{err.error}</p>
            </div>
          </button>
        ))}
      </PanelContent>
    </Panel>
  )
}
