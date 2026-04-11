/**
 * NarrativeTab — curated human-readable mission event feed.
 *
 * Reads from the console store (populated by MissionLayout's SSE fan-out)
 * and filters to narrative-relevant event types. This is a different lens
 * from the Stream tab (raw firehose) — Narrative shows opinionated,
 * grouped summaries of what the agents are doing.
 */

import { useRef, useEffect } from 'react'
import {
  Radio,
  Package,
  Brain,
  Zap,
  Activity,
  Play,
  ChevronDown,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { useConsoleStore, type ConsoleEvent } from '@/stores/console'
import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

// ---------------------------------------------------------------------------

const NARRATIVE_TYPES = new Set([
  'mission.narrative',
  'mission.artifact.found',
  'plan.step.started',
  'plan.step.completed',
  'agent.thinking.started',
  'agent.tool.called',
  'system.execution.created',
  'system.execution.completed',
])

// ---------------------------------------------------------------------------

export default function NarrativeTab() {
  const events = useConsoleStore((s) =>
    s.events.filter((e) => NARRATIVE_TYPES.has(e.event_type)),
  )
  const autoScroll = useConsoleStore((s) => s.autoScroll)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events.length, autoScroll])

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-4 py-3">
      {events.length === 0 && (
        <div className="flex h-full flex-col items-center justify-center gap-2">
          <Radio className="h-6 w-6 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground/60">
            Narrative events will appear here during a run.
          </p>
        </div>
      )}
      <div className="space-y-2">
        {events.map((ev) => (
          <NarrativeEventRow key={ev.event_id} event={ev} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function NarrativeEventRow({ event }: { event: ConsoleEvent }) {
  const d = event.data
  const ts = formatTime(event.timestamp)

  if (event.event_type === 'mission.narrative') {
    const narrative = String(d.narrative ?? '')
    const level = String(d.level ?? 'info')
    const accent =
      level === 'success' ? 'border-l-emerald-500/60 bg-emerald-500/5' :
      level === 'warning'  ? 'border-l-amber-500/60 bg-amber-500/5' :
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

  return null
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
