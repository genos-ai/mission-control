/**
 * RunDetailPanel — floating panel beside the runs table showing one run's
 * events, output or cost breakdown. Opened from a row's detail buttons.
 */

import { X } from 'lucide-react'
import { useExecution, useExecutionCost } from '@/hooks/use-executions'
import { useResizable } from '@/hooks/use-resizable'
import { OutputPreviewContent } from '@/components/drawer/output-preview-panel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DetailSection } from '@/components/ui/detail-section'
import { MetricTile } from '@/components/ui/metric-tile'
import { Panel, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { StatusPill } from '@/components/ui/status-pill'
import { fmtCost } from '@/lib/format'
import { parseUtc } from '@/lib/format-date'

export type RunDetailView = {
  type: 'events' | 'output' | 'cost'
  executionId: string
  content?: Record<string, unknown>
}

const TITLE: Record<RunDetailView['type'], string> = {
  events: 'Event log',
  output: 'Output',
  cost: 'Cost breakdown',
}

export function RunDetailPanel({ view, onClose }: { view: RunDetailView; onClose: () => void }) {
  const { width, onMouseDown } = useResizable(360)

  return (
    <Panel className="relative flex shrink-0 flex-col overflow-hidden" style={{ width }}>
      {/* Resize handle: invisible until hovered. */}
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 z-10 h-full w-1 cursor-col-resize transition-colors hover:bg-brand/30"
      />
      <PanelHeader
        title={TITLE[view.type]}
        actions={
          <Button variant="ghost" size="icon-sm" aria-label="Close details" title="Close" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {view.type === 'events' && <EventLogContent executionId={view.executionId} />}
        {view.type === 'output' && <OutputContent content={view.content} />}
        {view.type === 'cost' && <CostContent executionId={view.executionId} />}
      </div>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Event Log
// ---------------------------------------------------------------------------

function EventLogContent({ executionId }: { executionId: string }) {
  const { data: detail, isLoading } = useExecution(executionId)

  if (isLoading) return <Spinner />
  if (!detail) return <p className="text-xs text-subtle">No execution data.</p>

  const events: { time: string; type: string; label: string; detail?: string }[] = []

  for (const task of detail.task_executions) {
    const time = task.completed_at ?? task.started_at ?? task.created_at
    if (time) {
      events.push({
        time,
        type: task.status === 'completed' ? 'success' : task.status === 'failed' ? 'error' : 'start',
        label: `${task.agent_name} ${task.status}`,
        detail: `${task.task_id} · ${fmtCost(task.cost_usd)} · ${task.duration_seconds?.toFixed(1) ?? '?'}s`,
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
    return <p className="text-xs text-subtle">No events recorded.</p>
  }

  return (
    <div className="flex flex-col gap-2.5">
      <p className="text-2xs text-subtle">{events.length} events</p>
      {events.map((ev, i) => (
        <div key={i} className="flex gap-2.5 text-xs">
          <span className="w-[72px] shrink-0 font-mono text-2xs text-subtle">
            {parseUtc(ev.time).toLocaleTimeString()}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              {ev.type === 'success' || ev.type === 'error' ? (
                <StatusPill tone={ev.type === 'success' ? 'success' : 'danger'}>{ev.type}</StatusPill>
              ) : (
                <Badge>{ev.type}</Badge>
              )}
              <span className="truncate">{ev.label}</span>
            </div>
            {ev.detail && (
              <p className="mt-0.5 text-2xs text-subtle [overflow-wrap:anywhere]">{ev.detail}</p>
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
    return <p className="text-xs text-subtle">No output available.</p>
  }
  return <OutputPreviewContent content={content} />
}

// ---------------------------------------------------------------------------
// Cost Breakdown
// ---------------------------------------------------------------------------

function CostContent({ executionId }: { executionId: string }) {
  const { data: breakdown, isLoading } = useExecutionCost(executionId)

  if (isLoading) return <Spinner />
  if (!breakdown) return <p className="text-xs text-subtle">No cost data available.</p>

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2">
        <MetricTile label="Total" value={fmtCost(breakdown.total_cost_usd)} />
        <MetricTile label="Attempts" value={String(breakdown.attempt_count)} />
        <MetricTile label="Input tokens" value={breakdown.total_input_tokens.toLocaleString()} />
        <MetricTile label="Output tokens" value={breakdown.total_output_tokens.toLocaleString()} />
      </div>

      {breakdown.task_costs.length > 0 && (
        <DetailSection label="By task">
          <div className="flex flex-col gap-1">
            {breakdown.task_costs.map((tc, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-2 rounded-card bg-raised px-2.5 py-2 text-xs"
              >
                <span className="min-w-0 truncate font-medium">{tc.agent_name}</span>
                <div className="shrink-0 text-right font-mono text-2xs text-subtle">
                  <span className="font-medium text-foreground">{fmtCost(tc.cost_usd)}</span>
                  <span className="ml-1.5">{(tc.input_tokens + tc.output_tokens).toLocaleString()} tok</span>
                </div>
              </div>
            ))}
          </div>
        </DetailSection>
      )}

      {Object.keys(breakdown.model_costs).length > 0 && (
        <DetailSection label="By model">
          <div className="flex flex-col gap-1">
            {Object.entries(breakdown.model_costs).map(([model, cost]) => (
              <div
                key={model}
                className="flex items-center justify-between gap-2 rounded-card bg-raised px-2.5 py-2 text-xs"
              >
                <span className="min-w-0 truncate font-mono text-2xs">{model}</span>
                <span className="shrink-0 font-mono font-medium">{fmtCost(cost)}</span>
              </div>
            ))}
          </div>
        </DetailSection>
      )}
    </div>
  )
}
