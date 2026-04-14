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
  // Backend timestamps are UTC but may lack the Z suffix.
  // Append Z if missing so the browser converts to local time correctly.
  const raw = typeof value === 'string'
    ? (value.endsWith('Z') || value.includes('+') ? value : value + 'Z')
    : value
  const d = typeof raw === 'string' ? new Date(raw) : raw
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
  const raw = typeof value === 'string'
    ? (value.endsWith('Z') || value.includes('+') ? value : value + 'Z')
    : value
  const d = typeof raw === 'string' ? new Date(raw) : raw
  if (isNaN(d.getTime())) return '—'

  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')

  return `${h}:${m}`
}
