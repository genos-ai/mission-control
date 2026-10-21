import { Circle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { StatusIcon } from '@/components/ui/status-icon'
import { ROUTES } from '@/lib/constants'
import { cn } from '@/lib/cn'
import { taskTone } from '@/lib/status-tone'
import { TONE_BOX } from '@/lib/tone-class'

interface SetupChecklistProps {
  hasBrief: boolean
  agentCount: number
  workflowCount: number
  missionId: string
  /** Opens the mission edit dialog, where the brief is written. */
  onEditBrief: () => void
}

/** The first steps of a new mission: a brief, a team, and optionally a workflow. */
export function SetupChecklist({
  hasBrief,
  agentCount,
  workflowCount,
  missionId,
  onEditBrief,
}: SetupChecklistProps) {
  const navigate = useNavigate()

  const steps = [
    {
      done: hasBrief,
      label: 'Set a mission brief',
      hint: 'Open Edit and write a brief',
      action: onEditBrief,
    },
    {
      done: agentCount > 0,
      label: 'Add agents to your team',
      hint: 'Browse the catalog and assign agents to this mission',
      action: () => navigate(ROUTES.MISSION_TEAM(missionId)),
    },
    {
      done: workflowCount > 0,
      label: 'Set up a workflow (optional)',
      hint: 'Import a template or design one with the Architect',
      action: () => navigate(ROUTES.MISSION_WORKFLOWS(missionId)),
    },
  ]

  const completedCount = steps.filter((s) => s.done).length

  return (
    <Panel className={TONE_BOX.brand}>
      <PanelHeader title="Get started" meta={`${completedCount}/${steps.length}`} />
      <PanelContent className="flex flex-col gap-1">
        {steps.map((step) => (
          <button
            key={step.label}
            onClick={step.action}
            disabled={step.done}
            className="flex w-full items-start gap-3 rounded-card px-2 py-2 text-left transition-colors hover:bg-hover disabled:cursor-default disabled:hover:bg-transparent"
          >
            <StatusIcon
              {...(step.done ? taskTone.completed : { tone: 'neutral', icon: Circle })}
              className="mt-0.5 h-4 w-4"
            />
            <div>
              <p className={cn('text-sm font-medium', step.done && 'text-subtle line-through')}>
                {step.label}
              </p>
              {!step.done && <p className="mt-0.5 text-xs text-subtle">{step.hint}</p>}
            </div>
          </button>
        ))}
      </PanelContent>
    </Panel>
  )
}
