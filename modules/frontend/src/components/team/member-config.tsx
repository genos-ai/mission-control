import { Clock, Cpu, DollarSign, FolderOpen, Wrench } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ConfigRow, ConstraintsEditor } from '@/components/team/constraints-editor'
import type { AgentConfigSummary, MissionTeamMember } from '@/types'

/** A file-scope path, in the monospace chip the Tools row uses. */
function ScopeRow({ label, paths }: { label: string; paths: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="w-10 text-subtle">{label}</span>
      {paths.map((p) => (
        <span key={p} className="rounded-sm bg-raised px-1.5 py-0.5 font-mono text-2xs text-text-3">
          {p}
        </span>
      ))}
    </div>
  )
}

/** The expanded configuration of a team member: model, tools, scope, limits and custom constraints. */
export function MemberConfig({
  agent,
  member,
  missionId,
}: {
  agent: AgentConfigSummary
  member: MissionTeamMember
  missionId: string
}) {
  const { read, write } = agent.scope
  const engine = agent.engine && agent.engine !== 'pydantic_ai' ? agent.engine : null

  return (
    <div className="flex flex-col gap-3 rounded-card border border-line p-3 text-xs">
      <ConfigRow icon={<Cpu className="h-3 w-3" />} label="Model">
        <span className="font-mono text-text-2">{agent.model.name ?? 'default'}</span>
        {agent.model.max_tokens && (
          <span className="ml-2 text-subtle">max {agent.model.max_tokens.toLocaleString()} tokens</span>
        )}
        {engine && (
          <span className="ml-2 text-success">
            via {engine.replace('_', ' ')}
            {agent.effort ? ` (${agent.effort})` : ''}
          </span>
        )}
      </ConfigRow>

      {agent.tools.length > 0 && (
        <ConfigRow icon={<Wrench className="h-3 w-3" />} label="Tools">
          <div className="mt-1.5 flex flex-wrap gap-1">
            {agent.tools.map((t) => (
              <Badge key={t} className="font-mono">
                {t}
              </Badge>
            ))}
          </div>
        </ConfigRow>
      )}

      {read?.length || write?.length ? (
        <ConfigRow icon={<FolderOpen className="h-3 w-3" />} label="Scope">
          <div className="mt-1.5 flex flex-col gap-1">
            {read && read.length > 0 && <ScopeRow label="read" paths={read} />}
            {write && write.length > 0 && <ScopeRow label="write" paths={write} />}
          </div>
        </ConfigRow>
      ) : null}

      <ConfigRow icon={<Clock className="h-3 w-3" />} label="Limits">
        <span className="inline-flex flex-wrap items-center gap-x-3 text-muted-foreground">
          {agent.constraints.timeout_seconds && <span>{agent.constraints.timeout_seconds}s timeout</span>}
          {agent.constraints.cost_ceiling_usd && (
            <span>
              <DollarSign className="inline h-2.5 w-2.5" />
              {agent.constraints.cost_ceiling_usd} ceiling
            </span>
          )}
          {agent.constraints.retry_budget != null && <span>{agent.constraints.retry_budget} retries</span>}
        </span>
      </ConfigRow>

      <ConstraintsEditor member={member} missionId={missionId} />
    </div>
  )
}
