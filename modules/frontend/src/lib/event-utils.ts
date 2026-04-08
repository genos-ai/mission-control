import {
  Brain,
  Zap,
  CheckCircle,
  XCircle,
  Wrench,
  FileText,
  AlertTriangle,
  RotateCcw,
  Scale,
  Play,
} from 'lucide-react'
import { createElement } from 'react'

export const EVENT_ICONS: Record<string, React.ReactNode> = {
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
}

export function eventLabel(etype: string): string {
  const last = etype.split('.').slice(-2).join(' ')
  return last.charAt(0).toUpperCase() + last.slice(1)
}

export function eventDetail(etype: string, data: Record<string, unknown>): string {
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
  if (data.agent_id) return String(data.agent_id)
  if (data.step_id) return String(data.step_id)
  if (data.assigned_agent) return String(data.assigned_agent)
  return ''
}
