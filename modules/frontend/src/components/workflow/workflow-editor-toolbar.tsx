/**
 * Workflow editor toolbar — the panel above the canvas: where you are, what
 * state the workflow is in, and the actions on it. Step types are added from
 * the StepPalette (or from the Add step button when that panel is hidden).
 */

import { ArrowLeft, History, LayoutDashboard, Loader2, Play, Plus, Save, Wand2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { ROUTES } from '@/lib/constants'

interface WorkflowEditorToolbarProps {
  workflowName: string
  stepCount: number
  isDirty: boolean
  isSaving: boolean
  isRunning: boolean
  isRunActive?: boolean
  runProgress?: [number, number]
  showHistory: boolean
  runCount: number
  onAutoLayout: () => void
  onSave: () => void
  onRun: () => void
  onToggleHistory: () => void
  onOpenPalette: () => void
  onOpenArchitect?: () => void
}

export function WorkflowEditorToolbar({
  workflowName,
  stepCount,
  isDirty,
  isSaving,
  isRunning,
  isRunActive,
  runProgress,
  showHistory,
  runCount,
  onAutoLayout,
  onSave,
  onRun,
  onToggleHistory,
  onOpenPalette,
  onOpenArchitect,
}: WorkflowEditorToolbarProps) {
  const navigate = useNavigate()
  const { id: missionId } = useParams<{ id: string }>()

  return (
    <Panel className="flex shrink-0 flex-wrap items-center gap-3 py-2 pl-4 pr-2.5">
      <Button variant="ghost" size="sm" onClick={() => navigate(ROUTES.MISSION_WORKFLOWS(missionId!))}>
        <ArrowLeft className="h-3.5 w-3.5" />
        Workflows
      </Button>

      <span className="truncate text-base font-medium">{workflowName}</span>
      {isDirty && <span className="h-1.5 w-1.5 rounded-full bg-warning" title="Unsaved changes" />}
      <span className="text-xs text-subtle">
        {stepCount} step{stepCount === 1 ? '' : 's'}
      </span>

      {isRunActive && runProgress && (
        <span className="flex items-center gap-1.5 text-xs text-warning">
          <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
          <span className="font-mono">
            {runProgress[0]}/{runProgress[1]} steps
          </span>
        </span>
      )}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {/* The palette panel is hidden below 1100px; this keeps steps addable there. */}
        <Button variant="ghost" onClick={onOpenPalette} className="min-[1100px]:hidden">
          <Plus className="h-[13px] w-[13px]" />
          Add step
        </Button>
        {onOpenArchitect && (
          <Button variant="ghost" onClick={onOpenArchitect}>
            <Wand2 className="h-[13px] w-[13px]" />
            Architect
          </Button>
        )}
        <Button variant="ghost" onClick={onAutoLayout}>
          <LayoutDashboard className="h-[13px] w-[13px]" />
          Auto-layout
        </Button>
        <Button variant="secondary" aria-pressed={showHistory} onClick={onToggleHistory}>
          <History className="h-[13px] w-[13px]" />
          History
          {runCount > 0 && <span className="font-mono text-2xs text-subtle">{runCount}</span>}
        </Button>
        <Button variant="secondary" onClick={onSave} disabled={!isDirty || isSaving}>
          {isSaving ? (
            <Loader2 className="h-[13px] w-[13px] animate-spin motion-reduce:animate-none" />
          ) : (
            <Save className="h-[13px] w-[13px]" />
          )}
          Save
        </Button>
        <Button onClick={onRun} disabled={isRunning || isRunActive}>
          {isRunning ? (
            <Loader2 className="h-[13px] w-[13px] animate-spin motion-reduce:animate-none" />
          ) : (
            <Play className="h-[13px] w-[13px]" />
          )}
          Run workflow
        </Button>
      </div>
    </Panel>
  )
}
