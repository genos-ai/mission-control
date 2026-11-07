/**
 * MissionSettingsDrawer — slide-in panel for managing mission team & brief.
 * Adapted from team.tsx; accepts missionId as prop rather than useParams.
 */

import { useState } from 'react'
import {
  X,
  Plus,
  Trash2,
  History,
  Save,
  Cpu,
  FolderOpen,
  Wrench,
  Clock,
  DollarSign,
  ChevronDown,
  ChevronRight,
  Users,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useEscapeKey } from '@/hooks/use-escape-key'
import { useTeam, useRemoveFromTeam, useUpdatePrompt, useSeedTeam } from '@/hooks/use-team'
import { useMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { PanelHeader } from '@/components/ui/panel'
import { modelLabel } from '@/components/team/model-label'
import { ArchiveMissionButton } from '@/components/mission/archive-mission-button'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import type { MissionTeamMember } from '@/types'

// ---------------------------------------------------------------------------

export function MissionSettingsDrawer({
  missionId,
  onClose,
}: {
  missionId: string
  onClose: () => void
}) {
  const { data: members, isLoading } = useTeam(missionId)
  const { data: mission } = useMission(missionId)
  const user = useAuthStore((s) => s.user)
  const isOwner = mission?.owner_id === user?.id
  const { open: openDrawer } = useDrawerStore()
  const seedMutation = useSeedTeam(missionId)
  useEscapeKey(onClose)

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Mission settings"
        actions={
          <>
            {members && members.length > 0 && (
              <Button
                size="sm"
                onClick={() =>
                  openDrawer('agent-detail', { missionId, mode: 'add-from-catalog' })
                }
              >
                <Plus className="h-3 w-3" />
                Add Agent
              </Button>
            )}
            <Button variant="ghost" size="icon" aria-label="Close settings" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </>
        }
      />

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {/* Mission brief */}
        {mission?.brief && (
          <div className="rounded-card bg-raised px-3 py-2.5 text-xs">
            <p className="mb-0.5 font-medium text-muted-foreground">Mission Brief</p>
            <p className="leading-relaxed">{mission.brief}</p>
          </div>
        )}

        {/* Team section */}
        <div>
          <h3 className="mb-2 text-xs font-medium text-subtle">
            Team
            {members && members.length > 0 && (
              <span className="ml-2 font-normal">
                {members.length} agent{members.length !== 1 ? 's' : ''}
              </span>
            )}
          </h3>

          {isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner className="h-4 w-4" />
            </div>
          ) : !members?.length ? (
            <div className="rounded-lg border border-dashed px-4 py-6 text-center">
              <Users className="mx-auto mb-2 h-5 w-5 text-muted-foreground/40" />
              <p className="mb-3 text-xs text-muted-foreground">No agents yet</p>
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={() =>
                  seedMutation.mutate(undefined, {
                    onSuccess: () => toast.success('Agents added'),
                    onError: (err) => toast.error(err.message),
                  })
                }
                disabled={seedMutation.isPending}
              >
                Add All Agents
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {members.map((member) => (
                <MemberCard
                  key={member.id}
                  member={member}
                  missionId={missionId}
                />
              ))}
            </div>
          )}
        </div>

        {isOwner && mission && mission.status !== 'archived' && (
          <ArchiveMissionButton missionId={missionId} missionName={mission.name} onArchived={onClose} />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function MemberCard({
  member,
  missionId,
}: {
  member: MissionTeamMember
  missionId: string
}) {
  const user = useAuthStore((s) => s.user)
  const { open: openDrawer } = useDrawerStore()
  const removeMutation = useRemoveFromTeam(missionId)
  const updatePromptMutation = useUpdatePrompt(missionId, member.id)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(member.user_prompt ?? '')
  const [configExpanded, setConfigExpanded] = useState(false)

  const agent = member.agent
  const agentName = agent?.agent_name ?? member.agent_catalog_id

  const handleSave = () => {
    if (!draft.trim()) return
    updatePromptMutation.mutate(
      { content: draft.trim(), changed_by: user?.id ?? 'unknown' },
      {
        onSuccess: () => {
          setEditing(false)
          toast.success('Prompt updated')
        },
        onError: (err) => toast.error(err.message),
      },
    )
  }

  return (
    <div className="rounded-lg border bg-card text-xs">
      {/* Agent header */}
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-primary/10 text-[10px] font-bold text-primary">
            {agentName.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium">{agentName}</p>
            <div className="mt-0.5 flex items-center gap-1 flex-wrap">
              {agent?.agent_type && (
                <Badge>
                  {agent.agent_type}
                </Badge>
              )}
              <StatusPill tone={member.enabled ? 'success' : 'neutral'}>
                {member.enabled ? 'active' : 'disabled'}
              </StatusPill>
              {agent?.model?.name && (
                <Badge variant="outline" className="gap-0.5">
                  <Cpu className="h-2 w-2" />
                  {modelLabel(agent.model.name)}
                </Badge>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-0.5 shrink-0">
          <button
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            title="Prompt history"
            onClick={() =>
              openDrawer('prompt-history', { missionId, memberId: member.id })
            }
          >
            <History className="h-3 w-3" />
          </button>
          <button
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-destructive"
            title="Remove agent"
            onClick={() =>
              removeMutation.mutate(member.id, {
                onSuccess: () => toast.success('Agent removed'),
                onError: (err) => toast.error(err.message),
              })
            }
            disabled={removeMutation.isPending}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Agent description */}
      {agent?.description && (
        <p className="px-3 pb-2 text-[10px] text-muted-foreground leading-relaxed">
          {agent.description}
        </p>
      )}

      {/* Expandable config */}
      {agent && (
        <div className="border-t px-3 py-2">
          <button
            onClick={() => setConfigExpanded(!configExpanded)}
            className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-foreground"
          >
            {configExpanded ? (
              <ChevronDown className="h-2.5 w-2.5" />
            ) : (
              <ChevronRight className="h-2.5 w-2.5" />
            )}
            Configuration
          </button>

          {configExpanded && (
            <div className="mt-2 space-y-2 rounded border bg-muted/20 p-2 text-[10px]">
              <ConfigRow icon={<Cpu className="h-2.5 w-2.5" />} label="Model">
                <span className="font-mono">{agent.model.name ?? 'default'}</span>
                {agent.model.max_tokens && (
                  <span className="ml-1.5 text-muted-foreground">
                    max {agent.model.max_tokens.toLocaleString()} tokens
                  </span>
                )}
              </ConfigRow>

              {agent.tools.length > 0 && (
                <ConfigRow icon={<Wrench className="h-2.5 w-2.5" />} label="Tools">
                  <div className="flex flex-wrap gap-0.5">
                    {agent.tools.map((t) => (
                      <Badge key={t} className="font-mono">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </ConfigRow>
              )}

              {(agent.scope.read?.length || agent.scope.write?.length) ? (
                <ConfigRow icon={<FolderOpen className="h-2.5 w-2.5" />} label="Scope">
                  <div className="space-y-0.5">
                    {agent.scope.read && agent.scope.read.length > 0 && (
                      <div className="flex flex-wrap items-center gap-0.5">
                        <span className="mr-1 w-7 text-muted-foreground">read</span>
                        {agent.scope.read.map((p) => (
                          <span key={p} className="rounded bg-muted px-1 py-0.5 font-mono text-[9px]">{p}</span>
                        ))}
                      </div>
                    )}
                    {agent.scope.write && agent.scope.write.length > 0 && (
                      <div className="flex flex-wrap items-center gap-0.5">
                        <span className="mr-1 w-7 text-muted-foreground">write</span>
                        {agent.scope.write.map((p) => (
                          <span key={p} className="rounded bg-muted px-1 py-0.5 font-mono text-[9px]">{p}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </ConfigRow>
              ) : null}

              <ConfigRow icon={<Clock className="h-2.5 w-2.5" />} label="Limits">
                <span className="text-muted-foreground">
                  {agent.constraints.timeout_seconds && `${agent.constraints.timeout_seconds}s `}
                  {agent.constraints.cost_ceiling_usd && (
                    <>
                      <DollarSign className="inline h-2 w-2" />
                      {agent.constraints.cost_ceiling_usd}{' '}
                    </>
                  )}
                  {agent.constraints.retry_budget != null &&
                    `${agent.constraints.retry_budget} retries`}
                </span>
              </ConfigRow>
            </div>
          )}
        </div>
      )}

      {/* User prompt */}
      <div className="border-t px-3 py-2">
        {editing ? (
          <div className="space-y-1.5">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              className="text-xs"
              placeholder="Mission-specific instructions for this agent…"
            />
            <div className="flex gap-1.5">
              <Button
                size="sm"
                className="h-6 px-2 text-[10px]"
                onClick={handleSave}
                disabled={updatePromptMutation.isPending || !draft.trim()}
              >
                <Save className="mr-1 h-2.5 w-2.5" />
                Save
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[10px]"
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
            className="w-full cursor-pointer rounded border border-dashed border-muted-foreground/20 px-2.5 py-2 text-left text-[10px] text-muted-foreground hover:border-muted-foreground/40 hover:text-foreground"
            onClick={() => setEditing(true)}
          >
            {member.user_prompt || 'Click to add mission-specific prompt…'}
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function ConfigRow({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-1.5">
      <span className="mt-0.5 shrink-0 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <span className="font-medium text-muted-foreground mr-1.5">{label}</span>
        {children}
      </div>
    </div>
  )
}
