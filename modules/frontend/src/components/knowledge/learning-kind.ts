/**
 * How each kind of learning looks. Keys are the kinds the backend extracts;
 * the tone and icon are presentation only.
 */

import { Brain, ShieldAlert, TrendingUp, Zap } from 'lucide-react'

import type { StatusStyle } from '@/lib/status-tone'

export interface LearningKindStyle extends StatusStyle {
  label: string
}

export const LEARNING_KIND: Record<string, LearningKindStyle> = {
  failure_pattern: { label: 'Failure pattern', tone: 'danger', icon: ShieldAlert },
  success_pattern: { label: 'Success pattern', tone: 'success', icon: TrendingUp },
  anti_pattern: { label: 'Anti-pattern', tone: 'warning', icon: ShieldAlert },
  retry_strategy: { label: 'Retry strategy', tone: 'info', icon: Zap },
  capability_gap: { label: 'Capability gap', tone: 'violet', icon: Brain },
}
