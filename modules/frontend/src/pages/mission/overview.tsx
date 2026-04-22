import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { formatUtc } from '@/lib/format-date'
import {
  Play,
  AlertTriangle,
  Settings,
  X,
  XCircle,
  CheckCircle,
  Circle,
  Container,
  Trash2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useMission, useUpdateMission, useDeleteMission, useMissionEnvironment } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
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
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { IntentStrip } from '@/components/knowledge/intent-strip'

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
      {/* Current intent strip */}
      <IntentStrip missionId={id!} />

      {/* Action bar */}
      <div className="flex items-center justify-end gap-2">
        <DeleteMissionButton missionId={id!} missionName={mission.name} />
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

      {/* Quick stats — always first */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Status" value={mission.status} capitalize />
        <StatCard
          label="Environment"
          value={mission.execution_environment ?? 'local'}
          capitalize
        />
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

      {/* Container status — shown when execution_environment is container */}
      {mission.execution_environment === 'container' && (
        <EnvironmentStatusCard missionId={id!} />
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

      {/* Brief + Description */}
      {(mission.brief || mission.description) && (
        <Card>
          <CardContent className="pt-4">
            {mission.brief && (
              <MarkdownRenderer content={mission.brief} />
            )}
            {mission.brief && mission.description && (
              <hr className="my-3 border-muted" />
            )}
            <p className="text-sm text-muted-foreground">
              {mission.description}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Recent errors */}
      {failedRuns.length > 0 && (
        <RecentErrors
          failedRunIds={failedRuns.slice(0, 3).map((r) => r.id)}
          missionId={id!}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent runs */}

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
                          {formatUtc(run.created_at)}
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

function RecentErrors({
  failedRunIds,
  missionId,
}: {
  failedRunIds: string[]
  missionId: string
}) {
  const navigate = useNavigate()
  // Fetch details for up to 3 recent failed runs
  const q0 = useExecution(failedRunIds[0])
  const q1 = useExecution(failedRunIds[1])
  const q2 = useExecution(failedRunIds[2])
  const details = [q0.data, q1.data, q2.data].filter(Boolean)

  // Extract all task-level errors across runs
  const errors: { runId: string; agent: string; error: string; when: string }[] = []
  for (const detail of details) {
    if (!detail) continue
    for (const task of detail.task_executions) {
      if (task.status !== 'failed') continue
      const output = task.output_data as Record<string, unknown> | null
      const msg =
        String(output?.error ?? output?.message ?? '') ||
        `${task.agent_name} failed`
      errors.push({
        runId: detail.id,
        agent: task.agent_name,
        error: msg,
        when: task.completed_at ?? task.started_at ?? detail.created_at,
      })
    }
  }

  if (errors.length === 0) return null

  return (
    <Card className="border-destructive/20">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-destructive" />
          <CardTitle className="text-sm font-medium text-destructive">
            Recent Errors ({errors.length})
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {errors.slice(0, 5).map((err, i) => (
          <button
            key={i}
            onClick={() =>
              navigate(ROUTES.MISSION_RUN_LIVE(missionId, err.runId))
            }
            className="flex w-full items-start gap-3 rounded-md border border-destructive/10 bg-destructive/5 px-3 py-2 text-left transition-colors hover:bg-destructive/10"
          >
            <XCircle className="h-3.5 w-3.5 text-destructive flex-shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">{err.agent}</span>
                <span className="text-[10px] text-muted-foreground">
                  {formatUtc(err.when)}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground truncate">
                {err.error}
              </p>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
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
  mission: { description: string; brief: string | null; budget_ceiling_usd: number | null; execution_environment: string | null }
  missionId: string
  onClose: () => void
}) {
  const updateMission = useUpdateMission(missionId)
  const [description, setDescription] = useState(mission.description)
  const [brief, setBrief] = useState(mission.brief ?? '')
  const [budget, setBudget] = useState(
    mission.budget_ceiling_usd != null ? String(mission.budget_ceiling_usd) : '',
  )
  const [execEnv, setExecEnv] = useState(mission.execution_environment ?? 'local')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    updateMission.mutate(
      {
        description,
        brief: brief || undefined,
        budget_ceiling_usd: budget ? parseFloat(budget) : null,
        execution_environment: execEnv === 'local' ? undefined : execEnv,
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

          <div>
            <label className="mb-1 block text-sm font-medium">
              Execution Environment
            </label>
            <select
              value={execEnv}
              onChange={(e) => setExecEnv(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="local">Local (in-process)</option>
              <option value="container">Container (Docker isolation)</option>
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Container mode runs agent tasks inside Docker for full isolation.
              The container persists across runs within this mission.
            </p>
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


function EnvironmentStatusCard({ missionId }: { missionId: string }) {
  const { data: envData } = useMissionEnvironment(missionId)
  const active = envData?.active_environment
  const allEnvs = envData?.all_environments ?? []

  const statusColor = active
    ? 'text-green-500'
    : allEnvs.length > 0
      ? 'text-yellow-500'
      : 'text-muted-foreground'

  const statusText = active
    ? 'Running'
    : allEnvs.length > 0
      ? 'Stopped'
      : 'No container'

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Container className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm">Execution Environment</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${active ? 'bg-green-500' : 'bg-muted'}`} />
              <span className={`text-sm font-medium ${statusColor}`}>{statusText}</span>
            </div>
            {active && (
              <div className="space-y-0.5 text-xs text-muted-foreground">
                <p>Container: {active.container_name}</p>
                <p>Image: {active.image ?? 'code-workspace:latest'}</p>
                <p>Executions: {active.execution_count}</p>
                {active.last_execution_at && (
                  <p>Last active: {formatUtc(active.last_execution_at)}</p>
                )}
              </div>
            )}
            {!active && allEnvs.length === 0 && (
              <p className="text-xs text-muted-foreground">
                A container will be created on the first run.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}


function DeleteMissionButton({ missionId, missionName }: { missionId: string; missionName: string }) {
  const navigate = useNavigate()
  const deleteMission = useDeleteMission()
  useAuthStore()
  const [confirming, setConfirming] = useState(false)

  // TODO: also allow owner to delete (check mission.owner_id === user.id)
  // For now, show for admin always, and for all users (ownership check pending)

  if (confirming) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-xs text-destructive">Delete "{missionName}"?</span>
        <Button
          variant="destructive"
          size="sm"
          disabled={deleteMission.isPending}
          onClick={() => {
            deleteMission.mutate(missionId, {
              onSuccess: () => {
                toast.success(`Deleted: ${missionName}`)
                navigate(ROUTES.DASHBOARD)
              },
              onError: (err) => toast.error(err.message),
            })
          }}
        >
          {deleteMission.isPending ? 'Deleting...' : 'Confirm'}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          Cancel
        </Button>
      </div>
    )
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      className="text-muted-foreground hover:text-destructive"
      onClick={() => setConfirming(true)}
    >
      <Trash2 className="mr-2 h-4 w-4" />
      Delete
    </Button>
  )
}
