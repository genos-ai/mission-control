/**
 * StepPalette — the left panel of the workflow editor: every step type, one
 * click to add it to the canvas.
 */

import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { STEP_TYPES, STEP_TYPE_ORDER, type StepType } from './workflow-editor-types'

export function StepPalette({ onAddStep }: { onAddStep: (type: StepType) => void }) {
  return (
    <Panel className="hidden w-[220px] shrink-0 flex-col gap-0.5 overflow-y-auto px-2 py-3.5 min-[1100px]:flex">
      <p className="px-2 pb-1.5 text-xs text-subtle">Add step</p>
      {STEP_TYPE_ORDER.map((type) => {
        const { label, description, icon, tone } = STEP_TYPES[type]
        return (
          <button
            key={type}
            type="button"
            title={description}
            onClick={() => onAddStep(type)}
            className="flex w-full items-center gap-2.5 rounded-card p-2 text-left transition-colors duration-150 hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            <IconTile icon={icon} tone={tone} size="sm" shape="square" />
            <span className="min-w-0">
              <span className="block truncate text-sm">{label}</span>
              <span className="block truncate text-2xs text-subtle">{description}</span>
            </span>
          </button>
        )
      })}
    </Panel>
  )
}
