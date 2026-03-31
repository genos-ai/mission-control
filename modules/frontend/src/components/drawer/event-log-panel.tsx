import { useExecution } from '@/hooks/use-executions'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'

export function EventLogPanel() {
  const { context } = useDrawerStore()
  const executionId = context.executionId as string | undefined
  const { data: detail, isLoading } = useExecution(executionId)

  if (isLoading) return <Spinner />
  if (!detail) {
    return <p className="text-sm text-muted-foreground">No execution selected.</p>
  }

  // Build a chronological event list from task executions and decisions
  const events: { time: string; type: string; label: string; detail?: string }[] = []

  for (const task of detail.task_executions) {
    const time = task.completed_at ?? task.started_at ?? task.created_at
    if (time) {
      events.push({
        time,
        type: task.status === 'completed' ? 'success' : task.status === 'failed' ? 'error' : 'start',
        label: `${task.agent_name} ${task.status}`,
        detail: `${task.task_id} · $${task.cost_usd.toFixed(4)} · ${task.duration_seconds?.toFixed(1) ?? '?'}s`,
      })
    }
  }

  for (const d of detail.decisions) {
    events.push({
      time: d.created_at,
      type: 'decision',
      label: `MC: ${d.decision_type}`,
      detail: d.reasoning,
    })
  }

  events.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())

  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">No events recorded.</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {events.length} events
      </p>
      {events.map((ev, i) => (
        <div key={i} className="flex gap-3 text-sm">
          <span className="w-16 flex-shrink-0 text-[10px] text-muted-foreground">
            {new Date(ev.time).toLocaleTimeString()}
          </span>
          <div>
            <div className="flex items-center gap-1">
              <Badge
                variant={
                  ev.type === 'success'
                    ? 'success'
                    : ev.type === 'error'
                      ? 'destructive'
                      : 'secondary'
                }
                className="text-[10px]"
              >
                {ev.type}
              </Badge>
              <span>{ev.label}</span>
            </div>
            {ev.detail && (
              <p className="mt-0.5 text-xs text-muted-foreground">{ev.detail}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
