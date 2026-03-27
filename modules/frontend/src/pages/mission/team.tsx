import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Users, Trash2, History, Save, Plus, FileText } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTeam, useRemoveFromTeam, useUpdatePrompt, useSeedTeam } from '@/hooks/use-team'
import { useCatalog } from '@/hooks/use-catalog'
import { useMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { useDrawerStore } from '@/stores/drawer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'
import type { MissionTeamMember } from '@/types'

export default function TeamPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const { data: members, isLoading } = useTeam(missionId)
  const { data: catalog } = useCatalog()
  const { data: mission } = useMission(missionId)
  const { open: openDrawer } = useDrawerStore()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  const seedMutation = useSeedTeam(missionId!)

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

  // Build a lookup from catalog ID → agent name
  const catalogLookup = new Map(
    catalog?.map((a) => [a.id, a]) ?? [],
  )

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

      {/* Mission brief context — helps when writing agent prompts */}
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
            agentName={catalogLookup.get(member.agent_catalog_id)?.agent_name}
            agentType={catalogLookup.get(member.agent_catalog_id)?.agent_type}
          />
        ))}
      </div>
    </div>
  )
}

function TeamMemberCard({
  member,
  missionId,
  agentName,
  agentType,
}: {
  member: MissionTeamMember
  missionId: string
  agentName?: string
  agentType?: string
}) {
  const user = useAuthStore((s) => s.user)
  const { open: openDrawer } = useDrawerStore()
  const removeMutation = useRemoveFromTeam(missionId)
  const updatePromptMutation = useUpdatePrompt(missionId, member.id)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(member.user_prompt ?? '')

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
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-sm font-bold text-primary">
            {(agentName ?? 'A').charAt(0).toUpperCase()}
          </div>
          <div>
            <CardTitle className="text-base">
              {agentName ?? member.agent_catalog_id}
            </CardTitle>
            <div className="mt-1 flex items-center gap-2">
              {agentType && (
                <Badge variant="secondary" className="text-[11px]">
                  {agentType}
                </Badge>
              )}
              <Badge
                variant={member.enabled ? 'success' : 'outline'}
                className="text-[11px]"
              >
                {member.enabled ? 'Active' : 'Disabled'}
              </Badge>
              <span className="text-xs text-muted-foreground">
                v{member.user_prompt_version}
              </span>
            </div>
          </div>
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
      </CardHeader>

      <CardContent>
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
      </CardContent>
    </Card>
  )
}
