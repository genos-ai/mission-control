/** Helpers for reading the free-form Mission Context Document. */

export function formatLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** True when a value would render nothing: it is blank, or holds only blank values at any depth. */
export function isEmptyValue(val: unknown): boolean {
  if (val == null || val === '') return true
  if (Array.isArray(val)) return val.every(isEmptyValue)
  if (typeof val === 'object') return Object.values(val as object).every(isEmptyValue)
  return false
}
