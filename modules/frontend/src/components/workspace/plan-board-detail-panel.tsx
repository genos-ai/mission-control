/**
 * TaskDetailPanel — right panel for viewing full task details on the plan board.
 * Follows the same pattern as RunDetailPanel.
 */

import { ChevronRight, XCircle, CheckCircle2, RotateCcw } from 'lucide-react'
import { useResizable } from '@/hooks/use-resizable'
import { Badge } from '@/components/ui/badge'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import type { PlanTask } from '@/hooks/use-mission-plan'

export function TaskDetailPanel({
  task,
  onClose,
}: {
  task: PlanTask
  onClose: () => void
}) {
  const { width, onMouseDown } = useResizable(320)
  const isFailed = task.status === 'failed'
  const agentShort = task.agent.endsWith('.agent') ? task.agent.slice(0, -6) : task.agent

  return (
    <div className="relative flex shrink-0 flex-col border-l" style={{ width }}>
      <div
        onMouseDown={onMouseDown}
        className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/20 transition-colors z-10"
      />
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-1.5 min-w-0">
          {isFailed ? (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
          )}
          <span className="truncate text-xs font-medium">{agentShort}</span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          title="Close"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* Description */}
        <Section label="Description">
          <p className="text-xs">{task.description}</p>
        </Section>

        {/* Failure reason */}
        {task.failure_reason && (
          <Section label="Failure Reason">
            <div className="rounded border border-destructive/30 bg-destructive/5 p-2.5">
              <MarkdownRenderer content={task.failure_reason} className="text-xs text-destructive/90" />
            </div>
          </Section>
        )}

        {/* Result summary */}
        {task.result_summary && (
          <Section label="Result">
            <MarkdownRenderer content={task.result_summary} className="text-xs" />
          </Section>
        )}

        {/* Instructions */}
        {task.instructions && (
          <Section label="Instructions">
            <MarkdownRenderer content={task.instructions} className="text-xs text-muted-foreground" />
          </Section>
        )}

        {/* Metrics */}
        {(task.cost_usd > 0 || task.duration_seconds > 0 || task.retry_count > 0) && (
          <Section label="Metrics">
            <div className="grid grid-cols-3 gap-2">
              {task.cost_usd > 0 && <Stat label="Cost" value={`$${task.cost_usd.toFixed(4)}`} />}
              {task.duration_seconds > 0 && <Stat label="Duration" value={`${task.duration_seconds.toFixed(1)}s`} />}
              {task.retry_count > 0 && (
                <Stat
                  label="Retries"
                  value={String(task.retry_count)}
                  icon={<RotateCcw className="h-2.5 w-2.5 text-amber-400" />}
                />
              )}
            </div>
          </Section>
        )}

        {/* Dependencies */}
        {task.dependencies.length > 0 && (
          <Section label={`Dependencies (${task.dependencies.length})`}>
            <div className="space-y-1">
              {task.dependencies.map((dep) => (
                <p key={dep} className="font-mono text-[10px] text-muted-foreground">{dep.slice(0, 8)}…</p>
              ))}
            </div>
          </Section>
        )}

        {/* Domain tags */}
        {task.domain_tags.length > 0 && (
          <Section label="Tags">
            <div className="flex flex-wrap gap-1">
              {task.domain_tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="text-[9px]">{tag}</Badge>
              ))}
            </div>
          </Section>
        )}

        {/* Task ID */}
        <p className="font-mono text-[9px] text-muted-foreground/40 select-all">{task.id}</p>
      </div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      {children}
    </div>
  )
}

function Stat({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded border px-2 py-1.5">
      <p className="text-[9px] font-semibold uppercase text-muted-foreground">{label}</p>
      <div className="flex items-center gap-1">
        {icon}
        <p className="text-sm font-bold">{value}</p>
      </div>
    </div>
  )
}
