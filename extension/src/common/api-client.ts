import type {
  ExtensionStatus,
  Lead,
  ActivityEvent,
  UploadLeadsResponse,
  UploadActivitiesResponse,
} from './types';
import { config } from './config';
import { getAuthState, isTokenExpired, refreshToken } from './auth';

/** Custom error with HTTP status code. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Get a valid (non-expired) access token, refreshing if needed. */
async function getValidToken(): Promise<string> {
  const state = await getAuthState();
  if (!state) throw new ApiError(401, 'Not authenticated');

  if (isTokenExpired(state.access_token)) {
    return refreshToken();
  }
  return state.access_token;
}

/**
 * Authenticated fetch wrapper.
 * Automatically injects Bearer token and X-Namespace header.
 * Retries once on 401 after refreshing the token.
 */
async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = await getValidToken();
  const state = await getAuthState();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    'X-Namespace': state?.namespace || '',
  };

  const fetchOpts: RequestInit = {
    method: options.method || 'GET',
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  };

  const resp = await fetch(`${config.apiBase}${path}`, fetchOpts);

  if (resp.status === 401) {
    // One retry after token refresh
    const newToken = await refreshToken();
    const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
    const retry = await fetch(`${config.apiBase}${path}`, {
      ...fetchOpts,
      headers: retryHeaders,
    });
    if (!retry.ok) {
      throw new ApiError(retry.status, `API error: ${retry.statusText}`);
    }
    return retry.json() as Promise<T>;
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText })) as { error?: string };
    throw new ApiError(resp.status, err.error || `API error: ${resp.status}`);
  }

  return resp.json() as Promise<T>;
}

/** Upload extracted leads to the API. */
export async function uploadLeads(
  leads: Lead[],
  source: string,
  tag: string,
): Promise<UploadLeadsResponse> {
  return apiFetch<UploadLeadsResponse>('/api/extension/leads', {
    method: 'POST',
    body: { leads, source, tag },
  });
}

/** Upload activity events to the API. */
export async function uploadActivities(
  events: ActivityEvent[],
): Promise<UploadActivitiesResponse> {
  return apiFetch<UploadActivitiesResponse>('/api/extension/activities', {
    method: 'POST',
    body: { events },
  });
}

/** Get extension connection status from the API. */
export async function getStatus(): Promise<ExtensionStatus> {
  return apiFetch<ExtensionStatus>('/api/extension/status');
}

/** Fetch existing tags for autocomplete suggestions. */
export async function fetchTags(): Promise<{ id: string; name: string }[]> {
  const data = await apiFetch<{ tags: { id: string; name: string }[] }>('/api/tags');
  return data.tags || [];
}

/** Report detected LinkedIn account identity to the API. */
export interface LinkedInIdentityResponse {
  id: string;
  linkedin_name: string;
  linkedin_url: string;
  is_new: boolean;
}

export async function reportLinkedInIdentity(
  linkedinName: string,
  linkedinUrl: string,
): Promise<LinkedInIdentityResponse> {
  return apiFetch<LinkedInIdentityResponse>('/api/extension/linkedin-identity', {
    method: 'POST',
    body: { linkedin_name: linkedinName, linkedin_url: linkedinUrl },
  });
}

/** Validate a LinkedIn profile against CRM contacts. */
export interface ValidationResult {
  match: boolean;
  contact?: Record<string, unknown>;
  company?: Record<string, unknown>;
  enrichment_quality?: Record<string, unknown>;
  mismatches?: Array<{ field: string; linkedin_value: string; crm_value: string }>;
}

export async function validateContact(params: {
  linkedin_url?: string;
  name?: string;
  company?: string;
}): Promise<ValidationResult> {
  const query = new URLSearchParams();
  if (params.linkedin_url) query.set('linkedin_url', params.linkedin_url);
  if (params.name) query.set('name', params.name);
  if (params.company) query.set('company', params.company);
  return apiFetch<ValidationResult>(`/api/extension/validate-contact?${query.toString()}`);
}

/** Validate a LinkedIn company page against CRM companies. */
export async function validateCompany(params: {
  linkedin_url?: string;
  name?: string;
}): Promise<ValidationResult> {
  const query = new URLSearchParams();
  if (params.linkedin_url) query.set('linkedin_url', params.linkedin_url);
  if (params.name) query.set('name', params.name);
  return apiFetch<ValidationResult>(`/api/extension/validate-company?${query.toString()}`);
}

/** Update a contact in the CRM. */
export async function updateContact(
  contactId: string,
  fields: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/contacts/${contactId}`, {
    method: 'PATCH',
    body: fields,
  });
}

/** Update a company in the CRM. */
export async function updateCompanyRecord(
  companyId: string,
  fields: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/companies/${companyId}`, {
    method: 'PATCH',
    body: fields,
  });
}
