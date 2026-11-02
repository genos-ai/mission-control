import { useId, useState } from 'react'
import { X } from 'lucide-react'
import toast from 'react-hot-toast'

import { useEscapeKey } from '@/hooks/use-escape-key'
import { useUpdateMission } from '@/hooks/use-missions'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'

const SELECT_CLASS =
  'flex h-[38px] w-full rounded-md border border-border-strong bg-field px-3 text-md outline-none transition-colors focus:border-brand/60 focus:ring-2 focus:ring-brand/15'

interface MissionEditModalProps {
  mission: {
    description: string
    brief: string | null
    budget_ceiling_usd: number | null
    execution_environment: string | null
  }
  missionId: string
  onClose: () => void
}

/** Edits the mission's description, brief, budget and execution environment. */
export function MissionEditModal({ mission, missionId, onClose }: MissionEditModalProps) {
  const ids = useId()
  const updateMission = useUpdateMission(missionId)
  const [description, setDescription] = useState(mission.description)
  const [brief, setBrief] = useState(mission.brief ?? '')
  const [budget, setBudget] = useState(
    mission.budget_ceiling_usd != null ? String(mission.budget_ceiling_usd) : '',
  )
  const [execEnv, setExecEnv] = useState(mission.execution_environment ?? 'local')

  // aria-modal promises the keyboard a way out, as ConfirmDialog gives.
  useEscapeKey(onClose)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    updateMission.mutate(
      {
        description,
        brief: brief || undefined,
        budget_ceiling_usd: budget ? parseFloat(budget) : null,
        execution_environment: execEnv === 'local' ? undefined : execEnv,
      },
      {
        onSuccess: () => {
          toast.success('Mission updated')
          onClose()
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm">
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label="Mission settings"
        className="w-full max-w-md p-5 shadow-lg"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-medium">Mission settings</h3>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Field label="Description" htmlFor={`${ids}-description`}>
            <Textarea
              id={`${ids}-description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </Field>

          <Field label="Brief" htmlFor={`${ids}-brief`}>
            <Textarea
              id={`${ids}-brief`}
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={6}
              placeholder="Strategic brief for agents..."
            />
          </Field>

          <Field label="Budget (USD)" htmlFor={`${ids}-budget`}>
            <Input
              id={`${ids}-budget`}
              type="number"
              step="0.01"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="No limit"
            />
          </Field>

          <Field
            label="Execution environment"
            htmlFor={`${ids}-env`}
            hint="Container mode runs agent tasks inside Docker for full isolation. The container persists across runs within this mission."
          >
            <select
              id={`${ids}-env`}
              value={execEnv}
              onChange={(e) => setExecEnv(e.target.value)}
              className={SELECT_CLASS}
            >
              <option value="local">Local (in-process)</option>
              <option value="container">Container (Docker isolation)</option>
            </select>
          </Field>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMission.isPending}>
              {updateMission.isPending ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}
