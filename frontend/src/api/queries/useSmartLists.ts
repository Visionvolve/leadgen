/**
 * React Query hooks for smart lists.
 *
 * Smart lists are saved audience filters over contacts or companies. See
 * api/routes/smart_list_routes.py and migration 070 (v25 Phase 10).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export type SmartListTarget = 'contact' | 'company'

export interface SmartListFilters {
  [key: string]: string[]
}

export interface SmartList {
  id: string
  tenant_id: string
  name: string
  description: string | null
  target: SmartListTarget
  filters: SmartListFilters
  created_by: string | null
  created_at: string | null
  updated_at: string | null
  last_run_at: string | null
  last_run_count: number | null
}

export interface SmartListCompanyRow {
  id: string
  name: string
  domain: string | null
  status: string | null
  tier: string | null
  organization_type: string | null
  geo_region: string | null
  engagement_status: string | null
  hq_country: string | null
  industry: string | null
}

export interface SmartListContactRow {
  id: string
  first_name: string
  last_name: string
  full_name: string
  email_address: string | null
  job_title: string | null
  company_id: string | null
  company_name: string | null
  seniority_level: string | null
  department: string | null
  language: string | null
  organization_type: string | null
}

export interface SmartListRunResult {
  total: number
  page: number
  page_size: number
  pages: number
  companies?: SmartListCompanyRow[]
  contacts?: SmartListContactRow[]
  smart_list?: SmartList
}

interface ListResponse {
  smart_lists: SmartList[]
}

export function useSmartLists() {
  return useQuery({
    queryKey: ['smart-lists'],
    queryFn: () => apiFetch<ListResponse>('/smart-lists'),
  })
}

export function useSmartList(id: string | null) {
  return useQuery({
    queryKey: ['smart-lists', id],
    queryFn: () => apiFetch<SmartList>(`/smart-lists/${id}`),
    enabled: Boolean(id),
  })
}

export interface CreateSmartListInput {
  name: string
  description?: string
  target: SmartListTarget
  filters: SmartListFilters
}

export function useCreateSmartList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSmartListInput) =>
      apiFetch<SmartList>('/smart-lists', { method: 'POST', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['smart-lists'] })
    },
  })
}

export function useUpdateSmartList(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<CreateSmartListInput>) =>
      apiFetch<SmartList>(`/smart-lists/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['smart-lists'] })
    },
  })
}

export function useDeleteSmartList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ ok: true }>(`/smart-lists/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['smart-lists'] })
    },
  })
}

export function useRunSmartList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      page = 1,
      page_size = 25,
    }: {
      id: string
      page?: number
      page_size?: number
    }) =>
      apiFetch<SmartListRunResult>(`/smart-lists/${id}/run`, {
        method: 'POST',
        params: { page: String(page), page_size: String(page_size) },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['smart-lists'] })
    },
  })
}

export function usePreviewSmartList() {
  return useMutation({
    mutationFn: (body: {
      target: SmartListTarget
      filters: SmartListFilters
      page?: number
      page_size?: number
    }) =>
      apiFetch<SmartListRunResult>('/smart-lists/preview', {
        method: 'POST',
        body,
      }),
  })
}
