import { useState } from 'react'
import { X, Play } from 'lucide-react'
import toast from 'react-hot-toast'
import { useStartMissionRun } from '@/hooks/use-mission-runs'
import { Button } from '@/components/ui/button'
import { DialogFrame } from '@/components/ui/dialog-frame'
import { Textarea } from '@/components/ui/textarea'

interface RunModalProps {
  missionId: string
  workflowName?: string
  missionBrief?: string
  onClose: () => void
  onStarted: (runId: string) => void
}

export function RunModal({
  missionId,
  workflowName,
  missionBrief,
  onClose,
  onStarted,
}: RunModalProps) {
  const startRun = useStartMissionRun(missionId)

  const [objective, setObjective] = useState(
    workflowName ? `Execute workflow: ${workflowName}` : '',
  )

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!objective.trim()) {
      toast.error('Objective is required')
      return
    }

    try {
      const run = await startRun.mutateAsync({ objective: objective.trim() })
      toast.success(`Run #${run.sequence} started — streaming progress via console`)
      onStarted(run.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start run')
    }
  }

  return (
    // The backdrop does not close it: a stray click would throw away a typed objective.
    <DialogFrame title="New Run" onCancel={onClose} width="md" closeOnBackdrop={false}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">New Run</h3>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Show mission brief as context */}
        {missionBrief && (
          <div className="rounded-md border bg-muted/30 px-3 py-2">
            <p className="text-[11px] font-medium text-muted-foreground">
              Mission Brief
            </p>
            <p className="mt-0.5 text-sm">{missionBrief}</p>
          </div>
        )}

        <div>
          <label className="mb-1 block text-sm font-medium">
            Objective
          </label>
          <p className="mb-1.5 text-xs text-muted-foreground">
            What should this run accomplish?
          </p>
          <Textarea
            autoFocus
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            rows={3}
            placeholder="e.g. Audit the auth module"
            required
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={startRun.isPending}>
            <Play className="mr-2 h-4 w-4" />
            {startRun.isPending ? 'Starting...' : 'Start Run'}
          </Button>
        </div>
      </form>
    </DialogFrame>
  )
}
