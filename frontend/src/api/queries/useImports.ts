import { useQuery } from '@tanstack/react-query'
import { apiFetch, apiUpload } from '../client'

interface ColumnMapping {
  source_column: string
  target_field: string | null
  sample_values: string[]
  confidence: 'high' | 'medium' | 'low'
  is_custom: boolean
  custom_display_name?: string
}

interface UploadResponse {
  job_id: string
  filename: string
  row_count: number
  columns: ColumnMapping[]
  warnings: string[]
  custom_field_defs: Array<{
    field_key: string
    display_name: string
    source_column: string
  }>
}

interface PreviewRow {
  row_number: number
  data: Record<string, string>
  status: 'new' | 'duplicate' | 'update'
  match_type?: string
  match_details?: string
}

interface PreviewResponse {
  total_rows: number
  new_contacts: number
  duplicates: number
  updates: number
  new_companies: number
  existing_companies: number
  preview_rows: PreviewRow[]
}

interface ImportResultItem {
  row_idx: number
  action: 'created' | 'skipped' | 'updated' | 'error'
  contact_name: string
  company_name: string
  details: string
  conflicts?: Array<{ field: string; existing: string; incoming: string }>
}

interface ImportResponse {
  job_id: string
  status: string
  tag_name: string
  counts: {
    contacts_created: number
    contacts_skipped: number
    contacts_updated: number
    companies_created: number
    companies_linked: number
    total_conflicts?: number
  }
}

interface ImportResultsResponse {
  total: number
  page: number
  per_page: number
  rows: ImportResultItem[]
}

interface ImportJob {
  id: string
  filename: string
  source: 'csv' | 'google'
  status: 'uploaded' | 'mapped' | 'previewed' | 'completed' | 'failed' | 'error'
  row_count: number
  created_at: string
  stats?: { created: number; skipped: number; updated: number; errors: number }
}

interface ImportListResponse {
  imports: ImportJob[]
}

interface ImportStatusResponse {
  status: string
  mapping: ColumnMapping[] | null
  upload_response: UploadResponse | null
  preview: PreviewResponse | null
}

// Google OAuth types
interface OAuthConnection {
  id: string
  provider: string
  provider_email: string
  email: string // alias for backwards compat
  scopes: string[]
  status: string
  connected_at: string
}

interface GoogleAuthUrlResponse {
  auth_url: string
}

interface GoogleFetchResponse {
  job_id: string
  contacts_count: number
  source: string
}

interface GmailScanResponse {
  job_id: string
  emails_scanned: number
  contacts_found: number
}

// Re-export types that components will need
export type {
  ColumnMapping,
  UploadResponse,
  PreviewRow,
  PreviewResponse,
  ImportResultItem,
  ImportResponse,
  ImportResultsResponse,
  ImportJob,
  ImportListResponse,
  ImportStatusResponse,
  OAuthConnection,
  GoogleAuthUrlResponse,
  GoogleFetchResponse,
  GmailScanResponse,
}

// TanStack Query hook — for past imports list
export function useImports() {
  return useQuery({
    queryKey: ['imports'],
    queryFn: () => apiFetch<ImportListResponse>('/imports'),
    staleTime: 30_000,
  })
}

// Direct API calls for wizard flow (not cached)
export function uploadFile(file: File, batchName: string, ownerId: string) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('batch_name', batchName)
  formData.append('owner_id', ownerId)
  return apiUpload<UploadResponse>('/imports/upload', formData)
}

export function submitPreview(jobId: string, mapping: ColumnMapping[]) {
  return apiFetch<PreviewResponse>(`/imports/${jobId}/preview`, {
    method: 'POST',
    body: { mapping },
  })
}

export function executeImport(jobId: string, dedupStrategy: string) {
  return apiFetch<ImportResponse>(`/imports/${jobId}/execute`, {
    method: 'POST',
    body: { dedup_strategy: dedupStrategy },
  })
}

export function remapWithAI(jobId: string) {
  return apiFetch<UploadResponse>(`/imports/${jobId}/remap`, {
    method: 'POST',
  })
}

export function getImportResults(jobId: string, filter: string, page: number) {
  return apiFetch<ImportResultsResponse>(`/imports/${jobId}/results`, {
    params: { filter, page: String(page) },
  })
}

export function getImportStatus(jobId: string) {
  return apiFetch<ImportStatusResponse>(`/imports/${jobId}/status`)
}

export function retryImport(jobId: string) {
  return apiFetch<{ job_id: string; status: string }>(`/imports/${jobId}/retry`, {
    method: 'POST',
  })
}

// Google OAuth
export function getOAuthConnections() {
  return apiFetch<OAuthConnection[]>('/oauth/connections')
}

export function getGoogleAuthUrl(returnUrl: string, scopes = 'contacts') {
  return apiFetch<GoogleAuthUrlResponse>('/oauth/google/auth-url', {
    params: { return_url: returnUrl, scopes },
  })
}

export function getGmailSendAuthUrl(returnUrl: string) {
  return apiFetch<GoogleAuthUrlResponse>('/oauth/google/auth-url', {
    params: { return_url: returnUrl, scopes: 'gmail_send' },
  })
}

export function deleteConnection(connectionId: string) {
  return apiFetch('/oauth/connections/' + connectionId, { method: 'DELETE' })
}

export function fetchGoogleContacts(connectionId: string) {
  return apiFetch<GoogleFetchResponse>('/gmail/contacts/fetch', {
    method: 'POST',
    body: { connection_id: connectionId },
  })
}

export function startGmailScan(opts: {
  connection_id: string
  date_range: string
  exclude_domains: string[]
}) {
  return apiFetch<GmailScanResponse>('/gmail/scan/start', {
    method: 'POST',
    body: opts,
  })
}

export function googlePreview(jobId: string) {
  return apiFetch<PreviewResponse>(`/gmail/contacts/${jobId}/preview`, {
    method: 'POST',
  })
}

export function googleExecute(jobId: string, dedupStrategy: string) {
  return apiFetch<ImportResponse>(`/gmail/contacts/${jobId}/execute`, {
    method: 'POST',
    body: { dedup_strategy: dedupStrategy },
  })
}
