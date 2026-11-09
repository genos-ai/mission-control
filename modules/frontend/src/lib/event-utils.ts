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
  type LucideIcon,
} from 'lucide-react'
import { createElement } from 'react'

import { cn } from '@/lib/cn'
import type { Tone } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'

// ---------------------------------------------------------------------------
// Icon and tone per event type — for event types that don't need level-awareness
// ---------------------------------------------------------------------------

interface EventStyle {
  icon: LucideIcon
  tone: Tone
}

const EVENT_STYLES: Record<string, EventStyle> = {
  'mission.narrative': { icon: Radio, tone: 'info' },
  'mission.artifact.found': { icon: Package, tone: 'violet' },
  'plan.created': { icon: FileText, tone: 'info' },
  'plan.step.started': { icon: Zap, tone: 'warning' },
  'plan.step.completed': { icon: CheckCircle, tone: 'success' },
  'agent.thinking.started': { icon: Brain, tone: 'violet' },
  'agent.response.complete': { icon: CheckCircle, tone: 'success' },
  'agent.tool.called': { icon: Wrench, tone: 'info' },
  'agent.tool.returned': { icon: Wrench, tone: 'info' },
  'gate.request.opened': { icon: XCircle, tone: 'warning' },
  // Execution history events
  'execution.record': { icon: Play, tone: 'info' },
  'task.completed': { icon: CheckCircle, tone: 'success' },
  'task.failed': { icon: XCircle, tone: 'danger' },
  'task.skipped': { icon: AlertTriangle, tone: 'warning' },
  'task.attempt.failed': { icon: RotateCcw, tone: 'danger' },
  'decision.retry': { icon: RotateCcw, tone: 'warning' },
  'decision.fail': { icon: XCircle, tone: 'danger' },
  'decision.pass': { icon: CheckCircle, tone: 'success' },
  'decision.escalate': { icon: Scale, tone: 'warning' },
  // System events
  'system.execution.created': { icon: Activity, tone: 'info' },
  'system.execution.completed': { icon: CheckCircle, tone: 'success' },
  'system.budget.warning': { icon: DollarSign, tone: 'warning' },
  'system.session.created': { icon: UserPlus, tone: 'info' },
}

function eventStyle(eventType: string, data?: Record<string, unknown>): EventStyle {
  const level = String(data?.level ?? '')

  if (eventType === 'system.info') {
    if (level === 'error') return { icon: AlertCircle, tone: 'danger' }
    if (level === 'warning') return { icon: AlertTriangle, tone: 'warning' }
    return { icon: Info, tone: 'info' }
  }

  if (eventType === 'plan.phase') {
    if (String(data?.step ?? '') === 'error') return { icon: AlertCircle, tone: 'danger' }
    return { icon: Activity, tone: 'info' }
  }

  if (EVENT_STYLES[eventType]) return EVENT_STYLES[eventType]
  if (eventType.includes('failed') || eventType.includes('error')) {
    return { icon: XCircle, tone: 'danger' }
  }
  return { icon: Zap, tone: 'neutral' }
}

/**
 * The icon for an event, in its tone. Events like system.info can be
 * info/warning/error — the icon reflects the actual severity (data.level).
 */
export function getEventIcon(
  eventType: string,
  data?: Record<string, unknown>,
  className?: string,
): React.ReactNode {
  const { icon, tone } = eventStyle(eventType, data)
  return createElement(icon, { className: cn('h-3 w-3', TONE_TEXT[tone], className) })
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
