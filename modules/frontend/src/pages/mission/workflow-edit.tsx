/**
 * Workflow editor page — loads workflow by ID and renders the visual editor.
 */

import { useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { WorkflowEditor } from '@/components/workflow/workflow-editor'
import { useMissionWorkflowById, useSaveWorkflowGraph } from '@/hooks/use-workflows'
import { useRunWorkflow } from '@/hooks/use-workflows'
import type { WorkflowStep } from '@/types'
import type { CanvasState, WorkflowEdge } from '@/components/workflow/workflow-editor-types'

export default function WorkflowEditPage() {
  const { id: missionId, workflowId } = useParams<{ id: string; workflowId: string }>()
  const { data: workflow, isLoading } = useMissionWorkflowById(missionId, workflowId)
  const saveGraph = useSaveWorkflowGraph(missionId!, workflowId!)
  const runWorkflow = useRunWorkflow(missionId!)

  const handleSaveGraph = useCallback(
    async (canvasState: CanvasState, steps?: WorkflowStep[], edges?: WorkflowEdge[]): Promise<string[]> => {
      const result = await saveGraph.mutateAsync({
        canvas_state: canvasState,
        ...(steps ? { steps } : {}),
        ...(edges ? { edges_json: edges } : {}),
      })
      return result.validation_warnings ?? []
    },
    [saveGraph],
  )

  const handleRun = useCallback(async () => {
    if (!workflow) return
    await runWorkflow.mutateAsync(workflow.name)
  }, [workflow, runWorkflow])

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!workflow) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Workflow not found</p>
      </div>
    )
  }

  return (
    <WorkflowEditor
      workflow={workflow}
      onSaveGraph={handleSaveGraph}
      onRun={handleRun}
    />
  )
}
