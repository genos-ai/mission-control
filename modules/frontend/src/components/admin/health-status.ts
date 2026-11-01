import { AlertTriangle, CheckCircle2, CircleSlash, XCircle } from 'lucide-react'

import type { StatusStyle } from '@/lib/status-tone'

/**
 * Statuses the health service reports: a component is healthy, unhealthy or
 * not configured, and the overall status is healthy or degraded. Keyed by the
 * plain strings the API returns; look one up with `styleFor`.
 */
export const healthTone = {
  healthy: { tone: 'success', icon: CheckCircle2 },
  degraded: { tone: 'warning', icon: AlertTriangle },
  unhealthy: { tone: 'danger', icon: XCircle },
  not_configured: { tone: 'neutral', icon: CircleSlash },
} satisfies Record<string, StatusStyle>
