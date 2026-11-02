/**
 * Workflow visual editor — React Flow canvas with dagre auto-layout.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type Connection,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import toast from 'react-hot-toast'
import type { WorkflowStep } from '@/types'
import { useWorkflowRunStatus } from '@/hooks/use-workflow-run-status'
import { useResizable } from '@/hooks/use-resizable'
import { ArchitectChat } from '@/components/drawer/architect-chat-panel'
import { useWorkflowEditorDefaults, useWorkflowRuns } from '@/hooks/use-workflows'
import { Panel } from '@/components/ui/panel'
import { HumanInputPanel } from './human-input-panel'
import { StepDetail } from './step-detail'
import { WorkflowRunHistory } from './workflow-run-history'
import { WorkflowEditorNode, ConditionNode, NotificationNode, HumanInputNode, ToolCallNode, LlmCallNode, BranchNode, MergeNode, SubWorkflowNode, DecisionNode } from './workflow-editor-node'
import { WorkflowEditorToolbar } from './workflow-editor-toolbar'
import { NodePalette } from './node-palette'
import { StepPalette } from './step-palette'
import {
  dagreLayout,
  NODE_WIDTH,
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
  tool_call: 'toolCallStep',
  llm_call: 'llmCallStep',
  branch: 'branchStep',
  merge: 'mergeStep',
  sub_workflow: 'subWorkflowStep',
  decision: 'decisionStep',
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

/**
 * How an edge looks: condition outcomes are green and red, decision options violet,
 * everything else the neutral line.
 */
function edgeAppearance(label: string | undefined, isDecisionOption: boolean) {
  const isYes = label === 'Yes'
  const isNo = label === 'No'
  const stroke = isYes
    ? 'hsl(var(--success) / 0.6)'
    : isNo
      ? 'hsl(var(--danger) / 0.5)'
      : isDecisionOption
        ? 'hsl(var(--violet) / 0.6)'
        : 'hsl(var(--border-hover))'
  const emphasised = isYes || isNo || isDecisionOption
  return {
    labelStyle: emphasised ? { fontSize: 10, fontWeight: 600, fill: stroke } : undefined,
    style: { stroke, strokeWidth: emphasised ? 2 : 1.5 },
  }
}

function edgesToFlow(edges: WorkflowEdge[]): Edge[] {
  return edges.map((e) => {
    const label = e.label ?? undefined
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle ?? 'output',
      targetHandle: e.target_handle ?? 'input',
      label,
      ...edgeAppearance(label, false),
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

/** Extract WorkflowStep[] from React Flow nodes. */
function nodesToSteps(nodes: Node[]): WorkflowStep[] {
  return nodes.map((n) => (n.data as { step: WorkflowStep }).step)
}

/** Convert React Flow edges back to WorkflowEdge[] for the backend. */
function flowToEdges(edges: Edge[]): WorkflowEdge[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    source_handle: (e.sourceHandle as string) ?? 'output',
    target_handle: (e.targetHandle as string) ?? 'input',
    label: (e.label as string) ?? null,
  }))
}

/** Derive depends_on arrays from edges and patch into steps. */
function syncDependsOn(steps: WorkflowStep[], edges: WorkflowEdge[]): WorkflowStep[] {
  const depsMap: Record<string, string[]> = {}
  for (const e of edges) {
    if (!depsMap[e.target]) depsMap[e.target] = []
    if (!depsMap[e.target].includes(e.source)) {
      depsMap[e.target].push(e.source)
    }
  }
  return steps.map((s) => ({ ...s, depends_on: depsMap[s.id] ?? [] }))
}

// ── Human Input Panel ─────────────────────────────────────────────────────

// ── Component ─────────────────────────────────────────────────────────────

const nodeTypes = {
  workflowStep: WorkflowEditorNode,
  conditionStep: ConditionNode,
  notificationStep: NotificationNode,
  humanInputStep: HumanInputNode,
  toolCallStep: ToolCallNode,
  llmCallStep: LlmCallNode,
  branchStep: BranchNode,
  mergeStep: MergeNode,
  subWorkflowStep: SubWorkflowNode,
  decisionStep: DecisionNode,
}

interface WorkflowEditorProps {
  workflow: WorkflowDetailFull
  onSaveGraph: (canvas: CanvasState, steps?: WorkflowStep[], edges?: WorkflowEdge[]) => Promise<string[]>
  onRun: () => void
}

interface HistoryEntry {
  nodes: Node[]
  edges: Edge[]
}

const MAX_HISTORY = 50

/** Fit-to-view never zooms out past this, so a wide graph opens readable (pan, or zoom out, to see the rest). */
const FIT_MIN_ZOOM = 0.5

/** React Flow's zoom controls and minimap, on the panel surface. */
const CANVAS_CHROME = '!rounded-card !border !border-panel-border !bg-panel !shadow-none'

export function WorkflowEditor({ workflow, onSaveGraph, onRun }: WorkflowEditorProps) {
  const { id: missionId } = useParams<{ id: string }>()
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null)
  // Positions and structure are tracked apart because the drag autosave persists positions only:
  // it may clear the first flag, never the second.
  const [hasUnsavedPositions, setHasUnsavedPositions] = useState(false)
  const [hasUnsavedStructure, setHasUnsavedStructure] = useState(false)
  const isDirty = hasUnsavedPositions || hasUnsavedStructure
  const [isSaving, setIsSaving] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [showPalette, setShowPalette] = useState(false)
  const { data: editorDefaults } = useWorkflowEditorDefaults()
  const [architectOpen, setArchitectOpen] = useState(false)
  const { width: architectWidth, onMouseDown: onArchitectResize } = useResizable(380)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const historyRef = useRef<HistoryEntry[]>([])
  const redoRef = useRef<HistoryEntry[]>([])
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
  const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges)

  // Sync when workflow data changes (e.g. refetch)
  useEffect(() => {
    setNodes(initNodes)
  }, [initNodes, setNodes])

  // Inject execution overlay status + metrics into node data
  useEffect(() => {
    const statuses = runOverlay.nodeStatuses
    const metrics = runOverlay.nodeMetrics
    if (!runOverlay.isActive && Object.keys(statuses).length === 0) return
    setNodes((prev) =>
      prev.map((node) => {
        const status = statuses[node.id] ?? 'idle'
        const m = metrics[node.id]
        const prevData = node.data as Record<string, unknown>
        if (prevData.status === status && prevData.metrics === m) return node
        return { ...node, data: { ...node.data, status, metrics: m } }
      }),
    )
  }, [runOverlay.nodeStatuses, runOverlay.nodeMetrics, runOverlay.isActive, setNodes])

  // Animate edges whose source node is running
  useEffect(() => {
    const statuses = runOverlay.nodeStatuses
    if (!runOverlay.isActive && Object.keys(statuses).length === 0) return
    setEdges((prev) =>
      prev.map((edge) => {
        const animated = statuses[edge.source] === 'running'
        if (edge.animated === animated) return edge
        return { ...edge, animated }
      }),
    )
  }, [runOverlay.nodeStatuses, runOverlay.isActive, setEdges])

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

  // ── Undo / Redo ──────────────────────────────────────────────────────────

  const pushHistory = useCallback(() => {
    historyRef.current.push({ nodes: [...nodes], edges: [...edges] })
    if (historyRef.current.length > MAX_HISTORY) historyRef.current.shift()
    redoRef.current = [] // clear redo on new action
  }, [nodes, edges])

  const handleUndo = useCallback(() => {
    const entry = historyRef.current.pop()
    if (!entry) return
    redoRef.current.push({ nodes: [...nodes], edges: [...edges] })
    setNodes(entry.nodes)
    setEdges(entry.edges)
    setHasUnsavedStructure(true)
  }, [nodes, edges, setNodes, setEdges])

  const handleRedo = useCallback(() => {
    const entry = redoRef.current.pop()
    if (!entry) return
    historyRef.current.push({ nodes: [...nodes], edges: [...edges] })
    setNodes(entry.nodes)
    setEdges(entry.edges)
    setHasUnsavedStructure(true)
  }, [nodes, edges, setNodes, setEdges])

  // Track dirty state on node drag
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes)
      const hasDrag = changes.some((c) => c.type === 'position' && c.dragging)
      if (hasDrag) {
        setHasUnsavedPositions(true)
      }
    },
    [onNodesChange],
  )

  // Track dirty state on edge changes (removal)
  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (changes.some((c) => c.type === 'remove')) {
        pushHistory()
      }
      onEdgesChange(changes)
      if (changes.some((c) => c.type === 'remove')) {
        setHasUnsavedStructure(true)
      }
    },
    [onEdgesChange, pushHistory],
  )

  // Validate connections in real-time (prevent invalid edges)
  const isValidConnection = useCallback(
    (connection: Edge | Connection) => {
      // No self-loops
      if (connection.source === connection.target) return false
      // No duplicate edges
      if (edges.some((e) => e.source === connection.source && e.target === connection.target)) return false
      // Prevent cycles: check if target can already reach source
      const canReach = (from: string, to: string): boolean => {
        const visited = new Set<string>()
        const queue = [from]
        while (queue.length > 0) {
          const current = queue.pop()!
          if (current === to) return true
          if (visited.has(current)) continue
          visited.add(current)
          for (const e of edges) {
            if (e.source === current) queue.push(e.target)
          }
        }
        return false
      }
      if (canReach(connection.target!, connection.source!)) return false

      // Node-type-specific constraints
      const sourceNode = nodes.find((n) => n.id === connection.source)
      if (sourceNode) {
        const outgoing = edges.filter((e) => e.source === connection.source).length
        // Condition nodes: max 2 outgoing (Yes/No)
        if (sourceNode.type === 'conditionStep' && outgoing >= 2) return false
        // Decision nodes: max N outgoing (one per option)
        if (sourceNode.type === 'decisionStep') {
          const optionCount = (sourceNode.data as { step: WorkflowStep }).step.decision_config?.options?.length ?? 0
          if (outgoing >= optionCount) return false
        }
      }

      return true
    },
    [edges, nodes],
  )

  // Connect nodes — create edge on drag
  const handleConnect = useCallback(
    (connection: Connection) => {
      if (connection.source === connection.target) return
      const exists = edges.some(
        (e) => e.source === connection.source && e.target === connection.target,
      )
      if (exists) return

      // Auto-label edges from condition and decision nodes
      const sourceNode = nodes.find((n) => n.id === connection.source)
      const isCondition = sourceNode?.type === 'conditionStep'
      const isDecision = sourceNode?.type === 'decisionStep'

      let label: string | undefined
      if (isCondition) {
        label = connection.sourceHandle === 'yes' ? 'Yes'
          : connection.sourceHandle === 'no' ? 'No'
          : undefined
      } else if (isDecision) {
        // Auto-assign first unused option key
        const config = (sourceNode?.data as { step: WorkflowStep })?.step?.decision_config
        const usedLabels = new Set(edges.filter((e) => e.source === connection.source).map((e) => e.label))
        const available = config?.options?.find((o) => !usedLabels.has(o.key))
        label = available?.key ?? connection.sourceHandle ?? undefined
      }

      const appearance = edgeAppearance(label, isDecision && !!label)

      pushHistory()
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            id: `${connection.source}->${connection.target}`,
            label,
            ...appearance,
          },
          eds,
        ),
      )
      setHasUnsavedStructure(true)
    },
    [edges, nodes, setEdges, pushHistory],
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

  // Node deletion
  const handleNodesDelete = useCallback(() => {
    pushHistory()
    setSelectedStep(null)
    setHasUnsavedStructure(true)
  }, [pushHistory])

  // Auto-layout
  const handleAutoLayout = useCallback(() => {
    pushHistory()
    setNodes((prev) => dagreLayout(prev, edges))
    setHasUnsavedPositions(true)
  }, [edges, setNodes, pushHistory])

  // Save — send steps + edges + canvas atomically
  const handleSave = useCallback(async () => {
    setIsSaving(true)
    try {
      const canvasState: CanvasState = {
        node_positions: collectPositions(nodes),
      }
      const edgesData = flowToEdges(edges)
      let steps = nodesToSteps(nodes)
      steps = syncDependsOn(steps, edgesData)
      const warnings = await onSaveGraph(canvasState, steps, edgesData)
      setHasUnsavedPositions(false)
      setHasUnsavedStructure(false)
      if (warnings.length > 0) {
        toast.success(`Saved with ${warnings.length} warning${warnings.length > 1 ? 's' : ''}`)
        for (const w of warnings) {
          toast(w, { icon: '⚠️', duration: 5000 })
        }
      } else {
        toast.success('Workflow saved')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save workflow')
    } finally {
      setIsSaving(false)
    }
  }, [nodes, edges, onSaveGraph])

  // Debounced auto-save on drag end (positions only — lightweight)
  const handleNodeDragStop = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(async () => {
      const canvasState: CanvasState = {
        node_positions: collectPositions(nodes),
      }
      try {
        await onSaveGraph(canvasState)
        setHasUnsavedPositions(false)
      } catch {
        // silent — user can still save manually
      }
    }, 2000)
  }, [nodes, onSaveGraph])

  // Run: clear the last run's overlay and open the run dialog. The dialog starts the run
  // and reports its result, so nothing is announced here.
  const handleRun = useCallback(() => {
    runOverlay.reset()
    onRun()
  }, [onRun, runOverlay])

  // ── Keyboard shortcuts (Cmd+S, Cmd+Z, Cmd+Shift+Z) ─────────────────────
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key === 's') {
        e.preventDefault()
        if (isDirty && !isSaving) handleSave()
      } else if (mod && e.shiftKey && e.key === 'z') {
        e.preventDefault()
        handleRedo()
      } else if (mod && e.key === 'z') {
        e.preventDefault()
        handleUndo()
      } else if (e.key === ' ' && !mod) {
        // Space opens node palette (only when not typing in an input/textarea)
        const tag = (e.target as HTMLElement).tagName
        if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
          e.preventDefault()
          setShowPalette(true)
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isDirty, isSaving, handleSave, handleUndo, handleRedo])

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

  // Add node from toolbar
  const handleAddNode = useCallback(
    (nodeType: string) => {
      pushHistory()
      // New LLM-call and decision steps start with the model alias set in the backend config.
      const stepModel = editorDefaults?.step_model ?? ''
      if ((nodeType === 'llm_call' || nodeType === 'decision') && !stepModel) {
        toast.error("The default model couldn't be loaded; set this step's model yourself.")
      }
      const prefix = nodeType === 'agent_step' ? 'step'
        : nodeType === 'condition' ? 'check'
        : nodeType === 'notification' ? 'notify'
        : nodeType === 'tool_call' ? 'tool'
        : nodeType === 'llm_call' ? 'llm'
        : nodeType === 'branch' ? 'fork'
        : nodeType === 'merge' ? 'join'
        : nodeType === 'sub_workflow' ? 'sub'
        : 'input'
      const suffix = Math.random().toString(36).slice(2, 6)
      const stepId = `${prefix}-${suffix}`

      const step: WorkflowStep = {
        id: stepId,
        description: null,
        node_type: nodeType as WorkflowStep['node_type'],
        capability: nodeType === 'agent_step' ? 'code.general' : null,
        roster: 'default',
        complexity_tier: 'simple',
        cost_ceiling_usd: null,
        environment: 'local',
        input: {},
        output_mapping: null,
        depends_on: [],
        timeout_seconds: null,
        max_refinement_rounds: 1,
        termination: 'completion',
        max_iterations: null,
        ...(nodeType === 'condition' ? {
          condition_config: { expression: 'true', true_label: 'Yes', false_label: 'No' },
        } : {}),
        ...(nodeType === 'notification' ? {
          notification_config: { channel: 'sse', message_template: 'Notification', recipient: null },
        } : {}),
        ...(nodeType === 'human_input' ? {
          human_input_config: { prompt_message: 'Please respond', channel: 'telegram', timeout_hours: null, default_response: null, choices: null },
        } : {}),
        ...(nodeType === 'tool_call' ? {
          tool_call_config: { tool_name: 'search_web', tool_args: {} },
        } : {}),
        ...(nodeType === 'llm_call' ? {
          llm_call_config: { model: stepModel, system_prompt: null, prompt_template: 'Summarize the following:\n{{@node.step-id.output}}', temperature: 0.0, max_tokens: null, structured_output: null },
        } : {}),
        ...(nodeType === 'merge' ? {
          merge_config: { strategy: 'wait_all' },
        } : {}),
        ...(nodeType === 'sub_workflow' ? {
          sub_workflow_config: { workflow_id: '', workflow_name: '', pass_context: true, max_depth: 3 },
        } : {}),
        ...(nodeType === 'decision' ? {
          decision_config: {
            resolver: 'agent' as const,
            model: stepModel,
            prompt: 'Based on the upstream results, decide which path to take.',
            temperature: 0,
            prompt_message: null,
            channel: null,
            timeout_hours: null,
            default_option: null,
            expression: null,
            options: [
              { key: 'option_a', label: 'Option A' },
              { key: 'option_b', label: 'Option B' },
            ],
          },
        } : {}),
      }

      const maxX = Math.max(...nodes.map((n) => n.position.x), 0)
      const newNode: Node = {
        id: stepId,
        type: STEP_NODE_TYPE_MAP[nodeType] ?? 'workflowStep',
        position: { x: maxX + NODE_WIDTH + 80, y: 100 },
        data: { step },
      }

      setNodes((prev) => [...prev, newNode])
      setSelectedStep(step)
      setShowHistory(false)
      setHasUnsavedStructure(true)
    },
    [nodes, setNodes, pushHistory, editorDefaults],
  )

  const handleOpenArchitect = useCallback(() => {
    setArchitectOpen((v) => !v)
  }, [])

  // Palette selection → add node + close palette
  const handlePaletteSelect = useCallback(
    (nodeType: string) => {
      setShowPalette(false)
      handleAddNode(nodeType)
    },
    [handleAddNode],
  )

  // Update step from config panel
  const handleStepUpdate = useCallback(
    (updated: WorkflowStep) => {
      pushHistory()
      setNodes((prev) =>
        prev.map((node) =>
          node.id === updated.id
            ? { ...node, data: { ...node.data, step: updated } }
            : node,
        ),
      )
      setSelectedStep(updated)
      setHasUnsavedStructure(true)
    },
    [setNodes, pushHistory],
  )

  // Delete selected node
  const handleDeleteSelectedNode = useCallback(() => {
    if (!selectedStep) return
    pushHistory()
    setNodes((prev) => prev.filter((n) => n.id !== selectedStep.id))
    setEdges((prev) =>
      prev.filter((e) => e.source !== selectedStep.id && e.target !== selectedStep.id),
    )
    setSelectedStep(null)
    setHasUnsavedStructure(true)
  }, [selectedStep, setNodes, setEdges, pushHistory])

  return (
    <div className="flex h-full min-h-0 flex-col gap-gutter px-2 pb-2">
      <WorkflowEditorToolbar
        workflowName={workflow.name}
        stepCount={nodes.length}
        isDirty={isDirty}
        isSaving={isSaving}
        isRunActive={runOverlay.isActive}
        runProgress={runOverlay.progress}
        showHistory={showHistory}
        runCount={runs.length}
        onAutoLayout={handleAutoLayout}
        onSave={handleSave}
        onRun={handleRun}
        onToggleHistory={handleToggleHistory}
        onOpenPalette={() => setShowPalette(true)}
        onOpenArchitect={handleOpenArchitect}
      />

      {/* Human input panel — appears when any node is awaiting a decision */}
      <HumanInputPanel
        pending={runOverlay.pendingHumanInputs}
        missionId={missionId!}
      />

      <div className="relative flex min-h-0 flex-1 gap-gutter">
        <StepPalette onAddStep={handleAddNode} />

        {/* Canvas */}
        <Panel className="relative min-w-[360px] flex-1 overflow-hidden">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={handleConnect}
            isValidConnection={isValidConnection}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            onNodeDragStop={handleNodeDragStop}
            onNodesDelete={handleNodesDelete}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15, minZoom: FIT_MIN_ZOOM }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable
            nodesConnectable
            elementsSelectable
            deleteKeyCode={['Backspace', 'Delete']}
            minZoom={0.2}
            maxZoom={2}
            defaultEdgeOptions={{ style: edgeAppearance(undefined, false).style }}
          >
            <Background variant={BackgroundVariant.Dots} color="hsl(var(--canvas-dot))" gap={20} size={1} />
            <Controls showInteractive={false} className={CANVAS_CHROME} />
            <MiniMap nodeStrokeWidth={3} className={CANVAS_CHROME} maskColor="hsl(var(--background) / 0.8)" />
          </ReactFlow>

          {/* Node palette (Space key) */}
          {showPalette && (
            <NodePalette
              onSelect={handlePaletteSelect}
              onClose={() => setShowPalette(false)}
            />
          )}
        </Panel>

        {/* Right panel — step detail or run history (mutually exclusive) */}
        {selectedStep && !showHistory && (
          <Panel className="hidden w-[300px] shrink-0 flex-col overflow-y-auto min-[960px]:flex">
            <StepDetail
              step={selectedStep}
              onClose={() => setSelectedStep(null)}
              onUpdate={handleStepUpdate}
              onDelete={handleDeleteSelectedNode}
              missionId={missionId}
              currentWorkflowId={workflow.id}
              upstreamNodeIds={edges
                .filter((e) => e.target === selectedStep.id)
                .map((e) => e.source)}
            />
          </Panel>
        )}
        {showHistory && (
          <Panel className="w-[300px] shrink-0 overflow-y-auto">
            <WorkflowRunHistory
              runs={runs}
              isLoading={runsLoading}
              selectedRunId={selectedRunId}
              onSelectRun={setSelectedRunId}
              onClose={() => { setShowHistory(false); setSelectedRunId(null) }}
            />
          </Panel>
        )}

        {/* Architect chat — opened and closed from the toolbar */}
        {architectOpen && (
          <Panel className="relative flex shrink-0 flex-col overflow-hidden" style={{ width: architectWidth }}>
            <div
              onMouseDown={onArchitectResize}
              className="absolute left-0 top-0 z-10 h-full w-1 cursor-col-resize transition-colors hover:bg-brand/30"
            />
            <ArchitectChat
              missionId={missionId!}
              workflowId={workflow.id}
              workflowName={workflow.name}
              onClose={() => setArchitectOpen(false)}
            />
          </Panel>
        )}
      </div>
    </div>
  )
}
