import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { agentShortName, fmtCost } from '@/lib/format'
import type { AdminCostBreakdown } from '@/types'

/** Platform-wide spend per agent, each bar sized against the dearest agent. */
export function AdminCostByAgentPanel({ agents }: { agents: AdminCostBreakdown['by_agent'] }) {
  const maxCost = Math.max(0, ...agents.map((a) => a.total_cost_usd))

  return (
    <Panel>
      <PanelHeader title="Cost by agent" />
      <PanelContent>
        {agents.map((a) => (
          <div key={a.agent_name} className="py-2.5">
            <div className="flex items-baseline gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate" title={a.agent_name}>
                {agentShortName(a.agent_name)}
              </span>
              <span className="shrink-0 font-mono text-xs text-subtle">
                {a.runs} {a.runs === 1 ? 'run' : 'runs'}
              </span>
              <span className="w-[70px] shrink-0 text-right font-mono">{fmtCost(a.total_cost_usd)}</span>
            </div>
            <Progress
              value={maxCost > 0 ? (a.total_cost_usd / maxCost) * 100 : 0}
              label={`${agentShortName(a.agent_name)} cost relative to the highest`}
              className="mt-2"
            />
          </div>
        ))}
        {agents.length === 0 && <p className="text-xs text-subtle">No cost data yet.</p>}
      </PanelContent>
    </Panel>
  )
}
