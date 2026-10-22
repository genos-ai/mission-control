import { useState } from 'react'
import { ArrowUpCircle, ChevronDown } from 'lucide-react'

import { LEARNING_KIND } from '@/components/knowledge/learning-kind'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import type { MissionLearning } from '@/hooks/use-mission-learnings'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'

/** One learning: its kind, how sure and how often, with the detail one click away. */
export function LearningCard({ learning }: { learning: MissionLearning }) {
  const [expanded, setExpanded] = useState(false)
  const kind = LEARNING_KIND[learning.kind] ?? LEARNING_KIND.failure_pattern
  const KindIcon = kind.icon

  return (
    <div className="rounded-card bg-raised">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        className="flex w-full flex-col gap-2 rounded-card px-3.5 py-3 text-left transition-colors hover:bg-hover"
      >
        <div className="flex items-center gap-2">
          <StatusPill tone={kind.tone} dot={false}>
            <KindIcon className="h-3 w-3" />
            {kind.label}
          </StatusPill>
          {learning.platform_promoted && (
            <span role="img" aria-label="Promoted to the platform" title="Promoted to the platform">
              <ArrowUpCircle className="h-3.5 w-3.5 text-warning" />
            </span>
          )}
          <span className="ml-auto flex items-center gap-2 whitespace-nowrap font-mono text-2xs text-subtle">
            <span>conf {(learning.confidence * 100).toFixed(0)}%</span>
            <span>seen {learning.occurrence_count}&times;</span>
          </span>
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-subtle transition-transform duration-150 motion-reduce:transition-none',
              !expanded && '-rotate-90',
            )}
          />
        </div>
        <p className={cn('break-words text-base', !expanded && 'line-clamp-2')}>{learning.title}</p>
        {!expanded && (
          <p className="line-clamp-2 whitespace-pre-wrap break-words text-xs text-subtle">{learning.recommendation}</p>
        )}
      </button>

      {expanded && (
        <div className="flex flex-col gap-3 px-3.5 pb-3.5 text-xs">
          <div>
            <p className="mb-0.5 text-subtle">Recommendation</p>
            <p className="whitespace-pre-wrap break-words text-sm">{learning.recommendation}</p>
          </div>
          {learning.body && (
            <div>
              <p className="mb-0.5 text-subtle">Evidence</p>
              <p className="whitespace-pre-wrap break-words text-muted-foreground">{learning.body}</p>
            </div>
          )}
          {learning.domain_tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {learning.domain_tags.map((tag) => (
                <Badge key={tag} variant="outline">{tag}</Badge>
              ))}
            </div>
          )}
          <p className="text-subtle">
            {formatUtc(learning.created_at)}
            {learning.agent_names.length > 0 && <> &middot; Agents: {learning.agent_names.join(', ')}</>}
          </p>
        </div>
      )}
    </div>
  )
}
