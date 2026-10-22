import { Lightbulb } from 'lucide-react'

import { CollapsiblePanel } from '@/components/knowledge/collapsible-panel'
import { LearningCard } from '@/components/knowledge/learning-card'
import { LEARNING_KIND } from '@/components/knowledge/learning-kind'
import { FilterChip } from '@/components/ui/filter-chip'
import { IconTile } from '@/components/ui/icon-tile'
import { Spinner } from '@/components/ui/spinner'
import type { MissionLearning } from '@/hooks/use-mission-learnings'

interface LearningsPanelProps {
  learnings: MissionLearning[]
  total: number
  isLoading: boolean
  kindFilter: string | undefined
  onKindFilter: (kind: string | undefined) => void
}

/** What the mission has learned from its runs, filterable by kind. */
export function LearningsPanel({ learnings, total, isLoading, kindFilter, onKindFilter }: LearningsPanelProps) {
  return (
    <CollapsiblePanel title="Learnings" meta={total > 0 ? total : undefined}>
      <div className="flex flex-wrap gap-1.5 px-1.5 pb-3">
        <FilterChip active={!kindFilter} onClick={() => onKindFilter(undefined)}>All</FilterChip>
        {Object.entries(LEARNING_KIND).map(([kind, style]) => (
          <FilterChip
            key={kind}
            active={kindFilter === kind}
            onClick={() => onKindFilter(kindFilter === kind ? undefined : kind)}
          >
            {style.label}
          </FilterChip>
        ))}
      </div>
      {isLoading ? (
        <div className="flex justify-center py-6"><Spinner /></div>
      ) : learnings.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <IconTile icon={Lightbulb} size="lg" />
          <p className="text-sm text-subtle">No learnings extracted yet.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {learnings.map((l) => <LearningCard key={l.id} learning={l} />)}
        </div>
      )}
    </CollapsiblePanel>
  )
}
