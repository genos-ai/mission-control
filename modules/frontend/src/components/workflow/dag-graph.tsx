import { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Badge } from '@/components/ui/badge'
import type { WorkflowStep } from '@/types'

interface DagGraphProps {
  steps: WorkflowStep[]
  onStepClick?: (step: WorkflowStep) => void
}

/** Layout steps into waves (topological layers) for left-to-right rendering. */
function layoutSteps(steps: WorkflowStep[]) {
  const layers: string[][] = []
  const assigned = new Set<string>()

  // Kahn's-style layered assignment
  while (assigned.size < steps.length) {
    const wave: string[] = []
    for (const step of steps) {
      if (assigned.has(step.id)) continue
      if (step.depends_on.every((d) => assigned.has(d))) {
        wave.push(step.id)
      }
    }
    if (wave.length === 0) break // safety: cycle guard
    layers.push(wave)
    wave.forEach((id) => assigned.add(id))
  }

  return layers
}

const NODE_WIDTH = 220
const NODE_HEIGHT = 70
const H_GAP = 60
const V_GAP = 30

export function DagGraph({ steps, onStepClick }: DagGraphProps) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const layers = layoutSteps(steps)
    const stepMap = new Map(steps.map((s) => [s.id, s]))
    const nodes: Node[] = []
    const edges: Edge[] = []

    layers.forEach((wave, layerIdx) => {
      wave.forEach((stepId, posIdx) => {
        const step = stepMap.get(stepId)!
        nodes.push({
          id: stepId,
          type: 'stepNode',
          position: {
            x: layerIdx * (NODE_WIDTH + H_GAP),
            y: posIdx * (NODE_HEIGHT + V_GAP),
          },
          data: { step },
        })

        for (const dep of step.depends_on) {
          edges.push({
            id: `${dep}->${stepId}`,
            source: dep,
            target: stepId,
            animated: false,
            style: { stroke: 'hsl(var(--muted-foreground))', strokeWidth: 1.5 },
          })
        }
      })
    })

    return { initialNodes: nodes, initialEdges: edges }
  }, [steps])

  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  const nodeTypes = useMemo(
    () => ({
      stepNode: (props: NodeProps) => (
        <StepNode {...props} onClick={onStepClick} />
      ),
    }),
    [onStepClick],
  )

  return (
    <div className="h-[400px] w-full rounded-lg border bg-background">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.3}
        maxZoom={1.5}
      >
        <Background color="hsl(var(--muted-foreground) / 0.15)" gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

function StepNode({
  data,
  onClick,
}: NodeProps & { onClick?: (step: WorkflowStep) => void }) {
  const step = data.step as WorkflowStep

  return (
    <div
      className="cursor-pointer rounded-lg border bg-card px-3 py-2 shadow-sm transition-colors hover:border-primary/50"
      style={{ width: NODE_WIDTH }}
      onClick={() => onClick?.(step)}
    >
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground" />
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium truncate">{step.id}</span>
        {step.cost_ceiling_usd && (
          <span className="text-[10px] text-muted-foreground">
            ${step.cost_ceiling_usd}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-1">
        <Badge variant="outline" className="text-[10px]">
          {step.capability?.split('.').pop() ?? step.node_type ?? '—'}
        </Badge>
        <span className="text-[10px] text-muted-foreground">{step.environment}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground" />
    </div>
  )
}
