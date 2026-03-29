import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface StepConfig {
  max_length?: number
  tone?: string
  language?: string
  custom_instructions?: string
  example_messages?: ExampleMessage[]
  asset_ids?: string[]
  asset_mode?: Record<string, 'attach' | 'reference'>
}

export interface ExampleMessage {
  body: string
  note?: string
}

export type StepCondition = 'always' | 'no_response' | 'opened_not_replied'
export type ExecutionStatus = 'pending' | 'active' | 'completed' | 'skipped'

export interface CampaignStep {
  id: string
  campaign_id: string
  position: number
  channel: string
  day_offset: number
  label: string
  config: StepConfig
  condition: StepCondition
  execution_status: ExecutionStatus
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  updated_at: string | null
}

interface StepsResponse {
  steps: CampaignStep[]
}

export function useCampaignSteps(campaignId: string | null) {
  return useQuery({
    queryKey: ['campaign-steps', campaignId],
    queryFn: () => apiFetch<StepsResponse>(`/campaigns/${campaignId}/steps`),
    enabled: !!campaignId,
  })
}

export function useAddCampaignStep() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      campaignId,
      data,
    }: {
      campaignId: string
      data: { channel?: string; day_offset?: number; label?: string; config?: StepConfig }
    }) =>
      apiFetch<CampaignStep>(`/campaigns/${campaignId}/steps`, {
        method: 'POST',
        body: data,
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

export function useUpdateCampaignStep() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      campaignId,
      stepId,
      data,
    }: {
      campaignId: string
      stepId: string
      data: { channel?: string; day_offset?: number; label?: string; config?: StepConfig }
    }) =>
      apiFetch<CampaignStep>(`/campaigns/${campaignId}/steps/${stepId}`, {
        method: 'PATCH',
        body: data,
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

export function useDeleteCampaignStep() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, stepId }: { campaignId: string; stepId: string }) =>
      apiFetch<{ ok: boolean }>(`/campaigns/${campaignId}/steps/${stepId}`, {
        method: 'DELETE',
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

export function useReorderCampaignSteps() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, order }: { campaignId: string; order: string[] }) =>
      apiFetch<StepsResponse>(`/campaigns/${campaignId}/steps/reorder`, {
        method: 'PUT',
        body: { order },
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

export function usePopulateFromTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, templateId }: { campaignId: string; templateId: string }) =>
      apiFetch<StepsResponse>(`/campaigns/${campaignId}/steps/from-template`, {
        method: 'POST',
        body: { template_id: templateId },
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

// ── AI Step Designer ──────────────────────────────────────

export interface AiDesignProposedStep {
  channel: string
  day_offset: number
  label: string
  config: StepConfig
}

export interface AiDesignResponse {
  steps: AiDesignProposedStep[]
  reasoning: string
}

export function useAiDesignSteps() {
  return useMutation({
    mutationFn: ({
      campaignId,
      goal,
      channel_preference,
      num_steps,
    }: {
      campaignId: string
      goal: string
      channel_preference?: string
      num_steps?: number
    }) =>
      apiFetch<AiDesignResponse>(`/campaigns/${campaignId}/steps/ai-design`, {
        method: 'POST',
        body: { goal, channel_preference, num_steps },
      }),
  })
}

// ── Feedback Summary ─────────────────────────────────────

export interface StepFeedbackStats {
  total: number
  approved: number
  approval_rate: number
}

export interface FeedbackSummary {
  total: number
  by_action: Record<string, number>
  top_edit_reasons: [string, number][]
  per_step: Record<string, StepFeedbackStats>
}

export function useFeedbackSummary(campaignId: string | null) {
  return useQuery({
    queryKey: ['feedback-summary', campaignId],
    queryFn: () => apiFetch<FeedbackSummary>(`/campaigns/${campaignId}/feedback-summary`),
    enabled: !!campaignId,
    staleTime: 30_000,
  })
}

export function useConfirmAiDesign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      campaignId,
      steps,
    }: {
      campaignId: string
      steps: AiDesignProposedStep[]
    }) =>
      apiFetch<StepsResponse>(`/campaigns/${campaignId}/steps/ai-design/confirm`, {
        method: 'POST',
        body: { steps },
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

// ── Sequence API ─────────────────────────────────────────

interface SequenceResponse {
  steps: CampaignStep[]
}

export function useSequence(campaignId: string | null) {
  return useQuery({
    queryKey: ['campaign-sequence', campaignId],
    queryFn: () => apiFetch<SequenceResponse>(`/campaigns/${campaignId}/sequence`),
    enabled: !!campaignId,
  })
}

export function useUpdateSequenceStep() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      campaignId,
      stepNumber,
      data,
    }: {
      campaignId: string
      stepNumber: number
      data: { condition?: StepCondition; execution_status?: ExecutionStatus; day_offset?: number }
    }) =>
      apiFetch<CampaignStep>(`/campaigns/${campaignId}/sequence/${stepNumber}`, {
        method: 'PATCH',
        body: data,
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-sequence', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}

export function useReplaceSequence() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      campaignId,
      steps,
    }: {
      campaignId: string
      steps: Array<{ channel: string; day_offset: number; label: string; condition?: StepCondition; config?: StepConfig }>
    }) =>
      apiFetch<SequenceResponse>(`/campaigns/${campaignId}/sequence`, {
        method: 'PUT',
        body: { steps },
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-sequence', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign-steps', vars.campaignId] })
    },
  })
}
