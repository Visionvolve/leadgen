/**
 * Ref-token hooks — per-contact unique catalog tracking links (BL-1104).
 *
 * Used by the Contact-detail "Catalog tracking links" section to issue
 * tokens (with/without prices) and to render the visit-count table.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '../client'

export type RefTokenVariant = 'with_prices' | 'without_prices'

export interface RefTokenIssuedResponse {
  token: string
  url: string
  variant: RefTokenVariant
  expires_at: string | null
  reused: boolean
}

export interface RefTokenRow {
  token: string
  tenant_id: string
  contact_id: string
  variant: RefTokenVariant
  created_at: string | null
  created_by: string | null
  expires_at: string | null
  notes: string | null
  visit_count: number
  first_visited_at: string | null
  last_visited_at: string | null
  url: string
  is_expired: boolean
}

export interface RefTokensList {
  tokens: RefTokenRow[]
}

export function useContactRefTokens(contactId: string | null) {
  return useQuery({
    queryKey: ['ref-tokens', contactId],
    queryFn: () =>
      apiFetch<RefTokensList>(`/contacts/${contactId}/ref-tokens`),
    enabled: !!contactId,
  })
}

export function useIssueRefToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      contactId,
      variant,
      expires_in_days,
      notes,
    }: {
      contactId: string
      variant: RefTokenVariant
      expires_in_days?: number
      notes?: string
    }) =>
      apiFetch<RefTokenIssuedResponse>(`/contacts/${contactId}/ref-token`, {
        method: 'POST',
        body: { variant, expires_in_days, notes },
      }),
    onSuccess: (_data, { contactId }) => {
      qc.invalidateQueries({ queryKey: ['ref-tokens', contactId] })
    },
  })
}
