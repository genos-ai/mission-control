import { Cpu, MessageSquare } from 'lucide-react'
import { modelLabel } from '@/components/team/model-label'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import { agentShortName } from '@/lib/format'
import type { AgentCatalogItem } from '@/types'

/** Tools shown on a card; the rest are counted, and the drawer lists them all. */
const VISIBLE_TOOLS = 4

const TOOL_PILL = 'inline-flex h-[22px] max-w-full items-center gap-1 rounded-full bg-raised px-2.5 text-2xs text-muted-foreground'

/** One catalogue agent: who it is, what it does, the tools it can call, and a way into its detail drawer. */
export function AgentCard({ agent, onViewDetails }: { agent: AgentCatalogItem; onViewDetails: () => void }) {
  const style = agentStyle(agent.agent_name)
  const modelName = agent.model_config_json?.name
  const hiddenTools = agent.tools.length - VISIBLE_TOOLS

  return (
    <Panel className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3">
        <IconTile icon={style.icon} tone={style.tone} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-md font-medium" title={agent.agent_name}>
            {agentShortName(agent.agent_name)}
          </p>
          <p className="truncate text-xs text-subtle">{agent.agent_type}</p>
        </div>
        {agent.chat_enabled && (
          <span role="img" aria-label="Chat enabled" title="Chat enabled" className="shrink-0 text-subtle">
            <MessageSquare className="h-3.5 w-3.5" />
          </span>
        )}
      </div>

      <p className="line-clamp-2 min-h-[38px] text-sm text-muted-foreground">{agent.description}</p>

      {agent.tools.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {agent.tools.slice(0, VISIBLE_TOOLS).map((tool) => (
            <span key={tool} title={tool} className={cn(TOOL_PILL, 'truncate font-mono')}>
              {tool}
            </span>
          ))}
          {hiddenTools > 0 && <span className={cn(TOOL_PILL, 'font-mono')}>+{hiddenTools}</span>}
        </div>
      )}

      <div className="mt-auto flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-2xs text-subtle">
          {modelName && (
            <span title={modelName} className="flex min-w-0 items-center gap-1">
              <Cpu className="h-2.5 w-2.5 shrink-0" />
              <span className="truncate">{modelLabel(modelName)}</span>
            </span>
          )}
          <span className="shrink-0 font-mono">v{agent.version}</span>
        </div>
        <Button variant="secondary" size="sm" aria-label={`Details for ${agent.agent_name}`} onClick={onViewDetails}>
          Details
        </Button>
      </div>
    </Panel>
  )
}
