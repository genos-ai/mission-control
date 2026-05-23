import {
  Bot,
  Brain,
  GitBranch,
  Activity,
  Layers,
  ShieldCheck,
  ListTodo,
  FileText,
  Sparkles,
  CheckCircle2,
  type LucideIcon,
} from 'lucide-react'
import type { SessionMessage } from '@/types'
import type { ConsoleEvent } from '@/stores/console'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEFAULT_CHAT_AGENT = 'mission.director.agent'

export const AGENT_ICONS: Record<string, LucideIcon> = {
  'mission.director.agent':       Brain,
  'platform.director.agent':      Brain,
  'mission.workflow.architect':   GitBranch,
  'platform.health.agent':        Activity,
  'software.architecture.agent':  Layers,
  'software.quality.agent':       ShieldCheck,
  'system.planning.agent':        ListTodo,
  'system.summarization.agent':   FileText,
  'system.synthesis.agent':       Sparkles,
  'system.verification.agent':    CheckCircle2,
}

export function getAgentIcon(name: string): LucideIcon {
  return AGENT_ICONS[name] ?? Bot
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
