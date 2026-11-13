import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateMission } from '@/hooks/use-missions'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputGroup } from '@/components/ui/input-group'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import { TopBar } from '@/components/layout/top-bar'
import { DocumentPage } from '@/components/layout/document-page'
import type { GateMode } from '@/types/mission'

const GATE_MODE_OPTIONS: { value: GateMode; label: string }[] = [
  { value: 'interactive', label: 'Interactive' },
  { value: 'manual', label: 'Manual' },
  { value: 'ai_assisted', label: 'AI-assisted' },
  { value: 'autonomous', label: 'Autonomous' },
]

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
  const [budgetPerRun, setBudgetPerRun] = useState('')
  const [budgetPerMonth, setBudgetPerMonth] = useState('')
  const [budgetLifetime, setBudgetLifetime] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [gateMode, setGateMode] = useState<GateMode | ''>('')
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
    if (!gateMode) return

    try {
      const mission = await createMission.mutateAsync({
        name,
        description,
        brief: brief || undefined,
        owner_id: user.id,
        gate_mode: gateMode,
        budget_per_run_usd: budgetPerRun ? parseFloat(budgetPerRun) : undefined,
        budget_per_month_usd: budgetPerMonth ? parseFloat(budgetPerMonth) : undefined,
        budget_lifetime_usd: budgetLifetime ? parseFloat(budgetLifetime) : undefined,
        repo_url: repoUrl || undefined,
      })
      navigate(ROUTES.MISSION_TEAM(mission.id), { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create mission')
    }
  }

  return (
    <>
      <TopBar segments={[{ label: 'Missions', to: ROUTES.DASHBOARD }, { label: 'New mission' }]} />
      <DocumentPage className="max-w-[600px]">
        <div className="flex flex-col gap-1 pb-3">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">New mission</h1>
          <p className="text-md text-muted-foreground">
            Give agents a purpose and a budget. You&apos;ll pick the team next.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <Field
              label="Name"
              htmlFor="mission-name"
              describedById="mission-name-help"
              error={showNameError ? nameError : undefined}
              hint="Lowercase slug — must start with a letter, then letters, numbers, hyphens, or underscores. No spaces or other characters."
            >
              <InputGroup
                id="mission-name"
                prefixLabel="missions/"
                mono
                placeholder="daily-cti-brief"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setNameTouched(true)}
                aria-invalid={showNameError}
                aria-describedby="mission-name-help"
                required
                autoFocus
              />
            </Field>
            {showNameError && canSuggest && (
              <button
                type="button"
                className="self-start text-xs text-muted-foreground underline hover:text-foreground"
                onClick={() => setName(suggestion)}
              >
                Use “{suggestion}” instead
              </button>
            )}
          </div>

          <Field label="Description" htmlFor="mission-description">
            <Input
              id="mission-description"
              placeholder="What this mission does"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
            />
          </Field>

          <Field
            label="Brief"
            htmlFor="mission-brief"
            note="optional"
            hint="The directive agents read to understand their purpose"
          >
            <Textarea
              id="mission-brief"
              placeholder="Strategic directive for agents"
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={5}
            />
          </Field>

          <Field
            label="Gate mode"
            htmlFor="mission-gate-mode"
            hint="Who approves the plan's tasks"
          >
            <Select
              id="mission-gate-mode"
              value={gateMode}
              onChange={(e) => setGateMode(e.target.value as GateMode)}
              required
            >
              <option value="" disabled>
                Choose a gate mode
              </option>
              {GATE_MODE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </Field>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Budget per run" htmlFor="mission-budget-run" note="optional">
              <InputGroup
                id="mission-budget-run"
                type="number"
                prefixLabel="$"
                suffixLabel="USD"
                placeholder="Default"
                value={budgetPerRun}
                onChange={(e) => setBudgetPerRun(e.target.value)}
                min="0.01"
                step="0.01"
              />
            </Field>
            <Field label="Budget per month" htmlFor="mission-budget-month" note="optional">
              <InputGroup
                id="mission-budget-month"
                type="number"
                prefixLabel="$"
                suffixLabel="USD"
                placeholder="Default"
                value={budgetPerMonth}
                onChange={(e) => setBudgetPerMonth(e.target.value)}
                min="0.01"
                step="0.01"
              />
            </Field>
            <Field label="Lifetime budget" htmlFor="mission-budget-lifetime" note="optional">
              <InputGroup
                id="mission-budget-lifetime"
                type="number"
                prefixLabel="$"
                suffixLabel="USD"
                placeholder="No limit"
                value={budgetLifetime}
                onChange={(e) => setBudgetLifetime(e.target.value)}
                min="0.01"
                step="0.01"
              />
            </Field>
          </div>

          <Field label="Repository" htmlFor="mission-repo" note="optional">
            <Input
              id="mission-repo"
              placeholder="https://github.com/org/repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
            />
          </Field>

          {error && <p className="text-sm text-danger">{error}</p>}

          <div className="flex justify-end gap-2 border-t border-line pt-5">
            <Button type="button" variant="secondary" size="lg" onClick={() => navigate(-1)}>
              Cancel
            </Button>
            <Button type="submit" size="lg" disabled={createMission.isPending || nameError !== null || !gateMode}>
              {createMission.isPending ? <Spinner /> : null}
              Create mission
            </Button>
          </div>
        </form>
      </DocumentPage>
    </>
  )
}
