import { useState } from 'react'
import { X, Play } from 'lucide-react'
import toast from 'react-hot-toast'
import { useRunObjective } from '@/hooks/use-executions'
import { Button } from '@/components/ui/button'
import { DialogFrame } from '@/components/ui/dialog-frame'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'

interface RunModalProps {
  missionId: string
  workflowName?: string
  missionBrief?: string
  onClose: () => void
  onStarted: (planId: string) => void
}

const GATE_OPTIONS = [
  { value: '', label: 'Default' },
  { value: 'interactive', label: 'Interactive (step-through)' },
  { value: 'manual', label: 'Manual (HTTP approval)' },
  { value: 'ai_assisted', label: 'AI Assisted' },
  { value: 'autonomous', label: 'Autonomous' },
]

export function RunModal({
  missionId,
  workflowName,
  missionBrief,
  onClose,
  onStarted,
}: RunModalProps) {
  const runObjective = useRunObjective(missionId)

  const [objective, setObjective] = useState(
    workflowName ? `Execute workflow: ${workflowName}` : '',
  )
  const [budget, setBudget] = useState('')
  const [gateMode, setGateMode] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!objective.trim()) {
      toast.error('Objective is required')
      return
    }

    try {
      const result = await runObjective.mutateAsync({
        objective: objective.trim(),
        gate_mode: gateMode || undefined,
        budget_ceiling_usd: budget ? parseFloat(budget) : undefined,
      })

      toast.success('Objective dispatched — streaming progress via console')
      onStarted(result.plan_id)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start run'
      if (msg.includes('in-progress')) {
        toast.error('Plan has tasks in progress — wait for completion first')
      } else {
        toast.error(msg)
      }
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

        <div>
          <label className="mb-1 block text-sm font-medium">
            Budget (USD)
          </label>
          <Input
            type="number"
            step="0.01"
            min="0"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="Default from mission"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Gate Mode</label>
          <Select
            value={gateMode}
            onChange={(e) => setGateMode(e.target.value)}
          >
            {GATE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </Select>
        </div>


        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={runObjective.isPending}>
            <Play className="mr-2 h-4 w-4" />
            {runObjective.isPending ? 'Planning...' : 'Start Run'}
          </Button>
        </div>
      </form>
    </DialogFrame>
  )
}
