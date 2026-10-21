import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Rocket } from 'lucide-react'
import { useMissions } from '@/hooks/use-missions'
import { useExecutions } from '@/hooks/use-executions'
import { useAttention } from '@/hooks/use-attention'
import { useAuthStore } from '@/stores/auth'
import { AttentionPanel } from '@/components/dashboard/attention-panel'
import { MissionCard, NewMissionTile } from '@/components/dashboard/mission-card'
import { DocumentPage } from '@/components/layout/document-page'
import { TopBar } from '@/components/layout/top-bar'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Segmented } from '@/components/ui/segmented'
import { Spinner } from '@/components/ui/spinner'
import type { MissionStatus } from '@/types'

const NEW_MISSION_PATH = '/missions/new'

type Filter = 'all' | MissionStatus

const FILTER_OPTIONS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
  { value: 'archived', label: 'Archived' },
]

function greeting(hour: number): string {
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export default function DashboardPage() {
  const { data: missions, isLoading } = useMissions()
  const { data: running } = useExecutions({ status: 'running', limit: 5 })
  const { data: attention } = useAttention()
  const user = useAuthStore((s) => s.user)
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')

  const topBar = (
    <TopBar
      segments={[{ label: 'Home' }]}
      actions={<Button onClick={() => navigate(NEW_MISSION_PATH)}>New mission</Button>}
    />
  )

  if (isLoading) {
    return (
      <>
        {topBar}
        <div className="flex items-center justify-center py-24">
          <Spinner className="h-8 w-8" />
        </div>
      </>
    )
  }

  if (!missions || missions.length === 0) {
    return (
      <>
        {topBar}
        <EmptyState
          icon={<Rocket className="h-4 w-4" />}
          title="Welcome to Mission Control"
          description="Create your first mission to get started."
          action={{ label: 'Create mission', onClick: () => navigate(NEW_MISSION_PATH) }}
        />
      </>
    )
  }

  const countOf = (f: Filter) => (f === 'all' ? missions.length : missions.filter((m) => m.status === f).length)
  const visible = filter === 'all' ? missions : missions.filter((m) => m.status === filter)

  const firstName = user ? (user.display_name || user.email.split('@')[0]).split(/\s+/)[0] : null
  const summary = [
    countOf('active') > 0 && `${plural(countOf('active'), 'mission', 'missions')} active`,
    running && running.total > 0 && `${plural(running.total, 'run', 'runs')} in progress`,
    attention && attention.items.length > 0 && `${plural(attention.items.length, 'item', 'items')} waiting on you`,
  ].filter(Boolean)

  return (
    <>
      {topBar}
      <DocumentPage className="gap-6">
        <div className="flex flex-col gap-1.5 pt-4">
          <h1 className="text-3xl font-semibold tracking-[-0.025em]">
            {greeting(new Date().getHours())}
            {firstName && `, ${firstName}`}
          </h1>
          {summary.length > 0 && <p className="text-md text-muted-foreground">{summary.join(' · ')}</p>}
        </div>

        <AttentionPanel />

        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xs font-medium text-subtle">Missions</h2>
            <Segmented
              label="Filter missions"
              value={filter}
              onChange={setFilter}
              options={FILTER_OPTIONS.map((o) => ({ ...o, count: countOf(o.value) }))}
            />
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
            {visible.map((mission) => (
              <MissionCard key={mission.id} mission={mission} isAdmin={isAdmin} />
            ))}
            <NewMissionTile />
          </div>
        </section>
      </DocumentPage>
    </>
  )
}
