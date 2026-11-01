import { Panel, PanelHeader } from '@/components/ui/panel'
import { cn } from '@/lib/cn'
import { agentShortName, fmtCost, fmtTokens } from '@/lib/format'
import { formatUtc } from '@/lib/format-date'
import type { ExpensiveCall } from '@/types'

const HEAD = 'py-2 text-2xs font-medium text-subtle'

/** The dearest individual LLM calls in the chosen timeframe. */
export function TokenCallsTable({ calls }: { calls: ExpensiveCall[] }) {
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Most expensive calls" />
      {calls.length === 0 ? (
        <p className="px-4 pb-4 text-xs text-subtle">No calls recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr>
                <th className={cn(HEAD, 'pl-4 text-left')}>Time</th>
                <th className={cn(HEAD, 'text-left')}>Agent</th>
                <th className={cn(HEAD, 'text-left')}>Model</th>
                <th className={cn(HEAD, 'text-right')}>Input</th>
                <th className={cn(HEAD, 'text-right')}>Output</th>
                <th className={cn(HEAD, 'text-right')}>Cache</th>
                <th className={cn(HEAD, 'pr-4 text-right')}>Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {calls.map((call) => (
                <tr key={call.id} className="transition-colors hover:bg-hover">
                  <td className="whitespace-nowrap py-2 pl-4 pr-3 text-xs text-subtle">{formatUtc(call.created_at)}</td>
                  <td className="max-w-[200px] truncate py-2 pr-3" title={call.agent_name}>
                    {agentShortName(call.agent_name)}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                    {call.model.replace('anthropic:', '')}
                  </td>
                  <td className="py-2 text-right font-mono text-xs">{fmtTokens(call.input_tokens)}</td>
                  <td className="py-2 text-right font-mono text-xs">{fmtTokens(call.output_tokens)}</td>
                  <td className="py-2 text-right font-mono text-xs">{fmtTokens(call.cache_read_tokens)}</td>
                  <td className="py-2 pl-3 pr-4 text-right font-mono text-xs">{fmtCost(call.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
