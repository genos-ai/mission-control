/**
 * TaskDetailPanel — right panel for viewing full task details on the plan board.
 * Follows the same pattern as RunDetailPanel.
 */

import type { ReactNode } from 'react'
import { X, RotateCcw } from 'lucide-react'
import { useResizable } from '@/hooks/use-resizable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
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
        <Section label="Description">
          <p className="text-sm [overflow-wrap:anywhere]">{task.description}</p>
        </Section>

        {task.failure_reason && (
          <Section label="Failure reason">
            <div className="rounded-card border border-danger/20 bg-danger/5 p-2.5">
              <MarkdownRenderer content={task.failure_reason} className="text-xs text-danger [overflow-wrap:anywhere]" />
            </div>
          </Section>
        )}

        {task.result_summary && (
          <Section label="Result">
            <MarkdownRenderer content={task.result_summary} className="text-xs [overflow-wrap:anywhere]" />
          </Section>
        )}

        {task.instructions && (
          <Section label="Instructions">
            <MarkdownRenderer content={task.instructions} className="text-xs text-muted-foreground [overflow-wrap:anywhere]" />
          </Section>
        )}

        {(task.cost_usd > 0 || task.duration_seconds > 0 || task.retry_count > 0) && (
          <Section label="Metrics">
            <div className="grid grid-cols-3 gap-2">
              {task.cost_usd > 0 && <Stat label="Cost" value={fmtCost(task.cost_usd)} />}
              {task.duration_seconds > 0 && <Stat label="Duration" value={`${task.duration_seconds.toFixed(1)}s`} />}
              {task.retry_count > 0 && (
                <Stat
                  label="Retries"
                  value={String(task.retry_count)}
                  icon={<RotateCcw className="h-2.5 w-2.5 text-warning" />}
                />
              )}
            </div>
          </Section>
        )}

        {task.dependencies.length > 0 && (
          <Section label={`Dependencies (${task.dependencies.length})`}>
            <div className="space-y-1">
              {task.dependencies.map((dep) => (
                <p key={dep} className="font-mono text-2xs text-muted-foreground">{dep.slice(0, 8)}…</p>
              ))}
            </div>
          </Section>
        )}

        {task.domain_tags.length > 0 && (
          <Section label="Tags">
            <div className="flex flex-wrap gap-1">
              {task.domain_tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
          </Section>
        )}

        <p className="select-all font-mono text-2xs text-faint">{task.id}</p>
      </div>
    </Panel>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-xs text-subtle">{label}</p>
      {children}
    </div>
  )
}

function Stat({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return (
    <div className="rounded-card bg-raised px-2.5 py-2">
      <p className="text-2xs text-subtle">{label}</p>
      <div className="flex items-center gap-1">
        {icon}
        <p className="font-mono text-sm font-medium">{value}</p>
      </div>
    </div>
  )
}
