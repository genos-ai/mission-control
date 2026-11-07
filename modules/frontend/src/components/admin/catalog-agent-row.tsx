import { Brain, FileCode, Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Switch } from '@/components/ui/switch'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import type { AgentCatalogItem } from '@/types'

/** Shared by the header and the rows so the columns line up. */
export const CATALOG_ROW_GRID =
  'grid grid-cols-[36px_minmax(180px,1fr)_72px_52px_minmax(110px,190px)_80px] items-center gap-3 px-4'

/** The "k" figure for a fixed thinking budget, or "adaptive". */
function thinkingLabel(maxThinkingTokens: number): string {
  return maxThinkingTokens > 0 ? `${(maxThinkingTokens / 1000).toFixed(0)}k` : 'adaptive'
}

/** One catalogue entry as a table row: enable switch, identity, model and the edit actions. */
export function CatalogAgentRow({
  agent,
  onToggle,
  onEditPrompt,
  onEdit,
  onDelete,
}: {
  agent: AgentCatalogItem
  onToggle: () => void
  onEditPrompt: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const style = agentStyle(agent.agent_name)
  const modelName = agent.model_config_json?.name
  // Shown for every agent, the default included: an admin comparing agents needs to see which engine runs each.
  const engine = agent.engine ? agent.engine.replace('_', ' ') : null

  return (
    <div className={cn(CATALOG_ROW_GRID, 'border-t border-line py-2.5 text-sm transition-colors duration-150 hover:bg-hover')}>
      <Switch
        checked={agent.enabled}
        onChange={onToggle}
        label={`${agent.enabled ? 'Disable' : 'Enable'} ${agent.agent_name}`}
      />
      <div className={cn('flex min-w-0 items-center gap-3', !agent.enabled && 'opacity-60')}>
        <IconTile icon={style.icon} tone={style.tone} />
        <div className="min-w-0">
          <p className="truncate font-medium" title={agent.agent_name}>
            {agent.agent_name}
          </p>
          <p className="truncate text-xs text-muted-foreground" title={agent.description}>
            {agent.description}
          </p>
        </div>
      </div>
      <span className="truncate text-xs text-muted-foreground">{agent.agent_type}</span>
      <span className="font-mono text-xs text-text-3">v{agent.version}</span>
      <div className="flex min-w-0 flex-col gap-0.5">
        {modelName ? (
          <span className="truncate font-mono text-xs text-text-3" title={modelName}>
            {modelName}
          </span>
        ) : (
          <span className="text-xs text-subtle">—</span>
        )}
        {(engine || agent.thinking_budget_json) && (
          <span className="flex items-center gap-2 text-2xs text-subtle">
            {engine && (
              <span className="truncate" title={`Engine: ${engine}`}>
                {engine}
              </span>
            )}
            {agent.thinking_budget_json && (
              <span className="flex items-center gap-1">
                <Brain className="h-2.5 w-2.5" />
                {thinkingLabel(agent.thinking_budget_json.max_thinking_tokens)}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="flex items-center justify-end gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onEditPrompt}
          title="Edit system prompt"
          aria-label={`Edit system prompt of ${agent.agent_name}`}
        >
          <FileCode className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onEdit}
          title="Edit agent"
          aria-label={`Edit ${agent.agent_name}`}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-danger hover:bg-danger/10 hover:text-danger"
          onClick={onDelete}
          title="Delete agent"
          aria-label={`Delete ${agent.agent_name}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
