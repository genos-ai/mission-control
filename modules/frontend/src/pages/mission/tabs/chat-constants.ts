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
  'mission.workflow.agent':       GitBranch,
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

// Narrative event types to show inline in chat
export const INLINE_NARRATIVE_TYPES = new Set([
  'agent.thinking.started',
  'agent.tool.called',
  'agent.tool.returned',
  'plan.step.started',
  'plan.step.completed',
  'system.execution.created',
  'system.execution.completed',
  'mission.artifact.found',
])

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

export type TimelineEntry =
  | { kind: 'message'; ts: string; data: SessionMessage }
  | { kind: 'event'; ts: string; data: ConsoleEvent }
