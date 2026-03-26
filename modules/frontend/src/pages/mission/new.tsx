import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'

export default function NewMissionPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const createMission = useCreateMission()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [brief, setBrief] = useState('')
  const [budgetCeiling, setBudgetCeiling] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!user) return

    try {
      const mission = await createMission.mutateAsync({
        name,
        description,
        brief: brief || undefined,
        owner_id: user.id,
        budget_ceiling_usd: budgetCeiling ? parseFloat(budgetCeiling) : undefined,
        repo_url: repoUrl || undefined,
      })
      navigate(ROUTES.MISSION_TEAM(mission.id), { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create mission')
    }
  }

  return (
    <div className="flex justify-center p-8">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Create Mission</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Name</label>
              <Input
                placeholder="daily-cti-brief"
                value={name}
                onChange={(e) => setName(e.target.value)}
                pattern="^[a-z][a-z0-9_-]*$"
                title="Lowercase letters, numbers, hyphens, underscores. Must start with a letter."
                required
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                Lowercase slug — letters, numbers, hyphens, underscores
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Description</label>
              <Input
                placeholder="What this mission does"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Brief</label>
              <Textarea
                placeholder="Strategic directive for agents (optional)"
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                The directive agents read to understand their purpose
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Budget Ceiling (USD)</label>
              <Input
                type="number"
                placeholder="Optional"
                value={budgetCeiling}
                onChange={(e) => setBudgetCeiling(e.target.value)}
                min="0.01"
                step="0.01"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Repository URL</label>
              <Input
                placeholder="https://github.com/org/repo (optional)"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
              />
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate(-1)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMission.isPending}>
                {createMission.isPending ? <Spinner className="mr-2" /> : null}
                Create & Assemble Team
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
