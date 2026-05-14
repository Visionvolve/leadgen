import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export interface Campaign {
  id: string
  name: string
  status: string
  description: string | null
  owner_name: string | null
  total_contacts: number
  generated_count: number
  generation_cost: number
  template_config: TemplateStep[]
  generation_config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface SenderConfig {
  send_via?: 'resend' | 'gmail'
  from_email?: string
  from_name?: string
  reply_to?: string
  oauth_connection_id?: string
  linkedin_daily_connections?: number
  linkedin_daily_messages?: number
  linkedin_active_hours?: { start: string; end: string }
  linkedin_delay_range?: { min: number; max: number }
}

export interface CampaignDetail extends Campaign {
  owner_id: string | null
  generation_started_at: string | null
  generation_completed_at: string | null
  sender_config: SenderConfig
  contact_status_counts: Record<string, number>
}

export interface TemplateStep {
  step: number
  channel: string
  label: string
  enabled: boolean
  needs_pdf: boolean
  variant_count: number
}

export interface CampaignTemplate {
  id: string
  name: string
  description: string | null
  steps: TemplateStep[]
  default_config: Record<string, unknown>
  is_system: boolean
  created_at: string | null
}

interface CampaignsResponse {
  campaigns: Campaign[]
}

interface TemplatesResponse {
  templates: CampaignTemplate[]
}

export function useCampaigns() {
  return useQuery({
    queryKey: ['campaigns'],
    queryFn: () => apiFetch<CampaignsResponse>('/campaigns'),
  })
}

export function useCampaign(id: string | null) {
  return useQuery({
    queryKey: ['campaign', id],
    queryFn: () => apiFetch<CampaignDetail>(`/campaigns/${id}`),
    enabled: !!id,
  })
}

export function useCampaignTemplates() {
  return useQuery({
    queryKey: ['campaign-templates'],
    queryFn: () => apiFetch<TemplatesResponse>('/campaign-templates'),
  })
}

export function useCreateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; description?: string; owner_id?: string; template_id?: string }) =>
      apiFetch<{ id: string; name: string; status: string; created_at: string }>('/campaigns', {
        method: 'POST',
        body: data,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export interface AutoSetupResult {
  id: string
  name: string
  status: string
  total_contacts: number
  with_email: number
  with_linkedin: number
  strategy_prefilled: boolean
  generation_config: Record<string, unknown>
  template_config: TemplateStep[]
  created_at: string
}

export function useAutoSetupCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data?: { name?: string; description?: string; owner_id?: string; min_status?: string }) =>
      apiFetch<AutoSetupResult>('/campaigns/auto-setup', {
        method: 'POST',
        body: data || {},
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useUpdateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      apiFetch<{ ok: boolean }>(`/campaigns/${id}`, { method: 'PATCH', body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useDeleteCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ ok: boolean }>(`/campaigns/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useCloneCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ id: string; name: string; status: string }>(
        `/campaigns/${id}/clone`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

// ── Template Mutations ────────────────────────────────

export function useCreateCampaignTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; description?: string; steps: TemplateStep[]; default_config?: Record<string, unknown> }) =>
      apiFetch<CampaignTemplate>('/campaign-templates', { method: 'POST', body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-templates'] })
    },
  })
}

export function useSaveAsTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, name, description }: { campaignId: string; name: string; description?: string }) =>
      apiFetch<{ id: string; name: string }>(`/campaigns/${campaignId}/save-as-template`, {
        method: 'POST',
        body: { name, description },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-templates'] })
    },
  })
}

export function useUpdateCampaignTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string } }) =>
      apiFetch<{ ok: boolean }>(`/campaign-templates/${id}`, { method: 'PATCH', body: data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-templates'] })
    },
  })
}

export function useDeleteCampaignTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ ok: boolean }>(`/campaign-templates/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaign-templates'] })
    },
  })
}

// ── Set Template Body (fixed-template campaigns) ───────

export interface SetTemplateBodyRequest {
  subject: string
  body_html: string
  body_text?: string
  from_name?: string
  from_email: string
}

export interface SetTemplateBodyResponse {
  ok: boolean
  messages_created: number
  messages_updated: number
  campaign_contacts_updated: number
}

/**
 * Write a fixed HTML body + subject + sender to every Message on this
 * campaign. This is the canonical "generate messages for fixed-template
 * campaigns" operation — it does NOT call the LLM. Also persists the
 * editor values back to `Campaign.template_config[0].config` and
 * `Campaign.sender_config` so the editor can round-trip the values.
 */
export function useSetTemplateBody() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, data }: { campaignId: string; data: SetTemplateBodyRequest }) =>
      apiFetch<SetTemplateBodyResponse>(`/campaigns/${campaignId}/set-template-body`, {
        method: 'POST',
        body: data,
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['messages'] })
    },
  })
}

// ── Campaign Contacts ──────────────────────────────────

export interface CampaignContactItem {
  campaign_contact_id: string
  status: string
  enrichment_gaps: string[]
  generation_cost: number
  error: string | null
  added_at: string | null
  generated_at: string | null
  contact_id: string
  first_name: string | null
  last_name: string | null
  full_name: string
  job_title: string | null
  email_address: string | null
  linkedin_url: string | null
  contact_score: number | null
  icp_fit: string | null
  company_id: string | null
  company_name: string | null
  company_tier: string | null
  company_status: string | null
}

interface CampaignContactsResponse {
  contacts: CampaignContactItem[]
  total: number
}

export function useCampaignContacts(campaignId: string | null) {
  return useQuery({
    queryKey: ['campaign-contacts', campaignId],
    queryFn: () => apiFetch<CampaignContactsResponse>(`/campaigns/${campaignId}/contacts`),
    enabled: !!campaignId,
  })
}

export function useAddCampaignContacts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, contactIds, companyIds }: {
      campaignId: string
      contactIds?: string[]
      companyIds?: string[]
    }) =>
      apiFetch<{ added: number; skipped: number; total: number }>(
        `/campaigns/${campaignId}/contacts`,
        { method: 'POST', body: { contact_ids: contactIds, company_ids: companyIds } },
      ),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-contacts', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useRemoveCampaignContacts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ campaignId, contactIds }: { campaignId: string; contactIds: string[] }) =>
      apiFetch<{ removed: number }>(
        `/campaigns/${campaignId}/contacts`,
        { method: 'DELETE', body: { contact_ids: contactIds } },
      ),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['campaign-contacts', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign', vars.campaignId] })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

// ── Campaign Analytics ─────────────────────────────────

export interface CampaignAnalyticsData {
  messages: {
    total: number
    by_status: Record<string, number>
    by_channel: Record<string, number>
    by_step: Record<string, number>
  }
  sending: {
    email: { total: number; queued: number; sent: number; delivered: number; bounced: number; failed: number; unsubscribed?: number }
    linkedin: { total: number; queued: number; sent: number; delivered: number; failed: number }
  }
  engagement: {
    opened: number
    replied: number
    bounced: number
    clicked: number
    unsubscribed?: number
    delivered?: number
    total_opens: number
    total_clicks: number
    hard_bounces: number
    soft_bounces: number
    open_rate: number
    reply_rate: number
    bounce_rate: number
    click_rate: number
    unsubscribe_rate?: number
  }
  contacts: {
    total: number
    with_email: number
    with_linkedin: number
    both_channels: number
  }
  cost: {
    generation_usd: number
    email_sends: number
  }
  timeline: {
    created_at: string | null
    generation_started_at: string | null
    generation_completed_at: string | null
    first_send_at: string | null
    last_send_at: string | null
  }
}

export interface UseCampaignAnalyticsOptions {
  enabled?: boolean
  /** Override query stale time (ms). Defaults to 0 (always refetch on mount). */
  staleTime?: number
  /** Override refetch interval (ms). Pass `false` to disable polling. */
  refetchInterval?: number | false
}

export function useCampaignAnalytics(
  campaignId: string | null,
  optionsOrEnabled: boolean | UseCampaignAnalyticsOptions = true,
) {
  const opts: UseCampaignAnalyticsOptions =
    typeof optionsOrEnabled === 'boolean' ? { enabled: optionsOrEnabled } : optionsOrEnabled
  const { enabled = true, staleTime, refetchInterval = 10_000 } = opts
  return useQuery({
    queryKey: ['campaign-analytics', campaignId],
    queryFn: () => apiFetch<CampaignAnalyticsData>(`/campaigns/${campaignId}/analytics`),
    enabled: enabled && !!campaignId,
    refetchInterval,
    ...(staleTime !== undefined ? { staleTime } : {}),
  })
}

// ── Campaign Bounces (BL-1102) ─────────────────────────

export interface CampaignBounceRow {
  contact_id: string | null
  email: string
  first_name: string
  last_name: string
  company: string
  bounce_type: string
  bounced_at: string | null
  status: string
  error_message: string
}

export interface CampaignBouncesData {
  campaign_id: string
  campaign_name: string
  total: number
  bounces: CampaignBounceRow[]
}

/** List of undeliverable recipients for a campaign — used by the
 *  CampaignAnalytics surface for preview + count, and as a JSON peer
 *  to the CSV export endpoint. */
export function useCampaignBounces(
  campaignId: string | null,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['campaign-bounces', campaignId],
    queryFn: () => apiFetch<CampaignBouncesData>(`/campaigns/${campaignId}/bounces`),
    enabled: enabled && !!campaignId,
    staleTime: 30_000,
  })
}

// ── Campaign Reach (BL-1114) ───────────────────────────

export interface CampaignReachTotals {
  targeted: number
  sent: number
  delivered: number
  opened: number
  clicked: number
  bounced: number
  complained: number
  unsubscribed: number
}

export interface CampaignReachRates {
  send_rate: number
  delivery_rate: number
  open_rate: number
  click_rate: number
  bounce_rate: number
  complaint_rate: number
  unsubscribe_rate: number
}

export interface CampaignReachLanguageRow {
  language: string
  fallback: boolean
  sent: number
  delivered: number
  opened: number
  clicked: number
  bounced: number
  complained: number
  unsubscribed: number
}

export interface CampaignReachTimelineRow {
  date: string
  sent: number
  opened: number
  clicked: number
}

export interface CampaignReachData {
  campaign_id: string
  totals: CampaignReachTotals
  rates: CampaignReachRates
  by_language: CampaignReachLanguageRow[]
  timeline: CampaignReachTimelineRow[]
}

/** Per-campaign reach rollup — drives the Reach section on the
 *  CampaignDetailPage Analytics tab. */
export function useCampaignReach(
  campaignId: string | null,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ['campaign-reach', campaignId],
    queryFn: () => apiFetch<CampaignReachData>(`/campaigns/${campaignId}/reach`),
    enabled: enabled && !!campaignId,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

export interface CampaignReachSummaryRow {
  campaign_id: string
  name: string
  status: string | null
  totals: CampaignReachTotals
  rates: CampaignReachRates
}

export interface CampaignReachSummaryData {
  campaigns: CampaignReachSummaryRow[]
}

/** Tenant-wide reach rollup. Powers the optional "Campaigns reach
 *  overview" page. */
export function useCampaignReachSummary(enabled: boolean = true) {
  return useQuery({
    queryKey: ['campaign-reach-summary'],
    queryFn: () => apiFetch<CampaignReachSummaryData>(`/campaigns/reach/summary`),
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

// ── Campaign Analytics: Time-Series (BL-1037) ──────────

export type TimeSeriesRange = '24h' | '7d' | '30d' | 'all'
export type TimeSeriesBucket = 'hour' | 'day'

export interface TimeSeriesBucketPoint {
  bucket_start: string
  sent: number
  delivered: number
  opened: number
  clicked: number
  bounced: number
  unsubscribed: number
}

export interface CampaignTimeSeriesResponse {
  campaign_id: string
  range: TimeSeriesRange
  bucket: TimeSeriesBucket
  buckets: TimeSeriesBucketPoint[]
}

export function useCampaignAnalyticsTimeseries(
  campaignId: string | null,
  range: TimeSeriesRange = '7d',
  bucket?: TimeSeriesBucket,
) {
  // Auto-select bucket when caller doesn't override (mirrors backend default).
  const resolvedBucket: TimeSeriesBucket = bucket ?? (range === '24h' ? 'hour' : 'day')
  return useQuery({
    queryKey: ['campaign-analytics-timeseries', campaignId, range, resolvedBucket],
    queryFn: () =>
      apiFetch<CampaignTimeSeriesResponse>(
        `/campaigns/${campaignId}/analytics/timeseries`,
        { params: { range, bucket: resolvedBucket } },
      ),
    enabled: !!campaignId,
    staleTime: 10_000,
    refetchInterval: 10_000,
  })
}

// ── Campaign Recipients (per-recipient timeline drill-down — Phase 2) ──

export type RecipientTimelineMailEvent = {
  type: 'sent' | 'delivered' | 'opened' | 'clicked' | 'bounced' | 'unsubscribed'
  ts: string | null
}

export type RecipientTimelineMicrositeEvent = {
  type: 'microsite_activity'
  event: string
  ts: string | null
}

export type RecipientTimelineEvent = RecipientTimelineMailEvent | RecipientTimelineMicrositeEvent

export interface CampaignRecipient {
  campaign_contact_id: string
  contact_id: string | null
  email: string
  name: string
  microsite_partner_token: string | null
  timeline: RecipientTimelineEvent[]
}

export interface CampaignRecipientsResponse {
  recipients: CampaignRecipient[]
}

export function useCampaignRecipients(campaignId: string | null, enabled = true) {
  return useQuery({
    queryKey: ['campaign-recipients', campaignId],
    queryFn: () => apiFetch<CampaignRecipientsResponse>(`/campaigns/${campaignId}/recipients`),
    enabled: enabled && !!campaignId,
    refetchInterval: 15_000,
  })
}

// ── Send Emails ────────────────────────────────────────

export interface SendEmailsResponse {
  queued_count: number
  sender: { from_email?: string; from_name?: string }
}

export function useSendEmails() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (campaignId: string) =>
      apiFetch<SendEmailsResponse>(
        `/campaigns/${campaignId}/send-emails`,
        { method: 'POST', body: { confirm: true } },
      ),
    onSuccess: (_, campaignId) => {
      qc.invalidateQueries({ queryKey: ['campaign-analytics', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    },
  })
}

// ── Queue LinkedIn ─────────────────────────────────────

export interface QueueLinkedInResponse {
  queued_count: number
  by_owner: Record<string, number>
}

export function useQueueLinkedIn() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (campaignId: string) =>
      apiFetch<QueueLinkedInResponse>(
        `/campaigns/${campaignId}/queue-linkedin`,
        { method: 'POST' },
      ),
    onSuccess: (_, campaignId) => {
      qc.invalidateQueries({ queryKey: ['campaign-analytics', campaignId] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    },
  })
}
