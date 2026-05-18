/**
 * ContextPanel — Mission Context & Memory, rendered as a full feed mode
 * inside the workspace center panel.
 *
 * Shows the Mission Context Document (MCD): all sections are rendered
 * dynamically based on the data shape — no hardcoded section list.
 * The MCD is built automatically as agents run tasks — it represents
 * the mission's accumulated memory and learnings.
 */

import { useState } from 'react'
import {
  FileText,
  ChevronDown,
  ChevronRight,
  Clock,
  Bot,
  Database,
} from 'lucide-react'
import { formatUtc } from '@/lib/format-date'
import { useMCD, useContextHistory } from '@/hooks/use-context'
import type { ContextChange } from '@/hooks/use-context'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'

// Keys that are metadata, not content sections
const META_KEYS = new Set(['version', 'last_updated', 'last_updated_by'])

// ---------------------------------------------------------------------------

export function ContextPanel({ missionId }: { missionId: string }) {
  const { data: mcd, isLoading } = useMCD(missionId)
  const { data: history } = useContextHistory(missionId)

  const isEmpty =
    !mcd || !mcd.context_data || Object.keys(mcd.context_data).length === 0

  return (
    <div className="flex h-full flex-col">
      {/* Status bar */}
      {mcd && !isEmpty && (
        <div className="flex h-7 shrink-0 items-center justify-end gap-2 border-b px-4">
          {typeof mcd.context_data.last_updated_by === 'string' && (
            <span className="text-[10px] text-muted-foreground/60">
              updated by <span className="font-medium">{String(mcd.context_data.last_updated_by)}</span>
            </span>
          )}
          <Badge variant="secondary" className="text-[9px]">v{mcd.version}</Badge>
          <span className="text-[10px] text-muted-foreground">
            {(mcd.size_characters / 1024).toFixed(1)}KB / {(mcd.max_characters / 1024).toFixed(0)}KB
          </span>
          <div className="h-1.5 w-24 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                (mcd.pct_of_max ?? 0) > 80
                  ? 'bg-destructive'
                  : (mcd.pct_of_max ?? 0) > 50
                    ? 'bg-amber-500'
                    : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min(mcd.pct_of_max ?? 0, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-3 p-4">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner className="h-4 w-4" />
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <FileText className="h-8 w-8 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">No context yet</p>
              <p className="text-xs text-muted-foreground/60 max-w-[280px]">
                The Mission Context Document builds automatically as agents run tasks.
                Start a run to populate it.
              </p>
            </div>
          ) : (
            <McdContent mcd={mcd!} history={history ?? []} />
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function McdContent({
  mcd,
  history,
}: {
  mcd: NonNullable<ReturnType<typeof useMCD>['data']>
  history: ContextChange[]
}) {
  const ctx = mcd.context_data as Record<string, unknown>

  // Render every non-meta key dynamically
  const sections = Object.entries(ctx).filter(
    ([key, val]) => !META_KEYS.has(key) && val != null && !isEmptyValue(val),
  )

  return (
    <>
      {sections.map(([key], i) => (
        <Section
          key={key}
          title={formatLabel(key)}
          icon={<Database className="h-3.5 w-3.5" />}
          defaultOpen={i < 3}
        >
          <DynamicValue value={ctx[key]} />
        </Section>
      ))}

      {/* Recent Changes — always last */}
      <Section title="Recent Changes" icon={<Clock className="h-3.5 w-3.5" />}>
        {history.length === 0 ? (
          <p className="text-xs text-muted-foreground/60">No changes recorded yet.</p>
        ) : (
          <div className="space-y-3">
            {history.map((change) => (
              <ChangeEntry key={change.id} change={change} />
            ))}
          </div>
        )}
      </Section>
    </>
  )
}

// ---------------------------------------------------------------------------
// Dynamic value renderer — recursively renders any shape
// ---------------------------------------------------------------------------

function DynamicValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value == null) return null

  // String
  if (typeof value === 'string') {
    return value ? <p className="text-xs whitespace-pre-wrap">{value}</p> : null
  }

  // Number / boolean
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <p className="text-xs font-mono">{String(value)}</p>
  }

  // Array of strings — render as tag badges
  if (Array.isArray(value) && value.length > 0 && value.every((v) => typeof v === 'string')) {
    return (
      <div className="flex flex-wrap gap-1">
        {(value as string[]).map((item, i) => (
          <Badge key={i} variant="outline" className="text-[10px] h-5 px-1.5 font-normal">
            {item}
          </Badge>
        ))}
      </div>
    )
  }

  // Array of objects — render as cards
  if (Array.isArray(value) && value.length > 0) {
    return (
      <div className="space-y-1.5">
        {value.map((item, i) => (
          <div key={i} className="rounded border px-2.5 py-2">
            {typeof item === 'object' && item != null ? (
              <DynamicObject data={item as Record<string, unknown>} depth={depth + 1} />
            ) : (
              <p className="text-xs">{String(item)}</p>
            )}
          </div>
        ))}
      </div>
    )
  }

  // Empty array
  if (Array.isArray(value) && value.length === 0) return null

  // Object
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

  // Shallow object with only string/number values — render as key-value pairs
  const allScalar = entries.every(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean')
  if (allScalar) {
    return (
      <div className="space-y-1.5">
        {entries.map(([key, val]) => (
          <div key={key}>
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{formatLabel(key)}</p>
            <p className="mt-0.5 text-xs">{String(val)}</p>
          </div>
        ))}
      </div>
    )
  }

  // Nested objects — render each as a sub-card (up to 3 levels deep, then JSON)
  if (depth >= 3) {
    return (
      <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap rounded bg-muted/30 p-2">
        {JSON.stringify(data, null, 2)}
      </pre>
    )
  }

  return (
    <div className="space-y-2.5">
      {entries.map(([key, val]) => {
        // Nested object with its own children — render as a labeled sub-section
        if (typeof val === 'object' && val != null && !Array.isArray(val) && Object.keys(val as object).length > 0) {
          return (
            <div key={key}>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{formatLabel(key)}</p>
              <div className="rounded border px-2.5 py-2">
                <DynamicValue value={val} depth={depth + 1} />
              </div>
            </div>
          )
        }
        // Everything else
        return (
          <div key={key}>
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{formatLabel(key)}</p>
            <div className="mt-0.5">
              <DynamicValue value={val} depth={depth + 1} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string
  icon: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="rounded-lg border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <span className="text-muted-foreground">{icon}</span>
        <span className="flex-1 text-xs font-semibold">{title}</span>
        {open
          ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        }
      </button>
      {open && <div className="border-t px-3 pb-3 pt-2.5 space-y-2.5">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function isEmptyValue(val: unknown): boolean {
  if (val == null || val === '') return true
  if (Array.isArray(val) && val.length === 0) return true
  if (typeof val === 'object' && !Array.isArray(val) && Object.keys(val as object).length === 0) return true
  return false
}

function ChangeEntry({ change }: { change: ContextChange }) {
  const typeColor: Record<string, string> = {
    ADD: 'text-emerald-400',
    REPLACE: 'text-blue-400',
    REMOVE: 'text-destructive',
    PRUNE: 'text-amber-400',
    ARCHIVE: 'text-muted-foreground',
  }

  return (
    <div className="border-l-2 border-muted pl-2.5">
      <div className="flex items-center gap-1.5">
        <span className={`text-[10px] font-bold ${typeColor[change.change_type] ?? 'text-muted-foreground'}`}>
          {change.change_type}
        </span>
        <code className="text-[10px] text-muted-foreground">{change.path}</code>
      </div>
      {change.reason && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">{change.reason}</p>
      )}
      <div className="mt-0.5 flex items-center gap-2 text-[9px] text-muted-foreground/50">
        {change.agent_id && (
          <span className="flex items-center gap-0.5">
            <Bot className="h-2 w-2" />
            {change.agent_id.endsWith('.agent') ? change.agent_id.slice(0, -6) : change.agent_id}
          </span>
        )}
        <span className="flex items-center gap-0.5">
          <Clock className="h-2 w-2" />
          {formatUtc(change.created_at)}
        </span>
      </div>
    </div>
  )
}
