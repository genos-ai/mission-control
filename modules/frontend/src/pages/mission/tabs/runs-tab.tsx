import { useParams } from 'react-router-dom'
import { RunsPanel } from '@/components/workspace/runs-panel'

export default function RunsTab() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="h-full overflow-y-auto">
      <RunsPanel missionId={id!} />
    </div>
  )
}
