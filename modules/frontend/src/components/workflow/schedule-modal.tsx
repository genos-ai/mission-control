import { useMemo, useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { FilterChip } from '@/components/ui/filter-chip'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Segmented } from '@/components/ui/segmented'
import { Textarea } from '@/components/ui/textarea'
import { useCreateMissionSchedule, useUpdateMissionSchedule } from '@/hooks/use-mission-schedules'
import { useMissionWorkflows } from '@/hooks/use-workflows'
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
  MissionScheduleCreate,
  MissionScheduleKind,
  MissionScheduleResponse,
  MissionScheduleUpdate,
} from '@/types'

const LABEL_CLASS = 'mb-1 block text-xs font-medium text-muted-foreground'
const NAME_PATTERN = '[a-z0-9][a-z0-9\\-]{0,99}'
const SECONDS_PER_HOUR = 3600

const KIND_OPTIONS: { value: MissionScheduleKind; label: string }[] = [
  { value: 'objective', label: 'Objective' },
  { value: 'workflow_definition', label: 'Saved workflow' },
]

interface ParamRow {
  key: string
  value: string
}

/** Every IANA zone the browser knows, plus the given one if the browser omits it (e.g. "UTC"). */
function timeZoneOptions(current: string): string[] {
  const zones = Intl.supportedValuesOf('timeZone')
  return zones.includes(current) ? zones : [current, ...zones]
}

/** An ISO timestamp as the value of a datetime-local input, in the browser's time. */
function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function toParamRows(params: Record<string, unknown> | undefined): ParamRow[] {
  return Object.entries(params ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === 'string' ? value : JSON.stringify(value),
  }))
}

function fromParamRows(rows: ParamRow[]): Record<string, unknown> {
  return Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]))
}

interface ScheduleModalProps {
  missionId: string
  /** Preselects a saved workflow when creating from a workflow card. */
  workflowDefinitionId?: string
  onClose: () => void
  /** When present, the modal edits this schedule instead of creating one. */
  schedule?: MissionScheduleResponse
}

export function ScheduleModal({
  missionId,
  workflowDefinitionId,
  onClose,
  schedule,
}: ScheduleModalProps) {
  const isEdit = !!schedule
  const createMutation = useCreateMissionSchedule(missionId)
  const updateMutation = useUpdateMissionSchedule(missionId)
  const { data: workflows } = useMissionWorkflows(missionId)

  const [name, setName] = useState(schedule?.name ?? '')
  const [kind, setKind] = useState<MissionScheduleKind>(
    schedule?.kind ?? (workflowDefinitionId ? 'workflow_definition' : 'objective'),
  )
  const [objective, setObjective] = useState(schedule?.objective_template ?? '')
  const [workflowId, setWorkflowId] = useState(
    schedule?.workflow_definition_id ?? workflowDefinitionId ?? '',
  )
  const [params, setParams] = useState<ParamRow[]>(() => toParamRows(schedule?.workflow_parameters))
  const [cronState, setCronState] = useState<CronBuilderState>(() =>
    schedule ? parseCron(schedule.cron_expression) : DEFAULT_CRON_STATE,
  )
  const [timeZone, setTimeZone] = useState(
    schedule?.time_zone_name ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
  )
  const [startsAt, setStartsAt] = useState(toLocalInput(schedule?.starts_at ?? null))
  const [endsAt, setEndsAt] = useState(toLocalInput(schedule?.ends_at ?? null))
  const [maxRuns, setMaxRuns] = useState(schedule?.max_runs != null ? String(schedule.max_runs) : '')
  const [catchUpHours, setCatchUpHours] = useState(
    schedule ? String(schedule.catch_up_window_seconds / SECONDS_PER_HOUR) : '',
  )

  const zones = useMemo(() => timeZoneOptions(timeZone), [timeZone])

  const patch = (p: Partial<CronBuilderState>) => setCronState((s) => ({ ...s, ...p }))
  const toggleWeekday = (d: number) =>
    setCronState((s) => ({
      ...s,
      weekdays: s.weekdays.includes(d) ? s.weekdays.filter((x) => x !== d) : [...s.weekdays, d],
    }))
  const setParam = (i: number, p: Partial<ParamRow>) =>
    setParams((rows) => rows.map((r, j) => (j === i ? { ...r, ...p } : r)))

  const cron = buildCron(cronState)
  const summary = describeSchedule(cronState)
  const weeklyNoDays = cronState.frequency === 'weekly' && cronState.weekdays.length === 0
  const customEmpty = cronState.frequency === 'custom' && !cronState.raw.trim()
  const targetMissing = kind === 'objective' ? !objective.trim() : !workflowId
  const canSubmit = !weeklyNoDays && !customEmpty && !targetMissing && !!name

  const isObjective = kind === 'objective'
  const target = {
    objective_template: isObjective ? objective : null,
    workflow_definition_id: isObjective ? null : workflowId,
    workflow_parameters: isObjective ? {} : fromParamRows(params),
  }
  const bounds = {
    starts_at: fromLocalInput(startsAt),
    ends_at: fromLocalInput(endsAt),
    max_runs: maxRuns ? parseInt(maxRuns) : null,
    catch_up_window_seconds: catchUpHours
      ? Math.round(parseFloat(catchUpHours) * SECONDS_PER_HOUR)
      : null,
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    if (schedule) {
      // Send only what changed: an unchanged spec field would still re-probe the
      // spec, and kind cannot change.
      const next: MissionScheduleUpdate = {
        name,
        ...target,
        cron_expression: cron,
        time_zone_name: timeZone,
        starts_at: bounds.starts_at,
        ends_at: bounds.ends_at,
        max_runs: bounds.max_runs,
        catch_up_window_seconds: bounds.catch_up_window_seconds,
      }
      const current: MissionScheduleUpdate = {
        name: schedule.name,
        objective_template: schedule.objective_template,
        workflow_definition_id: schedule.workflow_definition_id,
        workflow_parameters: schedule.workflow_parameters,
        cron_expression: schedule.cron_expression,
        time_zone_name: schedule.time_zone_name,
        starts_at: fromLocalInput(toLocalInput(schedule.starts_at)),
        ends_at: fromLocalInput(toLocalInput(schedule.ends_at)),
        max_runs: schedule.max_runs,
        catch_up_window_seconds: schedule.catch_up_window_seconds,
      }
      const data = Object.fromEntries(
        Object.entries(next).filter(
          ([k, v]) => JSON.stringify(v) !== JSON.stringify(current[k as keyof MissionScheduleUpdate]),
        ),
      ) as MissionScheduleUpdate
      if (Object.keys(data).length === 0) {
        onClose()
        return
      }
      updateMutation.mutate(
        { scheduleId: schedule.id, data },
        {
          onSuccess: () => {
            toast.success('Schedule updated')
            onClose()
          },
          onError: (err) => toast.error(err.message),
        },
      )
      return
    }

    const data: MissionScheduleCreate = {
      name,
      kind,
      ...target,
      cron_expression: cron,
      time_zone_name: timeZone,
      ...bounds,
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
  const title = isEdit ? 'Edit Schedule' : 'Create Schedule'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm">
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-md overflow-y-auto p-5 shadow-lg"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-medium">{title}</h3>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className={LABEL_CLASS}>Name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              pattern={NAME_PATTERN}
              title="Lowercase letters, digits and hyphens"
              placeholder="daily-report"
              required
            />
          </div>

          {/* Target */}
          <div>
            <label className={LABEL_CLASS}>What runs?</label>
            <Segmented
              label="Schedule kind"
              value={kind}
              onChange={setKind}
              options={KIND_OPTIONS}
              disabled={isEdit}
            />
          </div>

          {isObjective ? (
            <div>
              <label className={LABEL_CLASS}>Objective</label>
              <Textarea
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                rows={3}
                placeholder="Summarise {mission_name} activity for run {sequence}"
                required
              />
              <p className="mt-1 text-xs text-subtle">
                Placeholders: <span className="font-mono">{'{scheduled_for}'}</span>,{' '}
                <span className="font-mono">{'{sequence}'}</span>,{' '}
                <span className="font-mono">{'{mission_name}'}</span>
              </p>
            </div>
          ) : (
            <>
              <div>
                <label className={LABEL_CLASS}>Workflow</label>
                <Select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} required>
                  <option value="" disabled>
                    Choose a workflow
                  </option>
                  {(workflows ?? []).map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label className={LABEL_CLASS}>Parameters</label>
                <div className="flex flex-col gap-1.5">
                  {params.map((row, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <Input
                        value={row.key}
                        onChange={(e) => setParam(i, { key: e.target.value })}
                        placeholder="key"
                        aria-label="Parameter name"
                      />
                      <Input
                        value={row.value}
                        onChange={(e) => setParam(i, { value: e.target.value })}
                        placeholder="value"
                        aria-label="Parameter value"
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        type="button"
                        aria-label="Remove parameter"
                        onClick={() => setParams((rows) => rows.filter((_, j) => j !== i))}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    size="sm"
                    type="button"
                    className="self-start"
                    onClick={() => setParams((rows) => [...rows, { key: '', value: '' }])}
                  >
                    <Plus className="h-3 w-3" />
                    Add parameter
                  </Button>
                </div>
              </div>
            </>
          )}

          {/* Frequency */}
          <div>
            <label className={LABEL_CLASS}>How often?</label>
            <Select
              value={cronState.frequency}
              onChange={(e) => patch({ frequency: e.target.value as CronFrequency })}
            >
              {FREQUENCY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </div>

          {/* Hourly: minute past the hour */}
          {cronState.frequency === 'hourly' && (
            <div>
              <label className={LABEL_CLASS}>Minute past the hour</label>
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
              <label className={LABEL_CLASS}>Time of day</label>
              <Input
                type="time"
                value={cronState.time}
                onChange={(e) => patch({ time: e.target.value })}
              />
            </div>
          )}

          {/* Weekly: day picker */}
          {cronState.frequency === 'weekly' && (
            <div>
              <label className={LABEL_CLASS}>On which days?</label>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAY_LABELS.map((label, d) => (
                  <FilterChip
                    key={d}
                    active={cronState.weekdays.includes(d)}
                    onClick={() => toggleWeekday(d)}
                  >
                    {label}
                  </FilterChip>
                ))}
              </div>
            </div>
          )}

          {/* Monthly: day of month */}
          {cronState.frequency === 'monthly' && (
            <div>
              <label className={LABEL_CLASS}>Day of month</label>
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
              <label className={LABEL_CLASS}>Cron Expression</label>
              <Input
                value={cronState.raw}
                onChange={(e) => patch({ raw: e.target.value })}
                placeholder="0 8 * * 1-5"
                required
              />
              <p className="mt-1 text-xs text-subtle">minute hour day month weekday</p>
            </div>
          )}

          {/* Live preview */}
          <div className="rounded-card bg-raised px-3 py-2">
            <p className="text-base font-medium">{summary}</p>
            <p className="mt-0.5 font-mono text-2xs text-muted-foreground">
              {cron || '—'} · {timeZone}
            </p>
          </div>

          <div>
            <label className={LABEL_CLASS}>Time zone</label>
            <Select value={timeZone} onChange={(e) => setTimeZone(e.target.value)} required>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </Select>
            <p className="mt-1 text-xs text-subtle">
              Cron times are evaluated in this time zone, including daylight-saving changes.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL_CLASS}>Starts at</label>
              <Input
                type="datetime-local"
                value={startsAt}
                onChange={(e) => setStartsAt(e.target.value)}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Ends at</label>
              <Input
                type="datetime-local"
                value={endsAt}
                onChange={(e) => setEndsAt(e.target.value)}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Max runs</label>
              <Input
                type="number"
                min="1"
                value={maxRuns}
                onChange={(e) => setMaxRuns(e.target.value)}
                placeholder="Unlimited"
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>Catch-up window (hours)</label>
              <Input
                type="number"
                min="0.01"
                step="any"
                value={catchUpHours}
                onChange={(e) => setCatchUpHours(e.target.value)}
                placeholder="Default"
              />
            </div>
          </div>
          <p className="text-xs text-subtle">Start and end are in your browser's local time.</p>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !canSubmit}>
              {isEdit ? 'Save' : 'Create Schedule'}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}
