import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  Zap,
  Pause,
  Play,
  Trash2,
  Radio,
  AlertCircle,
  User,
  Bot,
  MessageSquare,
  DollarSign,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { useConsoleHistory } from '@/hooks/use-console'
import { useMissionStream } from '@/hooks/use-sse'
import { useTeam } from '@/hooks/use-team'
import {
  useConsoleStore,
  selectFilteredEvents,
  type ConsoleEvent,
} from '@/stores/console'
import { EVENT_ICONS, eventLabel, eventDetail } from '@/lib/event-utils'

type CategoryTab = 'all' | 'execution' | 'chat' | 'system'

const CATEGORY_TABS: { value: CategoryTab; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'execution', label: 'Execution' },
  { value: 'chat', label: 'Chat' },
  { value: 'system', label: 'System' },
]

export default function ConsolePage() {
  const { id: missionId } = useParams<{ id: string }>()

  const { data: history, isLoading: historyLoading } =
    useConsoleHistory(missionId)
  const { events: sseEvents, connected } = useMissionStream(missionId ?? null)
  const { data: teamMembers } = useTeam(missionId)

  const addEvents = useConsoleStore((s) => s.addEvents)
  const addEvent = useConsoleStore((s) => s.addEvent)
  const setConnected = useConsoleStore((s) => s.setConnected)

  // Load history into store (only if store is empty — survives tab switches)
  const existingCount = useConsoleStore((s) => s.events.length)
  const historyLoaded = useRef(false)
  useEffect(() => {
    if (history && !historyLoaded.current && existingCount === 0) {
      historyLoaded.current = true
      addEvents(history)
    }
  }, [history, addEvents, existingCount])

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
        const d = ev.data as Record<string, unknown>
        addEvent({
          event_id: String(d.event_id ?? crypto.randomUUID()),
          event_type: ev.event_type,
          category: (d.category as ConsoleEvent['category']) ?? categorize(ev.event_type),
          timestamp: String(d.timestamp ?? new Date().toISOString()),
          source: String(d.agent_id ?? d.source ?? ''),
          data: d,
        })
      })
    }
  }, [sseEvents.length]) // eslint-disable-line react-hooks/exhaustive-deps

  if (historyLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <FilterBar teamMembers={teamMembers} />
      <Timeline />
      <StatusFooter />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter bar with category tabs
// ---------------------------------------------------------------------------

function FilterBar({
  teamMembers,
}: {
  teamMembers?: { agent_catalog_id: string; agent?: { agent_name: string } | null }[]
}) {
  const categoryTab = useConsoleStore((s) => s.categoryTab)
  const agentFilter = useConsoleStore((s) => s.agentFilter)
  const errorsOnly = useConsoleStore((s) => s.errorsOnly)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const setCategoryTab = useConsoleStore((s) => s.setCategoryTab)
  const setAgentFilter = useConsoleStore((s) => s.setAgentFilter)
  const setErrorsOnly = useConsoleStore((s) => s.setErrorsOnly)
  const toggleAutoScroll = useConsoleStore((s) => s.toggleAutoScroll)
  const clear = useConsoleStore((s) => s.clear)

  return (
    <div className="flex items-center gap-2 border-b px-4 py-2">
      {/* Category tabs */}
      <div className="flex items-center gap-0.5 rounded-md bg-muted/50 p-0.5">
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setCategoryTab(tab.value)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              categoryTab === tab.value
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mx-1 h-4 w-px bg-border" />

      {/* Agent filter */}
      <select
        value={agentFilter ?? ''}
        onChange={(e) => setAgentFilter(e.target.value || null)}
        className="h-7 rounded-md border bg-background px-2 text-xs"
      >
        <option value="">All Agents</option>
        {teamMembers?.map((m) => (
          <option key={m.agent_catalog_id} value={m.agent?.agent_name ?? m.agent_catalog_id}>
            {m.agent?.agent_name ?? m.agent_catalog_id}
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
        Errors
      </label>

      <div className="flex-1" />

      <Button variant="ghost" size="sm" onClick={clear} className="h-7 text-xs">
        <Trash2 className="mr-1 h-3 w-3" />
        Clear
      </Button>

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
// Unified timeline
// ---------------------------------------------------------------------------

function Timeline() {
  const categoryTab = useConsoleStore((s) => s.categoryTab)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const filtered = useConsoleStore((s) =>
    categoryTab === 'all'
      ? selectFilteredEvents(s, null)
      : selectFilteredEvents(s, categoryTab),
  )
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll) {
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [filtered.length, autoScroll])

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto bg-zinc-950/50 px-2 py-1">
      {filtered.length === 0 && (
        <p className="py-12 text-center text-sm text-muted-foreground/60">
          No events yet
        </p>
      )}
      <div className="space-y-px">
        {filtered.map((ev) => (
          <EventRow key={ev.event_id} event={ev} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Event row — renders differently based on category/type
// ---------------------------------------------------------------------------

function EventRow({ event }: { event: ConsoleEvent }) {
  const isError =
    event.data.error === true ||
    event.event_type.includes('failed') ||
    event.event_type.includes('error')

  // Chat messages get a richer layout
  if (event.category === 'chat' || event.event_type.startsWith('user.message') || event.event_type.startsWith('assistant.message')) {
    return <ChatEventRow event={event} isError={isError} />
  }

  // Execution records get a summary layout
  if (event.event_type === 'execution.record') {
    return <ExecutionRecordRow event={event} />
  }

  // Task results show output data
  if (event.event_type.startsWith('task.') && !event.event_type.includes('attempt')) {
    return <TaskResultRow event={event} isError={isError} />
  }

  // Default: compact log row
  return <LogRow event={event} isError={isError} />
}

function ChatEventRow({ event, isError }: { event: ConsoleEvent; isError: boolean }) {
  const d = event.data
  const role = String(d.role ?? '')
  const content = String(d.content ?? '')
  const isUser = role === 'user'
  const model = d.model ? String(d.model) : null
  const cost = d.cost_usd != null ? Number(d.cost_usd) : null
  const ts = formatTime(event.timestamp)

  return (
    <div className={`flex items-start gap-2 rounded px-2 py-1.5 ${
      isError ? 'bg-destructive/10' : 'hover:bg-muted/20'
    }`}>
      <span className="mt-0.5 shrink-0">
        {isUser ? (
          <User className="h-3.5 w-3.5 text-blue-400" />
        ) : (
          <Bot className="h-3.5 w-3.5 text-emerald-400" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">
            {isUser ? 'User' : event.source || 'Assistant'}
          </span>
          <span className="text-[10px] tabular-nums text-muted-foreground/60">{ts}</span>
          {model && (
            <Badge variant="outline" className="text-[9px] h-4">{model.split(':').pop()?.split('-').slice(0, 2).join('-')}</Badge>
          )}
          {cost != null && cost > 0 && (
            <span className="flex items-center text-[10px] text-muted-foreground">
              <DollarSign className="h-2.5 w-2.5" />
              {cost.toFixed(4)}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-foreground/90 whitespace-pre-wrap break-words">
          {content.length > 500 ? content.slice(0, 500) + '…' : content}
        </p>
      </div>
      <Badge
        variant="outline"
        className="shrink-0 text-[9px] h-4"
      >
        <MessageSquare className="mr-0.5 h-2 w-2" />
        chat
      </Badge>
    </div>
  )
}

function ExecutionRecordRow({ event }: { event: ConsoleEvent }) {
  const d = event.data
  const status = String(d.status ?? '')
  const objective = String(d.objective_statement ?? '').slice(0, 120)
  const cost = d.total_cost_usd != null ? Number(d.total_cost_usd) : null
  const ts = formatTime(event.timestamp)
  const isFailed = status === 'failed' || status === 'cancelled' || status === 'timed_out'

  return (
    <div className={`flex items-start gap-2 rounded px-2 py-1.5 ${
      isFailed ? 'bg-destructive/10' : 'hover:bg-muted/20'
    }`}>
      <span className="mt-0.5 shrink-0">
        {EVENT_ICONS[event.event_type] ?? <Zap className="h-3 w-3 text-gray-400" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">Run</span>
          <Badge
            variant={isFailed ? 'destructive' : 'success'}
            className="text-[9px] h-4"
          >
            {status}
          </Badge>
          {cost != null && (
            <span className="flex items-center text-[10px] text-muted-foreground">
              <DollarSign className="h-2.5 w-2.5" />
              {cost.toFixed(4)}
            </span>
          )}
          <span className="text-[10px] tabular-nums text-muted-foreground/60">{ts}</span>
        </div>
        {objective && (
          <p className="mt-0.5 text-xs text-muted-foreground">{objective}</p>
        )}
      </div>
    </div>
  )
}

function TaskResultRow({ event, isError }: { event: ConsoleEvent; isError: boolean }) {
  const d = event.data
  const agent = String(d.agent_name ?? '')
  const taskId = String(d.task_id ?? '')
  const status = String(d.status ?? '')
  const cost = d.cost_usd != null ? Number(d.cost_usd) : null
  const duration = d.duration_seconds != null ? Number(d.duration_seconds) : null
  const attempts = d.attempt_count ? Number(d.attempt_count) : null
  const output = d.output_data as Record<string, unknown> | null
  const verification = d.verification_outcome as Record<string, unknown> | null
  const ts = formatTime(event.timestamp)

  // Extract meaningful content from output_data
  const outputSummary = output ? formatOutput(output) : null

  return (
    <div className={`rounded px-2 py-1.5 ${
      isError ? 'bg-destructive/10' : 'hover:bg-muted/20'
    }`}>
      <div className="flex items-center gap-2">
        <span className="shrink-0">
          {EVENT_ICONS[event.event_type] ?? <Zap className="h-3 w-3 text-gray-400" />}
        </span>
        <span className="text-xs font-medium text-foreground">{agent}</span>
        <Badge variant="outline" className="text-[9px] h-4">{taskId}</Badge>
        <Badge
          variant={isError ? 'destructive' : 'success'}
          className="text-[9px] h-4"
        >
          {status}
        </Badge>
        {cost != null && (
          <span className="flex items-center text-[10px] text-muted-foreground">
            <DollarSign className="h-2.5 w-2.5" />{cost.toFixed(4)}
          </span>
        )}
        {duration != null && (
          <span className="text-[10px] text-muted-foreground">{duration.toFixed(1)}s</span>
        )}
        {attempts != null && attempts > 1 && (
          <span className="text-[10px] text-muted-foreground">{attempts} attempts</span>
        )}
        <span className="text-[10px] tabular-nums text-muted-foreground/60">{ts}</span>
      </div>

      {/* Verification errors */}
      {verification && (verification as { errors?: string[] }).errors?.length ? (
        <div className="mt-1 ml-5 space-y-0.5">
          {((verification as { errors?: string[] }).errors ?? []).map((err, i) => (
            <p key={i} className="text-xs text-destructive">{err}</p>
          ))}
        </div>
      ) : null}

      {/* Output data summary */}
      {outputSummary && (
        <div className="mt-1 ml-5 text-xs text-muted-foreground whitespace-pre-wrap break-words">
          {outputSummary}
        </div>
      )}
    </div>
  )
}

/** Format output_data into a readable summary */
function formatOutput(output: Record<string, unknown>): string | null {
  // Skip _meta field
  const keys = Object.keys(output).filter((k) => k !== '_meta')
  if (keys.length === 0) return null

  // If there's a 'result' string, show it directly
  if (typeof output.result === 'string') {
    const text = output.result
    return text.length > 500 ? text.slice(0, 500) + '…' : text
  }

  // If there's a 'summary' string, show it
  if (typeof output.summary === 'string') {
    const text = output.summary
    return text.length > 500 ? text.slice(0, 500) + '…' : text
  }

  // Otherwise show a compact JSON preview of the interesting keys
  const preview: Record<string, unknown> = {}
  for (const k of keys.slice(0, 5)) {
    const v = output[k]
    if (typeof v === 'string' && v.length > 200) {
      preview[k] = v.slice(0, 200) + '…'
    } else {
      preview[k] = v
    }
  }
  try {
    return JSON.stringify(preview, null, 2)
  } catch {
    return null
  }
}

function LogRow({ event, isError }: { event: ConsoleEvent; isError: boolean }) {
  const ts = formatTime(event.timestamp)
  const detail = eventDetail(event.event_type, event.data)
  const categoryColor = event.category === 'execution'
    ? 'text-blue-400'
    : event.category === 'system'
      ? 'text-amber-400'
      : 'text-muted-foreground'

  return (
    <div className={`flex items-start gap-2 rounded px-2 py-0.5 font-mono text-xs ${
      isError
        ? 'bg-destructive/10 text-destructive'
        : 'text-muted-foreground hover:bg-muted/20'
    }`}>
      <span className="shrink-0 text-[10px] tabular-nums opacity-60 mt-0.5">
        {ts}
      </span>
      <span className="mt-0.5 shrink-0">
        {EVENT_ICONS[event.event_type] ?? (
          <Zap className="h-3 w-3 text-gray-400" />
        )}
      </span>
      <span className={`shrink-0 font-medium ${isError ? '' : categoryColor}`}>
        {eventLabel(event.event_type)}
      </span>
      {event.source && (
        <span className="shrink-0 text-foreground/60">{event.source}</span>
      )}
      {detail && (
        <span className="min-w-0 break-words opacity-70">{detail}</span>
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
  const categoryTab = useConsoleStore((s) => s.categoryTab)
  const filteredCount = useConsoleStore((s) =>
    categoryTab === 'all'
      ? selectFilteredEvents(s, null).length
      : selectFilteredEvents(s, categoryTab).length,
  )

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
      <span>
        {filteredCount === eventCount
          ? `${eventCount} events`
          : `${filteredCount} / ${eventCount} events`}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function categorize(eventType: string): 'execution' | 'chat' | 'system' {
  if (
    eventType.startsWith('plan.') ||
    eventType.startsWith('agent.') ||
    eventType.startsWith('task.') ||
    eventType.startsWith('execution.') ||
    eventType.startsWith('decision.') ||
    eventType.startsWith('session.cost')
  ) {
    return 'execution'
  }
  if (
    eventType.startsWith('user.message') ||
    eventType.startsWith('assistant.message')
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
