/**
 * KnowledgeTab — mission-scoped learnings + relevant platform knowledge.
 *
 * Two sections:
 *   1. Mission Learnings — extracted from this mission's execution history
 *   2. Platform Knowledge — promoted entries relevant by domain tag overlap
 */

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  Globe,
  Lightbulb,
  ShieldAlert,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui/spinner'
import { useMissionLearnings, type MissionLearning } from '@/hooks/use-mission-learnings'
import { IntentStrip } from '@/components/knowledge/intent-strip'
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

// ---------------------------------------------------------------------------
// Tab
// ---------------------------------------------------------------------------

export default function KnowledgeTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [kindFilter, setKindFilter] = useState<string | undefined>()

  const { data: learningsData, isLoading } = useMissionLearnings(missionId, {
    kind: kindFilter,
  })

  const learnings = learningsData?.items ?? []
  const total = learningsData?.total ?? 0

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Intent strip */}
      <div className="border-b px-4 py-3">
        <IntentStrip missionId={missionId!} />
      </div>

      {/* Header + filters */}
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <BookOpen className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">
          Mission Learnings
          {total > 0 && (
            <span className="ml-1.5 text-muted-foreground font-normal">({total})</span>
          )}
        </h2>

        {/* Kind filter chips */}
        <div className="ml-auto flex gap-1.5">
          <FilterChip
            active={!kindFilter}
            onClick={() => setKindFilter(undefined)}
          >
            All
          </FilterChip>
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
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : learnings.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            <Lightbulb className="mx-auto mb-2 h-8 w-8 opacity-30" />
            <p>No learnings extracted yet.</p>
            <p className="mt-1 text-xs">
              Learnings are automatically created from recurring failure patterns
              in execution history.
            </p>
          </div>
        ) : (
          learnings.map((learning) => (
            <LearningCard key={learning.id} learning={learning} />
          ))
        )}
      </div>
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
              <Globe className="h-3 w-3 text-purple-500 shrink-0" title="Platform promoted" />
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary" className="text-[10px]">{cfg.label}</Badge>
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
                <Badge key={tag} variant="outline" className="text-[10px]">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
          <p className="text-muted-foreground/60">
            {formatUtc(learning.created_at)}
            {learning.agent_names.length > 0 && (
              <> &middot; Agents: {learning.agent_names.join(', ')}</>
            )}
          </p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// FilterChip
// ---------------------------------------------------------------------------

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium transition-colors ${
        active
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted text-muted-foreground hover:bg-muted/80'
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
