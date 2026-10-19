import { agentShortName } from '@/lib/format'
import type { SessionMessage } from '@/types'
import type { ConsoleEvent } from '@/stores/console'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEFAULT_CHAT_AGENT = 'mission.director.agent'

/** The name shown for an agent in chat: the Director by role, others by their short name. */
export function agentLabel(agentId: string): string {
  if (agentId === DEFAULT_CHAT_AGENT) return 'Director'
  return agentId ? agentShortName(agentId) : 'agent'
}

// Event types to HIDE from inline chat (blacklist — new events show by default)
export const CHAT_HIDDEN_EVENT_TYPES = new Set([
  // Handled separately by streaming/message logic, not as inline events
  'agent.response.chunk',
  'agent.response.complete',
  'user.message.sent',
  // Too noisy / internal bookkeeping
  'session.cost.updated',
  'workflow.graph.updated',
  'system.session.created',
])

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

export type TimelineEntry =
  | { kind: 'message'; ts: string; data: SessionMessage }
  | { kind: 'event'; ts: string; data: ConsoleEvent }
