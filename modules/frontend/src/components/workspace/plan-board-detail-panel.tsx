/**
 * TaskDetailPanel — right panel for viewing full task details on the plan board.
 * Follows the same pattern as RunDetailPanel.
 */

import { X, RotateCcw } from 'lucide-react'
import { useResizable } from '@/hooks/use-resizable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DetailSection } from '@/components/ui/detail-section'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { MetricTile } from '@/components/ui/metric-tile'
import { Panel, PanelHeader } from '@/components/ui/panel'
import { StatusIcon } from '@/components/ui/status-icon'
import type { PlanTask } from '@/hooks/use-mission-plan'
import { agentShortName, fmtCost } from '@/lib/format'
import { taskTone } from '@/lib/status-tone'

export function TaskDetailPanel({
  task,
  onClose,
}: {
  task: PlanTask
  onClose: () => void
}) {
  const { width, onMouseDown } = useResizable(360)

  return (
    <Panel className="relative flex shrink-0 flex-col overflow-hidden" style={{ width }}>
      {/* Resize handle: invisible until hovered. */}
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 z-10 h-full w-1 cursor-col-resize transition-colors hover:bg-brand/30"
      />
      <PanelHeader
        title={
          <span className="flex min-w-0 items-center gap-1.5">
            <StatusIcon {...taskTone[task.status]} className="h-3.5 w-3.5" />
            <span className="truncate">{agentShortName(task.agent)}</span>
          </span>
        }
        actions={
          <Button variant="ghost" size="icon-sm" aria-label="Close details" title="Close" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        }
      />
      <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        <DetailSection label="Description">
          <p className="text-sm [overflow-wrap:anywhere]">{task.description}</p>
        </DetailSection>

        {task.failure_reason && (
          <DetailSection label="Failure reason">
            <div className="rounded-card border border-danger/20 bg-danger/5 p-2.5">
              <MarkdownRenderer content={task.failure_reason} className="text-xs text-danger [overflow-wrap:anywhere]" />
            </div>
          </DetailSection>
        )}

        {task.result_summary && (
          <DetailSection label="Result">
            <MarkdownRenderer content={task.result_summary} className="text-xs [overflow-wrap:anywhere]" />
          </DetailSection>
        )}

        {task.instructions && (
          <DetailSection label="Instructions">
            <MarkdownRenderer content={task.instructions} className="text-xs text-muted-foreground [overflow-wrap:anywhere]" />
          </DetailSection>
        )}

        {(task.cost_usd > 0 || task.duration_seconds > 0 || task.retry_count > 0) && (
          <DetailSection label="Metrics">
            <div className="grid grid-cols-3 gap-2">
              {task.cost_usd > 0 && <MetricTile label="Cost" value={fmtCost(task.cost_usd)} />}
              {task.duration_seconds > 0 && <MetricTile label="Duration" value={`${task.duration_seconds.toFixed(1)}s`} />}
              {task.retry_count > 0 && (
                <MetricTile
                  label="Retries"
                  value={String(task.retry_count)}
                  icon={<RotateCcw className="h-2.5 w-2.5 text-warning" />}
                />
              )}
            </div>
          </DetailSection>
        )}

        {task.dependencies.length > 0 && (
          <DetailSection label={`Dependencies (${task.dependencies.length})`}>
            <div className="space-y-1">
              {task.dependencies.map((dep) => (
                <p key={dep} className="font-mono text-2xs text-muted-foreground">{dep.slice(0, 8)}…</p>
              ))}
            </div>
          </DetailSection>
        )}

        {task.domain_tags.length > 0 && (
          <DetailSection label="Tags">
            <div className="flex flex-wrap gap-1">
              {task.domain_tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
          </DetailSection>
        )}

        <p className="select-all font-mono text-2xs text-faint">{task.id}</p>
      </div>
    </Panel>
  )
}
