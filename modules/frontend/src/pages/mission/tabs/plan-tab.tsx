import { useParams } from 'react-router-dom'
import { PlanBoard } from '@/components/workspace/plan-board'

export default function PlanTab() {
  const { id } = useParams<{ id: string }>()
  return <PlanBoard missionId={id!} />
}
