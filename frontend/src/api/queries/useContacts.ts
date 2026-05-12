import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface ContactListItem {
  id: string
  full_name: string
  first_name: string
  last_name: string
  job_title: string | null
  company_id: string | null
  company_name: string | null
  email_address: string | null
  contact_score: number | null
  score: number | null
  icp_fit: string | null
  message_status: string | null
  owner_name: string | null
  tag_name: string | null
  tag_names?: string[]
  seniority_level: string | null
  department: string | null
  location_city: string | null
  location_country: string | null
  linkedin_url: string | null
  phone_number: string | null
  ai_champion_score: number | null
  authority_score: number | null
  linkedin_activity_level: string | null
  language: string | null
  contact_source: string | null
  address_style: string | null
  // Enrichment summary fields (BL-180)
  company_tier: string | null
  company_status: string | null
  enrichment_status: string | null
  last_enriched_at: string | null
}

interface ContactsPage {
  contacts: ContactListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface ContactMessage {
  id: string
  channel: string | null
  sequence_step: number | null
  variant: string | null
  subject: string | null
  status: string | null
  tone: string | null
}

export interface ContactEnrichment {
  person_summary: string | null
  linkedin_profile_summary: string | null
  relationship_synthesis: string | null
  ai_champion: boolean | null
  ai_champion_score: number | null
  authority_score: number | null
  career_trajectory: string | null
  previous_companies: Array<Record<string, unknown>> | null
  speaking_engagements: string | null
  publications: string | null
  twitter_handle: string | null
  github_username: string | null
  enriched_at: string | null
  enrichment_cost_usd: number | null
  // New fields
  education: string | null
  certifications: string | null
  expertise_areas: string | null
  budget_signals: string | null
  buying_signals: string | null
  pain_indicators: string | null
  technology_interests: string | null
  personalization_angle: string | null
  connection_points: string | unknown[] | null
  conversation_starters: string | null
  objection_prediction: string | null
  raw_response: Record<string, unknown> | null
}

export interface StageCompletion {
  stage: string
  status: string
  completed_at: string | null
  cost_usd: number | null
  error: string | null
}

export interface EmailActivity {
  campaign_name: string | null
  subject: string | null
  status: string | null
  sent_at: string | null
  delivered_at: string | null
  opened_at: string | null
  open_count: number
  clicked_at: string | null
  click_count: number
  bounced_at: string | null
}

export interface ContactDetail {
  id: string
  first_name: string
  last_name: string
  full_name: string
  job_title: string | null
  email_address: string | null
  linkedin_url: string | null
  phone_number: string | null
  profile_photo_url: string | null
  seniority_level: string | null
  department: string | null
  location_city: string | null
  location_country: string | null
  icp_fit: string | null
  relationship_status: string | null
  contact_source: string | null
  language: string | null
  address_style: string | null
  salutation: string | null
  salutation_overridden: boolean
  message_status: string | null
  ai_champion: string | null
  ai_champion_score: number | null
  authority_score: number | null
  contact_score: number | null
  enrichment_cost_usd: number | null
  processed_enrich: boolean | null
  email_lookup: string | null
  duplicity_check: string | null
  duplicity_conflict: string | null
  duplicity_detail: string | null
  notes: string | null
  error: string | null
  custom_fields: Record<string, string>
  created_at: string | null
  updated_at: string | null
  last_enriched_at: string | null
  employment_status: string | null
  employment_verified_at: string | null
  company: {
    id: string
    name: string
    domain: string | null
    status: string | null
    tier: string | null
  } | null
  owner_name: string | null
  tag_name: string | null
  batch_name?: string | null
  enrichment: ContactEnrichment | null
  stage_completions: StageCompletion[]
  messages: ContactMessage[]
  email_activity: EmailActivity[]
}

export interface ContactFilters {
  search?: string
  tag_name?: string
  owner_name?: string
  icp_fit?: string
  message_status?: string
  sort?: string
  sort_dir?: string
  // Multi-value ICP filters (comma-separated values)
  company_tier?: string
  company_tier_exclude?: string
  industry?: string
  industry_exclude?: string
  company_size?: string
  company_size_exclude?: string
  geo_region?: string
  geo_region_exclude?: string
  revenue_range?: string
  revenue_range_exclude?: string
  seniority_level?: string
  seniority_level_exclude?: string
  department?: string
  department_exclude?: string
  job_titles?: string
  job_titles_exclude?: string
  linkedin_activity?: string
  linkedin_activity_exclude?: string
  [key: string]: string | undefined
}

const PAGE_SIZE = 50

export function useContacts(filters: ContactFilters) {
  return useInfiniteQuery({
    queryKey: ['contacts', filters],
    queryFn: ({ pageParam = 1 }) => {
      const params: Record<string, string> = {
        page: String(pageParam),
        page_size: String(PAGE_SIZE),
      }
      // Pass through all non-empty filter values
      for (const [key, value] of Object.entries(filters)) {
        if (value) params[key] = value
      }
      return apiFetch<ContactsPage>('/contacts', { params })
    },
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
    initialPageParam: 1,
  })
}

export function useContact(id: string | null) {
  return useQuery({
    queryKey: ['contact', id],
    queryFn: () => apiFetch<ContactDetail>(`/contacts/${id}`),
    enabled: !!id,
  })
}

export function useUpdateContact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      data,
      params,
    }: {
      id: string
      data: Record<string, unknown>
      params?: Record<string, string>
    }) => apiFetch(`/contacts/${id}`, { method: 'PATCH', body: data, params }),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['contact', id] })
      qc.invalidateQueries({ queryKey: ['contacts'] })
    },
  })
}

export function useCreateContact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      first_name: string
      last_name: string
      email_address?: string
      job_title?: string
      company_id?: string
      seniority_level?: string
      department?: string
      phone_number?: string
      notes?: string
    }) => apiFetch<ContactDetail>('/contacts', { method: 'POST', body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] })
    },
  })
}

export function useDeleteContact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ deleted: boolean }>(`/contacts/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] })
    },
  })
}
