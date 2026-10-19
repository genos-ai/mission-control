/**
 * LiveActivityPanel — a run's activity as a vertical timeline: the planning
 * phase, every event so far, and the agents working right now at the live edge.
 */

import { useEffect, useRef, type ReactNode } from 'react'
import { Brain, Loader2 } from 'lucide-react'
import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/cn'
import { eventDetail, eventLabel, getEventIcon } from '@/lib/event-utils'
import { useLiveRunStore } from '@/stores/live-run'

export function LiveActivityPanel() {
  const phase = useLiveRunStore((s) => s.phase)
  const activeAgents = useLiveRunStore((s) => s.activeAgents)
  const thinkingBuffers = useLiveRunStore((s) => s.thinkingBuffers)
  const planningSteps = useLiveRunStore((s) => s.planningSteps)
  const eventLog = useLiveRunStore((s) => s.eventLog)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Keep the live edge in view as events arrive.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [eventLog.length, activeAgents.size, planningSteps.length])

  const agents = Array.from(activeAgents.entries())
  const planning = phase === 'planning'
  const empty = eventLog.length === 0 && agents.length === 0 && !planning

  return (
    <Panel ref={scrollRef} className="flex w-[360px] shrink-0 flex-col overflow-y-auto p-5">
      <p className="mb-4 text-xs text-subtle">Activity</p>

      {empty && (
        <p className="text-sm text-subtle">
          {phase === 'done'
            ? "This run has finished and its live events weren't kept. Its events, output and cost are in its row on the Runs tab."
            : 'Waiting for events…'}
        </p>
      )}

      {planning && (
        <TimelineItem
          running
          icon={<Loader2 className="h-3 w-3 animate-spin text-warning motion-reduce:animate-none" />}
          title="Planning execution"
          sub={
            planningSteps.length > 0 ? (
              <span className="flex flex-col gap-0.5">
                {planningSteps.map((ps, i) => (
                  <span key={i} className={cn(ps.step === 'error' && 'text-danger')}>
                    {ps.message}
                  </span>
                ))}
              </span>
            ) : undefined
          }
          last={eventLog.length === 0 && agents.length === 0}
        />
      )}

      {eventLog.map((ev, i) => {
        // The store itself reads `event.data ?? event`, so events may carry their fields at the top level.
        const data = (ev.data ?? ev) as Record<string, unknown>
        const detail = eventDetail(ev.event_type, data)
        return (
          <TimelineItem
            key={i}
            icon={getEventIcon(ev.event_type, data)}
            title={eventLabel(ev.event_type, data)}
            sub={detail || undefined}
            last={i === eventLog.length - 1 && agents.length === 0}
          />
        )
      })}

      {agents.map(([agentId, state], i) => {
        const thinking = thinkingBuffers.get(agentId)
        return (
          <TimelineItem
            key={agentId}
            running
            icon={<Brain className="h-3 w-3 animate-pulse-dot text-violet motion-reduce:animate-none" />}
            title={agentId}
            meta={state}
            sub={
              thinking ? (
                <span className="line-clamp-3 whitespace-pre-wrap font-mono italic">{thinking.slice(-300)}</span>
              ) : undefined
            }
            last={i === agents.length - 1}
          />
        )
      })}
    </Panel>
  )
}

/** One step on the timeline: a ringed icon on a connector line, a title, an optional meta and sub-line. */
function TimelineItem({
  icon,
  title,
  meta,
  sub,
  running = false,
  last = false,
}: {
  icon: ReactNode
  title: string
  meta?: string
  sub?: ReactNode
  running?: boolean
  last?: boolean
}) {
  return (
    <div className="relative flex gap-3 pb-4">
      {!last && <span className="absolute bottom-0 left-[10.5px] top-6 w-px bg-line" />}
      <span
        className={cn(
          'relative z-10 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border bg-panel',
          running ? 'border-warning/45' : 'border-border-strong',
        )}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1 pt-px">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-base">{title}</span>
          {meta && <span className="shrink-0 font-mono text-2xs text-subtle">{meta}</span>}
        </div>
        {sub && <div className="mt-0.5 text-xs text-subtle [overflow-wrap:anywhere]">{sub}</div>}
      </div>
    </div>
  )
}
