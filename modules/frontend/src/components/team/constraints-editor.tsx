import { useId, useState, type ReactNode } from 'react'
import { Save, Wrench } from 'lucide-react'
import toast from 'react-hot-toast'
import { useUpdateConstraints } from '@/hooks/use-team'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { MissionTeamMember } from '@/types'

/** A labelled row inside an agent's configuration block. */
export function ConfigRow({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 shrink-0 text-subtle">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className="mr-2 font-medium text-text-3">{label}</span>
        {children}
      </div>
    </div>
  )
}

/** The mission-specific constraints of a team member: shown as pills, edited in place. */
export function ConstraintsEditor({ member, missionId }: { member: MissionTeamMember; missionId: string }) {
  const ids = useId()
  const isResearch = member.agent?.agent_name?.startsWith('research.')
  const constraints = member.custom_constraints ?? {}
  const updateMutation = useUpdateConstraints(missionId, member.id)

  const [editing, setEditing] = useState(false)
  const [depth, setDepth] = useState((constraints.depth as string) ?? '')
  const [domains, setDomains] = useState(((constraints.include_domains as string[]) ?? []).join(', '))

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
        <div className="mt-1.5 flex min-w-0 flex-col gap-2">
          {isResearch && (
            <>
              <div className="flex items-center gap-2">
                <label htmlFor={`${ids}-depth`} className="w-16 shrink-0 text-subtle">
                  Depth
                </label>
                <Select
                  id={`${ids}-depth`}
                  value={depth}
                  onChange={(e) => setDepth(e.target.value)}
                  size="xs" className="min-w-0 flex-1"
                >
                  <option value="">Default</option>
                  <option value="quick">Quick (1 iteration, ~2 min)</option>
                  <option value="moderate">Moderate (3 iterations, ~10 min)</option>
                  <option value="comprehensive">Comprehensive (5 iterations, ~20 min)</option>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor={`${ids}-domains`} className="w-16 shrink-0 text-subtle">
                  Domains
                </label>
                <Input
                  id={`${ids}-domains`}
                  value={domains}
                  onChange={(e) => setDomains(e.target.value)}
                  placeholder="anthropic.com, openai.com"
                  className="h-7 w-auto min-w-0 flex-1 font-mono text-xs"
                />
              </div>
            </>
          )}
          {!isResearch && (
            <pre className="whitespace-pre-wrap font-mono text-2xs text-muted-foreground">
              {JSON.stringify(constraints, null, 2)}
            </pre>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending}>
              <Save className="h-3 w-3" />
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
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          {Object.keys(constraints).length > 0 ? (
            <span className="flex flex-wrap gap-1.5">
              {constraints.depth ? <Badge variant="outline">depth: {String(constraints.depth)}</Badge> : null}
              {Array.isArray(constraints.include_domains) && constraints.include_domains.length > 0 ? (
                <Badge variant="outline" className="font-mono">
                  {(constraints.include_domains as string[]).join(', ')}
                </Badge>
              ) : null}
              {!constraints.depth && !Array.isArray(constraints.include_domains) && (
                <span className="text-2xs">{JSON.stringify(constraints)}</span>
              )}
            </span>
          ) : (
            <span className="text-2xs">Click to configure...</span>
          )}
        </button>
      )}
    </ConfigRow>
  )
}
