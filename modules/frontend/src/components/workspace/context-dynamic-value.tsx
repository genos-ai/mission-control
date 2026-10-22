/**
 * Renders any shape of Mission Context Document value. The document is free-form
 * (agents add whatever sections they need), so the renderer follows the data
 * rather than a fixed list of fields.
 */

import { formatLabel, isEmptyValue } from '@/components/workspace/context-document'

const LABEL = 'text-2xs font-medium uppercase tracking-wider text-subtle'
const NESTED_BOX = 'rounded-chip border border-line px-2.5 py-2'

// Nesting deeper than this is shown as JSON rather than ever-narrower cards.
const MAX_CARD_DEPTH = 3

export function DynamicValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value == null) return null

  if (typeof value === 'string') {
    return value ? <p className="whitespace-pre-wrap">{value}</p> : null
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return <p className="font-mono text-sm">{String(value)}</p>
  }

  // Array of strings: a bullet list
  if (Array.isArray(value) && value.length > 0 && value.every((v) => typeof v === 'string')) {
    return (
      <ul className="space-y-1.5">
        {(value as string[]).map((item, i) => (
          <li key={i} className="flex gap-2.5">
            <span aria-hidden className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/35" />
            <span className="min-w-0 whitespace-pre-wrap break-words">{item}</span>
          </li>
        ))}
      </ul>
    )
  }

  // Array of objects: one card each
  if (Array.isArray(value) && value.length > 0) {
    return (
      <div className="space-y-1.5">
        {value.map((item, i) => (
          <div key={i} className={NESTED_BOX}>
            {typeof item === 'object' && item != null ? (
              <DynamicObject data={item as Record<string, unknown>} depth={depth + 1} />
            ) : (
              <p>{String(item)}</p>
            )}
          </div>
        ))}
      </div>
    )
  }

  if (Array.isArray(value)) return null

  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const entries = Object.entries(obj).filter(([, v]) => !isEmptyValue(v))
    if (entries.length === 0) return null
    return <DynamicObject data={obj} depth={depth} />
  }

  return null
}

function DynamicObject({ data, depth = 0 }: { data: Record<string, unknown>; depth?: number }) {
  const entries = Object.entries(data).filter(([, v]) => !isEmptyValue(v))
  if (entries.length === 0) return null

  // Shallow object with only scalar values: key-value pairs
  const allScalar = entries.every(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean')
  if (allScalar) {
    return (
      <div className="space-y-1.5">
        {entries.map(([key, val]) => (
          <div key={key}>
            <p className={LABEL}>{formatLabel(key)}</p>
            <p className="mt-0.5">{String(val)}</p>
          </div>
        ))}
      </div>
    )
  }

  if (depth >= MAX_CARD_DEPTH) {
    return (
      <pre className="whitespace-pre-wrap rounded-chip bg-well p-2 font-mono text-2xs text-muted-foreground">
        {JSON.stringify(data, null, 2)}
      </pre>
    )
  }

  return (
    <div className="space-y-2.5">
      {entries.map(([key, val]) => {
        // An object with its own children is a labelled sub-section
        if (typeof val === 'object' && val != null && !Array.isArray(val) && Object.keys(val as object).length > 0) {
          return (
            <div key={key}>
              <p className={`mb-1.5 ${LABEL}`}>{formatLabel(key)}</p>
              <div className={NESTED_BOX}>
                <DynamicValue value={val} depth={depth + 1} />
              </div>
            </div>
          )
        }
        return (
          <div key={key}>
            <p className={LABEL}>{formatLabel(key)}</p>
            <div className="mt-0.5">
              <DynamicValue value={val} depth={depth + 1} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
