import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Cpu, History, Save, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useRemoveFromTeam, useToggleTeamMember, useUpdatePrompt } from '@/hooks/use-team'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { MemberConfig } from '@/components/team/member-config'
import { modelLabel } from '@/components/team/model-label'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import { agentShortName } from '@/lib/format'
import type { MissionTeamMember } from '@/types'

/** A small rounded label in the card footer. */
function CapabilityPill({ title, className, children }: { title?: string; className?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-[22px] max-w-full items-center gap-1 whitespace-nowrap rounded-full bg-raised px-2.5 text-2xs text-muted-foreground',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** What the agent brings to the mission, from its catalogue entry and this mission's constraints. */
function CapabilityPills({ member }: { member: MissionTeamMember }) {
  const agent = member.agent
  const constraints = member.custom_constraints ?? {}
  const domains = Array.isArray(constraints.include_domains) ? (constraints.include_domains as string[]) : []
  const engine = agent?.engine && agent.engine !== 'pydantic_ai' ? agent.engine : null

  return (
    <>
      {!member.enabled && <CapabilityPill>disabled</CapabilityPill>}
      {agent?.model?.name && (
        <CapabilityPill title={agent.model.name}>
          <Cpu className="h-2.5 w-2.5" />
          {modelLabel(agent.model.name)}
        </CapabilityPill>
      )}
      {engine && <CapabilityPill>{engine.replace('_', ' ')}</CapabilityPill>}
      {agent && agent.tools.length > 0 && (
        <CapabilityPill>
          {agent.tools.length} {agent.tools.length === 1 ? 'tool' : 'tools'}
        </CapabilityPill>
      )}
      {constraints.depth ? <CapabilityPill>depth: {String(constraints.depth)}</CapabilityPill> : null}
      {domains.length > 0 && (
        <CapabilityPill title={domains.join(', ')} className="truncate font-mono">
          {domains.join(', ')}
        </CapabilityPill>
      )}
    </>
  )
}

/** One agent on the mission's team: switch, mission prompt, configuration and footer actions. */
export function TeamMemberCard({ member, missionId }: { member: MissionTeamMember; missionId: string }) {
  const user = useAuthStore((s) => s.user)
  const { open: openDrawer } = useDrawerStore()
  const removeMutation = useRemoveFromTeam(missionId)
  const toggleMutation = useToggleTeamMember(missionId, member.id)
  const updatePromptMutation = useUpdatePrompt(missionId, member.id)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(member.user_prompt ?? '')
  const [expanded, setExpanded] = useState(false)

  const agent = member.agent
  const agentName = agent?.agent_name ?? member.agent_catalog_id
  const style = agentStyle(agentName)
  const role = [agent?.agent_type, agent?.chat_enabled ? 'chat' : null].filter(Boolean).join(' · ')

  const handleToggle = (enabled: boolean) => {
    toggleMutation.mutate(enabled, {
      onSuccess: () => toast.success(enabled ? 'Agent enabled' : 'Agent disabled'),
      onError: (err) => toast.error(err.message),
    })
  }

  const handleSave = () => {
    if (!draft.trim()) return
    updatePromptMutation.mutate(
      {
        content: draft.trim(),
        changed_by: user?.id ?? 'unknown',
      },
      {
        onSuccess: () => {
          setEditing(false)
          toast.success('Prompt updated')
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  const handleRemove = () => {
    removeMutation.mutate(member.id, {
      onSuccess: () => toast.success('Agent removed'),
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <Panel className={cn('flex flex-col gap-3 p-4', !member.enabled && 'opacity-60')}>
      <div className="flex items-center gap-3">
        <IconTile icon={style.icon} tone={style.tone} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-md font-medium" title={agentName}>
            {agentShortName(agentName)}
          </p>
          {role && <p className="truncate text-xs text-subtle">{role}</p>}
        </div>
        <Switch
          checked={member.enabled}
          onChange={handleToggle}
          label={`${member.enabled ? 'Disable' : 'Enable'} ${agentName}`}
          disabled={toggleMutation.isPending}
        />
      </div>

      {agent?.description && <p className="text-xs text-muted-foreground">{agent.description}</p>}

      {editing ? (
        <div className="flex flex-col gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            placeholder="Enter mission-specific instructions for this agent..."
          />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={handleSave} disabled={updatePromptMutation.isPending || !draft.trim()}>
              <Save className="h-3 w-3" />
              Save
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditing(false)
                setDraft(member.user_prompt ?? '')
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <button
          className={cn(
            'min-h-[58px] w-full rounded-card bg-raised px-3 py-2.5 text-left text-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
            member.user_prompt ? 'line-clamp-5 whitespace-pre-wrap text-text-3' : 'text-subtle',
          )}
          onClick={() => setEditing(true)}
        >
          {member.user_prompt || 'Click to add mission-specific prompt...'}
        </button>
      )}

      {agent && (
        <div className="flex flex-col gap-2">
          <button
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
            className="flex w-fit items-center gap-1 text-xs font-medium text-subtle transition-colors hover:text-foreground"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Configuration
          </button>
          {expanded && <MemberConfig agent={agent} member={member} missionId={missionId} />}
        </div>
      )}

      <div className="mt-auto flex items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          <CapabilityPills member={member} />
        </div>
        <span className="whitespace-nowrap font-mono text-2xs leading-6 text-subtle">prompt v{member.user_prompt_version}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Prompt history for ${agentName}`}
          title="Prompt history"
          onClick={() => openDrawer('prompt-history', { missionId, memberId: member.id })}
        >
          <History className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="hover:text-danger"
          aria-label={`Remove ${agentName} from team`}
          title="Remove from team"
          onClick={handleRemove}
          disabled={removeMutation.isPending}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Panel>
  )
}
