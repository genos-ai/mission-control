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
 * Format a timestamp as "MMM d HH:mm" in the user's local timezone.
 * Input: ISO string or Date from the backend (always UTC).
 */
export function formatUtc(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
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
  const d = typeof value === 'string' ? new Date(value) : value
  if (isNaN(d.getTime())) return '—'

  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')

  return `${h}:${m}`
}
