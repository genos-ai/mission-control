import { Compass } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { EmptyState } from '@/components/ui/empty-state'
import { ROUTES } from '@/lib/constants'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <EmptyState
      icon={<Compass className="h-4 w-4" />}
      title="Page not found"
      description="The page you asked for does not exist or has moved."
      action={{ label: 'Back to Home', onClick: () => navigate(ROUTES.DASHBOARD) }}
    />
  )
}
