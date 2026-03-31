import { useEffect, useRef } from 'react'
import {
  Brain,
  Zap,
  CheckCircle,
  XCircle,
  AlertTriangle,
  FileText,
  Wrench,
  Loader2,
  Users,
  Database,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useLiveRunStore } from '@/stores/live-run'

const EVENT_ICONS: Record<string, React.ReactNode> = {
  'plan.created': <FileText className="h-3 w-3 text-blue-400" />,
  'plan.step.started': <Zap className="h-3 w-3 text-amber-400" />,
  'plan.step.completed': <CheckCircle className="h-3 w-3 text-emerald-400" />,
  'agent.thinking.started': <Brain className="h-3 w-3 text-purple-400" />,
  'agent.response.complete': (
    <CheckCircle className="h-3 w-3 text-emerald-400" />
  ),
  'agent.tool.called': <Wrench className="h-3 w-3 text-cyan-400" />,
  'agent.tool.returned': <Wrench className="h-3 w-3 text-cyan-400" />,
  'agent.approval.requested': <XCircle className="h-3 w-3 text-amber-400" />,
}

function eventLabel(etype: string): string {
  const last = etype.split('.').slice(-2).join(' ')
  return last.charAt(0).toUpperCase() + last.slice(1)
}

function eventDetail(etype: string, data: Record<string, unknown>): string {
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

const STEP_ICONS: Record<string, React.ReactNode> = {
  roster: <Users className="h-3 w-3 text-blue-400" />,
  context: <Database className="h-3 w-3 text-teal-400" />,
  thinking: <Brain className="h-3 w-3 text-purple-400" />,
  error: <AlertTriangle className="h-3 w-3 text-destructive" />,
}

export function LiveActivityPanel() {
  const phase = useLiveRunStore((s) => s.phase)
  const activeAgents = useLiveRunStore((s) => s.activeAgents)
  const thinkingBuffers = useLiveRunStore((s) => s.thinkingBuffers)
  const planningSteps = useLiveRunStore((s) => s.planningSteps)
  const eventLog = useLiveRunStore((s) => s.eventLog)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll event log to bottom
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [eventLog.length])

  return (
    <div className="flex h-full flex-col border-r">
      {/* Header */}
      <div className="border-b px-4 py-2">
        <h3 className="text-sm font-semibold text-muted-foreground">
          Live Activity
        </h3>
      </div>

      {/* Planning phase indicator */}
      {phase === 'planning' && (
        <div className="border-b bg-amber-500/5 px-4 py-3 space-y-2">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
            <span className="text-sm text-amber-600">Planning execution</span>
          </div>

          {/* Planning phase steps */}
          {planningSteps.length > 0 && (
            <div className="space-y-1">
              {planningSteps.map((ps, i) => (
                <div key={i} className={`flex items-start gap-2 text-xs ${ps.step === 'error' ? 'text-destructive' : 'text-muted-foreground'}`}>
                  <span className="mt-0.5 flex-shrink-0">
                    {STEP_ICONS[ps.step] ?? <Zap className="h-3 w-3 text-gray-400" />}
                  </span>
                  <span>{ps.message}</span>
                </div>
              ))}
            </div>
          )}

          {/* Planning agent thinking stream */}
          {activeAgents.size > 0 && (
            <div className="space-y-2">
              {Array.from(activeAgents.entries()).map(([agentId, agentState]) => (
                <div key={agentId}>
                  <div className="flex items-center gap-2">
                    <Brain className="h-3.5 w-3.5 text-purple-400 animate-pulse" />
                    <span className="text-xs font-medium truncate">
                      {agentId}
                    </span>
                    <Badge variant="secondary" className="text-[10px]">
                      {agentState}
                    </Badge>
                  </div>
                  {thinkingBuffers.get(agentId) && (
                    <p className="mt-1 ml-5 max-h-40 overflow-y-auto text-[11px] italic text-muted-foreground font-mono whitespace-pre-wrap">
                      {(thinkingBuffers.get(agentId) ?? '').slice(-600)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Active agents (executing phase) */}
      {phase !== 'planning' && activeAgents.size > 0 && (
        <div className="border-b px-4 py-2 space-y-1">
          {Array.from(activeAgents.entries()).map(([agentId, agentState]) => (
            <div key={agentId}>
              <div className="flex items-center gap-2">
                <Brain className="h-3.5 w-3.5 text-purple-400 animate-pulse" />
                <span className="text-xs font-medium truncate">
                  {agentId}
                </span>
                <Badge variant="secondary" className="text-[10px]">
                  {agentState}
                </Badge>
              </div>
              {thinkingBuffers.get(agentId) && (
                <p className="mt-1 ml-5 text-[11px] italic text-muted-foreground font-mono line-clamp-3 whitespace-pre-wrap">
                  {(thinkingBuffers.get(agentId) ?? '').slice(-300)}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Event stream */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-2">
        {eventLog.length === 0 && phase !== 'planning' && (
          <p className="text-xs text-muted-foreground">
            Waiting for events...
          </p>
        )}
        <div className="space-y-1">
          {eventLog.map((ev, i) => (
            <div
              key={i}
              className="flex items-start gap-2 text-xs text-muted-foreground"
            >
              <span className="mt-0.5 flex-shrink-0">
                {EVENT_ICONS[ev.event_type] ?? (
                  <Zap className="h-3 w-3 text-gray-400" />
                )}
              </span>
              <div className="min-w-0">
                <span className="font-medium text-foreground">
                  {eventLabel(ev.event_type)}
                </span>
                {eventDetail(ev.event_type, ev.data ?? ev) && (
                  <span className="ml-1.5 text-muted-foreground truncate">
                    {eventDetail(ev.event_type, ev.data ?? ev)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
