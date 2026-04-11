import { useParams } from 'react-router-dom'
import { ContextPanel } from '@/components/workspace/context-panel'

export default function ContextTab() {
  const { id } = useParams<{ id: string }>()
  return <ContextPanel missionId={id!} />
}
