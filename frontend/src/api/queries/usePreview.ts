import { useMutation } from '@tanstack/react-query'
import { apiFetch } from '../client'

// ── Preview generation ──────────────────────────────────

export interface PreviewResponse {
  subject: string | null
  body: string
  recommended_products?: unknown
  segment?: string | null
}

export interface PreviewRequest {
  campaignId: string
  contactId: string
  stepPosition: number
}

/**
 * Generate a one-off preview of a campaign message for a contact.
 * Calls Anthropic on the backend; expect ~1-3s latency.
 * Does NOT persist a message — purely a preview.
 */
export function useGeneratePreview() {
  return useMutation({
    mutationFn: ({ campaignId, contactId, stepPosition }: PreviewRequest) =>
      apiFetch<PreviewResponse>(
        `/campaigns/${campaignId}/generate-preview`,
        {
          method: 'POST',
          body: { contact_id: contactId, step_position: stepPosition },
        },
      ),
  })
}

// ── Send test email ─────────────────────────────────────

export interface SendTestResponse {
  ok: boolean
  sent_to: string
  message_id: string
  resend_id?: string
  attachments_included?: number
}

export interface SendTestRequest {
  campaignId: string
  messageId: string
}

/**
 * Send a test email of an existing message to the currently-authenticated user.
 * Subject is prefixed with [TEST]; recipient is the logged-in user, never the
 * contact. Logs as kind='preview' so it is excluded from analytics.
 */
export function useSendTestEmail() {
  return useMutation({
    mutationFn: ({ campaignId, messageId }: SendTestRequest) =>
      apiFetch<SendTestResponse>(
        `/campaigns/${campaignId}/send-test`,
        {
          method: 'POST',
          body: { message_id: messageId },
        },
      ),
  })
}
