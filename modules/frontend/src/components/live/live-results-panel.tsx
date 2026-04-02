import { CheckCircle, XCircle, MinusCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { GateApproval } from '@/components/mission/gate-approval'
import { useLiveRunStore } from '@/stores/live-run'

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  success: <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
  skipped: <MinusCircle className="h-3.5 w-3.5 text-amber-400" />,
}

function agentShortName(agent: string): string {
  if (!agent) return ''
  // "software.quality.agent" → "software.quality"
  return agent.endsWith('.agent')
    ? agent.slice(0, -6)
    : agent
}

export function LiveResultsPanel() {
  const errors = useLiveRunStore((s) => s.errors)
  const taskResults = useLiveRunStore((s) => s.taskResults)
  const pendingApproval = useLiveRunStore((s) => s.pendingApproval)
  const clearApproval = () =>
    useLiveRunStore.setState({ pendingApproval: null })

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b px-4 py-2">
        <h3 className="text-sm font-semibold text-muted-foreground">
          Results
        </h3>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
        {/* Errors section */}
        {errors.length > 0 && (
          <div className="space-y-1">
            {errors.map((err, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-xs"
              >
                <XCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0 mt-0.5" />
                <span className="font-medium text-destructive">{err}</span>
              </div>
            ))}
          </div>
        )}

        {/* Gate approval */}
        {pendingApproval && (
          <GateApproval
            executionId={pendingApproval.executionId}
            gateMessage={pendingApproval.message}
            onResolved={clearApproval}
          />
        )}

        {/* Task results */}
        {taskResults.length > 0 ? (
          <div className="space-y-2">
            {taskResults.map((r, i) => {
              const icon =
                STATUS_ICON[r.status] ?? (
                  <MinusCircle className="h-3.5 w-3.5 text-muted-foreground" />
                )

              return (
                <div key={i} className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    {icon}
                    <span className="text-xs font-semibold">{r.stepId}</span>
                    {r.agent && (
                      <Badge variant="secondary" className="text-[10px]">
                        {agentShortName(r.agent)}
                      </Badge>
                    )}
                  </div>
                  <div className="ml-5 text-[11px] text-muted-foreground">
                    {r.status === 'failed' && r.summary ? (
                      <span className="text-destructive">{r.summary}</span>
                    ) : (
                      <>
                        ${r.costUsd.toFixed(4)} &middot;{' '}
                        {r.durationSeconds.toFixed(1)}s
                        {r.summary && (
                          <span className="ml-1.5">&middot; {r.summary}</span>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          !pendingApproval &&
          errors.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No results yet...
            </p>
          )
        )}
      </div>
    </div>
  )
}
