/**
 * One narrative event as a timeline item. Every event type the mission
 * stream emits has its own sentence; anything else falls through to a generic
 * row that shows the type, its source and the message or payload.
 */

import type { ReactNode } from 'react'
import { Activity, AlertCircle, AlertTriangle, Brain, Info, Package, Play, Radio, Zap } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { cn } from '@/lib/cn'
import { fmtCost, agentShortName } from '@/lib/format'
import type { Tone } from '@/lib/status-tone'
import { TONE_BOX, TONE_TEXT } from '@/lib/tone-class'
import type { ConsoleEvent } from '@/stores/console'

import { isRenderable } from '@/components/narrative/narrative-groups'
import { TimelineItem } from '@/components/narrative/timeline-item'

function Emphasis({ children }: { children: ReactNode }) {
  return <span className="font-medium text-foreground">{children}</span>
}

function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-base text-foreground">{children}</span>
}

function Payload({ children }: { children: ReactNode }) {
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">
      {children}
    </pre>
  )
}

// Markdown brings its own paragraph margins; trim them so a sentence lines up with its icon.
const SENTENCE_MARKDOWN = 'text-md text-text-2 [&>p:first-child]:mt-0 [&>p:last-child]:mb-0'

function levelTone(level: string): Tone {
  switch (level) {
    case 'success':
      return 'success'
    case 'warning':
      return 'warning'
    case 'error':
      return 'danger'
    default:
      return 'info'
  }
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}

export function NarrativeEvent({ event }: { event: ConsoleEvent }) {
  const d = event.data
  const time = formatTime(event.timestamp)
  const agent = String(d.agent_id ?? event.source ?? '')

  // The same test the groups use, so a panel never holds a row-less event.
  if (!isRenderable(event)) return null

  switch (event.event_type) {
    case 'mission.narrative':
      return (
        <TimelineItem icon={Radio} tone={levelTone(String(d.level ?? 'info'))} time={time}>
          <MarkdownRenderer content={String(d.narrative ?? '')} className={SENTENCE_MARKDOWN} />
        </TimelineItem>
      )

    case 'mission.artifact.found': {
      const title = String(d.title ?? 'Artifact')
      const content = String(d.content ?? '')
      return (
        <TimelineItem
          icon={Package}
          tone="violet"
          time={time}
          detail={content ? <MarkdownRenderer content={content} className="text-sm" /> : undefined}
        >
          {agent && <Emphasis>{agentShortName(agent)}</Emphasis>} produced <Emphasis>{title}</Emphasis>{' '}
          <Badge variant="outline">{String(d.artifact_type ?? 'report')}</Badge>
        </TimelineItem>
      )
    }

    case 'agent.thinking.started':
      return (
        <TimelineItem icon={Brain} tone="violet" time={time}>
          <Emphasis>{agentShortName(agent)}</Emphasis> is thinking…
        </TimelineItem>
      )

    case 'agent.tool.called': {
      const args = (d.tool_args as Record<string, unknown> | undefined) ?? {}
      return (
        <TimelineItem
          icon={Zap}
          tone="warning"
          time={time}
          detail={Object.keys(args).length > 0 ? <Payload>{JSON.stringify(args, null, 2)}</Payload> : undefined}
        >
          <Emphasis>{agentShortName(agent)}</Emphasis> called <Mono>{String(d.tool_name ?? '')}</Mono>
        </TimelineItem>
      )
    }

    case 'agent.tool.returned': {
      const tool = String(d.tool_name ?? '')
      const result = String(d.result ?? '')
      const detail = result ? <Payload>{result}</Payload> : undefined
      if (String(d.status ?? 'success') === 'error') {
        return (
          <TimelineItem icon={AlertTriangle} tone="danger" time={time} detail={detail} defaultOpen>
            <Mono>{tool}</Mono> <span className={TONE_TEXT.danger}>failed</span>
          </TimelineItem>
        )
      }
      return (
        <TimelineItem icon={Zap} tone="success" time={time} detail={detail}>
          <Mono>{tool}</Mono> returned
        </TimelineItem>
      )
    }

    case 'agent.response.complete': {
      const content = String(d.full_content ?? '')
      const metadata = (d.metadata as Record<string, unknown> | undefined) ?? {}
      const thinking = typeof metadata.thinking === 'string' ? metadata.thinking : ''
      return (
        <TimelineItem
          icon={Brain}
          tone="info"
          time={time}
          detail={
            <div className="space-y-2">
              {thinking && (
                <details className={cn('rounded-card border px-3 py-2', TONE_BOX.violet)}>
                  <summary className={cn('flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium', TONE_TEXT.violet)}>
                    <Brain className="h-3 w-3" />
                    Thinking
                  </summary>
                  <div className="mt-2">
                    <Payload>{thinking}</Payload>
                  </div>
                </details>
              )}
              {content && <MarkdownRenderer content={content} className="text-sm" />}
            </div>
          }
        >
          <Emphasis>{agentShortName(agent)}</Emphasis> responded
          {thinking && <>{' '}<Badge variant="outline">thinking</Badge></>}
          {d.cost_usd != null && <>{' '}<Badge variant="outline">{fmtCost(Number(d.cost_usd))}</Badge></>}
        </TimelineItem>
      )
    }

    case 'plan.step.started':
      return (
        <TimelineItem icon={Activity} tone="info" time={time}>
          <Emphasis>Starting</Emphasis> {String(d.step_name ?? d.step_id ?? '')}
        </TimelineItem>
      )

    case 'plan.step.completed': {
      const ok = String(d.status ?? 'success') === 'success'
      return (
        <TimelineItem icon={Activity} tone={ok ? 'success' : 'danger'} time={time}>
          <Emphasis>{ok ? 'Completed' : 'Failed'}</Emphasis> {String(d.step_id ?? '')}
        </TimelineItem>
      )
    }

    case 'system.execution.created': {
      const objective = String(d.objective ?? '').slice(0, 80)
      return (
        <TimelineItem icon={Play} tone="info" time={time}>
          <Emphasis>Run started</Emphasis> {objective}
        </TimelineItem>
      )
    }

    case 'system.execution.completed': {
      const status = String(d.status ?? '')
      const ok = status === 'completed'
      return (
        <TimelineItem icon={Activity} tone={ok ? 'success' : 'danger'} time={time}>
          <Emphasis>Run {status}</Emphasis>
          {d.total_cost_usd != null && <span className="ml-2 font-mono text-xs text-subtle">{fmtCost(Number(d.total_cost_usd))}</span>}
          {d.duration_seconds != null && <span className="ml-2 font-mono text-xs text-subtle">{Number(d.duration_seconds).toFixed(1)}s</span>}
        </TimelineItem>
      )
    }
  }

  // Any other event type: severity from the payload's level, content from its message.
  const level = String(d.level ?? 'info')
  // Only failures and warnings are coloured; routine events stay quiet.
  const tone: Tone = level === 'error' ? 'danger' : level === 'warning' ? 'warning' : 'neutral'
  const message = String(d.message ?? d.narrative ?? d.detail ?? '')
  const hasPayload = !message && Object.keys(d).length > 0
  return (
    <TimelineItem
      icon={level === 'error' ? AlertCircle : level === 'warning' ? AlertTriangle : Info}
      tone={tone}
      time={time}
      detail={hasPayload ? <Payload>{JSON.stringify(d, null, 2)}</Payload> : undefined}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono">{event.event_type}</Badge>
        {event.source && <span className="text-2xs text-subtle">{event.source}</span>}
      </div>
      {message && (
        <p className={cn('mt-1 break-words', tone !== 'neutral' && TONE_TEXT[tone])}>{message}</p>
      )}
    </TimelineItem>
  )
}
