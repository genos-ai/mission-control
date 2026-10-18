import { Loader2, DollarSign, Users, Briefcase, Cpu } from 'lucide-react'
import { useMetricsOverview, useMetricsCosts, useMetricsAgents } from '@/hooks/use-admin'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'

export default function AdminMetricsPage() {
  const { data: overview, isLoading: loadingOverview } = useMetricsOverview()
  const { data: costs, isLoading: loadingCosts } = useMetricsCosts()
  const { data: agents, isLoading: loadingAgents } = useMetricsAgents()

  if (loadingOverview) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold">Platform Metrics</h2>

      {/* Overview cards */}
      {overview && (
        <div className="grid grid-cols-3 gap-4">
          <StatCard
            icon={<Users className="h-4 w-4" />}
            label="Users"
            value={overview.user_count}
          />
          <StatCard
            icon={<Briefcase className="h-4 w-4" />}
            label="Missions"
            value={overview.mission_count}
          />
          <StatCard
            icon={<Cpu className="h-4 w-4" />}
            label="Executions"
            value={overview.execution_count}
          />
          <StatCard
            icon={<DollarSign className="h-4 w-4" />}
            label="Total Cost"
            value={`$${overview.total_cost_usd.toFixed(2)}`}
          />
          <StatCard
            label="Workflows"
            value={overview.workflow_count}
          />
          <StatCard
            label="Active Sessions"
            value={overview.active_sessions}
          />
        </div>
      )}

      {/* Cost breakdown */}
      {!loadingCosts && costs && (
        <Panel>
          <PanelHeader title="Cost by Agent" />
          <PanelContent>
            <div className="space-y-2">
              {costs.by_agent.map((entry) => (
                <div
                  key={entry.agent_name}
                  className="flex items-center justify-between text-sm"
                >
                  <div className="flex items-center gap-2">
                    <span>{entry.agent_name}</span>
                    <Badge>
                      {entry.run_count} runs
                    </Badge>
                  </div>
                  <span className="font-mono">
                    ${entry.cost_usd.toFixed(4)}
                  </span>
                </div>
              ))}
              {!costs.by_agent.length && (
                <p className="text-xs text-muted-foreground">No cost data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>
      )}

      {/* Agent utilisation */}
      {!loadingAgents && agents && (
        <Panel>
          <PanelHeader title="Agent Utilisation" />
          <PanelContent>
            <div className="space-y-2">
              {agents.map((agent) => (
                <div
                  key={agent.agent_name}
                  className="flex items-center justify-between text-sm"
                >
                  <span>{agent.agent_name}</span>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{agent.run_count} runs</span>
                    <span>
                      {agent.avg_duration_seconds.toFixed(1)}s avg
                    </span>
                    <span className="font-mono">
                      ${agent.total_cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>
              ))}
              {!agents.length && (
                <p className="text-xs text-muted-foreground">No agent data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>
      )}
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode
  label: string
  value: string | number
}) {
  return (
    <Panel>
      <PanelContent className="flex items-center gap-3 py-4 px-4">
        {icon && (
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            {icon}
          </div>
        )}
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-semibold">{value}</p>
        </div>
      </PanelContent>
    </Panel>
  )
}
