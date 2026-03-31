import { useState } from 'react'
import { ChevronDown, ChevronRight, AlertTriangle, CheckCircle, XCircle, Info } from 'lucide-react'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'

const SEVERITY_ICON: Record<string, React.ReactNode> = {
  error: <XCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0" />,
  warning: <AlertTriangle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0" />,
  info: <Info className="h-3.5 w-3.5 text-blue-400 flex-shrink-0" />,
}

const STATUS_VARIANT: Record<string, 'success' | 'destructive' | 'warning' | 'secondary'> = {
  success: 'success',
  completed: 'success',
  healthy: 'success',
  failed: 'destructive',
  degraded: 'warning',
  error: 'destructive',
}

export function OutputPreviewPanel() {
  const { context } = useDrawerStore()
  const content = context.content as Record<string, unknown> | undefined

  if (!content) {
    return <p className="text-sm text-muted-foreground">No output available.</p>
  }

  // Try to render structured execution outcome
  if (isExecutionOutcome(content)) {
    return <ExecutionOutcomeView data={content} />
  }

  // Fallback: pretty JSON
  return (
    <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(content, null, 2)}
    </pre>
  )
}

// --- Structured renderers ---

interface TaskResult {
  task_id: string
  agent_name: string
  status: string
  summary?: string
  output_reference?: Record<string, unknown>
  findings?: Finding[]
}

interface Finding {
  category: string
  severity: string
  message: string
  details?: string
}

function isExecutionOutcome(obj: Record<string, unknown>): boolean {
  return 'task_results' in obj || 'status' in obj || 'overall_status' in obj
}

function ExecutionOutcomeView({ data }: { data: Record<string, unknown> }) {
  const status = String(data.overall_status ?? data.status ?? 'unknown')
  const taskResults = (data.task_results ?? []) as TaskResult[]
  const summary = data.summary as string | undefined

  // Collect all findings across tasks
  const allFindings: (Finding & { agent: string })[] = []
  for (const task of taskResults) {
    const findings = task.findings ?? task.output_reference?.findings as Finding[] | undefined ?? []
    for (const f of findings) {
      allFindings.push({ ...f, agent: task.agent_name })
    }
  }

  const errors = allFindings.filter((f) => f.severity === 'error')
  const warnings = allFindings.filter((f) => f.severity === 'warning')
  const infos = allFindings.filter((f) => f.severity === 'info')

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="flex items-center gap-2">
        <Badge variant={STATUS_VARIANT[status] ?? 'secondary'} className="capitalize">
          {status}
        </Badge>
        {summary && (
          <span className="text-xs text-muted-foreground">{summary}</span>
        )}
      </div>

      {/* Findings by severity */}
      {errors.length > 0 && (
        <FindingsList
          title={`Errors (${errors.length})`}
          findings={errors}
          severity="error"
          defaultOpen
        />
      )}
      {warnings.length > 0 && (
        <FindingsList
          title={`Warnings (${warnings.length})`}
          findings={warnings}
          severity="warning"
          defaultOpen={errors.length === 0}
        />
      )}
      {infos.length > 0 && (
        <FindingsList
          title={`Info (${infos.length})`}
          findings={infos}
          severity="info"
        />
      )}

      {/* Task summaries */}
      {taskResults.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Task Results
          </p>
          {taskResults.map((task) => (
            <TaskResultCard key={task.task_id} task={task} />
          ))}
        </div>
      )}

      {/* Raw data fallback for anything else */}
      <RawDataSection data={data} />
    </div>
  )
}

function FindingsList({
  title,
  findings,
  severity,
  defaultOpen,
}: {
  title: string
  findings: (Finding & { agent: string })[]
  severity: string
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen ?? false)

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs font-medium"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {SEVERITY_ICON[severity]}
        {title}
      </button>
      {open && (
        <div className="mt-1 ml-5 space-y-1.5">
          {findings.map((f, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <div className="min-w-0">
                <span className="font-medium">{f.category}</span>
                <span className="text-muted-foreground"> — {f.message}</span>
                {f.details && (
                  <p className="mt-0.5 text-muted-foreground/70">{f.details}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TaskResultCard({ task }: { task: TaskResult }) {
  const [expanded, setExpanded] = useState(false)
  const statusVariant = STATUS_VARIANT[task.status] ?? 'secondary'
  const summary =
    task.summary ??
    (task.output_reference?.summary as string | undefined) ??
    null

  return (
    <div className="rounded-md border px-3 py-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <Badge variant={statusVariant} className="text-[10px]">
            {task.status}
          </Badge>
          <span className="text-xs font-medium">{task.agent_name}</span>
          <span className="text-[10px] text-muted-foreground">{task.task_id}</span>
        </div>
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
      </button>
      {expanded && (
        <div className="mt-2 text-xs">
          {summary && (
            <p className="text-muted-foreground whitespace-pre-wrap">{summary}</p>
          )}
          {task.output_reference && !summary && (
            <pre className="mt-1 whitespace-pre-wrap rounded bg-muted p-2 text-[11px]">
              {JSON.stringify(task.output_reference, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function RawDataSection({ data }: { data: Record<string, unknown> }) {
  const [show, setShow] = useState(false)
  // Filter out already-rendered keys
  const extra = Object.fromEntries(
    Object.entries(data).filter(
      ([k]) => !['task_results', 'status', 'overall_status', 'summary', 'mission_id'].includes(k),
    ),
  )

  if (Object.keys(extra).length === 0) return null

  return (
    <div>
      <button
        onClick={() => setShow(!show)}
        className="text-[10px] text-muted-foreground hover:text-foreground"
      >
        {show ? 'Hide' : 'Show'} raw data
      </button>
      {show && (
        <pre className="mt-1 whitespace-pre-wrap rounded bg-muted p-2 text-[11px] max-h-60 overflow-y-auto">
          {JSON.stringify(extra, null, 2)}
        </pre>
      )}
    </div>
  )
}
