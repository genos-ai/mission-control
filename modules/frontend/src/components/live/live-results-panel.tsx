/**
 * LiveResultsPanel — a run's results as they arrive: one block per finished
 * task, any errors, and the approval prompt when a gate is waiting.
 */

import { Panel } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { GateApproval } from '@/components/mission/gate-approval'
import { StatusIcon } from '@/components/ui/status-icon'
import { cn } from '@/lib/cn'
import { agentShortName, fmtCost } from '@/lib/format'
import { styleFor, taskTone } from '@/lib/status-tone'
import { TONE_BOX } from '@/lib/tone-class'
import { useLiveRunStore } from '@/stores/live-run'

export function LiveResultsPanel() {
  const phase = useLiveRunStore((s) => s.phase)
  const errors = useLiveRunStore((s) => s.errors)
  const taskResults = useLiveRunStore((s) => s.taskResults)
  const pendingApproval = useLiveRunStore((s) => s.pendingApproval)
  const clearApproval = () => useLiveRunStore.setState({ pendingApproval: null })
  const writing = phase !== 'done'

  return (
    <Panel className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[720px] flex-col gap-5 px-8 pb-12 pt-7">
        <div className="flex items-center justify-between">
          <p className="text-xs text-subtle">Results</p>
          {writing && (
            <span className="flex items-center gap-1.5 text-xs text-warning">
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-dot motion-reduce:animate-none" />
              writing
            </span>
          )}
        </div>

        {errors.length > 0 && (
          <div className={cn('flex flex-col gap-1.5 rounded-card border p-3', TONE_BOX.danger)}>
            {errors.map((err, i) => (
              <p key={i} className="text-sm text-danger [overflow-wrap:anywhere]">
                {err}
              </p>
            ))}
          </div>
        )}

        {pendingApproval && (
          <GateApproval
            executionId={pendingApproval.executionId}
            gateMessage={pendingApproval.message}
            onResolved={clearApproval}
          />
        )}

        {taskResults.map((r, i) => {
          // The stream reports a finished step as completed, failed or skipped.
          const style = styleFor(taskTone, r.status === 'success' ? 'completed' : r.status, 'task result')
          return (
            <div key={i} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <StatusIcon {...style} />
                <span className="text-base font-medium">{r.stepId}</span>
                {r.agent && <Badge>{agentShortName(r.agent)}</Badge>}
                <span className="ml-auto font-mono text-2xs text-subtle">
                  {fmtCost(r.costUsd)} · {r.durationSeconds.toFixed(1)}s
                </span>
              </div>
              {r.summary && (
                <p
                  className={cn(
                    'pl-5 text-sm leading-relaxed [overflow-wrap:anywhere]',
                    r.status === 'failed' ? 'text-danger' : 'text-text-2',
                  )}
                >
                  {r.summary}
                </p>
              )}
            </div>
          )
        })}

        {taskResults.length === 0 && !pendingApproval && errors.length === 0 && (
          <div className="flex flex-col gap-2.5">
            <p className="text-sm text-subtle">
              {writing
                ? 'Waiting for the first result…'
                : "No results were streamed to this page. The run's output and cost are in its row on the Runs tab."}
            </p>
            {writing && (
              <>
                <div className="h-3 w-[58%] rounded bg-raised" />
                <div className="h-3 w-[41%] rounded bg-raised" />
              </>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}
