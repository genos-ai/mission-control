import { useParams } from 'react-router-dom'
import { DocumentPage } from '@/components/layout/document-page'
import { WorkflowsPanel } from '@/components/workspace/workflows-panel'

export default function WorkflowsTab() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="h-full overflow-y-auto">
      <DocumentPage>
        <WorkflowsPanel missionId={id!} />
      </DocumentPage>
    </div>
  )
}
