import { useParams, useNavigate } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { useMission } from '@/hooks/use-missions'
import { useTeam } from '@/hooks/use-team'
import { useMissionWorkflows } from '@/hooks/use-workflows'
import { useExecutions } from '@/hooks/use-executions'
import { Spinner } from '@/components/ui/spinner'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ActiveRunCard } from '@/components/mission/active-run-card'
import { ROUTES } from '@/lib/constants'

export default function OverviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
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

  return (
    <div className="p-6 space-y-6">
      {/* Active runs */}
      {activeRuns.map((run) => (
        <ActiveRunCard key={run.id} execution={run} />
      ))}

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
        <StatCard label="Agents" value={String(team?.length ?? 0)} />
        <StatCard label="Workflows" value={String(workflows?.length ?? 0)} />
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
                  onClick={() => navigate(ROUTES.MISSION_WORKFLOWS(id!))}
                >
                  Go to Workflows
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {recentRuns.map((run) => (
                  <button
                    key={run.id}
                    className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
                    onClick={() => navigate(ROUTES.MISSION_RUNS(id!))}
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

function StatCard({
  label,
  value,
  capitalize,
}: {
  label: string
  value: string
  capitalize?: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-2xl font-bold ${capitalize ? 'capitalize' : ''}`}>
          {value}
        </p>
      </CardContent>
    </Card>
  )
}
