import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'

const MISSION_NAME_PATTERN = /^[a-z][a-z0-9_-]*$/

function validateMissionName(value: string): string | null {
  if (!value) return 'Name is required'
  if (value.length > 200) return 'Name must be 200 characters or fewer'
  if (!/^[a-z]/.test(value)) return 'Must start with a lowercase letter (a–z)'
  if (!MISSION_NAME_PATTERN.test(value)) {
    return 'Only lowercase letters, numbers, hyphens, and underscores are allowed'
  }
  return null
}

function suggestSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-+/g, '-')
}

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
  const [nameTouched, setNameTouched] = useState(false)

  const nameError = validateMissionName(name)
  const showNameError = nameTouched && nameError !== null
  const suggestion =
    showNameError && name ? suggestSlug(name) : ''
  const canSuggest = suggestion && suggestion !== name && validateMissionName(suggestion) === null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setNameTouched(true)

    if (!user) return
    if (nameError) return

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
      <Panel className="w-full max-w-lg">
        <PanelHeader title="Create Mission" />
        <PanelContent className="pt-4">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Name</label>
              <Input
                placeholder="daily-cti-brief"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setNameTouched(true)}
                aria-invalid={showNameError}
                aria-describedby="mission-name-help"
                required
                autoFocus
              />
              {showNameError ? (
                <div className="space-y-1">
                  <p className="text-xs text-destructive" id="mission-name-help">
                    {nameError}
                  </p>
                  {canSuggest && (
                    <button
                      type="button"
                      className="text-xs underline text-muted-foreground hover:text-foreground"
                      onClick={() => setName(suggestion)}
                    >
                      Use “{suggestion}” instead
                    </button>
                  )}
                </div>
              ) : (
                <p
                  className="text-xs text-muted-foreground"
                  id="mission-name-help"
                >
                  Lowercase slug — must start with a letter, then letters,
                  numbers, hyphens, or underscores. No spaces or other
                  characters.
                </p>
              )}
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
                variant="secondary"
                onClick={() => navigate(-1)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createMission.isPending || nameError !== null}
              >
                {createMission.isPending ? <Spinner className="mr-2" /> : null}
                Create & Assemble Team
              </Button>
            </div>
          </form>
        </PanelContent>
      </Panel>
    </div>
  )
}
