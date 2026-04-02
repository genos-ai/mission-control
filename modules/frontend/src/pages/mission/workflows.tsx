import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  GitBranch,
  Clock,
  Zap,
  Hand,
  Import,
  MessageSquare,
  CalendarClock,
  Play,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useMissionWorkflows,
  useMissionWorkflow,
  useWorkflowTemplates,
  useImportTemplate,
  useSchedules,
} from '@/hooks/use-workflows'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'
import { DagGraph } from '@/components/workflow/dag-graph'
import { StepDetail } from '@/components/workflow/step-detail'
import { ScheduleModal } from '@/components/workflow/schedule-modal'
import { RunModal } from '@/components/mission/run-modal'
import { ROUTES } from '@/lib/constants'
import type { MissionWorkflow, WorkflowStep } from '@/types'

const TRIGGER_ICONS: Record<string, React.ReactNode> = {
  schedule: <Clock className="h-3 w-3" />,
  event: <Zap className="h-3 w-3" />,
  on_demand: <Hand className="h-3 w-3" />,
}

export default function WorkflowsPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const { data: workflows, isLoading } = useMissionWorkflows(missionId)
  const { open: openDrawer } = useDrawerStore()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  if (!workflows?.length && !showImport) {
    return (
      <div className="p-6">
        <WorkflowEmptyState
          missionId={missionId!}
          onDesign={() =>
            openDrawer('architect-chat', { missionId })
          }
        />
      </div>
    )
  }

  const selected = workflows?.find((w) => w.id === selectedId) ?? null

  return (
    <div className="flex h-full">
      {/* Left panel — workflow list */}
      <div className="w-64 flex-shrink-0 overflow-y-auto border-r p-3">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            Workflows
          </span>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              title="Import template"
              onClick={() => setShowImport(true)}
            >
              <Import className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              title="Design with Architect"
              onClick={() =>
                openDrawer('architect-chat', { missionId })
              }
            >
              <MessageSquare className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {workflows?.map((w) => (
          <WorkflowListItem
            key={w.id}
            workflow={w}
            active={w.id === selectedId}
            onClick={() => setSelectedId(w.id)}
          />
        ))}
      </div>

      {/* Right panel — detail */}
      <div className="flex-1 overflow-y-auto p-6">
        {selected ? (
          <WorkflowDetailPanel workflow={selected} missionId={missionId!} />
        ) : showImport ? (
          <ImportPanel
            missionId={missionId!}
            onDone={() => setShowImport(false)}
          />
        ) : (
          <div className="flex items-center justify-center py-24 text-sm text-muted-foreground">
            Select a workflow to view its details.
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Sub-components ----

function WorkflowListItem({
  workflow,
  active,
  onClick,
}: {
  workflow: MissionWorkflow
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`mb-1 w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
        active ? 'bg-accent text-accent-foreground' : ''
      }`}
    >
      <div className="flex items-center gap-2">
        {TRIGGER_ICONS[workflow.trigger_type] ?? (
          <GitBranch className="h-3 w-3" />
        )}
        <span className="truncate font-medium">{workflow.name}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground">
          {workflow.step_count} step{workflow.step_count !== 1 ? 's' : ''}
        </span>
        <Badge
          variant={workflow.enabled ? 'success' : 'outline'}
          className="text-[10px]"
        >
          {workflow.enabled ? 'Active' : 'Disabled'}
        </Badge>
        {workflow.locked_at && (
          <span className="text-[10px] text-muted-foreground">Locked</span>
        )}
      </div>
    </button>
  )
}

function WorkflowDetailPanel({
  workflow,
  missionId,
}: {
  workflow: MissionWorkflow
  missionId: string
}) {
  const navigate = useNavigate()
  const { data: detail } = useMissionWorkflow(missionId, workflow.name)
  const { data: schedules } = useSchedules(missionId)
  const [selectedStep, setSelectedStep] = useState<WorkflowStep | null>(null)
  const [showScheduleModal, setShowScheduleModal] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)

  const workflowSchedules = schedules?.filter(
    (s) => s.workflow_definition_id === workflow.id,
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-bold">{workflow.name}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {workflow.description}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Badge variant={workflow.enabled ? 'success' : 'outline'}>
              {workflow.enabled ? 'Active' : 'Disabled'}
            </Badge>
            <span className="text-xs text-muted-foreground">
              v{workflow.version}
            </span>
            <span className="text-xs text-muted-foreground">
              {workflow.step_count} steps
            </span>
            {workflow.designed_by && (
              <span className="text-xs text-muted-foreground">
                by {workflow.designed_by}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => setShowRunModal(true)}
          >
            <Play className="mr-1 h-3.5 w-3.5" />
            Run
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowScheduleModal(true)}
          >
            <CalendarClock className="mr-1 h-3.5 w-3.5" />
            Schedule
          </Button>
        </div>
      </div>

      {/* DAG Graph */}
      {detail?.steps?.length ? (
        <DagGraph steps={detail.steps} onStepClick={setSelectedStep} />
      ) : (
        <div className="flex h-[200px] items-center justify-center rounded-lg border text-sm text-muted-foreground">
          Loading workflow steps...
        </div>
      )}

      {/* Step detail popover */}
      {selectedStep && (
        <StepDetail
          step={selectedStep}
          onClose={() => setSelectedStep(null)}
        />
      )}

      {/* Schedules */}
      {workflowSchedules && workflowSchedules.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">Schedules</h3>
          <div className="space-y-2">
            {workflowSchedules.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between rounded-md border p-3 text-sm"
              >
                <div>
                  <code className="text-xs">{s.cron_expression}</code>
                  <span className="ml-2 text-xs text-muted-foreground">
                    ({s.timezone})
                  </span>
                  {s.description && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {s.description}
                    </p>
                  )}
                </div>
                <Badge
                  variant={s.enabled ? 'success' : 'outline'}
                  className="text-[10px]"
                >
                  {s.enabled ? 'Active' : 'Paused'}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Schedule modal */}
      {showScheduleModal && (
        <ScheduleModal
          missionId={missionId}
          workflowDefinitionId={workflow.id}
          onClose={() => setShowScheduleModal(false)}
        />
      )}

      {/* Run modal */}
      {showRunModal && (
        <RunModal
          missionId={missionId}
          workflowName={workflow.name}
          onClose={() => setShowRunModal(false)}
          onStarted={(execId) => {
            setShowRunModal(false)
            navigate(ROUTES.MISSION_RUN_LIVE(missionId, execId))
          }}
        />
      )}
    </div>
  )
}

function WorkflowEmptyState({
  missionId,
  onDesign,
}: {
  missionId: string
  onDesign: () => void
}) {
  const { data: templates, isLoading } = useWorkflowTemplates()
  const importMutation = useImportTemplate(missionId)

  const handleImport = (name: string) => {
    importMutation.mutate(name, {
      onSuccess: () => toast.success(`Imported "${name}" — you can now customize it`),
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <div className="space-y-8">
      {/* Templates section */}
      <div>
        <h2 className="text-lg font-semibold">Workflow Templates</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Import a template to create a mission-specific copy you can customize.
        </p>

        {isLoading ? (
          <div className="mt-6 flex justify-center"><Spinner /></div>
        ) : templates?.length ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {templates.map((t) => (
              <div key={t.workflow_name} className="rounded-lg border p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-medium">{t.workflow_name}</h3>
                  <Badge variant="outline" className="text-[10px] flex-shrink-0">
                    {t.trigger_type}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                  {t.description}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span>{t.step_count} steps</span>
                    <span>&middot;</span>
                    <span>${t.budget_usd} budget</span>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleImport(t.workflow_name)}
                    disabled={importMutation.isPending}
                  >
                    <Import className="mr-1 h-3 w-3" />
                    Import
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            No templates available.
          </p>
        )}
      </div>

      {/* Architect option */}
      <div className="rounded-lg border border-dashed p-6 text-center">
        <MessageSquare className="mx-auto h-6 w-6 text-muted-foreground" />
        <p className="mt-2 text-sm font-medium">Design a custom workflow</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Describe what you want to automate and the Architect will design a workflow for you.
        </p>
        <Button variant="outline" size="sm" className="mt-3" onClick={onDesign}>
          Design with Architect
        </Button>
      </div>
    </div>
  )
}

function ImportPanel({
  missionId,
  onDone,
}: {
  missionId: string
  onDone: () => void
}) {
  const { data: templates, isLoading } = useWorkflowTemplates()
  const importMutation = useImportTemplate(missionId)

  if (isLoading) return <Spinner />

  if (!templates?.length) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        No workflow templates available.
        <Button variant="link" onClick={onDone} className="ml-1">
          Go back
        </Button>
      </div>
    )
  }

  const handleImport = (name: string) => {
    importMutation.mutate(name, {
      onSuccess: () => {
        toast.success(`Template "${name}" imported`)
        onDone()
      },
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Import Template</h2>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {templates.map((t) => (
          <div
            key={t.workflow_name}
            className="rounded-lg border p-4"
          >
            <h3 className="text-sm font-medium">{t.workflow_name}</h3>
            <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
              {t.description}
            </p>
            <div className="mt-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px]">
                  {t.step_count} steps
                </Badge>
                <span className="text-[10px] text-muted-foreground">
                  ${t.budget_usd}
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleImport(t.workflow_name)}
                disabled={importMutation.isPending}
              >
                <Import className="mr-1 h-3 w-3" />
                Import
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
