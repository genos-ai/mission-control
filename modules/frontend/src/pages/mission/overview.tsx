import { useState, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useMission, useDeleteMission } from '@/hooks/use-missions'
import { useTeam } from '@/hooks/use-team'
import { useMissionWorkflows } from '@/hooks/use-workflows'
import { useExecutions } from '@/hooks/use-executions'
import { Spinner } from '@/components/ui/spinner'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { Progress } from '@/components/ui/progress'
import { StatusIcon } from '@/components/ui/status-icon'
import { DocumentPage } from '@/components/layout/document-page'
import { ActiveRunCard } from '@/components/mission/active-run-card'
import { EnvironmentStatusCard } from '@/components/mission/environment-status-card'
import { MissionEditModal } from '@/components/mission/mission-edit-modal'
import { RecentErrors } from '@/components/mission/recent-errors'
import { RunModal } from '@/components/mission/run-modal'
import { SetupChecklist } from '@/components/mission/setup-checklist'
import { TeamPanel } from '@/components/mission/team-panel'
import { IntentStrip } from '@/components/knowledge/intent-strip'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { fmtCost, fmtUsd } from '@/lib/format'
import { formatRelative } from '@/lib/format-date'
import { runTone, styleFor } from '@/lib/status-tone'

const RECENT_RUN_ROWS = 4

export default function OverviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [showRunModal, setShowRunModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const { data: mission, isLoading } = useMission(id)
  const { data: team } = useTeam(id)
  const { data: workflows } = useMissionWorkflows(id)
  const { data: executionData } = useExecutions({ limit: 10, mission_id: id })
  const deleteMission = useDeleteMission()

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    )
  }

  if (!mission) return null

  const executions = executionData?.executions ?? []
  const activeRuns = executions.filter((e) => e.status === 'running')
  const recentRuns = executions.filter((e) => e.status !== 'running').slice(0, 5)
  const failedRuns = recentRuns.filter((e) => e.status === 'failed')
  const agentCount = team?.length ?? 0
  const workflowCount = workflows?.length ?? 0
  const hasBrief = !!mission.brief
  const needsSetup = !hasBrief || agentCount === 0
  const ceiling = mission.budget_ceiling_usd

  const handleDelete = () => {
    setConfirmingDelete(false)
    deleteMission.mutate(id!, {
      onSuccess: () => {
        toast.success(`Deleted: ${mission.name}`)
        navigate(ROUTES.DASHBOARD)
      },
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <DocumentPage className="gap-4">
      <div className="flex flex-col gap-2 pt-2">
        <div className="flex items-center gap-1">
          <span className="text-xs text-subtle">Brief</span>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={() => setShowEditModal(true)}>
              Edit
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="hover:text-danger"
              disabled={deleteMission.isPending}
              onClick={() => setConfirmingDelete(true)}
            >
              Delete
            </Button>
          </div>
        </div>
        {mission.brief && (
          <MarkdownRenderer
            content={mission.brief}
            className="max-w-[760px] text-xl leading-[26px] tracking-[-0.01em]"
          />
        )}
        {mission.description && (
          <p className={cn('max-w-[760px] text-sm text-muted-foreground', mission.brief && 'mt-1')}>
            {mission.description}
          </p>
        )}
      </div>

      <IntentStrip missionId={id!} />

      {confirmingDelete && (
        <ConfirmDialog
          title="Delete mission"
          message={`Delete "${mission.name}"?`}
          confirmLabel="Delete"
          variant="danger"
          onConfirm={handleDelete}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}

      {showRunModal && (
        <RunModal
          missionId={id!}
          missionBrief={mission.brief ?? undefined}
          onClose={() => setShowRunModal(false)}
          onStarted={() => {
            setShowRunModal(false)
            navigate(ROUTES.MISSION_PLAN(id!))
          }}
        />
      )}

      {showEditModal && (
        <MissionEditModal
          mission={mission}
          missionId={id!}
          onClose={() => setShowEditModal(false)}
        />
      )}

      <Panel className="overflow-hidden">
        {/* Each cell has a left and top border and the grid is shifted by 1px, so the panel clips the outer ones: only inner dividers show, however the cells wrap. */}
        <div className="-ml-px -mt-px grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
          <Fact label="Status" value={mission.status} capitalize />
          <Fact label="Environment" value={mission.execution_environment ?? 'local'} capitalize />
          <Fact
            label="Budget"
            value={ceiling != null ? `${fmtUsd(mission.spent_usd)} / ${fmtUsd(ceiling)}` : `${fmtUsd(mission.spent_usd)} spent`}
          >
            {ceiling != null && (
              <Progress
                value={ceiling > 0 ? (mission.spent_usd / ceiling) * 100 : 100}
                size="sm"
                label="Budget spent"
                className="mt-2"
              />
            )}
          </Fact>
          <Fact
            label="Agents"
            value={String(agentCount)}
            empty={agentCount === 0 ? { label: 'Add agents', to: ROUTES.MISSION_TEAM(id!) } : undefined}
          />
          <Fact
            label="Workflows"
            value={String(workflowCount)}
            empty={workflowCount === 0 ? { label: 'Set up workflows', to: ROUTES.MISSION_WORKFLOWS(id!) } : undefined}
          />
        </div>
      </Panel>

      {mission.execution_environment === 'container' && <EnvironmentStatusCard missionId={id!} />}

      {needsSetup && executions.length === 0 && (
        <SetupChecklist
          hasBrief={hasBrief}
          agentCount={agentCount}
          workflowCount={workflowCount}
          missionId={id!}
          onEditBrief={() => setShowEditModal(true)}
        />
      )}

      {activeRuns.map((run) => (
        <ActiveRunCard
          key={run.id}
          execution={run}
          onClick={() => navigate(ROUTES.MISSION_RUN_LIVE(id!, run.id))}
        />
      ))}

      {failedRuns.length > 0 && (
        <RecentErrors failedRunIds={failedRuns.slice(0, 3).map((r) => r.id)} missionId={id!} />
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-4">
        <Panel>
          <PanelHeader
            title="Recent runs"
            actions={
              <Button variant="link" size="sm" onClick={() => navigate(ROUTES.MISSION_RUNS(id!))}>
                View all
              </Button>
            }
          />
          <PanelContent className="px-0 pb-2">
            {recentRuns.length === 0 ? (
              <div className="px-4 pb-2">
                <p className="text-sm text-subtle">No runs yet.</p>
                <Button
                  variant="link"
                  size="sm"
                  className="mt-1 h-auto p-0"
                  onClick={() => setShowRunModal(true)}
                >
                  Start your first run
                </Button>
              </div>
            ) : (
              recentRuns.slice(0, RECENT_RUN_ROWS).map((run) => (
                <button
                  key={run.id}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors hover:bg-hover"
                  onClick={() => navigate(ROUTES.MISSION_RUN_LIVE(id!, run.id))}
                >
                  <StatusIcon {...styleFor(runTone, run.status, 'run')} />
                  <span className="font-mono text-xs text-text-3">{run.id.slice(0, 8)}</span>
                  <span className="min-w-0 flex-1 truncate">{run.objective_statement}</span>
                  <span className="font-mono text-xs text-subtle">{fmtCost(run.total_cost_usd)}</span>
                  <span className="text-xs text-subtle">{formatRelative(run.created_at)}</span>
                </button>
              ))
            )}
          </PanelContent>
        </Panel>

        <TeamPanel missionId={id!} members={team ?? []} />
      </div>
    </DocumentPage>
  )
}

interface FactProps {
  label: string
  value: string
  capitalize?: boolean
  /** For a count of zero: mutes the value and adds a link to where it is set up. */
  empty?: { label: string; to: string }
  children?: ReactNode
}

/** One cell of the facts strip. */
function Fact({ label, value, capitalize, empty, children }: FactProps) {
  const navigate = useNavigate()
  return (
    <div className="border-l border-t border-line px-4 py-3.5">
      <p className="text-xs text-subtle">{label}</p>
      <p
        className={cn(
          'mt-1 text-[18px] font-medium tracking-[-0.02em]',
          capitalize && 'capitalize',
          empty && 'text-muted-foreground',
        )}
      >
        {value}
      </p>
      {empty && (
        <Button
          variant="link"
          size="sm"
          className="mt-1 h-auto p-0"
          onClick={() => navigate(empty.to)}
        >
          {empty.label} &rarr;
        </Button>
      )}
      {children}
    </div>
  )
}
