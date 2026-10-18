import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Users,
  Trash2,
  History,
  Save,
  Plus,
  FileText,
  Cpu,
  FolderOpen,
  Wrench,
  Clock,
  DollarSign,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useTeam, useRemoveFromTeam, useUpdatePrompt, useUpdateConstraints, useSeedTeam } from '@/hooks/use-team'
import { useMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'
import type { MissionTeamMember } from '@/types'

/** Extract provider from full model string, e.g. "anthropic:claude-opus-4-20250514" → "anthropic" */
function modelProvider(name: string | undefined): string | null {
  if (!name || !name.includes(':')) return null
  return name.split(':')[0]
}

/** Extract short model label from full model string, e.g. "anthropic:claude-opus-4-20250514" → "Opus 4" */
function modelLabel(name: string | undefined): string {
  if (!name) return 'Unknown'
  const bare = name.includes(':') ? name.split(':')[1] : name
  if (bare.includes('opus')) return 'Opus 4'
  if (bare.includes('sonnet-4-6')) return 'Sonnet 4.6'
  if (bare.includes('sonnet-4')) return 'Sonnet 4'
  if (bare.includes('haiku')) return 'Haiku 4.5'
  return bare
}

export default function TeamPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const { data: members, isLoading } = useTeam(missionId)
  const { data: mission } = useMission(missionId)
  const { open: openDrawer } = useDrawerStore()
  const seedMutation = useSeedTeam(missionId!)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  if (!members?.length) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<Users className="h-6 w-6 text-muted-foreground" />}
          title="No agents yet"
          description="Add all available agents from the catalog, or pick them individually."
          action={{
            label: 'Add All Agents',
            onClick: () =>
              seedMutation.mutate(undefined, {
                onSuccess: () => toast.success('Agents added to team'),
                onError: (err) => toast.error(err.message),
              }),
          }}
        />
        <div className="mt-3 text-center">
          <Button
            variant="link"
            size="sm"
            onClick={() =>
              openDrawer('agent-detail', { missionId, mode: 'add-from-catalog' })
            }
          >
            Or browse the catalog manually
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Team</h2>
          <p className="text-sm text-muted-foreground">
            {members.length} agent{members.length !== 1 ? 's' : ''} assigned
          </p>
        </div>
        <Button
          size="sm"
          onClick={() =>
            openDrawer('agent-detail', { missionId, mode: 'add-from-catalog' })
          }
        >
          <Plus className="mr-1 h-4 w-4" />
          Add Agent
        </Button>
      </div>

      {mission?.brief && (
        <div className="mb-6 flex items-start gap-3 rounded-lg border bg-muted/30 px-4 py-3">
          <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              Mission Brief
            </p>
            <p className="mt-0.5 text-sm">{mission.brief}</p>
          </div>
        </div>
      )}

      <div className="grid gap-4">
        {members.map((member) => (
          <TeamMemberCard
            key={member.id}
            member={member}
            missionId={missionId!}
          />
        ))}
      </div>
    </div>
  )
}

function TeamMemberCard({
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
  const [expanded, setExpanded] = useState(false)

  const agent = member.agent
  const agentName = agent?.agent_name ?? member.agent_catalog_id

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
    <Panel>
      <PanelHeader
        title={
          <span className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-sm font-bold text-primary">
              {agentName.charAt(0).toUpperCase()}
            </span>
            {agentName}
          </span>
        }
        meta={`v${member.user_prompt_version}`}
        actions={
          <>
            <div className="flex items-center gap-2 flex-wrap">
              {agent?.agent_type && (
                <Badge>
                  {agent.agent_type}
                </Badge>
              )}
              <StatusPill tone={member.enabled ? 'success' : 'neutral'}>
                {member.enabled ? 'Active' : 'Disabled'}
              </StatusPill>
              {agent?.model?.name && modelProvider(agent.model.name) && (
                <Badge variant="outline" title={agent.model.name}>
                  {modelProvider(agent.model.name)}
                </Badge>
              )}
              {agent?.model?.name && (
                <Badge variant="outline" className="gap-1" title={agent.model.name}>
                  <Cpu className="h-2.5 w-2.5" />
                  {modelLabel(agent.model.name)}
                </Badge>
              )}
              {agent?.engine && agent.engine !== 'pydantic_ai' && (
                <Badge variant="outline">{agent.engine.replace('_', ' ')}</Badge>
              )}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                title="Prompt history"
                onClick={() =>
                  openDrawer('prompt-history', { missionId, memberId: member.id })
                }
              >
                <History className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-destructive hover:text-destructive"
                title="Remove from team"
                onClick={handleRemove}
                disabled={removeMutation.isPending}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </>
        }
      />

      <PanelContent className="space-y-3">
        {/* Agent description */}
        {agent?.description && (
          <p className="text-xs text-muted-foreground">{agent.description}</p>
        )}

        {/* Expandable config section */}
        {agent && (
          <div>
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Configuration
            </button>

            {expanded && (
              <div className="mt-2 grid gap-3 rounded-md border bg-muted/20 p-3 text-xs">
                {/* Model + Engine */}
                <ConfigRow icon={<Cpu className="h-3 w-3" />} label="Model">
                  <span className="font-mono">
                    {agent.model.name ?? 'default'}
                  </span>
                  {agent.model.max_tokens && (
                    <span className="text-muted-foreground ml-2">
                      max {agent.model.max_tokens.toLocaleString()} tokens
                    </span>
                  )}
                  {agent.engine && agent.engine !== 'pydantic_ai' && (
                    <span className="ml-2 text-green-400">
                      via {agent.engine.replace('_', ' ')}
                      {agent.effort ? ` (${agent.effort})` : ''}
                    </span>
                  )}
                </ConfigRow>

                {/* Tools */}
                {agent.tools.length > 0 && (
                  <ConfigRow icon={<Wrench className="h-3 w-3" />} label="Tools">
                    <div className="flex flex-wrap gap-1">
                      {agent.tools.map((t) => (
                        <Badge key={t} className="font-mono">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  </ConfigRow>
                )}

                {/* Scope */}
                {(agent.scope.read?.length || agent.scope.write?.length) ? (
                  <ConfigRow icon={<FolderOpen className="h-3 w-3" />} label="Scope">
                    <div className="space-y-1">
                      {agent.scope.read && agent.scope.read.length > 0 && (
                        <div className="flex flex-wrap gap-1 items-center">
                          <span className="text-muted-foreground w-10">read</span>
                          {agent.scope.read.map((p) => (
                            <span key={p} className="font-mono text-[10px] rounded bg-muted px-1.5 py-0.5">
                              {p}
                            </span>
                          ))}
                        </div>
                      )}
                      {agent.scope.write && agent.scope.write.length > 0 && (
                        <div className="flex flex-wrap gap-1 items-center">
                          <span className="text-muted-foreground w-10">write</span>
                          {agent.scope.write.map((p) => (
                            <span key={p} className="font-mono text-[10px] rounded bg-muted px-1.5 py-0.5">
                              {p}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </ConfigRow>
                ) : null}

                {/* Constraints */}
                <ConfigRow icon={<Clock className="h-3 w-3" />} label="Limits">
                  <div className="flex items-center gap-3 text-muted-foreground">
                    {agent.constraints.timeout_seconds && (
                      <span>{agent.constraints.timeout_seconds}s timeout</span>
                    )}
                    {agent.constraints.cost_ceiling_usd && (
                      <span>
                        <DollarSign className="inline h-2.5 w-2.5" />
                        {agent.constraints.cost_ceiling_usd} ceiling
                      </span>
                    )}
                    {agent.constraints.retry_budget != null && (
                      <span>{agent.constraints.retry_budget} retries</span>
                    )}
                  </div>
                </ConfigRow>

                {/* Custom constraints (editable) */}
                <ConstraintsEditor
                  member={member}
                  missionId={missionId}
                />
              </div>
            )}
          </div>
        )}

        {/* User prompt editor */}
        {editing ? (
          <div className="space-y-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
              placeholder="Enter mission-specific instructions for this agent..."
            />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={updatePromptMutation.isPending || !draft.trim()}
              >
                <Save className="mr-1 h-3 w-3" />
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
            className="w-full cursor-pointer rounded-md border border-dashed border-muted-foreground/25 p-3 text-left text-sm text-muted-foreground transition-colors hover:border-muted-foreground/50 hover:text-foreground"
            onClick={() => setEditing(true)}
          >
            {member.user_prompt || 'Click to add mission-specific prompt...'}
          </button>
        )}
      </PanelContent>
    </Panel>
  )
}

function ConstraintsEditor({
  member,
  missionId,
}: {
  member: MissionTeamMember
  missionId: string
}) {
  const isResearch = member.agent?.agent_name?.startsWith('research.')
  const constraints = member.custom_constraints ?? {}
  const updateMutation = useUpdateConstraints(missionId, member.id)

  const [editing, setEditing] = useState(false)
  const [depth, setDepth] = useState(constraints.depth as string ?? '')
  const [domains, setDomains] = useState(
    (constraints.include_domains as string[] ?? []).join(', ')
  )

  if (!isResearch && !Object.keys(constraints).length) return null

  const handleSave = () => {
    const update: Record<string, unknown> = {}
    if (depth) update.depth = depth
    const domainList = domains
      .split(',')
      .map((d) => d.trim())
      .filter(Boolean)
    if (domainList.length) update.include_domains = domainList
    else update.include_domains = []

    updateMutation.mutate(update, {
      onSuccess: () => {
        setEditing(false)
        toast.success('Constraints updated')
      },
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <ConfigRow icon={<Wrench className="h-3 w-3" />} label="Custom">
      {editing ? (
        <div className="space-y-2 w-full">
          {isResearch && (
            <>
              <div className="flex items-center gap-2">
                <label className="text-muted-foreground w-16 shrink-0">Depth</label>
                <select
                  value={depth}
                  onChange={(e) => setDepth(e.target.value)}
                  className="rounded border bg-background px-2 py-1 text-xs"
                >
                  <option value="">Default</option>
                  <option value="quick">Quick (1 iteration, ~2 min)</option>
                  <option value="moderate">Moderate (3 iterations, ~10 min)</option>
                  <option value="comprehensive">Comprehensive (5 iterations, ~20 min)</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-muted-foreground w-16 shrink-0">Domains</label>
                <input
                  value={domains}
                  onChange={(e) => setDomains(e.target.value)}
                  placeholder="anthropic.com, openai.com"
                  className="flex-1 rounded border bg-background px-2 py-1 text-xs font-mono"
                />
              </div>
            </>
          )}
          {!isResearch && (
            <pre className="text-[10px] text-muted-foreground">
              {JSON.stringify(constraints, null, 2)}
            </pre>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending}>
              <Save className="mr-1 h-3 w-3" />
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          {Object.keys(constraints).length > 0 ? (
            <span className="flex flex-wrap gap-2">
              {constraints.depth ? (
                <Badge variant="outline">
                  depth: {String(constraints.depth)}
                </Badge>
              ) : null}
              {Array.isArray(constraints.include_domains) && constraints.include_domains.length > 0 ? (
                <Badge variant="outline" className="font-mono">
                  {(constraints.include_domains as string[]).join(', ')}
                </Badge>
              ) : null}
              {!constraints.depth && !Array.isArray(constraints.include_domains) && (
                <span className="text-[10px]">{JSON.stringify(constraints)}</span>
              )}
            </span>
          ) : (
            <span className="text-[10px]">Click to configure...</span>
          )}
        </button>
      )}
    </ConfigRow>
  )
}

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
    <div className="flex items-start gap-2">
      <span className="mt-0.5 flex-shrink-0 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <span className="font-medium text-muted-foreground mr-2">{label}</span>
        {children}
      </div>
    </div>
  )
}
