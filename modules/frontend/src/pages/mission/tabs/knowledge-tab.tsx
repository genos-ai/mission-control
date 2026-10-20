/**
 * KnowledgeTab — mission knowledge dashboard.
 *
 * Four sections:
 *   1. Current Intent + revision history
 *   2. Mission Learnings — extracted from execution history
 *   3. MCD Decisions — archived decisions from context pruning
 *   4. Recent failures — so agents don't repeat mistakes
 */

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  Globe,
  History,
  Lightbulb,
  ShieldAlert,
  Target,
  TrendingUp,
  Zap,
  AlertTriangle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { FilterChip } from '@/components/ui/filter-chip'
import { Spinner } from '@/components/ui/spinner'
import { useMissionLearnings, type MissionLearning } from '@/hooks/use-mission-learnings'
import { useCurrentIntent, useIntentHistory } from '@/hooks/use-mission-intent'
import { useMissionKnowledge } from '@/hooks/use-knowledge-search'
import { formatUtc } from '@/lib/format-date'

// ---------------------------------------------------------------------------
// Kind display config
// ---------------------------------------------------------------------------

const KIND_CONFIG: Record<string, { label: string; icon: typeof Lightbulb; color: string }> = {
  failure_pattern: { label: 'Failure Pattern', icon: ShieldAlert, color: 'text-red-500' },
  success_pattern: { label: 'Success Pattern', icon: TrendingUp, color: 'text-green-500' },
  anti_pattern: { label: 'Anti-Pattern', icon: ShieldAlert, color: 'text-orange-500' },
  retry_strategy: { label: 'Retry Strategy', icon: Zap, color: 'text-blue-500' },
  capability_gap: { label: 'Capability Gap', icon: Brain, color: 'text-purple-500' },
}

const SOURCE_LABELS: Record<string, string> = {
  user_chat: 'User',
  user_cli: 'CLI',
  director_inferred: 'Director',
  system: 'System',
}

// ---------------------------------------------------------------------------
// Tab
// ---------------------------------------------------------------------------

export default function KnowledgeTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [kindFilter, setKindFilter] = useState<string | undefined>()

  const { data: learningsData, isLoading: learningsLoading } = useMissionLearnings(missionId, {
    kind: kindFilter,
  })
  const { data: intent } = useCurrentIntent(missionId)
  const { data: intentHistory } = useIntentHistory(missionId)
  const { data: knowledge } = useMissionKnowledge(missionId)

  const learnings = learningsData?.items ?? []
  const total = learningsData?.total ?? 0
  const intents = intentHistory?.items ?? []
  const recentFailures = (knowledge as Record<string, unknown>)?.recent_failures as Record<string, unknown>[] | undefined

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* ── Section 1: Intent ─────────────────────────────── */}
      <CollapsibleSection
        title="Mission Intent"
        icon={Target}
        badge={intents.length > 0 ? `${intents.length} revisions` : undefined}
        defaultOpen
      >
        {intent ? (
          <div className="space-y-3">
            {/* Current intent */}
            <div className="rounded-md border border-amber-200/50 bg-amber-50/30 px-3 py-2 dark:border-amber-800/30 dark:bg-amber-950/20">
              <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                {intent.intent}
              </p>
              {intent.scope && (Object.keys(intent.scope).length > 0) && (
                <div className="mt-1.5 flex gap-4 text-xs text-muted-foreground">
                  {(intent.scope as Record<string, string[]>).in?.length > 0 && (
                    <span>
                      <span className="text-green-600 dark:text-green-400 font-medium">In:</span>{' '}
                      {(intent.scope as Record<string, string[]>).in.join(', ')}
                    </span>
                  )}
                  {(intent.scope as Record<string, string[]>).out?.length > 0 && (
                    <span>
                      <span className="text-red-600 dark:text-red-400 font-medium">Out:</span>{' '}
                      {(intent.scope as Record<string, string[]>).out.join(', ')}
                    </span>
                  )}
                </div>
              )}
              <p className="mt-1 text-xs text-muted-foreground/60">
                {SOURCE_LABELS[intent.source] ?? intent.source} &middot; {intent.reason}
              </p>
            </div>

            {/* Intent timeline */}
            {intents.length > 1 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                  <History className="h-3 w-3" /> Revision History
                </p>
                {intents.map((rev, i) => (
                  <div
                    key={rev.id}
                    className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${
                      i === 0 ? 'bg-amber-50/50 dark:bg-amber-950/30' : ''
                    }`}
                  >
                    <span className="text-muted-foreground/50 w-4 shrink-0 text-right">
                      {intents.length - i}
                    </span>
                    <span className="flex-1 truncate">{rev.intent_summary}</span>
                    <Badge className="shrink-0">
                      {SOURCE_LABELS[rev.source] ?? rev.source}
                    </Badge>
                    <span className="text-muted-foreground/40 shrink-0">
                      {formatUtc(rev.created_at as string)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No intent set.</p>
        )}
      </CollapsibleSection>

      {/* ── Section 2: Learnings ──────────────────────────── */}
      <CollapsibleSection
        title="Learnings"
        icon={BookOpen}
        badge={total > 0 ? `${total}` : undefined}
        defaultOpen
        headerRight={
          <div className="flex gap-1">
            <FilterChip active={!kindFilter} onClick={() => setKindFilter(undefined)}>All</FilterChip>
            {Object.entries(KIND_CONFIG).map(([kind, cfg]) => (
              <FilterChip
                key={kind}
                active={kindFilter === kind}
                onClick={() => setKindFilter(kindFilter === kind ? undefined : kind)}
              >
                {cfg.label}
              </FilterChip>
            ))}
          </div>
        }
      >
        {learningsLoading ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : learnings.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">
            <Lightbulb className="mx-auto mb-1.5 h-6 w-6 opacity-30" />
            No learnings extracted yet.
          </div>
        ) : (
          <div className="space-y-2">
            {learnings.map((l) => <LearningCard key={l.id} learning={l} />)}
          </div>
        )}
      </CollapsibleSection>

      {/* ── Section 3: Recent Failures ────────────────────── */}
      {recentFailures && recentFailures.length > 0 && (
        <CollapsibleSection
          title="Recent Failures"
          icon={AlertTriangle}
          badge={`${recentFailures.length}`}
          defaultOpen={false}
        >
          <div className="space-y-1">
            {recentFailures.map((f, i) => (
              <div key={i} className="flex items-start gap-2 rounded border px-2.5 py-1.5 text-xs">
                <AlertTriangle className="h-3 w-3 text-red-400 mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <span className="font-medium">{(f as Record<string, unknown>).agent_name as string}</span>
                  <span className="text-muted-foreground"> &middot; {(f as Record<string, unknown>).task_id as string}</span>
                  {typeof (f as Record<string, unknown>).failure_reason === 'string' && (
                    <p className="mt-0.5 text-muted-foreground truncate">
                      {((f as Record<string, unknown>).failure_reason as string).slice(0, 150)}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// CollapsibleSection
// ---------------------------------------------------------------------------

function CollapsibleSection({
  title,
  icon: Icon,
  badge,
  defaultOpen = true,
  headerRight,
  children,
}: {
  title: string
  icon: typeof BookOpen
  badge?: string
  defaultOpen?: boolean
  headerRight?: React.ReactNode
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-b">
      {/* The toggle is the title area only: the header controls beside it are buttons too, and a button cannot contain one. */}
      <div className="flex w-full items-center gap-2 px-4 py-2.5 hover:bg-muted/30">
        <button
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          )}
          <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-semibold">{title}</span>
          {badge && <Badge>{badge}</Badge>}
        </button>
        {headerRight}
      </div>
      {open && <div className="px-4 pb-3">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// LearningCard
// ---------------------------------------------------------------------------

function LearningCard({ learning }: { learning: MissionLearning }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = KIND_CONFIG[learning.kind] ?? KIND_CONFIG.failure_pattern
  const Icon = cfg.icon

  return (
    <div className="rounded-lg border bg-card text-card-foreground">
      <button
        className="flex w-full items-start gap-3 p-3 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="mt-0.5 h-3.5 w-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="mt-0.5 h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${cfg.color}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium truncate">{learning.title}</span>
            {learning.platform_promoted && (
              <span title="Platform promoted">
                <Globe className="h-3 w-3 text-purple-500 shrink-0" />
              </span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            <Badge>{cfg.label}</Badge>
            <span>conf: {(learning.confidence * 100).toFixed(0)}%</span>
            <span>&middot; {learning.occurrence_count}x</span>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="border-t px-3 pb-3 pt-2 space-y-2 text-xs">
          <div>
            <p className="font-medium text-muted-foreground mb-0.5">Recommendation</p>
            <p className="whitespace-pre-wrap">{learning.recommendation}</p>
          </div>
          {learning.body && (
            <div>
              <p className="font-medium text-muted-foreground mb-0.5">Evidence</p>
              <p className="whitespace-pre-wrap text-muted-foreground">{learning.body}</p>
            </div>
          )}
          {learning.domain_tags.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {learning.domain_tags.map((tag) => (
                <Badge key={tag} variant="outline">{tag}</Badge>
              ))}
            </div>
          )}
          <p className="text-muted-foreground/60">
            {formatUtc(learning.created_at as string)}
            {learning.agent_names.length > 0 && (
              <> &middot; Agents: {learning.agent_names.join(', ')}</>
            )}
          </p>
        </div>
      )}
    </div>
  )
}
