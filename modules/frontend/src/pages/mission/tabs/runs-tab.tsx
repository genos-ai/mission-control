import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { RunsPanel } from '@/components/workspace/runs-panel'
import { RunDetailPanel, type RunDetailView } from '@/components/workspace/run-detail-panel'

export default function RunsTab() {
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<RunDetailView | null>(null)

  return (
    <div className="flex h-full overflow-hidden">
      <RunsPanel
        missionId={id!}
        activeDetail={detail}
        onOpenDetail={setDetail}
      />
      <RunDetailPanel view={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
