import { Loader2, RefreshCw } from 'lucide-react'
import { useHealthCheck } from '@/hooks/use-admin'
import { EmergencyStopPanel } from '@/components/admin/emergency-stop-panel'
import { HealthChecksPanel } from '@/components/admin/health-checks-panel'
import { healthTone } from '@/components/admin/health-status'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { StatusPill } from '@/components/ui/status-pill'
import { statusLabel } from '@/lib/format'
import { styleFor } from '@/lib/status-tone'

export default function AdminHealthPage() {
  const { data: health, isLoading, refetch, isFetching } = useHealthCheck()

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Spinner className="h-5 w-5" />
      </div>
    )
  }

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-base font-medium">System health</h2>
            {health && (
              <StatusPill tone={styleFor(healthTone, health.status, 'health').tone}>
                {statusLabel(health.status)}
              </StatusPill>
            )}
          </div>
          <p className="mt-1 text-sm text-subtle">Auto-refreshes every 30 seconds.</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </Button>
      </div>

      {health?.checks && <HealthChecksPanel checks={health.checks} />}

      <EmergencyStopPanel />
    </>
  )
}
