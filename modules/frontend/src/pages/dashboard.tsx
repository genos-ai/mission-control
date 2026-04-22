import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Archive, Plus, Rocket, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useMissions, useDeleteMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { ROUTES } from '@/lib/constants'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import type { MissionListItem, MissionStatus } from '@/types'
import { useQueryClient } from '@tanstack/react-query'
import { missionKeys } from '@/hooks/use-missions'

const statusVariant: Record<MissionStatus, 'success' | 'warning' | 'secondary'> = {
  active: 'success',
  paused: 'warning',
  archived: 'secondary',
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  variant,
  onConfirm,
  onCancel,
}: {
  title: string
  message: string
  confirmLabel: string
  variant: 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}) {
  const colors = variant === 'danger'
    ? 'bg-red-600 hover:bg-red-700'
    : 'bg-amber-600 hover:bg-amber-700'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onCancel}>
      <div
        className="w-full max-w-sm rounded-lg border bg-background p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold">{title}</h3>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm border hover:bg-muted"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`rounded-md px-3 py-1.5 text-sm text-white ${colors}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

function MissionCard({ mission, isAdmin }: { mission: MissionListItem; isAdmin: boolean }) {
  const navigate = useNavigate()
  const deleteMission = useDeleteMission()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<'delete' | 'archive' | null>(null)

  async function handleArchive() {
    try {
      await api.patch(`/missions/${mission.id}`, { status: 'archived' })
      toast.success(`${mission.name} archived`)
      queryClient.invalidateQueries({ queryKey: missionKeys.all })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Archive failed')
    }
    setDialog(null)
  }

  async function handleDelete() {
    try {
      await deleteMission.mutateAsync(mission.id)
      toast.success(`${mission.name} deleted`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
    setDialog(null)
  }

  return (
    <>
      {dialog === 'delete' && (
        <ConfirmDialog
          title="Delete mission"
          message={`Permanently delete "${mission.name}" and all related data? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          onConfirm={handleDelete}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'archive' && (
        <ConfirmDialog
          title="Archive mission"
          message={`Archive "${mission.name}"? You can restore it later.`}
          confirmLabel="Archive"
          variant="warning"
          onConfirm={handleArchive}
          onCancel={() => setDialog(null)}
        />
      )}
      <Card
        className="cursor-pointer transition-colors hover:border-primary/40"
        onClick={() => navigate(ROUTES.MISSION_OVERVIEW(mission.id))}
      >
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">{mission.name}</CardTitle>
              {mission.tier === 'platform' && (
                <Badge variant="outline" className="text-[10px] border-amber-500 text-amber-600">platform</Badge>
              )}
            </div>
            <Badge variant={statusVariant[mission.status]}>{mission.status}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {mission.description}
          </p>
          <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
            <div className="flex items-center gap-4">
              {mission.budget_ceiling_usd != null && (
                <span>Budget: ${mission.budget_ceiling_usd.toLocaleString()}</span>
              )}
              <span>Created {new Date(mission.created_at).toLocaleDateString()}</span>
            </div>
            {isAdmin && (
              <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                {mission.status !== 'archived' && (
                  <button
                    onClick={() => setDialog('archive')}
                    className="rounded p-1 text-muted-foreground/50 transition-colors hover:text-amber-600"
                    title="Archive mission"
                  >
                    <Archive className="h-3.5 w-3.5" />
                  </button>
                )}
                <button
                  onClick={() => setDialog('delete')}
                  className="rounded p-1 text-muted-foreground/50 transition-colors hover:text-red-600"
                  title="Delete mission"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </>
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
  const isAdmin = useAuthStore((s) => s.isAdmin)
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
          <MissionCard key={mission.id} mission={mission} isAdmin={isAdmin} />
        ))}
      </div>
    </div>
  )
}
