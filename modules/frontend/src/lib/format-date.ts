/**
 * UTC date formatting utility.
 *
 * All backend timestamps are stored in UTC. This utility ensures
 * the frontend always displays UTC — no local timezone conversion.
 *
 * Standard format: "Apr 14 12:55 UTC"
 */

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/**
 * Format a UTC timestamp as "MMM d HH:mm UTC".
 * Input: ISO string or Date. Always displays in UTC.
 */
export function formatUtc(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (isNaN(d.getTime())) return '—'

  const mon = MONTHS[d.getUTCMonth()]
  const day = d.getUTCDate()
  const h = String(d.getUTCHours()).padStart(2, '0')
  const m = String(d.getUTCMinutes()).padStart(2, '0')

  return `${mon} ${day} ${h}:${m} UTC`
}

/**
 * Format a UTC timestamp as "HH:mm UTC" (time only, for compact views).
 */
export function formatUtcTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (isNaN(d.getTime())) return '—'

  const h = String(d.getUTCHours()).padStart(2, '0')
  const m = String(d.getUTCMinutes()).padStart(2, '0')

  return `${h}:${m} UTC`
}
