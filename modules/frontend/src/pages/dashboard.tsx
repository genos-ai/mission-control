import { useNavigate } from 'react-router-dom'
import { Plus, Rocket } from 'lucide-react'
import { useMissions } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import type { MissionListItem, MissionStatus } from '@/types'

const statusVariant: Record<MissionStatus, 'success' | 'warning' | 'secondary'> = {
  active: 'success',
  paused: 'warning',
  archived: 'secondary',
}

function MissionCard({ mission }: { mission: MissionListItem }) {
  const navigate = useNavigate()

  return (
    <Card
      className="cursor-pointer transition-colors hover:border-primary/40"
      onClick={() => navigate(ROUTES.MISSION_OVERVIEW(mission.id))}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <CardTitle className="text-base">{mission.name}</CardTitle>
          <Badge variant={statusVariant[mission.status]}>{mission.status}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="line-clamp-2 text-sm text-muted-foreground">
          {mission.description}
        </p>
        <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
          {mission.budget_ceiling_usd != null && (
            <span>Budget: ${mission.budget_ceiling_usd.toLocaleString()}</span>
          )}
          <span>Created {new Date(mission.created_at).toLocaleDateString()}</span>
        </div>
      </CardContent>
    </Card>
  )
}

function EmptyDashboard() {
  const navigate = useNavigate()

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-24">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Rocket className="h-8 w-8 text-primary" />
      </div>
      <div className="text-center">
        <h2 className="text-xl font-semibold">Welcome to Mission Control</h2>
        <p className="mt-2 text-muted-foreground">
          Create your first mission to get started.
        </p>
      </div>
      <Button onClick={() => navigate('/missions/new')}>
        <Plus className="mr-2 h-4 w-4" />
        Create Mission
      </Button>
    </div>
  )
}

export default function DashboardPage() {
  const { data: missions, isLoading } = useMissions()
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }

  if (!missions || missions.length === 0) {
    return (
      <div className="p-8">
        <EmptyDashboard />
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {user?.display_name ? `Welcome back, ${user.display_name}` : 'Mission overview'}
          </p>
        </div>
        <Button onClick={() => navigate('/missions/new')}>
          <Plus className="mr-2 h-4 w-4" />
          New Mission
        </Button>
      </div>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {missions.map((mission) => (
          <MissionCard key={mission.id} mission={mission} />
        ))}
      </div>
    </div>
  )
}
