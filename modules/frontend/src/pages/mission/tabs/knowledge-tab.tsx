/**
 * KnowledgeTab — what the mission knows: its intent, what it has learned from
 * its runs, and the failures agents should not repeat.
 */

import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { IntentPanel } from '@/components/knowledge/intent-panel'
import { LearningsPanel } from '@/components/knowledge/learnings-panel'
import { RecentFailuresPanel, type RecentFailure } from '@/components/knowledge/recent-failures-panel'
import { DocumentPage } from '@/components/layout/document-page'
import { useMissionLearnings } from '@/hooks/use-mission-learnings'
import { useCurrentIntent, useIntentHistory } from '@/hooks/use-mission-intent'
import { useMissionKnowledge } from '@/hooks/use-knowledge-search'

export default function KnowledgeTab() {
  const { id: missionId } = useParams<{ id: string }>()
  const [kindFilter, setKindFilter] = useState<string | undefined>()

  const { data: learningsData, isLoading: learningsLoading } = useMissionLearnings(missionId, {
    kind: kindFilter,
  })
  const { data: intent } = useCurrentIntent(missionId)
  const { data: intentHistory } = useIntentHistory(missionId)
  const { data: knowledge } = useMissionKnowledge(missionId)

  const recentFailures = knowledge?.recent_failures as RecentFailure[] | undefined

  return (
    <div className="h-full overflow-y-auto">
      <DocumentPage className="gap-4">
        <IntentPanel intent={intent} revisions={intentHistory?.items ?? []} />
        <div className="grid grid-cols-[repeat(auto-fit,minmax(360px,1fr))] items-start gap-4">
          <LearningsPanel
            learnings={learningsData?.items ?? []}
            total={learningsData?.total ?? 0}
            isLoading={learningsLoading}
            kindFilter={kindFilter}
            onKindFilter={setKindFilter}
          />
          {recentFailures && recentFailures.length > 0 && <RecentFailuresPanel failures={recentFailures} />}
        </div>
      </DocumentPage>
    </div>
  )
}
