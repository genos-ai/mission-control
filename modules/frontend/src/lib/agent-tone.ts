/**
 * Agent name → icon and tone. The single source for how an agent looks.
 *
 * Icon: an exact agent name wins, then its domain, then `Bot`.
 * Tone: an exact agent name wins, then its domain (the first `.` segment of
 * the name), then `neutral`. Domains are the ones the catalog really has.
 */

import {
  Activity,
  Bot,
  Brain,
  CheckCircle2,
  FileText,
  GitBranch,
  Layers,
  ListTodo,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

import type { Tone } from './status-tone'

export interface AgentStyle {
  icon: LucideIcon
  tone: Tone
}

const AGENT_ICON: Record<string, LucideIcon> = {
  'mission.director.agent': Brain,
  'platform.director.agent': Brain,
  'mission.workflow.architect': GitBranch,
  'platform.health.agent': Activity,
  'research.searcher.agent': Search,
  'software.architecture.agent': Layers,
  'software.quality.agent': ShieldCheck,
  'system.planning.agent': ListTodo,
  'system.summarization.agent': FileText,
  'system.synthesis.agent': Sparkles,
  'system.verification.agent': CheckCircle2,
}

const DOMAIN_ICON: Record<string, LucideIcon> = {
  security: Shield,
}

const AGENT_TONE: Record<string, Tone> = {
  'system.synthesis.agent': 'violet',
  'system.verification.agent': 'success',
}

const DOMAIN_TONE: Record<string, Tone> = {
  mission: 'brand',
  platform: 'brand',
  software: 'info',
  research: 'warning',
  security: 'danger',
  deliberation: 'violet',
  system: 'neutral',
}

function agentDomain(agentName: string): string {
  return agentName.split('.')[0].toLowerCase()
}

export function agentStyle(agentName: string): AgentStyle {
  const domain = agentDomain(agentName)
  return {
    icon: AGENT_ICON[agentName] ?? DOMAIN_ICON[domain] ?? Bot,
    tone: AGENT_TONE[agentName] ?? DOMAIN_TONE[domain] ?? 'neutral',
  }
}
