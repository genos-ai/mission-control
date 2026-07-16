import { useState } from 'react'
import { X } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCreateSchedule, useUpdateSchedule } from '@/hooks/use-workflows'
import {
  buildCron,
  parseCron,
  describeSchedule,
  DEFAULT_CRON_STATE,
  FREQUENCY_OPTIONS,
  WEEKDAY_LABELS,
  type CronBuilderState,
  type CronFrequency,
} from '@/lib/cron'
import type {
  WorkflowSchedule,
  WorkflowScheduleCreateRequest,
  WorkflowScheduleUpdateRequest,
} from '@/types'

// Matches the shared Input styling so native <select>/<input> blend in.
const FIELD_CLASS =
  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

interface ScheduleModalProps {
  missionId: string
  workflowDefinitionId: string
  onClose: () => void
  /** When present, the modal edits this schedule instead of creating one. */
  schedule?: WorkflowSchedule
}

export function ScheduleModal({
  missionId,
  workflowDefinitionId,
  onClose,
  schedule,
}: ScheduleModalProps) {
  const isEdit = !!schedule
  // Rules of Hooks: both mutations are constructed unconditionally. In create
  // mode the update mutation carries a harmless '' id and simply never fires.
  const createMutation = useCreateSchedule(missionId)
  const updateMutation = useUpdateSchedule(missionId, schedule?.id ?? '')

  const [cronState, setCronState] = useState<CronBuilderState>(() =>
    schedule ? parseCron(schedule.cron_expression) : DEFAULT_CRON_STATE,
  )
  const [timezone, setTimezone] = useState(schedule?.timezone ?? 'UTC')
  const [description, setDescription] = useState(schedule?.description ?? '')
  const [budget, setBudget] = useState(
    schedule?.budget_per_run_usd != null ? String(schedule.budget_per_run_usd) : '',
  )
  const [maxIterations, setMaxIterations] = useState(
    schedule?.max_iterations != null ? String(schedule.max_iterations) : '',
  )
  const [cooldown, setCooldown] = useState(
    schedule ? String(schedule.cooldown_seconds) : '0',
  )

  const patch = (p: Partial<CronBuilderState>) =>
    setCronState((s) => ({ ...s, ...p }))
  const toggleWeekday = (d: number) =>
    setCronState((s) => ({
      ...s,
      weekdays: s.weekdays.includes(d)
        ? s.weekdays.filter((x) => x !== d)
        : [...s.weekdays, d],
    }))

  const cron = buildCron(cronState)
  const summary = describeSchedule(cronState)
  const weeklyNoDays = cronState.frequency === 'weekly' && cronState.weekdays.length === 0
  const customEmpty = cronState.frequency === 'custom' && !cronState.raw.trim()
  const canSubmit = !weeklyNoDays && !customEmpty

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    if (isEdit) {
      const data: WorkflowScheduleUpdateRequest = {
        cron_expression: cron,
        timezone,
        description,
        budget_per_run_usd: budget ? parseFloat(budget) : null,
        max_iterations: maxIterations ? parseInt(maxIterations) : null,
        cooldown_seconds: cooldown ? parseInt(cooldown) : 0,
      }
      updateMutation.mutate(data, {
        onSuccess: () => {
          toast.success('Schedule updated')
          onClose()
        },
        onError: (err) => toast.error(err.message),
      })
      return
    }

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

  const pending = isEdit ? updateMutation.isPending : createMutation.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">
            {isEdit ? 'Edit Schedule' : 'Create Schedule'}
          </h3>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Frequency */}
          <div>
            <label className="mb-1 block text-sm font-medium">How often?</label>
            <select
              className={FIELD_CLASS}
              value={cronState.frequency}
              onChange={(e) =>
                patch({ frequency: e.target.value as CronFrequency })
              }
            >
              {FREQUENCY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          {/* Hourly: minute past the hour */}
          {cronState.frequency === 'hourly' && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                Minute past the hour
              </label>
              <Input
                type="number"
                min="0"
                max="59"
                value={cronState.minute}
                onChange={(e) => patch({ minute: parseInt(e.target.value || '0') })}
              />
            </div>
          )}

          {/* Time of day (daily / weekdays / weekly / monthly) */}
          {['daily', 'weekdays', 'weekly', 'monthly'].includes(cronState.frequency) && (
            <div>
              <label className="mb-1 block text-sm font-medium">Time of day</label>
              <input
                type="time"
                className={FIELD_CLASS}
                value={cronState.time}
                onChange={(e) => patch({ time: e.target.value })}
              />
            </div>
          )}

          {/* Weekly: day picker */}
          {cronState.frequency === 'weekly' && (
            <div>
              <label className="mb-1 block text-sm font-medium">On which days?</label>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAY_LABELS.map((label, d) => {
                  const active = cronState.weekdays.includes(d)
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => toggleWeekday(d)}
                      className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                        active
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-input text-muted-foreground hover:bg-accent'
                      }`}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Monthly: day of month */}
          {cronState.frequency === 'monthly' && (
            <div>
              <label className="mb-1 block text-sm font-medium">Day of month</label>
              <Input
                type="number"
                min="1"
                max="31"
                value={cronState.dayOfMonth}
                onChange={(e) => patch({ dayOfMonth: parseInt(e.target.value || '1') })}
              />
            </div>
          )}

          {/* Custom: raw cron */}
          {cronState.frequency === 'custom' && (
            <div>
              <label className="mb-1 block text-sm font-medium">
                Cron Expression
              </label>
              <Input
                value={cronState.raw}
                onChange={(e) => patch({ raw: e.target.value })}
                placeholder="0 8 * * 1-5"
                required
              />
              <p className="mt-1 text-xs text-muted-foreground">
                minute hour day month weekday
              </p>
            </div>
          )}

          {/* Live preview */}
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2">
            <p className="text-[13px] font-medium">{summary}</p>
            <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
              {cron || '—'} · {timezone}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">Timezone</label>
            <Input
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="UTC"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Times above are interpreted in this timezone.
            </p>
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
            <Button type="submit" disabled={pending || !canSubmit}>
              {isEdit ? 'Save' : 'Create Schedule'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
