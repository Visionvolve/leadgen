import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

interface BulkTagRequest {
  entity_type: 'contact' | 'company'
  ids?: string[]
  filters?: Record<string, string>
  tag_ids: string[]
}

interface BulkTagResponse {
  affected: number
  new_assignments: number
  already_tagged: number
  errors: string[]
}

interface BulkRemoveTagResponse {
  affected: number
  removed: number
  not_found: number
  errors: string[]
}

interface BulkAssignCampaignRequest {
  entity_type: 'contact'
  ids?: string[]
  filters?: Record<string, string>
  campaign_id: string
}

interface BulkAssignCampaignResponse {
  affected: number
  errors: string[]
}

interface MatchingCountResponse {
  count: number
}

export function useBulkAddTags() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BulkTagRequest) =>
      apiFetch<BulkTagResponse>('/bulk/add-tags', { method: 'POST', body: data }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [vars.entity_type === 'contact' ? 'contacts' : 'companies'] })
    },
  })
}

export function useBulkRemoveTags() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BulkTagRequest) =>
      apiFetch<BulkRemoveTagResponse>('/bulk/remove-tags', { method: 'POST', body: data }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [vars.entity_type === 'contact' ? 'contacts' : 'companies'] })
    },
  })
}

export function useBulkAssignCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BulkAssignCampaignRequest) =>
      apiFetch<BulkAssignCampaignResponse>('/bulk/assign-campaign', { method: 'POST', body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['campaign-contacts'] })
    },
  })
}

interface BulkDeleteRequest {
  entity_type: 'contact' | 'company'
  ids?: string[]
  filters?: Record<string, string>
}

interface BulkDeleteResponse {
  deleted: number
}

export function useBulkDelete() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BulkDeleteRequest) =>
      apiFetch<BulkDeleteResponse>('/bulk/delete', { method: 'POST', body: data }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: [vars.entity_type === 'contact' ? 'contacts' : 'companies'] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['campaign-contacts'] })
    },
  })
}

export function useContactsMatchingCount() {
  return useMutation({
    mutationFn: (filters: Record<string, string>) =>
      apiFetch<MatchingCountResponse>('/contacts/matching-count', { method: 'POST', body: { filters } }),
  })
}

export function useCompaniesMatchingCount() {
  return useMutation({
    mutationFn: (filters: Record<string, string>) =>
      apiFetch<MatchingCountResponse>('/companies/matching-count', { method: 'POST', body: { filters } }),
  })
}
