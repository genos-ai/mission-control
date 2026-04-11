import { useParams } from 'react-router-dom'
import { WorkflowsPanel } from '@/components/workspace/workflows-panel'

export default function WorkflowsTab() {
  const { id } = useParams<{ id: string }>()
  return <WorkflowsPanel missionId={id!} />
}
