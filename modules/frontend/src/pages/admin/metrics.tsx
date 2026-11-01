import { useMetricsOverview, useMetricsCosts, useMetricsAgents } from '@/hooks/use-admin'
import { AdminCostByAgentPanel } from '@/components/admin/admin-cost-panel'
import { AgentUtilisationPanel } from '@/components/admin/agent-utilisation-panel'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { StatCard } from '@/components/ui/stat-card'
import { fmtUsd } from '@/lib/format'

export default function AdminMetricsPage() {
  const { data: overview, isLoading: loadingOverview } = useMetricsOverview()
  const { data: costs, isLoading: loadingCosts } = useMetricsCosts()
  const { data: agents, isLoading: loadingAgents } = useMetricsAgents()

  if (loadingOverview) {
    return (
      <div className="flex justify-center p-12">
        <Spinner className="h-5 w-5" />
      </div>
    )
  }

  return (
    <>
      <h2 className="text-base font-medium">Platform metrics</h2>

      {overview && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
          <StatCard label="Missions" value={overview.counts.missions.toLocaleString()} />
          <StatCard label="Executions" value={overview.counts.execution_records.toLocaleString()} />
          <StatCard label="Total cost" value={fmtUsd(overview.total_cost_usd)} />
          <StatCard label="Workflow runs" value={overview.counts.workflow_runs.toLocaleString()} />
          <StatCard label="Sessions" value={overview.counts.sessions.toLocaleString()} />
          <StatCard label="Agents" value={overview.counts.agents.toLocaleString()} />
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] items-start gap-4">
        {loadingCosts ? (
          <LoadingPanel />
        ) : (
          costs && <AdminCostByAgentPanel agents={costs.by_agent} />
        )}
        {loadingAgents ? <LoadingPanel /> : agents && <AgentUtilisationPanel agents={agents} />}
      </div>
    </>
  )
}

function LoadingPanel() {
  return (
    <Panel className="flex justify-center py-12">
      <Spinner />
    </Panel>
  )
}
