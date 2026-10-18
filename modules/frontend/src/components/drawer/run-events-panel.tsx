import { useRunStream } from '@/hooks/use-sse'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'

export function RunEventsPanel() {
  const { context } = useDrawerStore()
  const sessionId = context.sessionId as string | undefined
  const { events, connected } = useRunStream(sessionId ?? null)

  if (!sessionId) {
    return <p className="text-sm text-muted-foreground">No session selected.</p>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {events.length} events
        </p>
        {connected && (
          <StatusPill tone="success" pulse>
            Live
          </StatusPill>
        )}
      </div>

      <div className="space-y-1">
        {events.map((ev, i) => (
          <div key={i} className="flex gap-2 text-xs">
            <Badge className="shrink-0">
              {ev.event_type.split('.').pop()}
            </Badge>
            <span className="text-muted-foreground truncate">
              {typeof ev.data === 'object'
                ? JSON.stringify(ev.data).slice(0, 100)
                : String(ev.data)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
