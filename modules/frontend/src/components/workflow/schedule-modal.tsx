import { useState } from 'react'
import { X } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCreateSchedule } from '@/hooks/use-workflows'
import type { WorkflowScheduleCreateRequest } from '@/types'

interface ScheduleModalProps {
  missionId: string
  workflowDefinitionId: string
  onClose: () => void
}

export function ScheduleModal({
  missionId,
  workflowDefinitionId,
  onClose,
}: ScheduleModalProps) {
  const createMutation = useCreateSchedule(missionId)

  const [cron, setCron] = useState('0 8 * * 1-5')
  const [timezone, setTimezone] = useState('UTC')
  const [description, setDescription] = useState('')
  const [budget, setBudget] = useState('')
  const [maxIterations, setMaxIterations] = useState('')
  const [cooldown, setCooldown] = useState('0')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: WorkflowScheduleCreateRequest = {
      workflow_definition_id: workflowDefinitionId,
      cron_expression: cron,
      timezone,
      description: description || undefined,
      budget_per_run_usd: budget ? parseFloat(budget) : undefined,
      max_iterations: maxIterations ? parseInt(maxIterations) : undefined,
      cooldown_seconds: cooldown ? parseInt(cooldown) : undefined,
    }
    createMutation.mutate(data, {
      onSuccess: () => {
        toast.success('Schedule created')
        onClose()
      },
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Create Schedule</h3>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium">
              Cron Expression
            </label>
            <Input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 8 * * 1-5"
              required
            />
            <p className="mt-1 text-xs text-muted-foreground">
              minute hour day month weekday
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">Timezone</label>
            <Input
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="UTC"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">Description</label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional description..."
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Budget per Run ($)
              </label>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="10.00"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                Max Iterations
              </label>
              <Input
                type="number"
                min="1"
                value={maxIterations}
                onChange={(e) => setMaxIterations(e.target.value)}
                placeholder="Unlimited"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">
              Cooldown (seconds)
            </label>
            <Input
              type="number"
              min="0"
              value={cooldown}
              onChange={(e) => setCooldown(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Create Schedule
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
