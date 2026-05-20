import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  WorkflowListItem,
  WorkflowDetail,
  WorkflowEdge,
  WorkflowStep,
  MissionWorkflow,
  WorkflowRunRecord,
  WorkflowSchedule,
  WorkflowScheduleCreateRequest,
  WorkflowScheduleUpdateRequest,
  ArchitectChatResponse,
} from '@/types'
import type { WorkflowDetailFull, CanvasState } from '@/components/workflow/workflow-editor-types'

// ---- Query keys ----

export const workflowKeys = {
  templates: ['workflow-templates'] as const,
  templateDetail: (name: string) => ['workflow-templates', name] as const,
  missionWorkflows: (missionId: string) =>
    ['missions', missionId, 'workflows'] as const,
  schedules: (missionId: string) =>
    ['missions', missionId, 'schedules'] as const,
}

// ---- Global workflow templates ----

export function useWorkflowTemplates() {
  return useQuery({
    queryKey: workflowKeys.templates,
    queryFn: () =>
      api.get<{ workflows: WorkflowListItem[] }>('/workflows'),
    select: (data) => data.workflows,
  })
}

export function useWorkflowTemplate(name: string | undefined) {
  return useQuery({
    queryKey: workflowKeys.templateDetail(name!),
    queryFn: () => api.get<WorkflowDetail>(`/workflows/${name}`),
    enabled: !!name,
  })
}

// ---- Mission-scoped workflows ----

export function useMissionWorkflow(missionId: string | undefined, name: string | undefined) {
  return useQuery({
    queryKey: [...workflowKeys.missionWorkflows(missionId!), name] as const,
    queryFn: () =>
      api.get<WorkflowDetailFull>(`/missions/${missionId}/workflows/${name}`),
    enabled: !!missionId && !!name,
  })
}

export function useMissionWorkflowById(missionId: string | undefined, workflowId: string | undefined) {
  const { data: workflows } = useMissionWorkflows(missionId)
  const workflow = workflows?.find((w) => w.id === workflowId)
  return useMissionWorkflow(missionId, workflow?.name)
}

export function useSaveWorkflowGraph(missionId: string, workflowId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { canvas_state: CanvasState; edges_json?: WorkflowEdge[]; steps?: WorkflowStep[] }) =>
      api.put<{ id: string; canvas_state: CanvasState; edges_json: WorkflowEdge[]; steps: WorkflowStep[]; validation_warnings?: string[] }>(
        `/missions/${missionId}/workflows/${workflowId}/graph`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.missionWorkflows(missionId),
      })
    },
  })
}

export function useMissionWorkflows(missionId: string | undefined) {
  return useQuery({
    queryKey: workflowKeys.missionWorkflows(missionId!),
    queryFn: () =>
      api.get<{ workflows: MissionWorkflow[]; total: number }>(
        `/missions/${missionId}/workflows?enabled_only=false`,
      ),
    select: (data) => data.workflows,
    enabled: !!missionId,
  })
}

export function useCreateWorkflow(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.post<{ id: string; name: string }>(
        `/missions/${missionId}/workflows`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.missionWorkflows(missionId),
      })
    },
  })
}

export function useImportTemplate(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (templateName: string) =>
      api.post<{ id: string; name: string }>(
        `/missions/${missionId}/workflows/import?template_name=${encodeURIComponent(templateName)}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.missionWorkflows(missionId),
      })
    },
  })
}

// ---- Workflow runs (history) ----

export const workflowRunKeys = {
  list: (missionId: string, workflowName?: string) =>
    ['missions', missionId, 'workflow-runs', workflowName ?? ''] as const,
}

export function useWorkflowRuns(missionId: string | undefined, workflowName?: string) {
  return useQuery({
    queryKey: workflowRunKeys.list(missionId!, workflowName),
    queryFn: () => {
      const params = new URLSearchParams()
      if (workflowName) params.set('workflow_name', workflowName)
      params.set('limit', '50')
      const qs = params.toString()
      return api.get<{ runs: WorkflowRunRecord[]; total: number }>(
        `/missions/${missionId}/workflow-runs?${qs}`,
      )
    },
    select: (data) => data.runs,
    enabled: !!missionId,
    refetchInterval: (query) => {
      const runs = query.state.data?.runs
      if (runs?.some((r) => r.status === 'RUNNING' || r.status === 'PENDING' || r.status === 'AWAITING_INPUT'))
        return 5000
      return false
    },
  })
}

// ---- Run workflow ----

export function useRunWorkflow(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workflowName, contextOverrides }: { workflowName: string; contextOverrides?: Record<string, unknown> }) =>
      api.post<{
        run_id: string
        workflow_name: string
        status: string
        total_cost_usd: number
      }>(`/missions/${missionId}/workflows/${encodeURIComponent(workflowName)}/run`, {
        context_overrides: contextOverrides,
      }),
    onSuccess: () => {
      // Invalidate executions so the Runs tab picks up the new run
      qc.invalidateQueries({ queryKey: ['executions'] })
      qc.invalidateQueries({ queryKey: ['missions', missionId] })
      qc.invalidateQueries({ queryKey: ['missions', missionId, 'workflow-runs'] })
    },
  })
}

// ---- Delete workflow ----

export function useDeleteWorkflow(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (workflowId: string) =>
      api.del(`/missions/${missionId}/workflows/${workflowId}`),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.missionWorkflows(missionId),
      })
    },
  })
}

// ---- Schedules ----

export function useSchedules(missionId: string | undefined) {
  return useQuery({
    queryKey: workflowKeys.schedules(missionId!),
    queryFn: () =>
      api.get<{ schedules: WorkflowSchedule[]; total: number }>(
        `/missions/${missionId}/schedules?enabled_only=false`,
      ),
    select: (data) => data.schedules,
    enabled: !!missionId,
  })
}

export function useCreateSchedule(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: WorkflowScheduleCreateRequest) =>
      api.post<WorkflowSchedule>(`/missions/${missionId}/schedules`, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.schedules(missionId),
      })
    },
  })
}

export function useUpdateSchedule(missionId: string, scheduleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: WorkflowScheduleUpdateRequest) =>
      api.patch<WorkflowSchedule>(
        `/missions/${missionId}/schedules/${scheduleId}`,
        data,
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.schedules(missionId),
      })
    },
  })
}

export function useDeleteSchedule(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (scheduleId: string) =>
      api.del(`/missions/${missionId}/schedules/${scheduleId}`),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: workflowKeys.schedules(missionId),
      })
    },
  })
}

// ---- Human input ----

export function useRespondToHumanInput(missionId: string) {
  return useMutation({
    mutationFn: ({ requestId, response }: { requestId: string; response: string }) =>
      api.post<void>(
        `/missions/${missionId}/human-input/${requestId}/respond`,
        { response, responder_id: '' },
      ),
  })
}

// ---- Architect chat ----

export function useArchitectChat(missionId: string) {
  return useMutation({
    mutationFn: (message: string) =>
      api.post<ArchitectChatResponse>(
        `/missions/${missionId}/architect/chat?message=${encodeURIComponent(message)}`,
      ),
  })
}
