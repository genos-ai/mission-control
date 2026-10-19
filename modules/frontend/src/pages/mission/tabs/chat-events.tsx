import type { ReactNode } from 'react'
import { Activity, AlertTriangle, Brain, Info, Loader2, Package, Search, Zap, type LucideIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { eventLabel } from '@/lib/event-utils'
import { agentShortName, fmtCost } from '@/lib/format'
import { parseUtc } from '@/lib/format-date'
import type { Tone } from '@/lib/status-tone'
import { TONE_BOX, TONE_TEXT } from '@/lib/tone-class'
import type { ConsoleEvent } from '@/stores/console'

// Events sit under the message text, so both shapes are indented past the agent avatar.

interface EventLineProps {
  icon: LucideIcon
  tone: Tone
  /** Omit for a line with no time (it then has no hairline either). */
  ts?: string
  spin?: boolean
  children: ReactNode
}

/** A quiet one-line event: icon, text, a hairline, then the time. */
export function EventLine({ icon: Icon, tone, ts, spin = false, children }: EventLineProps) {
  return (
    <div className="flex items-center gap-2 pl-9 text-xs text-subtle">
      <Icon className={cn('h-3 w-3 shrink-0', TONE_TEXT[tone], spin && 'animate-spin motion-reduce:animate-none')} />
      <span className="flex min-w-0 items-center gap-1.5">{children}</span>
      {ts && (
        <>
          <span className="h-px flex-1 bg-border/60" />
          <span className="font-mono text-2xs">{ts}</span>
        </>
      )}
    </div>
  )
}

interface EventBoxProps {
  icon: LucideIcon
  tone: Tone
  ts: string
  title: ReactNode
  /** Extra inline content after the title, e.g. a badge. */
  extra?: ReactNode
  detail?: string
}

/** A tinted callout for an event that needs attention: failures, warnings, new artifacts. */
function EventBox({ icon: Icon, tone, ts, title, extra, detail }: EventBoxProps) {
  return (
    <div className={cn('ml-9 flex items-start gap-2 rounded-card border px-3 py-2 text-xs', TONE_BOX[tone])}>
      <Icon className={cn('mt-0.5 h-3 w-3 shrink-0', TONE_TEXT[tone])} />
      <div className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className={cn('font-medium', TONE_TEXT[tone])}>{title}</span>
          {extra}
        </span>
        {detail && <p className="mt-0.5 line-clamp-3 [overflow-wrap:anywhere] text-muted-foreground">{detail}</p>}
      </div>
      <span className="shrink-0 font-mono text-2xs text-subtle">{ts}</span>
    </div>
  )
}

const mono = (text: string, tone: Tone) => <span className={cn('font-mono', TONE_TEXT[tone])}>{text}</span>
const text = (value: unknown) => String(value ?? '')

/** One narrative event rendered inline in the conversation; returns null for events that are noise. */
export function InlineNarrativeRow({ event }: { event: ConsoleEvent }) {
  const d = event.data as Record<string, unknown>
  const ts = parseUtc(event.timestamp).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  const agent = agentShortName(text(d.agent_id ?? event.source))
  const cost = (value: unknown) => (value != null ? fmtCost(Number(value)) : '')

  switch (event.event_type) {
    case 'agent.thinking.started':
      return <EventLine icon={Brain} tone="violet" ts={ts}>{agent} is thinking…</EventLine>

    case 'agent.tool.called':
      return (
        <EventLine icon={Zap} tone="warning" ts={ts}>
          {agent}
          <span className="text-faint">→</span>
          {mono(text(d.tool_name), 'warning')}
        </EventLine>
      )

    case 'agent.tool.returned':
      // Success is noise; only failures are shown.
      if (text(d.status ?? 'success') !== 'error') return null
      return <EventBox icon={AlertTriangle} tone="danger" ts={ts} title={`${text(d.tool_name)} failed`} detail={text(d.result)} />

    case 'plan.step.started':
      return <EventLine icon={Activity} tone="info" ts={ts}>Starting {text(d.step_name ?? d.step_id)}</EventLine>

    case 'plan.step.completed': {
      const ok = text(d.status ?? 'success') === 'success'
      return (
        <EventLine icon={Activity} tone={ok ? 'success' : 'danger'} ts={ts}>
          {ok ? 'Completed' : 'Failed'} {text(d.step_id)}
          {cost(d.cost_usd) && <span className="font-mono">{cost(d.cost_usd)}</span>}
        </EventLine>
      )
    }

    case 'system.execution.created':
      return <EventLine icon={Activity} tone="info" ts={ts}>Run started</EventLine>

    case 'system.execution.completed': {
      const ok = text(d.status) === 'completed'
      return (
        <EventLine icon={Activity} tone={ok ? 'success' : 'danger'} ts={ts}>
          Run {text(d.status)}
          {cost(d.total_cost_usd) && <span className="font-mono">{cost(d.total_cost_usd)}</span>}
          {d.duration_seconds != null && <span className="font-mono">{Number(d.duration_seconds).toFixed(1)}s</span>}
        </EventLine>
      )
    }

    case 'mission.artifact.found':
      return (
        <EventBox
          icon={Package}
          tone="violet"
          ts={ts}
          title={text(d.title ?? 'Artifact')}
          extra={<Badge variant="outline">{text(d.artifact_type ?? 'report')}</Badge>}
        />
      )

    case 'research.started':
      return <EventLine icon={Search} tone="info" ts={ts}>Research started <span className="truncate">{text(d.query)}</span></EventLine>

    case 'research.decomposed':
      return <EventLine icon={Search} tone="info" ts={ts}>Decomposed into {Number(d.sub_question_count ?? 0)} sub-questions</EventLine>

    case 'research.subquestion.updated': {
      const status = text(d.status)
      const tone: Tone = status === 'searching' ? 'info' : status === 'covered' ? 'success' : 'neutral'
      return (
        <EventLine icon={Search} tone={tone} ts={ts}>
          <span className="truncate">{text(d.text)}</span>
          <StatusPill tone={tone} pulse={status === 'searching'} className="shrink-0">{status}</StatusPill>
        </EventLine>
      )
    }

    case 'research.search.completed':
      return (
        <EventLine icon={Search} tone="info" ts={ts}>
          Search round complete · {Number(d.sources_found ?? 0)} sources, {Number(d.findings_count ?? 0)} findings
        </EventLine>
      )

    case 'research.coverage.updated':
      return (
        <EventLine icon={Search} tone="info" ts={ts}>
          Coverage updated
          {d.coverage_ratio != null && <span className="font-mono">{(Number(d.coverage_ratio) * 100).toFixed(0)}%</span>}
        </EventLine>
      )

    case 'research.synthesizing':
      return <EventLine icon={Loader2} tone="info" ts={ts} spin>Synthesizing research report…</EventLine>

    case 'research.completed':
      return (
        <EventLine icon={Search} tone="success" ts={ts}>
          Research complete · {Number(d.total_findings ?? 0)} findings
          {cost(d.total_cost_usd) && <span className="font-mono">{cost(d.total_cost_usd)}</span>}
        </EventLine>
      )

    case 'research.failed':
      return <EventBox icon={AlertTriangle} tone="danger" ts={ts} title="Research failed" detail={text(d.error)} />
  }

  // Anything else: an error or warning is a callout, the rest a quiet line.
  const level = text(d.level ?? (d.step === 'error' ? 'error' : ''))
  const message = text(d.message ?? d.content ?? d.summary)
  const isError =
    level === 'error' || d.status === 'failed' || event.event_type.includes('error') || event.event_type.includes('failed')
  if (isError || level === 'warning') {
    return (
      <EventBox
        icon={AlertTriangle}
        tone={isError ? 'danger' : 'warning'}
        ts={ts}
        title={eventLabel(event.event_type, d)}
        detail={message}
      />
    )
  }
  return (
    <EventLine icon={Info} tone="neutral" ts={ts}>
      {event.event_type.replace(/\./g, ' ')}
      {message && <span className="truncate text-faint">{message}</span>}
    </EventLine>
  )
}
