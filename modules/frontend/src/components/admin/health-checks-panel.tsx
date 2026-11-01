import { Panel } from '@/components/ui/panel'
import { StatusIcon } from '@/components/ui/status-icon'
import { StatusPill } from '@/components/ui/status-pill'
import { healthTone } from '@/components/admin/health-status'
import { cn } from '@/lib/cn'
import { statusLabel } from '@/lib/format'
import { styleFor } from '@/lib/status-tone'
import type { HealthCheck } from '@/types'

const ROW_GRID = 'grid grid-cols-[minmax(120px,1fr)_130px_80px_minmax(0,1.5fr)] items-center gap-4 px-4'

/** One row per backing service the health check probes: status, round-trip time and any error. */
export function HealthChecksPanel({ checks }: { checks: HealthCheck['checks'] }) {
  const entries = Object.entries(checks)

  return (
    <Panel className="overflow-x-auto">
      <div className="min-w-[560px]">
        <div className={cn(ROW_GRID, 'py-2.5 text-2xs text-subtle')}>
          <span>Component</span>
          <span>Status</span>
          <span className="text-right">Latency</span>
          <span>Detail</span>
        </div>
        {entries.length === 0 ? (
          <p className="border-t border-line px-4 py-6 text-center text-sm text-subtle">No checks reported.</p>
        ) : (
          entries.map(([name, check]) => {
            const style = styleFor(healthTone, check.status, 'health')
            return (
              <div key={name} className={cn(ROW_GRID, 'border-t border-line py-[11px] text-sm')}>
                <span className="flex min-w-0 items-center gap-2">
                  <StatusIcon {...style} className="h-3.5 w-3.5" />
                  <span className="truncate font-medium">{name}</span>
                </span>
                <span>
                  <StatusPill tone={style.tone}>{statusLabel(check.status)}</StatusPill>
                </span>
                <span className="text-right font-mono text-text-3">
                  {check.latency_ms != null ? `${check.latency_ms.toFixed(0)}ms` : '—'}
                </span>
                <span className="truncate text-danger" title={check.error}>
                  {check.error}
                </span>
              </div>
            )
          })
        )}
      </div>
    </Panel>
  )
}
