/**
 * Workflow editor toolbar — actions above the canvas.
 */

import {
  ArrowLeft,
  Bell,
  Bot,
  GitBranch,
  History,
  Layers,
  LayoutDashboard,
  Merge,
  Play,
  Save,
  Split,
  Loader2,
  Sparkles,
  UserRound,
  Wrench,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/lib/constants'

interface WorkflowEditorToolbarProps {
  workflowName: string
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
  onAddNode: (nodeType: string) => void
}

export function WorkflowEditorToolbar({
  workflowName,
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
  onAddNode,
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

      {isRunActive && runProgress && (
        <div className="flex items-center gap-1.5 text-xs text-amber-400">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span className="tabular-nums">{runProgress[0]}/{runProgress[1]} steps</span>
        </div>
      )}

      <div className="mx-1 h-4 w-px bg-border" />

      {/* Add node buttons */}
      <div className="flex items-center gap-0.5">
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add agent step"
          onClick={() => onAddNode('agent_step')}>
          <Bot className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add condition"
          onClick={() => onAddNode('condition')}>
          <GitBranch className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add notification"
          onClick={() => onAddNode('notification')}>
          <Bell className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add human input"
          onClick={() => onAddNode('human_input')}>
          <UserRound className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add tool call"
          onClick={() => onAddNode('tool_call')}>
          <Wrench className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add LLM call"
          onClick={() => onAddNode('llm_call')}>
          <Sparkles className="h-3.5 w-3.5" />
        </Button>
        <div className="mx-0.5 h-4 w-px bg-border" />
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add fork (branch)"
          onClick={() => onAddNode('branch')}>
          <Split className="h-3.5 w-3.5" />
        </Button>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add join (merge)"
          onClick={() => onAddNode('merge')}>
          <Merge className="h-3.5 w-3.5" />
        </Button>
        <div className="mx-0.5 h-4 w-px bg-border" />
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Add sub-workflow"
          onClick={() => onAddNode('sub_workflow')}>
          <Layers className="h-3.5 w-3.5" />
        </Button>
      </div>

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
        variant={showHistory ? 'secondary' : 'ghost'}
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        onClick={onToggleHistory}
      >
        <History className="h-3.5 w-3.5" />
        History
        {runCount > 0 && (
          <span className="ml-0.5 text-[10px] text-muted-foreground">{runCount}</span>
        )}
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
        disabled={isRunning || isRunActive}
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
