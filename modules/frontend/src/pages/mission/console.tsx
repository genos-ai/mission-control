import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  Zap,
  Pause,
  Play,
  Trash2,
  Radio,
  AlertCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { useConsoleHistory } from '@/hooks/use-console'
import { useMissionStream } from '@/hooks/use-sse'
import { useTeam } from '@/hooks/use-team'
import type { MissionTeamMember } from '@/types'
import {
  useConsoleStore,
  selectFilteredEvents,
  type ConsoleEvent,
} from '@/stores/console'
import { EVENT_ICONS, eventLabel, eventDetail } from '@/lib/event-utils'

export default function ConsolePage() {
  const { id: missionId } = useParams<{ id: string }>()

  // Fetch history on mount
  const { data: history, isLoading: historyLoading } =
    useConsoleHistory(missionId)

  // SSE stream
  const { events: sseEvents, connected } = useMissionStream(missionId ?? null)

  // Team for agent filter dropdown
  const { data: teamMembers } = useTeam(missionId)

  // Store actions
  const addEvents = useConsoleStore((s) => s.addEvents)
  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)
  const reset = useConsoleStore((s) => s.reset)

  // Load history into store
  const historyLoaded = useRef(false)
  useEffect(() => {
    if (history && !historyLoaded.current) {
      historyLoaded.current = true
      addEvents(history)
    }
  }, [history, addEvents])

  // Sync SSE connected state
  useEffect(() => {
    setConnected(connected)
  }, [connected, setConnected])

  // Forward SSE events to store
  const processedCount = useRef(0)
  useEffect(() => {
    if (sseEvents.length > processedCount.current) {
      const newEvents = sseEvents.slice(processedCount.current)
      processedCount.current = sseEvents.length
      newEvents.forEach((ev) => {
        addEvent({
          event_id: String((ev.data as Record<string, unknown>).event_id ?? crypto.randomUUID()),
          event_type: ev.event_type,
          category: categorize(ev.event_type),
          timestamp: String((ev.data as Record<string, unknown>).timestamp ?? new Date().toISOString()),
          source: String((ev.data as Record<string, unknown>).agent_id ?? (ev.data as Record<string, unknown>).source ?? ''),
          data: ev.data,
        })
      })
    }
  }, [sseEvents.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup on unmount
  useEffect(() => reset, [reset])

  if (historyLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* Filter bar */}
      <FilterBar missionId={missionId} teamMembers={teamMembers} />

      {/* Three-column layout */}
      <div className="flex flex-1 overflow-hidden">
        <ConsolePanel category="execution" title="Execution Events" />
        <ConsolePanel category="chat" title="Chat Messages" />
        <ConsolePanel category="system" title="System Logs" />
      </div>

      {/* Status footer */}
      <StatusFooter />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

function FilterBar({
  teamMembers,
}: {
  missionId: string | undefined
  teamMembers: MissionTeamMember[] | undefined
}) {
  const agentFilter = useConsoleStore((s) => s.agentFilter)
  const typeFilter = useConsoleStore((s) => s.typeFilter)
  const errorsOnly = useConsoleStore((s) => s.errorsOnly)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const setAgentFilter = useConsoleStore((s) => s.setAgentFilter)
  const setTypeFilter = useConsoleStore((s) => s.setTypeFilter)
  const setErrorsOnly = useConsoleStore((s) => s.setErrorsOnly)
  const toggleAutoScroll = useConsoleStore((s) => s.toggleAutoScroll)
  const clear = useConsoleStore((s) => s.clear)

  const eventTypes = useConsoleStore((s) => {
    const types = new Set(s.events.map((e) => e.event_type))
    return Array.from(types).sort()
  })

  return (
    <div className="flex items-center gap-2 border-b px-4 py-2">
      {/* Agent filter */}
      <select
        value={agentFilter ?? ''}
        onChange={(e) => setAgentFilter(e.target.value || null)}
        className="h-8 rounded-md border bg-background px-2 text-xs"
      >
        <option value="">All Agents</option>
        {teamMembers?.map((m) => (
          <option key={m.agent_catalog_id} value={m.agent_catalog_id}>
            {m.agent?.agent_name ?? m.agent_catalog_id}
          </option>
        ))}
      </select>

      {/* Type filter */}
      <select
        value={typeFilter ?? ''}
        onChange={(e) => setTypeFilter(e.target.value || null)}
        className="h-8 rounded-md border bg-background px-2 text-xs"
      >
        <option value="">All Types</option>
        {eventTypes.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      {/* Errors only */}
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
        <input
          type="checkbox"
          checked={errorsOnly}
          onChange={(e) => setErrorsOnly(e.target.checked)}
          className="h-3.5 w-3.5 rounded border"
        />
        <AlertCircle className="h-3 w-3" />
        Errors only
      </label>

      <div className="flex-1" />

      {/* Clear */}
      <Button variant="ghost" size="sm" onClick={clear} className="h-7 text-xs">
        <Trash2 className="mr-1 h-3 w-3" />
        Clear
      </Button>

      {/* Auto-scroll toggle */}
      <Button
        variant={autoScroll ? 'secondary' : 'ghost'}
        size="sm"
        onClick={toggleAutoScroll}
        className="h-7 text-xs"
      >
        {autoScroll ? (
          <Pause className="mr-1 h-3 w-3" />
        ) : (
          <Play className="mr-1 h-3 w-3" />
        )}
        Auto
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Console panel (one per category)
// ---------------------------------------------------------------------------

function ConsolePanel({
  category,
  title,
}: {
  category: 'execution' | 'chat' | 'system'
  title: string
}) {
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const filtered = useConsoleStore((s) => selectFilteredEvents(s, category))
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) {
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [filtered.length, autoScroll])

  return (
    <div className="flex flex-1 flex-col border-r last:border-r-0">
      {/* Column header */}
      <div className="border-b bg-muted/30 px-3 py-1.5">
        <h4 className="text-xs font-semibold text-muted-foreground">
          {title}
          <Badge variant="secondary" className="ml-2 text-[10px]">
            {filtered.length}
          </Badge>
        </h4>
      </div>

      {/* Event list */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-muted/10 px-2 py-1 font-mono text-xs"
      >
        {filtered.length === 0 && (
          <p className="py-4 text-center text-muted-foreground/60">
            No events
          </p>
        )}
        <div className="space-y-px">
          {filtered.map((ev) => (
            <ConsoleEventRow key={ev.event_id} event={ev} />
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single event row
// ---------------------------------------------------------------------------

function ConsoleEventRow({ event }: { event: ConsoleEvent }) {
  const isError =
    event.data.error === true ||
    event.event_type.includes('failed') ||
    event.event_type.includes('error')

  const ts = formatTime(event.timestamp)
  const detail = eventDetail(event.event_type, event.data)

  return (
    <div
      className={`flex items-start gap-1.5 rounded px-1.5 py-0.5 ${
        isError
          ? 'bg-destructive/10 text-destructive'
          : 'text-muted-foreground hover:bg-muted/40'
      }`}
    >
      <span className="shrink-0 text-[10px] tabular-nums opacity-60">
        {ts}
      </span>
      <span className="mt-0.5 shrink-0">
        {EVENT_ICONS[event.event_type] ?? (
          <Zap className="h-3 w-3 text-gray-400" />
        )}
      </span>
      <span className="font-medium text-foreground">
        {eventLabel(event.event_type)}
      </span>
      {detail && (
        <span className="truncate opacity-70">{detail}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status footer
// ---------------------------------------------------------------------------

function StatusFooter() {
  const connected = useConsoleStore((s) => s.connected)
  const eventCount = useConsoleStore((s) => s.events.length)

  return (
    <div className="flex items-center gap-4 border-t bg-muted/20 px-4 py-1.5 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        {connected ? (
          <>
            <Radio className="h-3 w-3 animate-pulse text-emerald-500" />
            Connected
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-muted-foreground/40" />
            Disconnected
          </>
        )}
      </span>
      <span>{eventCount} events</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function categorize(eventType: string): 'execution' | 'chat' | 'system' {
  if (
    eventType.startsWith('plan.') ||
    eventType.startsWith('agent.tool') ||
    eventType.startsWith('agent.thinking') ||
    eventType.startsWith('agent.response')
  ) {
    return 'execution'
  }
  if (
    eventType.startsWith('chat.') ||
    eventType.startsWith('agent.approval')
  ) {
    return 'chat'
  }
  return 'system'
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}
