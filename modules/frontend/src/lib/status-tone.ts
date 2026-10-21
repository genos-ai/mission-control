/**
 * Status → visual style. The single source for how a state looks: every
 * screen picks its colour and icon from here instead of keeping its own map.
 *
 * Each map is keyed by the full status union, so adding a status to the type
 * fails compilation until it is given a style here. The API returns statuses
 * as plain strings; `styleFor` checks one against a map and throws on an
 * unknown value instead of quietly rendering it as something else.
 */

import {
  Archive,
  Check,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleDot,
  CircleSlash,
  Clock,
  Loader2,
  MessageSquare,
  MinusCircle,
  PauseCircle,
  RotateCcw,
  Settings2,
  User,
  XCircle,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import type { PlanTaskStatus } from '@/hooks/use-mission-plan'
import type { ConsoleEvent } from '@/stores/console'
import type { AttentionKind, MissionStatus, RunStatus } from '@/types'

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'brand' | 'violet' | 'neutral'

export interface StatusStyle {
  tone: Tone
  icon: LucideIcon
}

export const missionTone: Record<MissionStatus, StatusStyle> = {
  active: { tone: 'success', icon: CircleDot },
  paused: { tone: 'warning', icon: PauseCircle },
  archived: { tone: 'neutral', icon: Archive },
}

export const taskTone: Record<PlanTaskStatus, StatusStyle> = {
  proposed: { tone: 'neutral', icon: CircleDashed },
  approved: { tone: 'brand', icon: Circle },
  queued: { tone: 'brand', icon: CircleDot },
  running: { tone: 'warning', icon: Loader2 },
  completed: { tone: 'success', icon: CheckCircle2 },
  failed: { tone: 'danger', icon: XCircle },
  skipped: { tone: 'neutral', icon: MinusCircle },
  cancelled: { tone: 'neutral', icon: CircleSlash },
}

export const runTone: Record<RunStatus, StatusStyle> = {
  pending: { tone: 'neutral', icon: Circle },
  running: { tone: 'warning', icon: Loader2 },
  awaiting_input: { tone: 'warning', icon: User },
  completed: { tone: 'success', icon: CheckCircle2 },
  failed: { tone: 'danger', icon: XCircle },
  cancelled: { tone: 'neutral', icon: CircleSlash },
  timed_out: { tone: 'danger', icon: Clock },
}

/** What each kind of attention item looks like: a decision to make, a question to answer, a failure to retry. */
export const attentionTone: Record<AttentionKind, StatusStyle> = {
  task_approval: { tone: 'brand', icon: Check },
  gate: { tone: 'brand', icon: Check },
  human_input: { tone: 'warning', icon: User },
  retry: { tone: 'danger', icon: RotateCcw },
}

export const consoleCategoryTone: Record<ConsoleEvent['category'], StatusStyle> = {
  execution: { tone: 'brand', icon: Zap },
  chat: { tone: 'violet', icon: MessageSquare },
  system: { tone: 'neutral', icon: Settings2 },
}

/** Look up the style for a status the API returned as a plain string. */
export function styleFor<S extends string>(
  map: Record<S, StatusStyle>,
  status: string,
  kind: string,
): StatusStyle {
  if (!Object.prototype.hasOwnProperty.call(map, status)) {
    throw new Error(
      `Unknown ${kind} status "${status}". Known: ${Object.keys(map).join(', ')}. Add it to lib/status-tone.ts.`,
    )
  }
  return map[status as S]
}
