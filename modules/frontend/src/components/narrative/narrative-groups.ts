/**
 * Narrative events grouped by the session that emitted them.
 *
 * Everything shown in a group's header (start, outcome, cost, duration) is a
 * value an event carried. Nothing is estimated from timestamps: a session that
 * has not reported an outcome simply shows none.
 */

import type { ConsoleEvent } from '@/stores/console'

export interface NarrativeGroup {
  /** The session id; empty for events that arrived without one. */
  key: string
  /** The run the events belong to, when any event names one. */
  executionId: string
  /** What the run was asked to do, from its created event. */
  objective: string
  /** Timestamp of the session's first event, whether or not it is filtered out. */
  firstSeenAt: string
  /** When the latest run was created, from its created event; empty if none was received. */
  startedAt: string
  /** Outcome reported by a run-completed event; empty until one arrives. */
  status: string
  costUsd: number | null
  durationSeconds: number | null
  /** The events to show, after the hidden-type filter. */
  events: ConsoleEvent[]
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function amount(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

/**
 * Whether an event produces a row. Tool results and responses with nothing to
 * show render none, so they are left out of counts and cannot keep a panel alive.
 */
export function isRenderable(event: ConsoleEvent): boolean {
  const d = event.data
  switch (event.event_type) {
    case 'agent.tool.returned':
      // An error row is shown even without output; a success with no output says nothing.
      return String(d.status ?? 'success') === 'error' || String(d.result ?? '') !== ''
    case 'agent.response.complete': {
      const metadata = (d.metadata as Record<string, unknown> | undefined) ?? {}
      return String(d.full_content ?? '') !== '' || (typeof metadata.thinking === 'string' && metadata.thinking !== '')
    }
    default:
      return true
  }
}

function startGroup(key: string, first: ConsoleEvent): NarrativeGroup {
  return {
    key,
    executionId: '',
    objective: '',
    firstSeenAt: first.timestamp,
    startedAt: '',
    status: '',
    costUsd: null,
    durationSeconds: null,
    events: [],
  }
}

/** Fold what an event says about its run into the group's header fields. */
function absorb(group: NarrativeGroup, event: ConsoleEvent): void {
  const d = event.data
  if (!group.executionId) group.executionId = text(d.execution_record_id) || text(d.execution_id)

  switch (event.event_type) {
    case 'system.execution.created':
      // A session can host several runs and the header describes the latest, so
      // a new run must not inherit the previous run's id or outcome.
      group.executionId = text(d.execution_record_id) || text(d.execution_id)
      group.objective = text(d.objective)
      group.startedAt = event.timestamp
      group.status = ''
      group.costUsd = null
      group.durationSeconds = null
      break
    case 'system.execution.completed':
      group.status = text(d.status)
      group.costUsd = amount(d.total_cost_usd)
      group.durationSeconds = amount(d.duration_seconds)
      break
    case 'mission_plan.run.completed':
      group.status = text(d.run_status)
      group.costUsd = amount(d.run_cost_usd)
      break
    case 'session.cost.updated':
      // A running total, superseded by the cost the completed event reports.
      if (!group.status) group.costUsd = amount(d.cumulative_cost_usd)
      break
  }
}

/**
 * Group events by session, oldest activity first. Headers read every event, so
 * hiding an event type never hides a run's outcome; a group left with nothing
 * to show, counting events that render no row, is dropped.
 */
export function groupBySession(all: ConsoleEvent[], hiddenTypes: Set<string>): NarrativeGroup[] {
  const groups = new Map<string, NarrativeGroup>()
  for (const event of all) {
    const key = text(event.data.session_id)
    const group = groups.get(key) ?? startGroup(key, event)
    // Re-inserting moves the group to the end, so the session with the newest
    // event is always last and live events land where auto-scroll is looking.
    groups.delete(key)
    groups.set(key, group)
    absorb(group, event)
    if (!hiddenTypes.has(event.event_type) && isRenderable(event)) group.events.push(event)
  }
  return [...groups.values()].filter((group) => group.events.length > 0)
}
