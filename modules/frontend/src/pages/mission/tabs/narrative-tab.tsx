/**
 * NarrativeTab — console view showing ALL mission events.
 *
 * On mount, loads historical events from GET /missions/{id}/narrative
 * (execution records, task states, artifacts reconstructed from DB).
 * Then live SSE events arrive via the console store. Both are merged
 * and deduplicated by event_id.
 *
 * Uses a BLACKLIST approach: everything is shown unless the user
 * explicitly filters it out via toggle controls.
 */

import { useRef, useEffect, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertTriangle,
  Radio,
  Package,
  Brain,
  Zap,
  Activity,
  Play,
  ChevronDown,
  Filter,
  Info,
  AlertCircle,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { api } from '@/lib/api'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

// ---------------------------------------------------------------------------
// Filter persistence
// ---------------------------------------------------------------------------

const FILTER_STORAGE_KEY = 'mc:narrative-hidden-types'

function loadHiddenTypes(): Set<string> {
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set()
}

function saveHiddenTypes(hidden: Set<string>) {
  localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify([...hidden]))
}

// ---------------------------------------------------------------------------

export default function NarrativeTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [historical, setHistorical] = useState<ConsoleEvent[]>([])
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(loadHiddenTypes)
  const [showFilters, setShowFilters] = useState(false)
  const liveEvents = useConsoleStore((s) => s.events)
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load historical events from DB on mount
  useEffect(() => {
    if (!missionId) return
    api.get<{ events: ConsoleEvent[]; count: number }>(`/missions/${missionId}/narrative`)
      .then((data) => setHistorical(data.events))
      .catch(() => {})
  }, [missionId])

  // Merge historical + live, deduplicate by event_id
  const seen = new Set<string>()
  const allEvents: ConsoleEvent[] = []
  for (const ev of [...historical, ...liveEvents]) {
    if (!seen.has(ev.event_id)) {
      seen.add(ev.event_id)
      allEvents.push(ev)
    }
  }

  // Apply blacklist filter
  const events = allEvents.filter((e) => !hiddenTypes.has(e.event_type))

  // Collect unique event types for filter UI
  const eventTypes = [...new Set(allEvents.map((e) => e.event_type))].sort()

  const toggleType = useCallback((type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      saveHiddenTypes(next)
      return next
    })
  }, [])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events.length, autoScroll])

  return (
    <div className="flex h-full flex-col">
      {/* Filter bar */}
      <div className="flex items-center gap-2 border-b border-border/40 px-4 py-1.5">
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={cn(
            'flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors',
            showFilters ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Filter className="h-3 w-3" />
          Filters
          {hiddenTypes.size > 0 && (
            <Badge variant="secondary" className="ml-1 h-4 px-1 text-[9px]">
              {hiddenTypes.size} hidden
            </Badge>
          )}
        </button>
        <span className="ml-auto text-[10px] text-muted-foreground/50">
          {events.length} event{events.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Filter panel */}
      {showFilters && eventTypes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-border/40 px-4 py-2">
          {eventTypes.map((type) => (
            <button
              key={type}
              onClick={() => toggleType(type)}
              className={cn(
                'rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors',
                hiddenTypes.has(type)
                  ? 'bg-muted/50 text-muted-foreground/40 line-through'
                  : 'bg-accent text-accent-foreground',
              )}
            >
              {type}
            </button>
          ))}
        </div>
      )}

      {/* Event list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3">
        {events.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <Radio className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground/60">
              {allEvents.length > 0
                ? 'All events are filtered out. Adjust filters above.'
                : 'Events will appear here during a run.'}
            </p>
          </div>
        )}
        <div className="space-y-2">
          {events.map((ev) => (
            <NarrativeEventRow key={ev.event_id} event={ev} />
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Level-based styling utilities
// ---------------------------------------------------------------------------

function getLevelFromEvent(event: ConsoleEvent): string {
  return String((event.data as Record<string, unknown>).level ?? 'info')
}

function levelStyles(level: string) {
  switch (level) {
    case 'error':
      return 'border-l-red-500/60 bg-red-500/5 text-red-300'
    case 'warning':
      return 'border-l-amber-500/60 bg-amber-500/5 text-amber-300'
    default:
      return 'border-l-slate-500/30 bg-muted/20 text-muted-foreground'
  }
}

function LevelIcon({ level }: { level: string }) {
  switch (level) {
    case 'error':
      return <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
    case 'warning':
      return <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
    default:
      return <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
  }
}

// ---------------------------------------------------------------------------

function NarrativeEventRow({ event }: { event: ConsoleEvent }) {
  const d = event.data as Record<string, unknown>
  const ts = formatTime(event.timestamp)

  if (event.event_type === 'mission.narrative') {
    const narrative = String(d.narrative ?? '')
    const level = String(d.level ?? 'info')
    const accent =
      level === 'success' ? 'border-l-emerald-500/60 bg-emerald-500/5' :
      level === 'warning'  ? 'border-l-amber-500/60 bg-amber-500/5' :
      level === 'error'    ? 'border-l-red-500/60 bg-red-500/5' :
      'border-l-sky-500/40 bg-sky-500/5'
    return (
      <div className={cn('flex items-start gap-2.5 rounded border-l-2 px-3 py-2', accent)}>
        <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-400" />
        <div className="min-w-0 flex-1">
          <MarkdownRenderer content={narrative} className="text-sm" />
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'mission.artifact.found') {
    const title = String(d.title ?? 'Artifact')
    const content = String(d.content ?? '')
    const artifactType = String(d.artifact_type ?? 'report')
    return (
      <details className="group rounded border border-violet-500/20 bg-violet-500/5 px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center gap-2">
          <Package className="h-3.5 w-3.5 shrink-0 text-violet-400" />
          <span className="flex-1 text-sm font-medium">{title}</span>
          <Badge variant="outline" className="h-4 text-[9px]">{artifactType}</Badge>
          <span className="text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-2 border-t border-violet-500/20 pt-2">
          <MarkdownRenderer content={content} className="text-sm" />
        </div>
      </details>
    )
  }

  if (event.event_type === 'agent.thinking.started') {
    const agent = String(d.agent_id ?? event.source ?? '')
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground/70">
        <Brain className="h-3 w-3 text-purple-400" />
        <span>{shortName(agent)} is thinking…</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'agent.tool.called') {
    const agent = String(d.agent_id ?? event.source ?? '')
    const tool = String(d.tool_name ?? '')
    return (
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground/70">
        <Zap className="h-3 w-3 text-amber-400" />
        <span>{shortName(agent)}</span>
        <span className="text-muted-foreground/40">→</span>
        <span className="font-medium text-amber-400/90">{tool}</span>
        <span className="ml-auto text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'agent.tool.returned') {
    const tool = String(d.tool_name ?? '')
    const status = String(d.status ?? 'success')
    const result = String(d.result ?? '')
    if (status !== 'error') return null
    return (
      <div className="flex items-start gap-2 rounded border border-destructive/20 bg-destructive/5 px-3 py-1.5 text-xs">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-destructive">{tool} failed</span>
          <p className="mt-0.5 truncate text-muted-foreground">{result}</p>
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.started') {
    const stepName = String(d.step_name ?? d.step_id ?? '')
    return (
      <div className="flex items-center gap-2 rounded bg-blue-500/5 px-3 py-1.5 text-xs">
        <Activity className="h-3.5 w-3.5 shrink-0 text-blue-400" />
        <span className="font-medium">Starting</span>
        <span className="text-muted-foreground">{stepName}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'plan.step.completed') {
    const status = String(d.status ?? 'success')
    const ok = status === 'success'
    return (
      <div className={cn(
        'flex items-center gap-2 rounded px-3 py-1.5 text-xs',
        ok ? 'bg-emerald-500/5' : 'bg-destructive/5',
      )}>
        <Activity className={cn('h-3.5 w-3.5 shrink-0', ok ? 'text-emerald-400' : 'text-destructive')} />
        <span className="font-medium">{ok ? 'Completed' : 'Failed'}</span>
        <span className="text-muted-foreground">{String(d.step_id ?? '')}</span>
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'system.execution.created') {
    const obj = String(d.objective ?? '').slice(0, 80)
    return (
      <div className="flex items-center gap-2 rounded bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        <Play className="h-3 w-3 shrink-0 text-blue-400" />
        <span className="font-medium">Run started</span>
        {obj && <span className="truncate">{obj}</span>}
        <span className="ml-auto shrink-0 text-[10px] tabular-nums">{ts}</span>
      </div>
    )
  }

  if (event.event_type === 'system.execution.completed') {
    const status = String(d.status ?? '')
    const cost = d.total_cost_usd != null ? `$${Number(d.total_cost_usd).toFixed(4)}` : ''
    const dur = d.duration_seconds != null ? `${Number(d.duration_seconds).toFixed(1)}s` : ''
    const ok = status === 'completed'
    return (
      <div className={cn(
        'flex items-center gap-2 rounded px-3 py-1.5 text-xs',
        ok ? 'bg-emerald-500/5 text-emerald-300' : 'bg-destructive/5 text-destructive',
      )}>
        <Activity className="h-3 w-3 shrink-0" />
        <span className="font-medium">Run {status}</span>
        {cost && <span>{cost}</span>}
        {dur && <span>{dur}</span>}
        <span className="ml-auto text-[10px] tabular-nums opacity-60">{ts}</span>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // CATCH-ALL: render any unrecognized event type with level-based styling
  // ---------------------------------------------------------------------------
  const level = getLevelFromEvent(event)
  const message = String(d.message ?? d.narrative ?? d.detail ?? '')

  return (
    <div className={cn('flex items-start gap-2.5 rounded border-l-2 px-3 py-2', levelStyles(level))}>
      <LevelIcon level={level} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="h-4 shrink-0 text-[9px] font-mono">
            {event.event_type}
          </Badge>
          {event.source && (
            <span className="text-[10px] text-muted-foreground/50">{event.source}</span>
          )}
        </div>
        {message && (
          <p className="mt-1 text-sm">{message}</p>
        )}
        {!message && d && Object.keys(d).length > 0 && (
          <pre className="mt-1 max-h-24 overflow-auto text-[11px] text-muted-foreground/70">
            {JSON.stringify(d, null, 2)}
          </pre>
        )}
      </div>
      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/50">{ts}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------

function shortName(agentId: string): string {
  return agentId.endsWith('.agent') ? agentId.slice(0, -6) : agentId
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}
