import { useState } from 'react'
import { Loader2, StopCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useEmergencyStop } from '@/hooks/use-admin'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'

/** Pauses every active autonomous plan, behind an inline "Are you sure?" step. */
export function EmergencyStopPanel() {
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
    <Panel className="flex flex-wrap items-center justify-between gap-3 border-danger/30 p-4">
      <div className="min-w-0 flex-1 basis-[320px]">
        <h3 className="text-base font-medium">Emergency stop</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Pause all active autonomous plans. Stops the daemon from dispatching
          new work. In-flight runs finish but no new waves start.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {confirming ? (
          <>
            <span className="text-xs font-medium text-danger">Are you sure?</span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setConfirming(false)}
              disabled={emergencyStop.isPending}
            >
              Cancel
            </Button>
            <Button size="sm" variant="destructive" onClick={handleStop} disabled={emergencyStop.isPending}>
              {emergencyStop.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
              ) : (
                <StopCircle className="h-3 w-3" />
              )}
              Stop all
            </Button>
          </>
        ) : (
          <Button size="sm" variant="destructive" onClick={() => setConfirming(true)}>
            <StopCircle className="h-3 w-3" />
            Emergency stop
          </Button>
        )}
      </div>
    </Panel>
  )
}
