/**
 * Cron builder helpers.
 *
 * Lets non-technical users pick a schedule (Daily / Weekly / …) without
 * knowing crontab syntax. `buildCron` turns builder state into the 5-field
 * cron string the backend expects; `parseCron` does the reverse for edit
 * mode (falling back to 'custom' for anything the simple builder can't
 * represent); `describeSchedule` renders a plain-English summary.
 *
 * The generated fields (ranges like `1-5`, lists like `1,3,5`) are all
 * accepted by Temporal, which interprets mission schedule crons.
 */

export type CronFrequency =
  | 'hourly'
  | 'daily'
  | 'weekdays'
  | 'weekly'
  | 'monthly'
  | 'custom'

export interface CronBuilderState {
  frequency: CronFrequency
  /** "HH:MM" (24h) — used by daily / weekdays / weekly / monthly. */
  time: string
  /** Minute past each hour — used by hourly. */
  minute: number
  /** 0=Sun … 6=Sat — used by weekly. */
  weekdays: number[]
  /** 1…31 — used by monthly. */
  dayOfMonth: number
  /** Raw cron string — used by (and preserved for) custom. */
  raw: string
}

export const FREQUENCY_OPTIONS: { value: CronFrequency; label: string }[] = [
  { value: 'hourly', label: 'Every hour' },
  { value: 'daily', label: 'Every day' },
  { value: 'weekdays', label: 'Every weekday (Mon–Fri)' },
  { value: 'weekly', label: 'Weekly (pick days)' },
  { value: 'monthly', label: 'Monthly (pick a day)' },
  { value: 'custom', label: 'Custom (advanced cron)' },
]

export const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const DEFAULT_CRON_STATE: CronBuilderState = {
  frequency: 'daily',
  time: '08:00',
  minute: 0,
  weekdays: [1],
  dayOfMonth: 1,
  raw: '0 8 * * *',
}

const pad = (n: number) => String(n).padStart(2, '0')
const clampMinute = (n: number) => Math.min(59, Math.max(0, Math.trunc(n) || 0))
const clampDom = (n: number) => Math.min(31, Math.max(1, Math.trunc(n) || 1))

function parseTime(time: string): [number, number] {
  const [h, m] = time.split(':')
  const hh = Math.min(23, Math.max(0, parseInt(h || '0', 10) || 0))
  const mm = Math.min(59, Math.max(0, parseInt(m || '0', 10) || 0))
  return [hh, mm]
}

/** Turn builder state into a 5-field cron string. */
export function buildCron(s: CronBuilderState): string {
  if (s.frequency === 'custom') return s.raw.trim()
  const [hh, mm] = parseTime(s.time)
  switch (s.frequency) {
    case 'hourly':
      return `${clampMinute(s.minute)} * * * *`
    case 'daily':
      return `${mm} ${hh} * * *`
    case 'weekdays':
      return `${mm} ${hh} * * 1-5`
    case 'weekly': {
      const days = [...new Set(s.weekdays)].sort((a, b) => a - b)
      return `${mm} ${hh} * * ${days.length ? days.join(',') : '0'}`
    }
    case 'monthly':
      return `${mm} ${hh} ${clampDom(s.dayOfMonth)} * *`
  }
  return s.raw.trim()
}

const isInt = (v: string) => /^\d+$/.test(v)

/**
 * Parse a cron string back into builder state. Recognizes the patterns
 * `buildCron` produces; anything else resolves to 'custom' with the raw
 * string preserved so advanced schedules survive an edit round-trip.
 */
export function parseCron(expr: string): CronBuilderState {
  const base: CronBuilderState = { ...DEFAULT_CRON_STATE, raw: expr.trim() }
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return { ...base, frequency: 'custom' }
  const [min, hr, dom, mon, dow] = parts

  // Only month=* schedules map to the simple builder.
  if (mon !== '*') return { ...base, frequency: 'custom' }

  // Every hour: "M * * * *"
  if (hr === '*' && dom === '*' && dow === '*' && isInt(min)) {
    return { ...base, frequency: 'hourly', minute: clampMinute(parseInt(min, 10)) }
  }
  if (!isInt(min) || !isInt(hr)) return { ...base, frequency: 'custom' }
  const time = `${pad(parseInt(hr, 10))}:${pad(parseInt(min, 10))}`

  // Every day: "M H * * *"
  if (dom === '*' && dow === '*') return { ...base, frequency: 'daily', time }
  // Weekdays: "M H * * 1-5"
  if (dom === '*' && dow === '1-5') return { ...base, frequency: 'weekdays', time }
  // Weekly: "M H * * d[,d...]" with each day 0-6
  if (dom === '*' && /^[0-6](,[0-6])*$/.test(dow)) {
    const weekdays = [...new Set(dow.split(',').map((d) => parseInt(d, 10)))]
    return { ...base, frequency: 'weekly', time, weekdays }
  }
  // Monthly: "M H D * *"
  if (isInt(dom) && dow === '*') {
    return { ...base, frequency: 'monthly', time, dayOfMonth: clampDom(parseInt(dom, 10)) }
  }
  return { ...base, frequency: 'custom' }
}

/** Plain-English summary of the schedule (time is in the schedule's timezone). */
export function describeSchedule(s: CronBuilderState): string {
  if (s.frequency === 'custom') return describeCronExpression(s.raw)
  const [hh, mm] = parseTime(s.time)
  const t = `${pad(hh)}:${pad(mm)}`
  switch (s.frequency) {
    case 'hourly':
      return `Every hour at :${pad(clampMinute(s.minute))}`
    case 'daily':
      return `Every day at ${t}`
    case 'weekdays':
      return `Every weekday (Mon–Fri) at ${t}`
    case 'weekly': {
      const days = [...new Set(s.weekdays)].sort((a, b) => a - b).map((d) => WEEKDAY_LABELS[d])
      return days.length ? `Every ${days.join(', ')} at ${t}` : 'Pick at least one day'
    }
    case 'monthly':
      return `On day ${clampDom(s.dayOfMonth)} of each month at ${t}`
  }
  return describeCronExpression(s.raw)
}

/** Best-effort description of a raw cron string (used for custom mode). */
export function describeCronExpression(expr: string): string {
  const parsed = parseCron(expr)
  if (parsed.frequency !== 'custom') return describeSchedule(parsed)
  return expr.trim() ? `Custom cron: ${expr.trim()}` : 'Enter a cron expression'
}
