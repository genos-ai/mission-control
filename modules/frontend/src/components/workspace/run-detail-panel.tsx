/**
 * RunDetailPanel — inline right panel for run events, output, and cost.
 * Same fixed-width pattern as ArtifactsPanel in chat-tab.tsx.
 */

import { ChevronRight, List } from 'lucide-react'
import { useExecution, useExecutionCost } from '@/hooks/use-executions'
import { useResizable } from '@/hooks/use-resizable'
import { OutputPreviewContent } from '@/components/drawer/output-preview-panel'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { Spinner } from '@/components/ui/spinner'

export type RunDetailView = {
  type: 'events' | 'output' | 'cost'
  executionId: string
  content?: Record<string, unknown>
}

const TITLE: Record<RunDetailView['type'], string> = {
  events: 'Event Log',
  output: 'Output',
  cost: 'Cost Breakdown',
}

export function RunDetailPanel({
  view,
  onClose,
}: {
  view: RunDetailView | null
  onClose: () => void
}) {
  const { width, onMouseDown } = useResizable(280)

  return (
    <div className="relative flex shrink-0 flex-col border-l" style={{ width }}>
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/20 transition-colors z-10"
      />
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <span className="text-xs font-medium">
          {view ? TITLE[view.type] : 'Details'}
        </span>
        {view && (
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            title="Clear selection"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {!view ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 py-8">
            <List className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-center text-xs leading-relaxed text-muted-foreground/70">
              Select <strong>Events</strong>, <strong>Output</strong>, or{' '}
              <strong>Cost</strong> from any run to view details here.
            </p>
          </div>
        ) : (
          <div className="p-3">
            {view.type === 'events' && <EventLogContent executionId={view.executionId} />}
            {view.type === 'output' && <OutputContent content={view.content} />}
            {view.type === 'cost' && <CostContent executionId={view.executionId} />}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Event Log
// ---------------------------------------------------------------------------

function EventLogContent({ executionId }: { executionId: string }) {
  const { data: detail, isLoading } = useExecution(executionId)

  if (isLoading) return <Spinner />
  if (!detail) return <p className="text-xs text-muted-foreground">No execution data.</p>

  const events: { time: string; type: string; label: string; detail?: string }[] = []

  for (const task of detail.task_executions) {
    const time = task.completed_at ?? task.started_at ?? task.created_at
    if (time) {
      events.push({
        time,
        type:
          task.status === 'completed'
            ? 'success'
            : task.status === 'failed'
              ? 'error'
              : 'start',
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
    return <p className="text-xs text-muted-foreground">No events recorded.</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-[10px] text-muted-foreground">{events.length} events</p>
      {events.map((ev, i) => (
        <div key={i} className="flex gap-2 text-xs">
          <span className="w-14 shrink-0 text-[10px] text-muted-foreground">
            {new Date(ev.time).toLocaleTimeString()}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1">
              {ev.type === 'success' || ev.type === 'error' ? (
                <StatusPill tone={ev.type === 'success' ? 'success' : 'danger'}>{ev.type}</StatusPill>
              ) : (
                <Badge>{ev.type}</Badge>
              )}
              <span className="truncate">{ev.label}</span>
            </div>
            {ev.detail && (
              <p className="mt-0.5 text-[10px] text-muted-foreground">{ev.detail}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

function OutputContent({ content }: { content: Record<string, unknown> | undefined }) {
  if (!content || Object.keys(content).length === 0) {
    return <p className="text-xs text-muted-foreground">No output available.</p>
  }
  return <OutputPreviewContent content={content} />
}

// ---------------------------------------------------------------------------
// Cost Breakdown
// ---------------------------------------------------------------------------

function CostContent({ executionId }: { executionId: string }) {
  const { data: breakdown, isLoading } = useExecutionCost(executionId)

  if (isLoading) return <Spinner />
  if (!breakdown) return <p className="text-xs text-muted-foreground">No cost data available.</p>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <StatCard label="Total" value={`$${breakdown.total_cost_usd.toFixed(4)}`} />
        <StatCard label="Attempts" value={String(breakdown.attempt_count)} />
        <StatCard label="Input Tok" value={breakdown.total_input_tokens.toLocaleString()} />
        <StatCard label="Output Tok" value={breakdown.total_output_tokens.toLocaleString()} />
      </div>

      {breakdown.task_costs.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
            By Task
          </p>
          <div className="space-y-1">
            {breakdown.task_costs.map((tc, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded border px-2 py-1.5 text-xs"
              >
                <span className="min-w-0 truncate font-medium">{tc.agent_name}</span>
                <div className="ml-2 shrink-0 text-right text-[10px] text-muted-foreground">
                  <span className="font-medium text-foreground">${tc.cost_usd.toFixed(4)}</span>
                  <span className="ml-1">
                    {(tc.input_tokens + tc.output_tokens).toLocaleString()}tok
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(breakdown.model_costs).length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
            By Model
          </p>
          <div className="space-y-1">
            {Object.entries(breakdown.model_costs).map(([model, cost]) => (
              <div
                key={model}
                className="flex items-center justify-between rounded border px-2 py-1.5 text-xs"
              >
                <span className="min-w-0 truncate font-mono text-[10px]">{model}</span>
                <span className="ml-2 shrink-0 font-medium">${cost.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase text-muted-foreground">{label}</p>
      <p className="text-sm font-bold">{value}</p>
    </div>
  )
}
