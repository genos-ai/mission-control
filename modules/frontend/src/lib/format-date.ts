/**
 * Date formatting utility.
 *
 * All backend timestamps are stored in UTC. The browser converts
 * to the user's local timezone for display. No timezone suffix —
 * each user sees their own local time naturally.
 *
 * Standard format: "Apr 14 16:55"
 */

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/**
 * Parse a backend timestamp. Backend timestamps are UTC but may lack the Z
 * suffix; append it when missing so the browser reads them as UTC and converts
 * to local time correctly. An unparseable string yields an Invalid Date.
 */
export function parseUtc(value: string | Date): Date {
  if (typeof value !== 'string') return value
  return new Date(value.endsWith('Z') || value.includes('+') ? value : value + 'Z')
}

/**
 * Format a timestamp as "MMM d HH:mm" in the user's local timezone.
 * Input: ISO string or Date from the backend (always UTC).
 */
export function formatUtc(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = parseUtc(value)
  if (isNaN(d.getTime())) return '—'

  const mon = MONTHS[d.getMonth()]
  const day = d.getDate()
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')

  return `${mon} ${day} ${h}:${m}`
}

/**
 * Format a timestamp as "HH:mm" in the user's local timezone (compact).
 */
export function formatUtcTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = parseUtc(value)
  if (isNaN(d.getTime())) return '—'

  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')

  return `${h}:${m}`
}

/**
 * Wall-clock time between two timestamps: "12.3s", then "2m 5s".
 * "—" when either end is missing or the end precedes the start.
 */
export function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return '—'
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime()
  if (ms < 0) return '—'
  const sec = ms / 1000
  if (sec < 60) return `${sec.toFixed(1)}s`
  const min = Math.floor(sec / 60)
  const rem = Math.round(sec % 60)
  return `${min}m ${rem}s`
}

/** A running clock from a millisecond count: "4:12". */
export function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `${min}:${sec.toString().padStart(2, '0')}`
}
