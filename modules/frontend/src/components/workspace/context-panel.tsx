/**
 * ContextPanel — Mission Context & Memory, rendered as a full feed mode
 * inside the workspace center panel.
 *
 * Shows the Mission Context Document (MCD): identity, architecture,
 * decisions, current state, guardrails, and recent agent changes.
 * The MCD is built automatically as agents run tasks — it represents
 * the mission's accumulated memory and learnings.
 */

import { useState } from 'react'
import {
  FileText,
  ChevronDown,
  ChevronRight,
  Shield,
  Clock,
  Bot,
  Layers,
  AlertCircle,
  Target,
  GitBranch,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useMCD, useContextHistory } from '@/hooks/use-context'
import type { ContextChange } from '@/hooks/use-context'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'

// ---------------------------------------------------------------------------

export function ContextPanel({ missionId }: { missionId: string }) {
  const { data: mcd, isLoading } = useMCD(missionId)
  const { data: history } = useContextHistory(missionId)

  const isEmpty =
    !mcd || !mcd.context_data || Object.keys(mcd.context_data).length === 0

  return (
    <div className="flex h-full flex-col">
      {/* Status bar — version + fill level (only when populated) */}
      {mcd && !isEmpty && (
        <div className="flex h-7 shrink-0 items-center justify-end gap-2 border-b px-4">
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
  const identity = (ctx.identity ?? {}) as Record<string, unknown>
  const architecture = (ctx.architecture ?? {}) as Record<string, unknown>
  const decisions = (ctx.decisions ?? []) as Record<string, unknown>[]
  const currentState = (ctx.current_state ?? {}) as Record<string, unknown>
  const guardrails = (ctx.guardrails ?? []) as unknown[]

  const hasArchitecture =
    (typeof architecture.data_flow === 'string' && architecture.data_flow !== '') ||
    (architecture.components != null &&
      typeof architecture.components === 'object' &&
      Object.keys(architecture.components as object).length > 0)

  const hasCurrentState = Object.values(currentState).some(
    (v) =>
      (Array.isArray(v) && v.length > 0) ||
      (typeof v === 'object' && v != null && !Array.isArray(v) &&
        Object.keys(v as object).length > 0),
  )

  return (
    <>
      {/* Identity */}
      <Section title="Identity" icon={<Target className="h-3.5 w-3.5" />} defaultOpen>
        <KV label="Name" value={identity.name} />
        <KV label="Purpose" value={identity.purpose} />
        {Array.isArray(identity.tech_stack) && identity.tech_stack.length > 0 && (
          <div>
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Tech Stack</p>
            <div className="flex flex-wrap gap-1">
              {(identity.tech_stack as string[]).map((t, i) => (
                <Badge key={i} variant="outline" className="text-[9px] h-4 px-1">{t}</Badge>
              ))}
            </div>
          </div>
        )}
        {typeof ctx.last_updated_by === 'string' && (
          <p className="text-[10px] text-muted-foreground/60">
            Last updated by <span className="font-medium">{String(ctx.last_updated_by)}</span>
          </p>
        )}
      </Section>

      {/* Current State */}
      {hasCurrentState && (
        <Section title="Current State" icon={<AlertCircle className="h-3.5 w-3.5" />} defaultOpen>
          {currentState.pqi_score != null && typeof currentState.pqi_score === 'object' && (
            <PQIScore data={currentState.pqi_score as Record<string, unknown>} />
          )}
          <StateList label="Active Workstreams" items={currentState.active_workstreams} />
          <StateList label="Next Priorities" items={currentState.next_priorities} />
          <StateList label="Known Issues" items={currentState.known_issues} variant="destructive" />
          <StateList label="Recent Milestones" items={currentState.recent_milestones} variant="success" />
          <DynamicFields
            data={currentState}
            exclude={['active_workstreams', 'known_issues', 'next_priorities', 'recent_milestones', 'pqi_score']}
          />
        </Section>
      )}

      {/* Decisions */}
      {decisions.length > 0 && (
        <Section title={`Decisions (${decisions.length})`} icon={<GitBranch className="h-3.5 w-3.5" />}>
          <div className="space-y-1.5">
            {decisions.map((d, i) => (
              <div key={i} className="rounded border px-2.5 py-2 text-xs">
                <p className="font-medium">{String(d.title ?? d.decision ?? `Decision ${i + 1}`)}</p>
                {typeof d.rationale === 'string' && (
                  <p className="mt-0.5 text-muted-foreground">{String(d.rationale)}</p>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Architecture */}
      {hasArchitecture && (
        <Section title="Architecture" icon={<Layers className="h-3.5 w-3.5" />}>
          {typeof architecture.data_flow === 'string' && (
            <KV label="Data Flow" value={architecture.data_flow} />
          )}
          {architecture.components != null &&
            typeof architecture.components === 'object' &&
            Object.keys(architecture.components as object).length > 0 && (
              <div>
                <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Components</p>
                <div className="space-y-1">
                  {Object.entries(architecture.components as Record<string, unknown>).map(([key, val]) => (
                    <div key={key} className="flex items-start gap-1.5 rounded border px-2.5 py-1.5 text-xs">
                      <span className="font-medium">{key}</span>
                      {val != null && (
                        <span className="text-muted-foreground">
                          {typeof val === 'string' ? val : JSON.stringify(val)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
        </Section>
      )}

      {/* Guardrails */}
      {guardrails.length > 0 && (
        <Section title={`Guardrails (${guardrails.length})`} icon={<Shield className="h-3.5 w-3.5" />}>
          <div className="space-y-1">
            {guardrails.map((g, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-amber-500/20 bg-amber-500/5 px-2.5 py-2 text-xs">
                <Shield className="h-3 w-3 text-amber-500 shrink-0" />
                <span>{typeof g === 'string' ? g : JSON.stringify(g as object)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Recent Changes */}
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

function KV({ label, value }: { label: string; value: unknown }) {
  if (!value) return null
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-xs">{String(value)}</p>
    </div>
  )
}

function StateList({
  label,
  items,
  variant,
}: {
  label: string
  items: unknown
  variant?: 'destructive' | 'success'
}) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <div>
      <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <div className="space-y-0.5">
        {items.map((item, i) => (
          <div
            key={i}
            className={`rounded px-2.5 py-1.5 text-xs ${
              variant === 'destructive'
                ? 'bg-destructive/5 text-destructive'
                : variant === 'success'
                  ? 'bg-emerald-500/5 text-emerald-400'
                  : 'bg-muted/50'
            }`}
          >
            {typeof item === 'string' ? item : JSON.stringify(item as object)}
          </div>
        ))}
      </div>
    </div>
  )
}

function PQIScore({ data }: { data: Record<string, unknown> }) {
  const composite = Number(data.composite ?? 0)
  const band = String(data.quality_band ?? '')
  const dims = (data.dimensions ?? {}) as Record<string, number>

  const bandColor =
    composite >= 80 ? 'text-emerald-400' :
    composite >= 60 ? 'text-amber-400' :
    'text-destructive'

  return (
    <div className="rounded border p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <span className={`text-2xl font-bold ${bandColor}`}>{composite.toFixed(1)}</span>
        <span className="text-xs text-muted-foreground">/ 100</span>
        {band && <Badge variant="secondary" className="text-[9px]">{band}</Badge>}
      </div>
      <div className="space-y-1">
        {Object.entries(dims).sort(([, a], [, b]) => b - a).map(([dim, score]) => (
          <div key={dim} className="flex items-center gap-2">
            <span className="w-24 truncate text-[10px] text-muted-foreground capitalize">
              {dim.replace(/_/g, ' ')}
            </span>
            <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${
                  score >= 80 ? 'bg-emerald-500' : score >= 60 ? 'bg-amber-500' : 'bg-destructive'
                }`}
                style={{ width: `${score}%` }}
              />
            </div>
            <span className="w-7 text-right text-[10px] font-mono text-muted-foreground">
              {score.toFixed(0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function DynamicFields({
  data,
  exclude,
}: {
  data: Record<string, unknown>
  exclude: string[]
}) {
  const entries = Object.entries(data).filter(
    ([key, val]) =>
      !exclude.includes(key) &&
      val != null && val !== '' &&
      !(Array.isArray(val) && val.length === 0) &&
      !(typeof val === 'object' && !Array.isArray(val) && Object.keys(val as object).length === 0),
  )
  if (entries.length === 0) return null
  return (
    <>
      {entries.map(([key, val]) => (
        <div key={key}>
          <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground capitalize">
            {key.replace(/_/g, ' ')}
          </p>
          <div className="rounded border px-2.5 py-2 text-xs">
            {typeof val === 'string' ? val : (
              <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap">
                {JSON.stringify(val, null, 2)}
              </pre>
            )}
          </div>
        </div>
      ))}
    </>
  )
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
          {formatDistanceToNow(new Date(change.created_at), { addSuffix: true })}
        </span>
      </div>
    </div>
  )
}
