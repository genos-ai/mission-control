import { useLocation } from 'react-router-dom'
import { Loader2, MoreHorizontal, Pause, Play, RotateCcw } from 'lucide-react'

import { TopBar, type TopBarSegment } from '@/components/layout/top-bar'
import { Button } from '@/components/ui/button'
import { StatusPill } from '@/components/ui/status-pill'
import { useBackgroundTasks } from '@/hooks/use-executions'
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useRunningMissionRun } from '@/hooks/use-mission-runs'
import { MISSION_NAV_GROUPS, ROUTES } from '@/lib/constants'
import { missionTone } from '@/lib/status-tone'
import { useAuthStore } from '@/stores/auth'
import type { MissionStatus } from '@/types'

export interface MissionTopBarProps {
  missionId: string
  onOpenSettings: () => void
  onRun: () => void
}

const SECTIONS = MISSION_NAV_GROUPS.flat()

/** The breadcrumb's tail for the current URL: the section, plus the run id on a run page. */
function sectionSegments(missionId: string, pathname: string): TopBarSegment[] {
  const section = SECTIONS.find((item) => pathname.startsWith(item.to(missionId)))
  if (!section) return []
  const tail: TopBarSegment[] = [{ label: section.label, to: section.to(missionId) }]
  const run = new RegExp(`^${ROUTES.MISSION_RUNS(missionId)}/([^/]+)$`).exec(pathname)
  if (run) tail.push({ label: run[1].slice(0, 8) })
  return tail
}

export function MissionTopBar({ missionId, onOpenSettings, onRun }: MissionTopBarProps) {
  const { pathname } = useLocation()
  const { data: mission, isLoading } = useMission(missionId)
  const updateMission = useUpdateMission(missionId)
  const user = useAuthStore((s) => s.user)
  const run = useRunningMissionRun(missionId)
  const { activeCount: bgTaskCount, activeTasks: bgTasks } = useBackgroundTasks(missionId)

  const isOwner = mission?.owner_id === user?.id

  const name = mission?.name ?? (isLoading ? 'Loading…' : 'Mission not found')
  const segments: TopBarSegment[] = [
    { label: 'Missions', to: ROUTES.DASHBOARD },
    { label: name, to: ROUTES.MISSION(missionId) },
    ...sectionSegments(missionId, pathname),
  ]

  const status = mission && (
    <div className="flex items-center gap-2">
      <StatusPill tone={missionTone[mission.status as MissionStatus].tone}>{mission.status}</StatusPill>
      {mission.tier === 'platform' && (
        <StatusPill tone="warning" dot={false}>
          platform
        </StatusPill>
      )}
    </div>
  )

  const bgTitle = bgTasks.map((t) => `${t.task_type}: ${t.status}`).join('\n')
  const showPill = run !== null || bgTaskCount > 0

  return (
    <TopBar
      segments={segments}
      status={status}
      actions={
        <>
          {showPill && (
            <div
              className="flex h-[26px] items-center gap-1.5 rounded-full border border-warning/25 bg-warning/5 px-2.5 text-xs text-warning"
              title={bgTitle || undefined}
            >
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
              {run ? (
                <>
                  <span className="max-[1099px]:hidden">
                    Run #{run.sequence} · {run.completed_task_count} of {run.task_count}
                  </span>
                  <span className="min-[1100px]:hidden">
                    {run.completed_task_count}/{run.task_count}
                  </span>
                </>
              ) : (
                <span>
                  {bgTaskCount} background {bgTaskCount === 1 ? 'task' : 'tasks'}
                </span>
              )}
            </div>
          )}
          {isOwner && mission?.status === 'active' && (
            <Button variant="secondary" onClick={() => updateMission.mutate({ status: 'paused' })}>
              <Pause className="h-[13px] w-[13px]" />
              Pause
            </Button>
          )}
          {isOwner && mission?.status === 'paused' && (
            <Button variant="secondary" onClick={() => updateMission.mutate({ status: 'active' })}>
              <RotateCcw className="h-[13px] w-[13px]" />
              Resume
            </Button>
          )}
          <Button variant="secondary" size="icon" aria-label="Mission settings" onClick={onOpenSettings}>
            <MoreHorizontal className="h-[15px] w-[15px]" />
          </Button>
          <Button onClick={onRun}>
            <Play className="h-[13px] w-[13px]" />
            Run
          </Button>
        </>
      }
    />
  )
}
