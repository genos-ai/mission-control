import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { agentShortName, fmtCost } from '@/lib/format'
import type { AdminAgentStats } from '@/types'

// Dots and underscores are break opportunities, so "deliberation.debater_systems"
// wraps between words under its bar instead of mid-word.
const withBreaks = (name: string) => name.replace(/[._]/g, (c) => `${c}\u200b`)

/** Runs per agent as vertical bars, each sized against the busiest agent; scrolls sideways when there are many. */
export function AgentUtilisationPanel({ agents }: { agents: AdminAgentStats[] }) {
  const maxRuns = Math.max(0, ...agents.map((a) => a.total_runs))

  return (
    <Panel>
      <PanelHeader title="Agent utilisation" meta="runs per agent" />
      <PanelContent>
        {agents.length === 0 ? (
          <p className="text-xs text-subtle">No agent data yet.</p>
        ) : (
          <div
            role="region"
            aria-label="Agent utilisation chart"
            tabIndex={0}
            className="overflow-x-auto pb-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            <div className="flex w-max gap-2 pt-6">
              {agents.map((agent) => {
                const name = agentShortName(agent.agent_name)
                const duration =
                  agent.avg_duration_seconds === null ? '—' : `${agent.avg_duration_seconds.toFixed(1)}s`
                return (
                  <div
                    key={agent.agent_name}
                    className="relative flex w-[84px] shrink-0 flex-col items-center gap-2"
                    title={`${agent.agent_name}: ${agent.total_runs} runs, ${duration} avg, ${fmtCost(agent.total_cost_usd)}`}
                  >
                    <div className="flex h-[160px] w-full items-end justify-center">
                      <div
                        className="relative min-h-[3px] w-9 rounded-[5px_5px_2px_2px] bg-border-strong"
                        style={{ height: `${maxRuns > 0 ? (agent.total_runs / maxRuns) * 100 : 0}%` }}
                      >
                        <span className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 font-mono text-2xs text-muted-foreground">
                          {agent.total_runs}
                        </span>
                      </div>
                    </div>
                    <span className="w-full break-words text-center text-2xs leading-tight text-text-3">
                      {withBreaks(name)}
                    </span>
                    <span className="font-mono text-2xs text-subtle">{duration}</span>
                    <span className="sr-only">
                      {agent.total_runs} runs, {duration} average, {fmtCost(agent.total_cost_usd)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </PanelContent>
    </Panel>
  )
}
