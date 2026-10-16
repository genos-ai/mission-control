import {
  Brain,
  Zap,
  CheckCircle,
  XCircle,
  Wrench,
  FileText,
  AlertTriangle,
  AlertCircle,
  RotateCcw,
  Scale,
  Play,
  Info,
  Activity,
  DollarSign,
  UserPlus,
  Radio,
  Package,
} from 'lucide-react'
import { createElement } from 'react'

// ---------------------------------------------------------------------------
// Static icon map — used for event types that don't need level-awareness
// ---------------------------------------------------------------------------

const EVENT_ICONS: Record<string, React.ReactNode> = {
  'mission.narrative': createElement(Radio, { className: 'h-3 w-3 text-sky-400' }),
  'mission.artifact.found': createElement(Package, { className: 'h-3 w-3 text-violet' }),
  'plan.created': createElement(FileText, { className: 'h-3 w-3 text-blue-400' }),
  'plan.step.started': createElement(Zap, { className: 'h-3 w-3 text-amber-400' }),
  'plan.step.completed': createElement(CheckCircle, { className: 'h-3 w-3 text-emerald-400' }),
  'agent.thinking.started': createElement(Brain, { className: 'h-3 w-3 text-purple-400' }),
  'agent.response.complete': createElement(CheckCircle, { className: 'h-3 w-3 text-emerald-400' }),
  'agent.tool.called': createElement(Wrench, { className: 'h-3 w-3 text-cyan-400' }),
  'agent.tool.returned': createElement(Wrench, { className: 'h-3 w-3 text-cyan-400' }),
  'agent.approval.requested': createElement(XCircle, { className: 'h-3 w-3 text-amber-400' }),
  // Execution history events
  'execution.record': createElement(Play, { className: 'h-3 w-3 text-blue-400' }),
  'task.completed': createElement(CheckCircle, { className: 'h-3 w-3 text-emerald-400' }),
  'task.failed': createElement(XCircle, { className: 'h-3 w-3 text-destructive' }),
  'task.skipped': createElement(AlertTriangle, { className: 'h-3 w-3 text-amber-400' }),
  'task.attempt.failed': createElement(RotateCcw, { className: 'h-3 w-3 text-destructive' }),
  'decision.retry': createElement(RotateCcw, { className: 'h-3 w-3 text-amber-400' }),
  'decision.fail': createElement(XCircle, { className: 'h-3 w-3 text-destructive' }),
  'decision.pass': createElement(CheckCircle, { className: 'h-3 w-3 text-emerald-400' }),
  'decision.escalate': createElement(Scale, { className: 'h-3 w-3 text-amber-400' }),
  // System events
  'system.execution.created': createElement(Activity, { className: 'h-3 w-3 text-blue-400' }),
  'system.execution.completed': createElement(CheckCircle, { className: 'h-3 w-3 text-emerald-400' }),
  'system.budget.warning': createElement(DollarSign, { className: 'h-3 w-3 text-amber-400' }),
  'system.session.created': createElement(UserPlus, { className: 'h-3 w-3 text-blue-400' }),
}

/**
 * Get the appropriate icon for an event, taking into account its data.level field.
 * Events like system.info can be info/warning/error — the icon reflects the actual severity.
 */
export function getEventIcon(eventType: string, data?: Record<string, unknown>): React.ReactNode {
  const level = String(data?.level ?? '')

  if (eventType === 'system.info') {
    if (level === 'error') return createElement(AlertCircle, { className: 'h-3 w-3 text-red-400' })
    if (level === 'warning') return createElement(AlertTriangle, { className: 'h-3 w-3 text-amber-400' })
    return createElement(Info, { className: 'h-3 w-3 text-blue-400' })
  }

  if (eventType === 'plan.phase') {
    const step = String(data?.step ?? '')
    if (step === 'error') return createElement(AlertCircle, { className: 'h-3 w-3 text-red-400' })
    return createElement(Activity, { className: 'h-3 w-3 text-blue-400' })
  }

  if (EVENT_ICONS[eventType]) return EVENT_ICONS[eventType]
  if (eventType.includes('failed') || eventType.includes('error')) {
    return createElement(XCircle, { className: 'h-3 w-3 text-red-400' })
  }
  return createElement(Zap, { className: 'h-3 w-3 text-gray-400' })
}

/**
 * Human-readable label for an event. Level-aware for system.info events.
 */
export function eventLabel(eventType: string, data?: Record<string, unknown>): string {
  if (eventType === 'system.info' && data) {
    const level = String(data.level ?? 'info')
    if (level === 'error') return 'System error'
    if (level === 'warning') return 'System warning'
    return 'System info'
  }

  if (eventType === 'plan.phase' && data) {
    const step = String(data.step ?? '')
    if (step === 'error') return 'Plan error'
    return 'Plan phase'
  }

  const last = eventType.split('.').slice(-2).join(' ')
  return last.charAt(0).toUpperCase() + last.slice(1)
}

export function eventDetail(etype: string, data: Record<string, unknown>): string {
  if (etype === 'mission.narrative') return String(data.narrative ?? '')
  if (etype === 'mission.artifact.found') {
    const title = String(data.title ?? '')
    const type = String(data.artifact_type ?? '')
    return type ? `[${type}] ${title}` : title
  }
  if (etype === 'agent.tool.called') {
    const tool = String(data.tool_name ?? '')
    const detail = (data.tool_args as Record<string, unknown>)?.detail
    return detail ? `${tool} — ${detail}` : tool
  }
  if (etype === 'agent.tool.returned') {
    const tool = String(data.tool_name ?? '')
    const result = data.result ? String(data.result).slice(0, 60) : ''
    return result ? `${tool} → ${result}` : tool
  }
  if (etype === 'execution.record') {
    const status = String(data.status ?? '')
    const obj = String(data.objective_statement ?? '').slice(0, 60)
    const cost = data.total_cost_usd != null ? ` $${Number(data.total_cost_usd).toFixed(4)}` : ''
    return `${status}${cost}${obj ? ` — ${obj}` : ''}`
  }
  if (etype.startsWith('task.attempt.failed')) {
    const tier = String(data.failure_tier ?? '').replace('tier_', 'T').replace('_', ' ')
    const reason = String(data.failure_reason ?? '').slice(0, 80)
    return `${data.agent_name} attempt ${data.attempt_number}${tier ? ` [${tier}]` : ''}: ${reason}`
  }
  if (etype.startsWith('task.')) {
    const agent = String(data.agent_name ?? '')
    const taskId = String(data.task_id ?? '')
    const cost = data.cost_usd != null ? ` $${Number(data.cost_usd).toFixed(4)}` : ''
    const attempts = data.attempt_count ? ` (${data.attempt_count} attempts)` : ''
    return `${agent} ${taskId}${cost}${attempts}`
  }
  if (etype.startsWith('decision.')) {
    const taskId = data.task_id ? ` [${data.task_id}]` : ''
    const reason = String(data.reasoning ?? '').slice(0, 80)
    return `${taskId} ${reason}`
  }
  if (etype === 'system.execution.created') {
    const obj = String(data.objective ?? '').slice(0, 80)
    const by = data.triggered_by ? ` by ${data.triggered_by}` : ''
    return `${obj}${by}`
  }
  if (etype === 'system.execution.completed') {
    const status = String(data.status ?? '')
    const cost = data.total_cost_usd != null ? ` $${Number(data.total_cost_usd).toFixed(4)}` : ''
    const dur = data.duration_seconds != null ? ` ${Number(data.duration_seconds).toFixed(1)}s` : ''
    return `${status}${cost}${dur}`
  }
  if (etype === 'system.budget.warning') {
    return String(data.message ?? '')
  }
  if (etype === 'system.session.created') {
    const agent = String(data.agent_id ?? '')
    const goal = String(data.goal ?? '')
    return agent ? `${agent} — ${goal}` : goal
  }
  if (etype === 'system.info') {
    return String(data.message ?? '')
  }
  if (etype === 'plan.phase') {
    return String(data.message ?? '')
  }
  if (data.agent_id) return String(data.agent_id)
  if (data.step_id) return String(data.step_id)
  if (data.assigned_agent) return String(data.assigned_agent)
  return ''
}
