import { useState } from 'react'
import { useParams } from 'react-router-dom'
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'

export default function ContextPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const { data: mcd, isLoading } = useMCD(missionId)
  const { data: history } = useContextHistory(missionId)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  if (!mcd || !mcd.context_data || Object.keys(mcd.context_data).length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<FileText className="h-6 w-6 text-muted-foreground" />}
          title="No context yet"
          description="The Mission Context Document builds automatically as agents run tasks. Start a run to populate it."
        />
      </div>
    )
  }

  const ctx = mcd.context_data as Record<string, unknown>
  const identity = (ctx.identity ?? {}) as Record<string, unknown>
  const architecture = (ctx.architecture ?? {}) as Record<string, unknown>
  const decisions = (ctx.decisions ?? []) as Record<string, unknown>[]
  const currentState = (ctx.current_state ?? {}) as Record<string, unknown>
  const guardrails = (ctx.guardrails ?? []) as unknown[]
  const sizePercent = mcd.pct_of_max ?? 0

  // Check if sections have real content beyond seed defaults
  const hasArchitecture =
    (typeof architecture.data_flow === 'string' && architecture.data_flow !== '') ||
    (architecture.components != null && typeof architecture.components === 'object' && Object.keys(architecture.components as object).length > 0)
  const hasCurrentStateContent =
    Object.values(currentState).some(
      (v) => (Array.isArray(v) && v.length > 0) || (typeof v === 'object' && v != null && !Array.isArray(v) && Object.keys(v as object).length > 0),
    )

  return (
    <div className="p-6 space-y-6">
      {/* Health bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Badge variant="secondary">v{mcd.version}</Badge>
          {typeof ctx.last_updated_by === 'string' && (
            <span className="text-xs text-muted-foreground">
              Last updated by{' '}
              <span className="font-medium">
                {String(ctx.last_updated_by)}
              </span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {(mcd.size_characters / 1024).toFixed(1)} KB / 20 KB
          </span>
          <div className="h-2 w-32 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                sizePercent > 80
                  ? 'bg-destructive'
                  : sizePercent > 50
                    ? 'bg-amber-500'
                    : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min(sizePercent, 100)}%` }}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left column: MCD sections */}
        <div className="lg:col-span-2 space-y-4">
          {/* Identity */}
          <ContextSection
            title="Identity"
            icon={<Target className="h-4 w-4" />}
            defaultOpen
          >
            <KeyValue label="Name" value={identity.name} />
            <KeyValue label="Purpose" value={identity.purpose} />
            {Array.isArray(identity.tech_stack) &&
              identity.tech_stack.length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground">
                    Tech Stack
                  </span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(identity.tech_stack as string[]).map((t: string, i: number) => (
                      <Badge key={i} variant="outline" className="text-[10px]">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
          </ContextSection>

          {/* Architecture — only show if agents have populated it */}
          {hasArchitecture && (
          <ContextSection
            title="Architecture"
            icon={<Layers className="h-4 w-4" />}
          >
            {typeof architecture.data_flow === 'string' && (
              <KeyValue label="Data Flow" value={architecture.data_flow} />
            )}
            {architecture.components != null &&
              typeof architecture.components === 'object' &&
              Object.keys(architecture.components as object).length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground">
                    Components
                  </span>
                  <div className="mt-1 space-y-1">
                    {Object.entries(
                      architecture.components as Record<string, unknown>,
                    ).map(([key, val]) => (
                      <div
                        key={key}
                        className="rounded border px-3 py-2 text-sm"
                      >
                        <span className="font-medium">{key}</span>
                        {val != null && (
                          <span className="ml-2 text-muted-foreground">
                            {typeof val === 'string'
                              ? val
                              : JSON.stringify(val)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            {architecture.conventions != null &&
              typeof architecture.conventions === 'object' &&
              Object.keys(architecture.conventions as object).length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground">
                    Conventions
                  </span>
                  <div className="mt-1 space-y-1">
                    {Object.entries(
                      architecture.conventions as Record<string, unknown>,
                    ).map(([key, val]) => (
                      <div
                        key={key}
                        className="text-sm text-muted-foreground"
                      >
                        <span className="font-medium text-foreground">
                          {key}:
                        </span>{' '}
                        {String(val)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            {!architecture.data_flow &&
              (!architecture.components ||
                Object.keys(architecture.components as object).length ===
                  0) && (
                <p className="text-xs text-muted-foreground italic">
                  Agents will populate architecture details as they analyze the
                  codebase.
                </p>
              )}
          </ContextSection>
          )}

          {/* Decisions — only show if there are any */}
          {decisions.length > 0 && (
          <ContextSection
            title={`Decisions (${decisions.length})`}
            icon={<GitBranch className="h-4 w-4" />}
          >
            {decisions.length > 0 ? (
              <div className="space-y-2">
                {decisions.map((d, i) => (
                  <div key={i} className="rounded border px-3 py-2">
                    <p className="text-sm font-medium">
                      {String(d.title ?? d.decision ?? `Decision ${i + 1}`)}
                    </p>
                    {typeof d.rationale === 'string' && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {String(d.rationale)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">
                No decisions recorded yet.
              </p>
            )}
          </ContextSection>
          )}

          {/* Current State — only show if has content */}
          {hasCurrentStateContent && (
          <ContextSection
            title="Current State"
            icon={<AlertCircle className="h-4 w-4" />}
            defaultOpen
          >
            {/* PQI Score — special rendering if present */}
            {currentState.pqi_score != null && typeof currentState.pqi_score === 'object' && (
              <PQIScore data={currentState.pqi_score as Record<string, unknown>} />
            )}
            <StateList
              label="Active Workstreams"
              items={currentState.active_workstreams}
            />
            <StateList
              label="Known Issues"
              items={currentState.known_issues}
              variant="destructive"
            />
            <StateList
              label="Next Priorities"
              items={currentState.next_priorities}
            />
            <StateList
              label="Recent Milestones"
              items={currentState.recent_milestones}
              variant="success"
            />
            {/* Render any other dynamic keys agents may have added */}
            <DynamicFields
              data={currentState}
              exclude={['active_workstreams', 'known_issues', 'next_priorities', 'recent_milestones', 'pqi_score']}
            />
          </ContextSection>
          )}

          {/* Guardrails */}
          {guardrails.length > 0 && (
            <ContextSection
              title={`Guardrails (${guardrails.length})`}
              icon={<Shield className="h-4 w-4" />}
            >
              <div className="space-y-1">
                {guardrails.map((g, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm"
                  >
                    <Shield className="h-3.5 w-3.5 text-amber-500 flex-shrink-0" />
                    {typeof g === 'string' ? g : JSON.stringify(g as object)}
                  </div>
                ))}
              </div>
            </ContextSection>
          )}
        </div>

        {/* Right column: Activity feed */}
        <div>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Recent Changes
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!history || history.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No changes recorded yet.
                </p>
              ) : (
                <div className="space-y-3">
                  {history.map((change) => (
                    <ChangeEntry key={change.id} change={change} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

// --- Sub-components ---

function ContextSection({
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
    <Card>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold">{title}</span>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open && <CardContent className="pt-0 space-y-3">{children}</CardContent>}
    </Card>
  )
}

function KeyValue({
  label,
  value,
}: {
  label: string
  value: unknown
}) {
  if (!value) return null
  return (
    <div>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <p className="text-sm">{String(value)}</p>
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
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="mt-1 space-y-1">
        {items.map((item, i) => (
          <div
            key={i}
            className={`rounded px-3 py-1.5 text-sm ${
              variant === 'destructive'
                ? 'bg-destructive/5 text-destructive'
                : variant === 'success'
                  ? 'bg-emerald-500/5 text-emerald-600'
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
  const fileCount = Number(data.file_count ?? 0)
  const lineCount = Number(data.line_count ?? 0)

  const bandColor =
    composite >= 80
      ? 'text-emerald-500'
      : composite >= 60
        ? 'text-amber-500'
        : 'text-destructive'

  return (
    <div>
      <span className="text-xs font-medium text-muted-foreground">
        Code Quality (PQI)
      </span>
      <div className="mt-2 rounded-lg border p-4">
        <div className="flex items-baseline gap-3 mb-3">
          <span className={`text-3xl font-bold ${bandColor}`}>
            {composite.toFixed(1)}
          </span>
          <span className="text-sm text-muted-foreground">/ 100</span>
          {band && (
            <Badge variant="secondary" className="text-xs">
              {band}
            </Badge>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            {fileCount} files &middot; {lineCount.toLocaleString()} lines
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(dims)
            .sort(([, a], [, b]) => b - a)
            .map(([dim, score]) => (
              <div key={dim} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-28 truncate capitalize">
                  {dim}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      score >= 80
                        ? 'bg-emerald-500'
                        : score >= 60
                          ? 'bg-amber-500'
                          : 'bg-destructive'
                    }`}
                    style={{ width: `${score}%` }}
                  />
                </div>
                <span className="text-xs font-mono w-8 text-right">
                  {score.toFixed(0)}
                </span>
              </div>
            ))}
        </div>
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
      val != null &&
      val !== '' &&
      !(Array.isArray(val) && val.length === 0) &&
      !(typeof val === 'object' && !Array.isArray(val) && Object.keys(val as object).length === 0),
  )

  if (entries.length === 0) return null

  return (
    <>
      {entries.map(([key, val]) => (
        <div key={key}>
          <span className="text-xs font-medium text-muted-foreground capitalize">
            {key.replace(/_/g, ' ')}
          </span>
          <div className="mt-1 rounded border px-3 py-2 text-sm">
            {typeof val === 'string' ? (
              val
            ) : (
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap">
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
    ADD: 'text-emerald-500',
    REPLACE: 'text-blue-400',
    REMOVE: 'text-destructive',
    PRUNE: 'text-amber-500',
    ARCHIVE: 'text-muted-foreground',
  }

  return (
    <div className="border-l-2 border-muted pl-3">
      <div className="flex items-center gap-2">
        <span
          className={`text-[10px] font-bold ${typeColor[change.change_type] ?? 'text-muted-foreground'}`}
        >
          {change.change_type}
        </span>
        <code className="text-[11px] text-muted-foreground">{change.path}</code>
      </div>
      {change.reason && (
        <p className="mt-0.5 text-xs text-muted-foreground">{change.reason}</p>
      )}
      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground/60">
        {change.agent_id && (
          <span className="flex items-center gap-1">
            <Bot className="h-2.5 w-2.5" />
            {change.agent_id.endsWith('.agent')
              ? change.agent_id.slice(0, -6)
              : change.agent_id}
          </span>
        )}
        <span className="flex items-center gap-1">
          <Clock className="h-2.5 w-2.5" />
          {formatDistanceToNow(new Date(change.created_at), {
            addSuffix: true,
          })}
        </span>
      </div>
    </div>
  )
}
