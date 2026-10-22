import { useParams, useNavigate } from 'react-router-dom'
import { BookOpen, FileText, Plus, Users } from 'lucide-react'
import toast from 'react-hot-toast'
import { useTeam, useSeedTeam } from '@/hooks/use-team'
import { useMission } from '@/hooks/use-missions'
import { useDrawerStore } from '@/stores/drawer'
import { DocumentPage } from '@/components/layout/document-page'
import { TeamMemberCard } from '@/components/team/team-member-card'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Spinner } from '@/components/ui/spinner'
import { ROUTES } from '@/lib/constants'

export default function TeamPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  // Disabled members stay listed, so they can be switched back on.
  const { data: members, isLoading } = useTeam(missionId, false)
  const { data: mission } = useMission(missionId)
  const { open: openDrawer } = useDrawerStore()
  const seedMutation = useSeedTeam(missionId!)

  const addFromCatalog = () => openDrawer('agent-detail', { missionId, mode: 'add-from-catalog' })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  if (!members?.length) {
    return (
      <DocumentPage>
        <EmptyState
          icon={<Users className="h-4 w-4" />}
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
          secondaryAction={{ label: 'Or browse the catalog manually', onClick: addFromCatalog }}
        />
      </DocumentPage>
    )
  }

  const chatCount = members.filter((m) => m.enabled && m.agent?.chat_enabled).length
  const disabledCount = members.filter((m) => !m.enabled).length

  return (
    <DocumentPage className="gap-4">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2 pt-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">Team</h2>
          <p className="text-sm text-muted-foreground">
            {members.length} {members.length === 1 ? 'agent' : 'agents'}
            {disabledCount > 0 && ` · ${disabledCount} disabled`} · {chatCount} can chat · each agent gets the
            mission brief plus its own instructions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => navigate(ROUTES.CATALOG)}>
            <BookOpen className="h-3.5 w-3.5" />
            Browse catalog
          </Button>
          <Button onClick={addFromCatalog}>
            <Plus className="h-3.5 w-3.5" />
            Add agent
          </Button>
        </div>
      </div>

      {mission?.brief && (
        <div className="flex items-start gap-3 rounded-card bg-raised px-3.5 py-3">
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-subtle" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-subtle">Mission brief</p>
            <p className="mt-0.5 text-sm text-text-2">{mission.brief}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] items-start gap-gutter">
        {members.map((member) => (
          <TeamMemberCard key={member.id} member={member} missionId={missionId!} />
        ))}
      </div>
    </DocumentPage>
  )
}
