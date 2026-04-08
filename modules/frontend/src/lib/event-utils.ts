import {
  Brain,
  Zap,
  CheckCircle,
  XCircle,
  Wrench,
  FileText,
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
  if (data.agent_id) return String(data.agent_id)
  if (data.step_id) return String(data.step_id)
  if (data.assigned_agent) return String(data.assigned_agent)
  return ''
}
