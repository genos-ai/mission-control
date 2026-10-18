import { useState } from 'react'
import { Loader2, CheckCircle, XCircle, RefreshCw, StopCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useHealthCheck, useEmergencyStop } from '@/hooks/use-admin'
import { Panel, PanelContent } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
import { Button } from '@/components/ui/button'


export default function AdminHealthPage() {
  const { data: health, isLoading, refetch, isFetching } = useHealthCheck()

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">System Health</h2>
          {health && (
            <StatusPill tone={health.status === 'healthy' ? 'success' : 'danger'}>
              {health.status}
            </StatusPill>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 mr-1" />
          )}
          Refresh
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Auto-refreshes every 30 seconds.
      </p>

      {health?.checks && (
        <div className="space-y-2">
          {Object.entries(health.checks).map(([name, check]) => (
            <Panel key={name}>
              <PanelContent className="flex items-center justify-between py-3 px-4">
                <div className="flex items-center gap-3">
                  {check.status === 'healthy' || check.status === 'ok' ? (
                    <CheckCircle className="h-4 w-4 text-emerald-500" />
                  ) : (
                    <XCircle className="h-4 w-4 text-destructive" />
                  )}
                  <span className="text-sm font-medium">{name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {check.latency_ms != null && (
                    <span>{check.latency_ms.toFixed(0)}ms</span>
                  )}
                  <StatusPill
                    tone={
                      check.status === 'healthy' || check.status === 'ok'
                        ? 'success'
                        : 'danger'
                    }
                  >
                    {check.status}
                  </StatusPill>
                  {check.error && (
                    <span className="text-destructive truncate max-w-[200px]">
                      {check.error}
                    </span>
                  )}
                </div>
              </PanelContent>
            </Panel>
          ))}
        </div>
      )}

      <EmergencyStopSection />
    </div>
  )
}


function EmergencyStopSection() {
  const emergencyStop = useEmergencyStop()
  const [confirming, setConfirming] = useState(false)

  async function handleStop() {
    try {
      const result = await emergencyStop.mutateAsync()
      toast.success(result.message)
      setConfirming(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Emergency stop failed')
    }
  }

  return (
    <Panel className="border-destructive/50">
      <PanelContent className="flex items-center justify-between py-4 px-4">
        <div>
          <h3 className="text-sm font-semibold">Emergency Stop</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Pause all active autonomous plans. Stops the daemon from dispatching
            new work. In-flight runs finish but no new waves start.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {confirming ? (
            <>
              <span className="text-xs text-destructive font-medium">
                Are you sure?
              </span>
              <Button
                size="sm"
                variant="secondary"
                className="h-7 text-xs"
                onClick={() => setConfirming(false)}
                disabled={emergencyStop.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-7 gap-1 text-xs"
                onClick={handleStop}
                disabled={emergencyStop.isPending}
              >
                {emergencyStop.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <StopCircle className="h-3 w-3" />
                )}
                Stop All
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="destructive"
              className="h-7 gap-1 text-xs"
              onClick={() => setConfirming(true)}
            >
              <StopCircle className="h-3 w-3" />
              Emergency Stop
            </Button>
          )}
        </div>
      </PanelContent>
    </Panel>
  )
}
