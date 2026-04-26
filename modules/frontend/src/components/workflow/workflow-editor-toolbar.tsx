/**
 * Workflow editor toolbar — actions above the canvas.
 */

import {
  ArrowLeft,
  LayoutDashboard,
  Play,
  Save,
  Loader2,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/lib/constants'

interface WorkflowEditorToolbarProps {
  workflowName: string
  isDirty: boolean
  isSaving: boolean
  isRunning: boolean
  onAutoLayout: () => void
  onSave: () => void
  onRun: () => void
}

export function WorkflowEditorToolbar({
  workflowName,
  isDirty,
  isSaving,
  isRunning,
  onAutoLayout,
  onSave,
  onRun,
}: WorkflowEditorToolbarProps) {
  const navigate = useNavigate()
  const { id: missionId } = useParams<{ id: string }>()

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur-sm">
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1 px-2 text-xs text-muted-foreground"
        onClick={() => navigate(ROUTES.MISSION_WORKFLOWS(missionId!))}
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Workflows
      </Button>

      <div className="mx-1 h-4 w-px bg-border" />

      <span className="text-sm font-medium truncate">{workflowName}</span>

      {isDirty && (
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" title="Unsaved changes" />
      )}

      <div className="flex-1" />

      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        onClick={onAutoLayout}
      >
        <LayoutDashboard className="h-3.5 w-3.5" />
        Auto-layout
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        onClick={onSave}
        disabled={!isDirty || isSaving}
      >
        {isSaving ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Save className="h-3.5 w-3.5" />
        )}
        Save
      </Button>

      <Button
        variant="default"
        size="sm"
        className="h-7 gap-1 px-3 text-xs"
        onClick={onRun}
        disabled={isRunning}
      >
        {isRunning ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
        Run
      </Button>
    </div>
  )
}
