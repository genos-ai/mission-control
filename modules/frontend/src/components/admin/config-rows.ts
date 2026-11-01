export type ConfigRow = { key: string; value: unknown }
export interface ConfigSection {
  /** Stable React key; prefixed so a real group named "general" cannot collide with the synthetic one. */
  id: string
  title: string
  rows: ConfigRow[]
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

/** Nested objects become dotted keys ("limits.max_steps"), so every value gets one row. */
export function flattenConfig(values: Record<string, unknown>, prefix = ''): ConfigRow[] {
  return Object.entries(values).flatMap(([key, value]) =>
    isRecord(value) ? flattenConfig(value, `${prefix}${key}.`) : [{ key: `${prefix}${key}`, value }],
  )
}

/** Each top-level group becomes a section; bare top-level values share a "general" one, listed first. */
export function configSections(config: Record<string, unknown>): ConfigSection[] {
  const entries = Object.entries(config)
  const loose = Object.fromEntries(entries.filter(([, v]) => !isRecord(v)))
  const groups = entries.flatMap(([title, v]) =>
    isRecord(v) ? [{ id: `group:${title}`, title, rows: flattenConfig(v) }] : [],
  )
  return [
    ...(Object.keys(loose).length > 0 ? [{ id: 'loose', title: 'general', rows: flattenConfig(loose) }] : []),
    ...groups,
  ]
}
