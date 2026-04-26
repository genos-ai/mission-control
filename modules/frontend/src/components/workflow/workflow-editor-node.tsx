/**
 * Custom React Flow nodes for the workflow editor.
 *
 * Four node types: agent_step (default), condition, notification, human_input.
 */

import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Bot, GitBranch, Bell, UserRound, Loader2, CheckCircle2, XCircle, MinusCircle, Clock } from 'lucide-react'
import type { WorkflowStep } from '@/types'
import type { NodeStatus } from '@/hooks/use-workflow-run-status'
import { NODE_WIDTH, getDomainBorder, getDomainBg, NODE_TYPE_STYLES } from './workflow-editor-types'

export interface StepNodeData {
  step: WorkflowStep
  status?: NodeStatus
  [key: string]: unknown
}

// ── Shared handles ──────────────────────────────────────────────────────

const TargetHandle = () => (
  <Handle
    type="target"
    position={Position.Left}
    className="!h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
  />
)
const SourceHandle = () => (
  <Handle
    type="source"
    position={Position.Right}
    className="!h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
  />
)

const selectedRing = 'ring-2 ring-primary/60 ring-offset-1 ring-offset-background'

const STATUS_RING: Record<string, string> = {
  idle: '',
  running: 'ring-2 ring-amber-400/70 animate-pulse',
  completed: 'ring-2 ring-emerald-500/60',
  failed: 'ring-2 ring-red-500/70',
  skipped: 'opacity-40',
  awaiting_input: 'ring-2 ring-orange-400/70 animate-pulse',
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" />
    case 'completed':
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
    case 'failed':
      return <XCircle className="h-3.5 w-3.5 text-red-500" />
    case 'skipped':
      return <MinusCircle className="h-3.5 w-3.5 text-muted-foreground" />
    case 'awaiting_input':
      return <Clock className="h-3.5 w-3.5 text-orange-400" />
    default:
      return null
  }
}

// ── Agent Step Node ─────────────────────────────────────────────────────

function AgentStepNodeRaw({ data, selected }: NodeProps) {
  const step = (data as StepNodeData).step
  const status = (data as StepNodeData).status ?? 'idle'
  const capShort = step.capability?.split('.').pop() ?? step.capability ?? '—'

  return (
    <div
      className={[
        'relative rounded-xl border-2 px-3 py-2 shadow-sm transition-all',
        getDomainBorder(step.capability),
        getDomainBg(step.capability),
        selected ? selectedRing : '',
        STATUS_RING[status],
      ].join(' ')}
      style={{ width: NODE_WIDTH }}
    >
      <TargetHandle />
      {status !== 'idle' && (
        <div className="absolute -right-1.5 -top-1.5 rounded-full bg-background">
          <StatusIcon status={status} />
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <Bot className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate text-sm font-medium">{step.id}</span>
        {step.cost_ceiling_usd != null && (
          <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted-foreground">
            ${step.cost_ceiling_usd}
          </span>
        )}
      </div>

      <div className="mt-1 flex items-center gap-1.5">
        <span className="inline-flex items-center rounded-md bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-inset ring-border/50">
          {capShort}
        </span>
        <span className="text-[10px] text-muted-foreground/70">{step.environment}</span>
        {step.complexity_tier === 'complex' && (
          <span className="text-[10px] text-amber-400/80">complex</span>
        )}
      </div>

      <SourceHandle />
    </div>
  )
}

// ── Condition Node ──────────────────────────────────────────────────────

function ConditionNodeRaw({ data, selected }: NodeProps) {
  const step = (data as StepNodeData).step
  const status = (data as StepNodeData).status ?? 'idle'
  const config = step.condition_config
  const expr = config?.expression ?? ''
  // Show a compact version of the expression
  const exprShort = expr.length > 35 ? expr.slice(0, 32) + '…' : expr

  return (
    <div
      className={[
        'relative rounded-xl border-2 px-3 py-2 shadow-sm transition-all',
        NODE_TYPE_STYLES.condition.border,
        NODE_TYPE_STYLES.condition.bg,
        selected ? selectedRing : '',
        STATUS_RING[status],
      ].join(' ')}
      style={{ width: NODE_WIDTH }}
    >
      <TargetHandle />
      {status !== 'idle' && (
        <div className="absolute -right-1.5 -top-1.5 rounded-full bg-background">
          <StatusIcon status={status} />
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <GitBranch className="h-3.5 w-3.5 shrink-0 text-amber-500" />
        <span className="truncate text-sm font-medium">{step.id}</span>
      </div>

      <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={expr}>
        {exprShort}
      </p>

      <div className="mt-1 flex items-center gap-2 text-[10px]">
        <span className="text-emerald-500">{config?.true_label ?? 'Yes'}</span>
        <span className="text-muted-foreground/40">/</span>
        <span className="text-red-400">{config?.false_label ?? 'No'}</span>
      </div>

      <SourceHandle />
    </div>
  )
}

// ── Notification Node ───────────────────────────────────────────────────

function NotificationNodeRaw({ data, selected }: NodeProps) {
  const step = (data as StepNodeData).step
  const status = (data as StepNodeData).status ?? 'idle'
  const config = step.notification_config
  const msgShort = (config?.message_template ?? '').length > 40
    ? (config?.message_template ?? '').slice(0, 37) + '…'
    : config?.message_template ?? ''

  return (
    <div
      className={[
        'relative rounded-xl border-2 px-3 py-2 shadow-sm transition-all',
        NODE_TYPE_STYLES.notification.border,
        NODE_TYPE_STYLES.notification.bg,
        selected ? selectedRing : '',
        STATUS_RING[status],
      ].join(' ')}
      style={{ width: NODE_WIDTH }}
    >
      <TargetHandle />
      {status !== 'idle' && (
        <div className="absolute -right-1.5 -top-1.5 rounded-full bg-background">
          <StatusIcon status={status} />
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <Bell className="h-3.5 w-3.5 shrink-0 text-sky-500" />
        <span className="truncate text-sm font-medium">{step.id}</span>
        <span className="ml-auto shrink-0 inline-flex items-center rounded-md bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-inset ring-border/50">
          {config?.channel ?? 'sse'}
        </span>
      </div>

      <p className="mt-1 truncate text-[10px] text-muted-foreground" title={config?.message_template}>
        {msgShort}
      </p>

      <SourceHandle />
    </div>
  )
}

// ── Human Input Node ────────────────────────────────────────────────────

function HumanInputNodeRaw({ data, selected }: NodeProps) {
  const step = (data as StepNodeData).step
  const status = (data as StepNodeData).status ?? 'idle'
  const config = step.human_input_config
  const promptShort = (config?.prompt_message ?? '').length > 40
    ? (config?.prompt_message ?? '').slice(0, 37) + '…'
    : config?.prompt_message ?? ''

  return (
    <div
      className={[
        'relative rounded-xl border-2 border-dashed px-3 py-2 shadow-sm transition-all',
        'border-orange-500/60',
        'bg-orange-500/5',
        selected ? selectedRing : '',
        STATUS_RING[status],
      ].join(' ')}
      style={{ width: NODE_WIDTH }}
    >
      <TargetHandle />
      {status !== 'idle' && (
        <div className="absolute -right-1.5 -top-1.5 rounded-full bg-background">
          <StatusIcon status={status} />
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <UserRound className="h-3.5 w-3.5 shrink-0 text-orange-500" />
        <span className="truncate text-sm font-medium">{step.id}</span>
        <span className="ml-auto shrink-0 inline-flex items-center rounded-md bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground ring-1 ring-inset ring-border/50">
          {config?.channel ?? 'telegram'}
        </span>
      </div>

      <p className="mt-1 truncate text-[10px] text-muted-foreground" title={config?.prompt_message}>
        {promptShort}
      </p>

      <div className="mt-1 flex items-center gap-1.5 text-[10px] text-muted-foreground/70">
        {config?.timeout_hours != null && (
          <span>{config.timeout_hours}h timeout</span>
        )}
        {config?.choices && config.choices.length > 0 && (
          <span>{config.choices.length} choices</span>
        )}
      </div>

      <SourceHandle />
    </div>
  )
}

// ── Exports ─────────────────────────────────────────────────────────────

export const WorkflowEditorNode = memo(AgentStepNodeRaw)
export const ConditionNode = memo(ConditionNodeRaw)
export const NotificationNode = memo(NotificationNodeRaw)
export const HumanInputNode = memo(HumanInputNodeRaw)
