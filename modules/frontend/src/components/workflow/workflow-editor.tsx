/**
 * Workflow visual editor — React Flow canvas with dagre auto-layout.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import toast from 'react-hot-toast'
import type { WorkflowStep } from '@/types'
import { useWorkflowRunStatus } from '@/hooks/use-workflow-run-status'
import { useWorkflowRuns } from '@/hooks/use-workflows'
import { StepDetail } from './step-detail'
import { WorkflowRunHistory } from './workflow-run-history'
import { WorkflowEditorNode, ConditionNode, NotificationNode, HumanInputNode } from './workflow-editor-node'
import { WorkflowEditorToolbar } from './workflow-editor-toolbar'
import {
  dagreLayout,
  type WorkflowDetailFull,
  type WorkflowEdge,
  type CanvasState,
} from './workflow-editor-types'

// ── Helpers ───────────────────────────────────────────────────────────────

const STEP_NODE_TYPE_MAP: Record<string, string> = {
  agent_step: 'workflowStep',
  condition: 'conditionStep',
  notification: 'notificationStep',
  human_input: 'humanInputStep',
}

function stepsToNodes(
  steps: WorkflowStep[],
  canvasState: CanvasState,
): Node[] {
  return steps.map((step) => ({
    id: step.id,
    type: STEP_NODE_TYPE_MAP[step.node_type ?? 'agent_step'] ?? 'workflowStep',
    position: canvasState.node_positions?.[step.id] ?? { x: 0, y: 0 },
    data: { step },
  }))
}

function edgesToFlow(edges: WorkflowEdge[]): Edge[] {
  return edges.map((e) => {
    const label = e.label ?? undefined
    // Color condition-branch edges
    const isYes = label === 'Yes'
    const isNo = label === 'No'
    const stroke = isYes
      ? 'hsl(142 71% 45% / 0.6)'  // emerald
      : isNo
        ? 'hsl(0 84% 60% / 0.5)'  // red
        : 'hsl(var(--muted-foreground) / 0.4)'

    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle ?? 'output',
      targetHandle: e.target_handle ?? 'input',
      label,
      labelStyle: (isYes || isNo) ? { fontSize: 10, fontWeight: 600, fill: stroke } : undefined,
      style: { stroke, strokeWidth: isYes || isNo ? 2 : 1.5 },
      animated: false,
    }
  })
}

function hasPositions(canvasState: CanvasState): boolean {
  const pos = canvasState.node_positions
  return !!pos && Object.keys(pos).length > 0
}

function collectPositions(nodes: Node[]): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {}
  for (const n of nodes) {
    positions[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) }
  }
  return positions
}

// ── Component ─────────────────────────────────────────────────────────────

const nodeTypes = {
  workflowStep: WorkflowEditorNode,
  conditionStep: ConditionNode,
  notificationStep: NotificationNode,
  humanInputStep: HumanInputNode,
}

interface WorkflowEditorProps {
  workflow: WorkflowDetailFull
  onSaveGraph: (canvas: CanvasState) => Promise<void>
  onRun: () => Promise<void>
}

export function WorkflowEditor({ workflow, onSaveGraph, onRun }: WorkflowEditorProps) {
  const { id: missionId } = useParams<{ id: string }>()
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null)
  const [isDirty, setIsDirty] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const runOverlay = useWorkflowRunStatus()
  const { data: runs = [], isLoading: runsLoading } = useWorkflowRuns(missionId, workflow.name)

  // Build initial nodes + edges
  const { initNodes, initEdges } = useMemo(() => {
    let nodes = stepsToNodes(workflow.steps, workflow.canvas_state ?? {})
    const edges = edgesToFlow(workflow.edges_json ?? [])

    // Auto-layout if no saved positions
    if (!hasPositions(workflow.canvas_state ?? {})) {
      nodes = dagreLayout(nodes, edges)
    }

    return { initNodes: nodes, initEdges: edges }
  }, [workflow])

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes)
  const [edges, , onEdgesChange] = useEdgesState(initEdges)

  // Sync when workflow data changes (e.g. refetch)
  useEffect(() => {
    setNodes(initNodes)
  }, [initNodes, setNodes])

  // Inject execution overlay status into node data
  useEffect(() => {
    const statuses = runOverlay.nodeStatuses
    if (!runOverlay.isActive && Object.keys(statuses).length === 0) return
    setNodes((prev) =>
      prev.map((node) => {
        const status = statuses[node.id] ?? 'idle'
        if ((node.data as Record<string, unknown>).status === status) return node
        return { ...node, data: { ...node.data, status } }
      }),
    )
  }, [runOverlay.nodeStatuses, runOverlay.isActive, setNodes])

  // Replay overlay for historical runs — set all nodes to the run's final status
  useEffect(() => {
    if (!selectedRunId || runOverlay.isActive) return
    const run = runs.find((r) => r.id === selectedRunId)
    if (!run) return
    const status = run.status === 'COMPLETED' ? 'completed'
      : run.status === 'FAILED' ? 'failed'
      : 'idle'
    setNodes((prev) =>
      prev.map((node) => {
        if ((node.data as Record<string, unknown>).status === status) return node
        return { ...node, data: { ...node.data, status } }
      }),
    )
  }, [selectedRunId, runs, runOverlay.isActive, setNodes])

  // Clear replay overlay when deselecting a historical run
  useEffect(() => {
    if (selectedRunId || runOverlay.isActive) return
    setNodes((prev) =>
      prev.map((node) => {
        if ((node.data as Record<string, unknown>).status === 'idle') return node
        return { ...node, data: { ...node.data, status: 'idle' } }
      }),
    )
  }, [selectedRunId, runOverlay.isActive, setNodes])

  // Track dirty state on node drag
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes)
      const hasDrag = changes.some((c) => c.type === 'position' && c.dragging)
      if (hasDrag) {
        setIsDirty(true)
      }
    },
    [onNodesChange],
  )

  // Node click → select step (hides history panel)
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const step = (node.data as { step: WorkflowStep }).step
      setSelectedStep(step)
      setShowHistory(false)
      setSelectedRunId(null)
    },
    [],
  )

  // Deselect on pane click
  const handlePaneClick = useCallback(() => {
    setSelectedStep(null)
  }, [])

  // Auto-layout
  const handleAutoLayout = useCallback(() => {
    setNodes((prev) => dagreLayout(prev, edges))
    setIsDirty(true)
  }, [edges, setNodes])

  // Save
  const handleSave = useCallback(async () => {
    setIsSaving(true)
    try {
      const canvasState: CanvasState = {
        node_positions: collectPositions(nodes),
      }
      await onSaveGraph(canvasState)
      setIsDirty(false)
      toast.success('Canvas saved')
    } catch {
      toast.error('Failed to save canvas')
    } finally {
      setIsSaving(false)
    }
  }, [nodes, onSaveGraph])

  // Debounced auto-save on drag end
  const handleNodeDragStop = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(async () => {
      const canvasState: CanvasState = {
        node_positions: collectPositions(nodes),
      }
      try {
        await onSaveGraph(canvasState)
        setIsDirty(false)
      } catch {
        // silent — user can still save manually
      }
    }, 2000)
  }, [nodes, onSaveGraph])

  // Run
  const handleRun = useCallback(async () => {
    runOverlay.reset()
    setIsRunning(true)
    try {
      await onRun()
      toast.success('Workflow started')
    } catch {
      toast.error('Failed to start workflow')
    } finally {
      setIsRunning(false)
    }
  }, [onRun, runOverlay])

  // Toggle history panel
  const handleToggleHistory = useCallback(() => {
    setShowHistory((prev) => {
      if (!prev) {
        setSelectedStep(null) // hide step detail when opening history
      } else {
        setSelectedRunId(null)
      }
      return !prev
    })
  }, [])

  return (
    <div className="flex h-full flex-col">
      <WorkflowEditorToolbar
        workflowName={workflow.name}
        isDirty={isDirty}
        isSaving={isSaving}
        isRunning={isRunning}
        isRunActive={runOverlay.isActive}
        runProgress={runOverlay.progress}
        showHistory={showHistory}
        runCount={runs.length}
        onAutoLayout={handleAutoLayout}
        onSave={handleSave}
        onRun={handleRun}
        onToggleHistory={handleToggleHistory}
      />

      <div className="relative flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onNodeDragStop={handleNodeDragStop}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable
            nodesConnectable={false}
            elementsSelectable
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{
              style: { stroke: 'hsl(var(--muted-foreground) / 0.4)', strokeWidth: 1.5 },
            }}
          >
            <Background color="hsl(var(--muted-foreground) / 0.1)" gap={20} />
            <Controls showInteractive={false} className="!bg-card !border-border !shadow-md" />
            <MiniMap
              nodeStrokeWidth={3}
              className="!bg-card !border-border !shadow-md"
              maskColor="hsl(var(--background) / 0.8)"
            />
          </ReactFlow>
        </div>

        {/* Right panel — step detail or run history (mutually exclusive) */}
        {selectedStep && !showHistory && (
          <div className="w-[320px] shrink-0 overflow-y-auto border-l bg-background p-3">
            <StepDetail
              step={selectedStep}
              onClose={() => setSelectedStep(null)}
            />
          </div>
        )}
        {showHistory && (
          <div className="w-[320px] shrink-0 overflow-y-auto border-l bg-background">
            <WorkflowRunHistory
              runs={runs}
              isLoading={runsLoading}
              selectedRunId={selectedRunId}
              onSelectRun={setSelectedRunId}
              onClose={() => { setShowHistory(false); setSelectedRunId(null) }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
