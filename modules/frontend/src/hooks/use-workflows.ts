import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  WorkflowListItem,
  WorkflowDetail,
  MissionWorkflow,
  WorkflowSchedule,
  WorkflowScheduleCreateRequest,
  WorkflowScheduleUpdateRequest,
  ArchitectChatResponse,
} from '@/types'

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
      api.get<{
        id: string
        name: string
        description: string
        version: number
        enabled: boolean
        trigger_type: string
        step_count: number
        designed_by: string
        locked_at: string | null
        steps: import('@/types').WorkflowStep[]
        objective: Record<string, unknown>
        budget_config: Record<string, unknown>
        trigger_config: Record<string, unknown>
        context: Record<string, unknown>
      }>(`/missions/${missionId}/workflows/${name}`),
    enabled: !!missionId && !!name,
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

// ---- Architect chat ----

export function useArchitectChat(missionId: string) {
  return useMutation({
    mutationFn: (message: string) =>
      api.post<ArchitectChatResponse>(
        `/missions/${missionId}/architect/chat?message=${encodeURIComponent(message)}`,
      ),
  })
}
