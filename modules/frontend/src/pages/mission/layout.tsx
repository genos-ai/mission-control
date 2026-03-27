import { useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import {
  Activity,
  Users,
  MessageSquare,
  GitBranch,
  Play,
  FlaskConical,
  FileText,
  Pause,
  Archive,
  RotateCcw,
  Pencil,
  Check,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import type { MissionStatus } from '@/types'

const tabs = [
  { label: 'Overview', icon: Activity, path: 'overview' },
  { label: 'Team', icon: Users, path: 'team' },
  { label: 'Chat', icon: MessageSquare, path: 'chat' },
  { label: 'Workflows', icon: GitBranch, path: 'workflows' },
  { label: 'Runs', icon: Play, path: 'runs' },
  { label: 'Workshop', icon: FlaskConical, path: 'workshop' },
  { label: 'Context', icon: FileText, path: 'context' },
]

const statusVariant: Record<MissionStatus, 'success' | 'warning' | 'secondary'> = {
  active: 'success',
  paused: 'warning',
  archived: 'secondary',
}

export default function MissionLayout() {
  const { id } = useParams<{ id: string }>()
  const { data: mission, isLoading } = useMission(id)
  const updateMission = useUpdateMission(id!)
  const user = useAuthStore((s) => s.user)

  const isOwner = mission?.owner_id === user?.id

  function setStatus(status: MissionStatus) {
    updateMission.mutate({ status })
  }

  return (
    <div className="flex h-full flex-col">
      {/* Mission header */}
      <div className="flex items-start justify-between border-b px-6 py-4">
        <div className="min-w-0 flex-1">
          {isLoading ? (
            <Spinner className="h-5 w-5" />
          ) : mission ? (
            <>
              <div className="flex items-center gap-3">
                <h1 className="truncate text-lg font-bold">{mission.name}</h1>
                <Badge variant={statusVariant[mission.status as MissionStatus]}>
                  {mission.status}
                </Badge>
              </div>
              <InlineBrief
                brief={mission.brief}
                missionId={id!}
                editable={isOwner}
              />
            </>
          ) : (
            <p className="text-muted-foreground">Mission not found</p>
          )}
        </div>

        {isOwner && mission && (
          <div className="ml-4 flex shrink-0 items-center gap-2">
            {mission.status === 'active' && (
              <Button variant="outline" size="sm" onClick={() => setStatus('paused')}>
                <Pause className="mr-1.5 h-3.5 w-3.5" />
                Pause
              </Button>
            )}
            {mission.status === 'paused' && (
              <Button variant="outline" size="sm" onClick={() => setStatus('active')}>
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Resume
              </Button>
            )}
            {mission.status !== 'archived' && (
              <Button variant="outline" size="sm" onClick={() => setStatus('archived')}>
                <Archive className="mr-1.5 h-3.5 w-3.5" />
                Archive
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex border-b px-4">
        {tabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={`/missions/${id}/${tab.path}`}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </NavLink>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}

function InlineBrief({
  brief,
  missionId,
  editable,
}: {
  brief: string | null
  missionId: string
  editable: boolean
}) {
  const updateMission = useUpdateMission(missionId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(brief ?? '')

  const save = () => {
    const value = draft.trim()
    updateMission.mutate(
      { brief: value || undefined },
      {
        onSuccess: () => {
          setEditing(false)
          toast.success('Brief updated')
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  if (editing) {
    return (
      <div className="mt-1 flex items-center gap-2">
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') {
              setEditing(false)
              setDraft(brief ?? '')
            }
          }}
          className="flex-1 rounded-md border bg-transparent px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Set mission objective / brief..."
        />
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={save}
          disabled={updateMission.isPending}
        >
          <Check className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => {
            setEditing(false)
            setDraft(brief ?? '')
          }}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
    )
  }

  if (!brief && editable) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        <Pencil className="h-3 w-3" />
        <span className="italic">Set mission brief...</span>
      </button>
    )
  }

  return (
    <button
      onClick={() => editable && setEditing(true)}
      className={cn(
        'mt-1 flex items-center gap-1.5 text-sm text-muted-foreground group',
        editable && 'cursor-pointer hover:text-foreground',
      )}
    >
      <span className="line-clamp-1">{brief}</span>
      {editable && (
        <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
      )}
    </button>
  )
}
