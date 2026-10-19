/**
 * Custom React Flow nodes for the workflow editor: one NodeFrame, and a thin
 * body per step type that says what its sub-line shows.
 */

import { memo, type ReactNode } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { IconTile } from '@/components/ui/icon-tile'
import { StatusIcon } from '@/components/ui/status-icon'
import type { NodeStatus, NodeMetrics } from '@/hooks/use-workflow-run-status'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import { fmtCost } from '@/lib/format'
import { runTone, taskTone, type StatusStyle, type Tone } from '@/lib/status-tone'
import type { WorkflowStep } from '@/types'
import { NODE_WIDTH, STEP_TYPES, type StepType } from './workflow-editor-types'

export interface StepNodeData {
  step: WorkflowStep
  status?: NodeStatus
  metrics?: NodeMetrics
  [key: string]: unknown
}

// ── Frame ───────────────────────────────────────────────────────────────

const FORK_JOIN_WIDTH = 120

const HANDLE = '!h-2 !w-2 !rounded-full !border-0 !bg-border-hover hover:!bg-brand'

/** How a node shows the state of the run it belongs to; an idle node shows nothing. */
const RUN_STATE: Record<Exclude<NodeStatus, 'idle'>, StatusStyle> = {
  running: taskTone.running,
  completed: taskTone.completed,
  failed: taskTone.failed,
  skipped: taskTone.skipped,
  awaiting_input: runTone.awaiting_input,
}

// Whole class literals, so Tailwind and the lint rule can see them.
const STATE_BORDER: Record<NodeStatus, string> = {
  idle: 'border-panel-border',
  running: 'border-warning/45',
  completed: 'border-success/45',
  failed: 'border-danger/50',
  skipped: 'border-panel-border opacity-40',
  awaiting_input: 'border-warning/45',
}

const SELECTED = 'border-brand ring-[3px] ring-brand/15'

function nodeData(data: NodeProps['data']) {
  const { step, status = 'idle', metrics } = data as StepNodeData
  return { step, status, metrics }
}

function NodeFrame({
  step,
  status,
  metrics,
  selected,
  type,
  tone,
  sub,
  subTitle,
  narrow = false,
  dashed = false,
  handles,
  children,
}: {
  step: WorkflowStep
  status: NodeStatus
  metrics?: NodeMetrics
  selected: boolean
  type: StepType
  tone: Tone
  /** A mono line under the title: what this step is configured to do. */
  sub?: ReactNode
  subTitle?: string
  /** Fork and Join are narrower: they only carry a name. */
  narrow?: boolean
  dashed?: boolean
  /** Replaces the single output handle, for steps that branch. */
  handles?: ReactNode
  children?: ReactNode
}) {
  const { icon, label } = STEP_TYPES[type]
  const showMetrics = status === 'completed' && metrics && (metrics.cost_usd != null || metrics.duration_seconds != null)

  return (
    <div
      className={cn(
        'relative flex items-center gap-2.5 rounded-[12px] border bg-raised px-3 py-2.5 shadow-node transition-colors duration-150',
        selected ? SELECTED : STATE_BORDER[status],
        dashed && 'border-dashed',
        (status === 'running' || status === 'awaiting_input') && 'animate-pulse-dot motion-reduce:animate-none',
      )}
      style={{ width: narrow ? FORK_JOIN_WIDTH : NODE_WIDTH }}
      title={label}
    >
      <Handle type="target" id="input" position={Position.Left} className={HANDLE} />
      {status !== 'idle' && (
        <span className="absolute -right-1.5 -top-1.5 rounded-full bg-panel">
          <StatusIcon {...RUN_STATE[status]} className="h-3.5 w-3.5" />
        </span>
      )}

      <IconTile icon={icon} tone={tone} shape="square" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{step.label || step.id}</p>
        {sub && (
          <p className="truncate font-mono text-2xs text-subtle" title={subTitle}>
            {sub}
          </p>
        )}
        {children}
        {showMetrics && (
          <p className="font-mono text-2xs text-subtle">
            {[
              metrics.cost_usd != null && fmtCost(metrics.cost_usd),
              metrics.duration_seconds != null && `${metrics.duration_seconds.toFixed(1)}s`,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
      </div>

      {handles ?? <Handle type="source" id="output" position={Position.Right} className={HANDLE} />}
    </div>
  )
}

function short(text: string | null | undefined, max: number): string {
  const value = text ?? ''
  return value.length > max ? `${value.slice(0, max - 3)}…` : value
}

// ── Step types ──────────────────────────────────────────────────────────

function AgentStepNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const capability = step.capability?.split('.').pop() ?? step.capability ?? '—'
  const sub = [
    capability,
    step.environment,
    step.complexity_tier === 'complex' && 'complex',
    step.cost_ceiling_usd != null && `$${step.cost_ceiling_usd}`,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="agent_step"
      tone={agentStyle(step.capability ?? '').tone}
      sub={sub}
      subTitle={step.capability ?? undefined}
    />
  )
}

function ConditionNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.condition_config
  const expression = config?.expression ?? ''

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="condition"
      tone={STEP_TYPES.condition.tone}
      sub={short(expression, 35)}
      subTitle={expression}
      handles={
        <>
          {/* One output per outcome */}
          <Handle type="source" id="yes" position={Position.Right} style={{ top: '30%' }} className="!h-2 !w-2 !rounded-full !border-0 !bg-success" />
          <Handle type="source" id="no" position={Position.Right} style={{ top: '70%' }} className="!h-2 !w-2 !rounded-full !border-0 !bg-danger" />
        </>
      }
    >
      <p className="flex items-center gap-1.5 text-2xs">
        <span className="text-success">{config?.true_label ?? 'Yes'}</span>
        <span className="text-faint">/</span>
        <span className="text-danger">{config?.false_label ?? 'No'}</span>
      </p>
    </NodeFrame>
  )
}

function NotificationNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.notification_config

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="notification"
      tone={STEP_TYPES.notification.tone}
      sub={`${config?.channel ?? 'sse'} · ${short(config?.message_template, 40)}`}
      subTitle={config?.message_template}
    />
  )
}

function HumanInputNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.human_input_config
  const extras = [
    config?.timeout_hours != null && `${config.timeout_hours}h timeout`,
    config?.choices && config.choices.length > 0 && `${config.choices.length} choices`,
  ].filter(Boolean)

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="human_input"
      tone={STEP_TYPES.human_input.tone}
      dashed
      sub={`${config?.channel ?? 'telegram'} · ${short(config?.prompt_message, 40)}`}
      subTitle={config?.prompt_message}
    >
      {extras.length > 0 && <p className="text-2xs text-subtle">{extras.join(' · ')}</p>}
    </NodeFrame>
  )
}

function ToolCallNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.tool_call_config
  const args = Object.keys(config?.tool_args ?? {})
  const argsPreview = args.length > 0 ? args.slice(0, 3).join(', ') + (args.length > 3 ? '…' : '') : '—'

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="tool_call"
      tone={STEP_TYPES.tool_call.tone}
      sub={`${config?.tool_name ?? '—'} · ${argsPreview}`}
    />
  )
}

function LlmCallNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.llm_call_config
  const model = config?.model?.split(':').pop()?.split('-').slice(0, 2).join('-') ?? '—'

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="llm_call"
      tone={STEP_TYPES.llm_call.tone}
      sub={`${model} · ${short(config?.prompt_template, 40)}`}
      subTitle={config?.prompt_template}
    />
  )
}

function BranchNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  return (
    <NodeFrame step={step} status={status} metrics={metrics} selected={selected} type="branch" tone={STEP_TYPES.branch.tone} narrow />
  )
}

function MergeNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const strategy = step.merge_config?.strategy ?? 'wait_all'
  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="merge"
      tone={STEP_TYPES.merge.tone}
      narrow
      sub={strategy === 'wait_any' ? 'any' : 'all'}
    />
  )
}

function SubWorkflowNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.sub_workflow_config
  const name = config?.workflow_name || config?.workflow_id || '—'

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="sub_workflow"
      tone={STEP_TYPES.sub_workflow.tone}
      sub={short(name, 28)}
      subTitle={name}
    >
      <p className="text-2xs text-subtle">
        {config?.pass_context && 'ctx · '}depth ≤{config?.max_depth ?? 3}
      </p>
    </NodeFrame>
  )
}

function DecisionNodeRaw({ data, selected }: NodeProps) {
  const { step, status, metrics } = nodeData(data)
  const config = step.decision_config
  const options = config?.options ?? []

  return (
    <NodeFrame
      step={step}
      status={status}
      metrics={metrics}
      selected={selected}
      type="decision"
      tone={STEP_TYPES.decision.tone}
      sub={config ? `${config.resolver} · ${options.length} options` : undefined}
      handles={options.map((opt, i) => (
        <Handle
          key={opt.key}
          type="source"
          id={opt.key}
          position={Position.Right}
          style={{ top: `${((i + 1) / (options.length + 1)) * 100}%` }}
          className="!h-2 !w-2 !rounded-full !border-0 !bg-violet"
        />
      ))}
    />
  )
}

export const WorkflowEditorNode = memo(AgentStepNodeRaw)
export const ConditionNode = memo(ConditionNodeRaw)
export const NotificationNode = memo(NotificationNodeRaw)
export const HumanInputNode = memo(HumanInputNodeRaw)
export const ToolCallNode = memo(ToolCallNodeRaw)
export const LlmCallNode = memo(LlmCallNodeRaw)
export const BranchNode = memo(BranchNodeRaw)
export const MergeNode = memo(MergeNodeRaw)
export const SubWorkflowNode = memo(SubWorkflowNodeRaw)
export const DecisionNode = memo(DecisionNodeRaw)
