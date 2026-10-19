import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { DocumentPage } from '@/components/layout/document-page'
import { RunsPanel } from '@/components/workspace/runs-panel'
import { RunDetailPanel, type RunDetailView } from '@/components/workspace/run-detail-panel'

export default function RunsTab() {
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<RunDetailView | null>(null)

  return (
    <div className="flex h-full min-h-0 gap-gutter pr-2">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <DocumentPage>
          <RunsPanel missionId={id!} activeDetail={detail} onOpenDetail={setDetail} />
        </DocumentPage>
      </div>
      {detail && (
        <div className="flex shrink-0 pb-2">
          <RunDetailPanel view={detail} onClose={() => setDetail(null)} />
        </div>
      )}
    </div>
  )
}
