import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import {
  Play,
  AlertTriangle,
  Settings,
  X,
  CheckCircle,
  Circle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useMission, useUpdateMission } from '@/hooks/use-missions'
import { useTeam } from '@/hooks/use-team'
import { useMissionWorkflows } from '@/hooks/use-workflows'
import { useExecutions, useExecution } from '@/hooks/use-executions'
import { Spinner } from '@/components/ui/spinner'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ActiveRunCard } from '@/components/mission/active-run-card'
import { RunModal } from '@/components/mission/run-modal'
import { ROUTES } from '@/lib/constants'

export default function OverviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [showRunModal, setShowRunModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const { data: mission, isLoading } = useMission(id)
  const { data: team } = useTeam(id)
  const { data: workflows } = useMissionWorkflows(id)
  const { data: executionData } = useExecutions({ limit: 10, mission_id: id })

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
  const totalCost = executions.reduce((sum, e) => sum + e.total_cost_usd, 0)
  const failedRuns = recentRuns.filter((e) => e.status === 'failed')
  const agentCount = team?.length ?? 0
  const workflowCount = workflows?.length ?? 0
  const hasBrief = !!mission.brief
  const needsSetup = !hasBrief || agentCount === 0

  return (
    <div className="p-6 space-y-6">
      {/* Action bar */}
      <div className="flex items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowEditModal(true)}
        >
          <Settings className="mr-2 h-4 w-4" />
          Settings
        </Button>
        <Button onClick={() => setShowRunModal(true)}>
          <Play className="mr-2 h-4 w-4" />
          New Run
        </Button>
      </div>

      {showRunModal && (
        <RunModal
          missionId={id!}
          missionBrief={mission.brief ?? undefined}
          onClose={() => setShowRunModal(false)}
          onStarted={(execId) => {
            setShowRunModal(false)
            navigate(ROUTES.MISSION_RUN_LIVE(id!, execId))
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

      {/* Setup checklist — shown when mission needs configuration */}
      {needsSetup && executions.length === 0 && (
        <SetupChecklist
          hasBrief={hasBrief}
          agentCount={agentCount}
          workflowCount={workflowCount}
          missionId={id!}
        />
      )}

      {/* Active runs */}
      {activeRuns.map((run) => (
        <ActiveRunCard
          key={run.id}
          execution={run}
          onClick={() => navigate(ROUTES.MISSION_RUN_LIVE(id!, run.id))}
        />
      ))}

      {/* Failure banner */}
      {failedRuns.length > 0 && activeRuns.length === 0 && (
        <FailureBanner lastFailedId={failedRuns[0].id} />
      )}

      {/* Quick stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Status" value={mission.status} capitalize />
        <StatCard
          label="Budget"
          value={
            mission.budget_ceiling_usd != null
              ? `$${mission.budget_ceiling_usd.toLocaleString()}`
              : 'No limit'
          }
        />
        <StatCard
          label="Agents"
          value={String(agentCount)}
          emptyAction={
            agentCount === 0
              ? { label: 'Add agents', onClick: () => navigate(ROUTES.MISSION_TEAM(id!)) }
              : undefined
          }
        />
        <StatCard
          label="Workflows"
          value={String(workflowCount)}
          emptyAction={
            workflowCount === 0
              ? { label: 'Set up workflows', onClick: () => navigate(ROUTES.MISSION_WORKFLOWS(id!)) }
              : undefined
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Mission summary */}
        <div className="space-y-4">
          {mission.brief && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Brief
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm">{mission.brief}</p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Description
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm">{mission.description}</p>
            </CardContent>
          </Card>
        </div>

        {/* Recent runs */}
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Recent Runs
              </CardTitle>
              {executions.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  ${totalCost.toFixed(4)} total
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {recentRuns.length === 0 ? (
              <div className="py-4 text-center">
                <p className="text-sm text-muted-foreground">No runs yet.</p>
                <Button
                  variant="link"
                  size="sm"
                  className="mt-1"
                  onClick={() => setShowRunModal(true)}
                >
                  Start your first run
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {recentRuns.map((run) => (
                  <button
                    key={run.id}
                    className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
                    onClick={() =>
                      navigate(ROUTES.MISSION_RUN_LIVE(id!, run.id))
                    }
                  >
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          run.status === 'completed'
                            ? 'success'
                            : run.status === 'failed'
                              ? 'destructive'
                              : 'secondary'
                        }
                        className="text-[10px]"
                      >
                        {run.status}
                      </Badge>
                      <span className="font-mono text-xs">
                        {run.id.slice(0, 8)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>${run.total_cost_usd.toFixed(4)}</span>
                      {run.created_at && (
                        <span>
                          {formatDistanceToNow(new Date(run.created_at), {
                            addSuffix: true,
                          })}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// --- Sub-components ---

function FailureBanner({ lastFailedId }: { lastFailedId: string }) {
  const { data: detail } = useExecution(lastFailedId)

  // Extract failure reason from task executions or outcome
  let reason = ''
  if (detail) {
    const failedTask = detail.task_executions.find((t) => t.status === 'failed')
    if (failedTask?.output_data) {
      reason = String(
        (failedTask.output_data as Record<string, unknown>).error ??
          (failedTask.output_data as Record<string, unknown>).message ??
          '',
      )
    }
    if (!reason && detail.execution_outcome_json) {
      const outcome = detail.execution_outcome_json as Record<string, unknown>
      reason = String(outcome.error ?? outcome.summary ?? '')
    }
    if (!reason) {
      reason = `${detail.task_executions.filter((t) => t.status === 'failed').length} task(s) failed`
    }
  }

  return (
    <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
      <AlertTriangle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
      <div>
        <p className="text-sm font-medium text-destructive">
          Last run failed
        </p>
        {reason && (
          <p className="mt-0.5 text-xs text-muted-foreground">{reason}</p>
        )}
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  capitalize,
  emptyAction,
}: {
  label: string
  value: string
  capitalize?: boolean
  emptyAction?: { label: string; onClick: () => void }
}) {
  const isEmpty = value === '0' && emptyAction
  return (
    <Card className={isEmpty ? 'border-dashed' : ''}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p
          className={`text-2xl font-bold ${capitalize ? 'capitalize' : ''} ${isEmpty ? 'text-muted-foreground' : ''}`}
        >
          {value}
        </p>
        {isEmpty && (
          <Button
            variant="link"
            size="sm"
            className="mt-1 h-auto p-0 text-xs"
            onClick={emptyAction.onClick}
          >
            {emptyAction.label} &rarr;
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

function SetupChecklist({
  hasBrief,
  agentCount,
  workflowCount,
  missionId,
}: {
  hasBrief: boolean
  agentCount: number
  workflowCount: number
  missionId: string
}) {
  const navigate = useNavigate()

  const steps = [
    {
      done: hasBrief,
      label: 'Set a mission brief',
      hint: 'Click the brief area in the header above to describe your objective',
      action: undefined, // inline edit in header
    },
    {
      done: agentCount > 0,
      label: 'Add agents to your team',
      hint: 'Browse the catalog and assign agents to this mission',
      action: () => navigate(ROUTES.MISSION_TEAM(missionId)),
    },
    {
      done: workflowCount > 0,
      label: 'Set up a workflow (optional)',
      hint: 'Import a template or design one with the Architect',
      action: () => navigate(ROUTES.MISSION_WORKFLOWS(missionId)),
    },
  ]

  const completedCount = steps.filter((s) => s.done).length

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">
          Get started ({completedCount}/{steps.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {steps.map((step, i) => (
          <button
            key={i}
            onClick={step.action}
            disabled={!step.action || step.done}
            className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent"
          >
            {step.done ? (
              <CheckCircle className="mt-0.5 h-4 w-4 text-emerald-500 flex-shrink-0" />
            ) : (
              <Circle className="mt-0.5 h-4 w-4 text-muted-foreground flex-shrink-0" />
            )}
            <div>
              <p
                className={`text-sm font-medium ${step.done ? 'text-muted-foreground line-through' : ''}`}
              >
                {step.label}
              </p>
              {!step.done && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {step.hint}
                </p>
              )}
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  )
}

function MissionEditModal({
  mission,
  missionId,
  onClose,
}: {
  mission: { description: string; brief: string | null; budget_ceiling_usd: number | null }
  missionId: string
  onClose: () => void
}) {
  const updateMission = useUpdateMission(missionId)
  const [description, setDescription] = useState(mission.description)
  const [brief, setBrief] = useState(mission.brief ?? '')
  const [budget, setBudget] = useState(
    mission.budget_ceiling_usd != null ? String(mission.budget_ceiling_usd) : '',
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    updateMission.mutate(
      {
        description,
        brief: brief || undefined,
        budget_ceiling_usd: budget ? parseFloat(budget) : null,
      },
      {
        onSuccess: () => {
          toast.success('Mission updated')
          onClose()
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Mission Settings</h3>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium">
              Description
            </label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">Brief</label>
            <Textarea
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={3}
              placeholder="Strategic brief for agents..."
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">
              Budget (USD)
            </label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="No limit"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateMission.isPending}>
              {updateMission.isPending ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
