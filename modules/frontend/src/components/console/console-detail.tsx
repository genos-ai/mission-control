import type { ReactNode } from 'react'
import { Brain, DollarSign } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { StatusPill } from '@/components/ui/status-pill'
import { chatContent, formatOutput, type ConsoleRowView } from '@/lib/console-event'
import type { ConsoleEvent } from '@/stores/console'

/** What opens under a row: the part of the event that does not fit in one line. */
export function ConsoleDetail({ event, view }: { event: ConsoleEvent; view: ConsoleRowView }) {
  switch (view.kind) {
    case 'chat':
      return <ChatDetail event={event} />
    case 'narrative':
      return (
        <Body>
          <MarkdownRenderer content={String(event.data.narrative ?? '')} className="text-sm text-text-2" />
        </Body>
      )
    case 'artifact':
      return <ArtifactDetail event={event} />
    case 'execution':
      return <ExecutionDetail event={event} view={view} />
    case 'task':
      return <TaskDetail event={event} view={view} />
    case 'log':
      return (
        <Body>
          <p className="whitespace-pre-wrap break-words text-sm text-text-2">{view.message}</p>
        </Body>
      )
  }
}

function Body({ children }: { children: ReactNode }) {
  return (
    <div className="mx-2 mb-1.5 mt-0.5 space-y-2 rounded-card border border-panel-border bg-panel px-3 py-2.5">
      {children}
    </div>
  )
}

function Cost({ usd }: { usd: number }) {
  return (
    <span className="flex items-center font-mono text-2xs text-subtle">
      <DollarSign className="h-2.5 w-2.5" />
      {usd.toFixed(4)}
    </span>
  )
}

function ChatDetail({ event }: { event: ConsoleEvent }) {
  const d = event.data
  const content = chatContent(event)
  const model = d.model ? String(d.model) : null
  const cost = d.cost_usd != null ? Number(d.cost_usd) : null

  return (
    <Body>
      {(model || (cost != null && cost > 0)) && (
        <div className="flex items-center gap-2">
          {model && (
            <Badge variant="outline">{model.split(':').pop()?.split('-').slice(0, 2).join('-')}</Badge>
          )}
          {cost != null && cost > 0 && <Cost usd={cost} />}
        </div>
      )}
      {typeof d.thinking === 'string' && d.thinking && (
        <details className="rounded-card border border-violet/20 bg-violet/5 px-2.5 py-1.5">
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-violet">
            <Brain className="h-3 w-3" />
            Thinking
          </summary>
          <p className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-muted-foreground">
            {d.thinking}
          </p>
        </details>
      )}
      <MarkdownRenderer
        content={content.length > 2000 ? content.slice(0, 2000) + '…' : content}
        className="text-sm text-text-2"
      />
    </Body>
  )
}

function ArtifactDetail({ event }: { event: ConsoleEvent }) {
  const d = event.data
  return (
    <Body>
      <div className="flex items-center gap-2">
        <span className="min-w-0 truncate text-sm font-medium text-foreground">{String(d.title ?? 'Artifact')}</span>
        <Badge variant="outline">{String(d.artifact_type ?? 'report')}</Badge>
      </div>
      <MarkdownRenderer content={String(d.content ?? '')} className="text-sm text-text-2" />
    </Body>
  )
}

function ExecutionDetail({ event, view }: { event: ConsoleEvent; view: ConsoleRowView }) {
  const d = event.data
  const objective = String(d.objective_statement ?? '')
  const cost = d.total_cost_usd != null ? Number(d.total_cost_usd) : null

  return (
    <Body>
      <div className="flex items-center gap-2">
        <StatusPill tone={view.error || d.status === 'cancelled' || d.status === 'timed_out' ? 'danger' : 'success'}>
          {String(d.status ?? '')}
        </StatusPill>
        {cost != null && <Cost usd={cost} />}
      </div>
      {objective && <p className="text-sm text-text-2">{objective}</p>}
    </Body>
  )
}

function TaskDetail({ event, view }: { event: ConsoleEvent; view: ConsoleRowView }) {
  const d = event.data
  const cost = d.cost_usd != null ? Number(d.cost_usd) : null
  const duration = d.duration_seconds != null ? Number(d.duration_seconds) : null
  const attempts = d.attempt_count ? Number(d.attempt_count) : null
  const output = d.output_data as Record<string, unknown> | null
  const outputSummary = output ? formatOutput(output) : null
  const errors = (d.verification_outcome as { errors?: string[] } | null)?.errors ?? []

  return (
    <Body>
      <div className="flex flex-wrap items-center gap-2">
        {d.task_id != null && <Badge variant="outline">{String(d.task_id)}</Badge>}
        <StatusPill tone={view.error ? 'danger' : 'success'}>{String(d.status ?? '')}</StatusPill>
        {cost != null && <Cost usd={cost} />}
        {duration != null && <span className="font-mono text-2xs text-subtle">{duration.toFixed(1)}s</span>}
        {attempts != null && attempts > 1 && (
          <span className="font-mono text-2xs text-subtle">{attempts} attempts</span>
        )}
      </div>
      {errors.map((err, i) => (
        <p key={i} className="text-xs text-danger">{err}</p>
      ))}
      {outputSummary && <MarkdownRenderer content={outputSummary} className="text-sm text-muted-foreground" />}
    </Body>
  )
}
