import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { cn } from '@/lib/cn'
import { agentShortName, fmtCost, fmtTokens } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import type { MissionCostCall } from '@/types'

const HEAD = 'py-2 text-2xs font-medium text-subtle'

/** The ten dearest individual LLM calls in the chosen range. */
export function CostCallsPanel({ calls }: { calls: MissionCostCall[] }) {
  return (
    <Panel>
      <PanelHeader title="Most expensive calls" />
      <PanelContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={cn(HEAD, 'text-left')}>Time</th>
              <th className={cn(HEAD, 'text-left')}>Agent</th>
              <th className={cn(HEAD, 'text-left')}>Model</th>
              <th className={cn(HEAD, 'text-right')}>Input</th>
              <th className={cn(HEAD, 'text-right')}>Output</th>
              <th className={cn(HEAD, 'text-right')}>Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {calls.map((call) => (
              <tr key={call.id} className="transition-colors hover:bg-hover">
                <td className="whitespace-nowrap py-2 pr-3 text-xs text-subtle">{formatUtc(call.created_at)}</td>
                <td className="max-w-[200px] truncate py-2 pr-3" title={call.agent_name}>
                  {agentShortName(call.agent_name)}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                  {call.model.replace('anthropic:', '')}
                </td>
                <td className="py-2 text-right font-mono text-xs">{fmtTokens(call.input_tokens)}</td>
                <td className="py-2 text-right font-mono text-xs">{fmtTokens(call.output_tokens)}</td>
                <td className="py-2 text-right font-mono text-xs">{fmtCost(call.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {calls.length === 0 && <p className="py-4 text-center text-xs text-subtle">No calls yet.</p>}
      </PanelContent>
    </Panel>
  )
}
