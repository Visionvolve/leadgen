import { useEffect, useMemo, useRef, useState } from 'react'
import { useGeneratePreview, useSendTestEmail } from '../../api/queries/usePreview'
import { useCampaignContacts, type CampaignContactItem } from '../../api/queries/useCampaigns'
import { useMessages, type Message } from '../../api/queries/useMessages'
import { useAuth } from '../../hooks/useAuth'
import { ApiError } from '../../api/client'

interface PreviewModalProps {
  open: boolean
  onClose: () => void
  campaignId: string
  /** Pre-select this contact when opened (per-row preview). */
  initialContactId?: string | null
  /** Which sequence step to render. Defaults to 1. */
  stepPosition?: number
}

const MAX_DEFAULT_CONTACTS = 5

/**
 * Modal that previews a campaign message rendered for a chosen contact.
 * Lets the user flip between contacts (top-5 alphabetical by default),
 * and fire a Send-Test email of any existing draft/approved message
 * to the currently authenticated user.
 */
export function PreviewModal({
  open,
  onClose,
  campaignId,
  initialContactId,
  stepPosition = 1,
}: PreviewModalProps) {
  const { user } = useAuth()
  const overlayRef = useRef<HTMLDivElement>(null)
  const iframeRef = useRef<HTMLIFrameElement>(null)

  const previewMutation = useGeneratePreview()
  const sendTestMutation = useSendTestEmail()

  // Load campaign contacts to build the picker
  const { data: contactsData, isLoading: contactsLoading } =
    useCampaignContacts(open ? campaignId : null)

  // Load all messages for this campaign so we can match per-contact for Send-Test
  const { data: messagesData, refetch: refetchMessages } = useMessages({ campaign_id: campaignId })
  useEffect(() => {
    if (open) {
      refetchMessages()
    }
  }, [open, refetchMessages])

  // Top-N alphabetical contacts (the picker default set)
  const pickerOptions = useMemo<CampaignContactItem[]>(() => {
    const all = contactsData?.contacts ?? []
    const sorted = [...all].sort((a, b) =>
      (a.full_name || '').localeCompare(b.full_name || ''),
    )
    const top = sorted.slice(0, MAX_DEFAULT_CONTACTS)
    // Make sure the pre-selected contact is always in the picker even if
    // it falls outside the top-N.
    if (initialContactId) {
      const present = top.some((c) => c.contact_id === initialContactId)
      if (!present) {
        const pinned = all.find((c) => c.contact_id === initialContactId)
        if (pinned) return [pinned, ...top]
      }
    }
    return top
  }, [contactsData, initialContactId])

  const [selectedContactId, setSelectedContactId] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [sendOk, setSendOk] = useState<{ to: string } | null>(null)

  // Reset state when modal opens / closes
  useEffect(() => {
    if (!open) {
      setSelectedContactId(null)
      setSendError(null)
      setSendOk(null)
      previewMutation.reset()
      sendTestMutation.reset()
      return
    }
    // On open, pick the initial contact or fall back to first picker option
    if (initialContactId) {
      setSelectedContactId(initialContactId)
    } else if (pickerOptions.length > 0 && pickerOptions[0]) {
      setSelectedContactId(pickerOptions[0].contact_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialContactId, pickerOptions.length])

  // Close on Escape + lock body scroll
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handler)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  // Fetch the preview whenever the selected contact changes
  useEffect(() => {
    if (!open || !selectedContactId) return
    setSendError(null)
    setSendOk(null)
    previewMutation.mutate({
      campaignId,
      contactId: selectedContactId,
      stepPosition,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selectedContactId, campaignId, stepPosition])

  // Build the srcdoc for the rendered iframe (atomic, paints reliably).
  const previewSrcdoc = useMemo(() => {
    const body = previewMutation.data?.body
    if (!body) return ''
    return `<!doctype html><html><head><meta charset="utf-8"><style>
          body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                 font-size: 14px; color: #222; padding: 16px; line-height: 1.55; margin: 0;
                 background: #ffffff; }
          a { color: #2563eb; }
          pre, code { white-space: pre-wrap; word-break: break-word; }
          img { max-width: 100%; }
          table { max-width: 100%; }
        </style></head><body>${escapeForIframe(body)}</body></html>`
  }, [previewMutation.data])

  // Find an existing message for the selected contact (for Send-Test)
  const messageForSelected: Message | null = useMemo(() => {
    if (!selectedContactId || !messagesData?.messages) return null
    // Prefer variant A; fall back to the first one
    const all = messagesData.messages.filter(
      (m) => m.contact.id === selectedContactId,
    )
    if (all.length === 0) return null
    const variantA = all.find((m) => (m.variant || '').toUpperCase() === 'A')
    return variantA ?? all[0] ?? null
  }, [selectedContactId, messagesData])

  const handleSendTest = async () => {
    if (!messageForSelected) return
    setSendError(null)
    setSendOk(null)
    try {
      const res = await sendTestMutation.mutateAsync({
        campaignId,
        messageId: messageForSelected.id,
      })
      setSendOk({ to: res.sent_to })
    } catch (err) {
      if (err instanceof ApiError) {
        setSendError(err.message || `Request failed (${err.status})`)
      } else {
        setSendError('Failed to send test email')
      }
    }
  }

  if (!open) return null

  const selectedContact = pickerOptions.find(
    (c) => c.contact_id === selectedContactId,
  )
  const selectedFullName = selectedContact?.full_name || ''
  const selectedEmail = selectedContact?.email_address || ''

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 backdrop-blur-sm overflow-y-auto py-8"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Message preview"
    >
      <div className="relative w-full max-w-3xl bg-surface rounded-lg border border-border-solid shadow-2xl shadow-black/40 mx-4 my-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-solid">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold font-title text-text truncate">
              Preview for {selectedFullName || '…'}
            </h2>
            {selectedEmail && (
              <div className="text-xs text-text-muted truncate mt-0.5">
                {selectedEmail}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-4 flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-md text-text-muted hover:text-text hover:bg-surface-alt transition-colors"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Contact picker */}
          <div className="flex items-center gap-3 flex-wrap">
            <label
              htmlFor="preview-contact-picker"
              className="text-xs font-medium text-text-muted shrink-0"
            >
              Render for:
            </label>
            <select
              id="preview-contact-picker"
              value={selectedContactId ?? ''}
              onChange={(e) => setSelectedContactId(e.target.value || null)}
              disabled={contactsLoading || pickerOptions.length === 0}
              className="flex-1 min-w-[200px] px-2 py-1.5 text-xs rounded border border-border bg-surface text-text focus:outline-none focus:border-accent disabled:opacity-50"
            >
              {pickerOptions.length === 0 && (
                <option value="">
                  {contactsLoading ? 'Loading contacts…' : 'No contacts in this campaign'}
                </option>
              )}
              {pickerOptions.map((c) => (
                <option key={c.contact_id} value={c.contact_id}>
                  {c.full_name}
                  {c.job_title ? ` — ${c.job_title}` : ''}
                  {c.company_name ? ` (${c.company_name})` : ''}
                </option>
              ))}
            </select>
            {contactsData && contactsData.total > MAX_DEFAULT_CONTACTS && (
              <span className="text-[10px] text-text-dim">
                Showing first {Math.min(MAX_DEFAULT_CONTACTS, pickerOptions.length)} of {contactsData.total}
              </span>
            )}
          </div>

          {/* Subject */}
          <div>
            <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">
              Subject
            </div>
            <div
              data-testid="preview-subject"
              className="px-3 py-2 text-sm rounded border border-border bg-surface-alt/30 text-text break-words min-h-[2.25rem]"
            >
              {previewMutation.isPending
                ? <span className="inline-block w-2/3 h-3 bg-border-solid/40 rounded animate-pulse" />
                : previewMutation.data?.subject || <span className="text-text-dim italic">(no subject)</span>}
            </div>
          </div>

          {/* Iframe preview */}
          <div>
            <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">
              Rendered body
            </div>
            <div className="relative rounded border border-border bg-white overflow-hidden">
              {previewMutation.isPending && (
                <div
                  data-testid="preview-skeleton"
                  className="absolute inset-0 flex items-center justify-center bg-surface-alt/80 z-10"
                >
                  <div className="space-y-2 w-3/4">
                    <div className="h-3 w-full bg-border-solid/40 rounded animate-pulse" />
                    <div className="h-3 w-5/6 bg-border-solid/40 rounded animate-pulse" />
                    <div className="h-3 w-4/6 bg-border-solid/40 rounded animate-pulse" />
                    <div className="h-3 w-2/3 bg-border-solid/40 rounded animate-pulse" />
                  </div>
                </div>
              )}
              {previewMutation.isError && !previewMutation.isPending && (
                <div className="p-4 text-xs text-error">
                  {previewMutation.error instanceof Error
                    ? previewMutation.error.message
                    : 'Preview failed'}
                </div>
              )}
              <iframe
                ref={iframeRef}
                data-testid="preview-iframe"
                title="Rendered email preview"
                // allow-same-origin lets the CSS inside srcdoc apply; we
                // do not add allow-scripts so JS is still blocked.
                sandbox="allow-same-origin"
                srcDoc={previewSrcdoc}
                className="w-full bg-white"
                style={{ minHeight: 320, height: 360 }}
              />
            </div>
          </div>

          {/* Send-test feedback */}
          {sendOk && (
            <div
              data-testid="send-test-success"
              className="text-xs px-3 py-2 rounded bg-success/10 text-success border border-success/30"
            >
              Test email sent to {sendOk.to}. Check your inbox in ~30s.
            </div>
          )}
          {sendError && (
            <div
              data-testid="send-test-error"
              className="text-xs px-3 py-2 rounded bg-error/10 text-error border border-error/30 whitespace-pre-wrap"
            >
              {sendError}
            </div>
          )}
          {!messageForSelected && selectedContactId && (
            <div className="text-[11px] text-text-dim italic">
              No generated message exists for this contact yet. Send Test requires an existing message — generate messages first.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-solid">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs bg-surface border border-border text-text rounded-md hover:bg-surface-alt transition-colors"
          >
            Close
          </button>
          <button
            type="button"
            data-testid="send-test-button"
            onClick={handleSendTest}
            disabled={
              !messageForSelected ||
              sendTestMutation.isPending ||
              !selectedContactId
            }
            title={
              !messageForSelected
                ? 'Generate messages first'
                : `Send a test to ${user?.email ?? 'you'}`
            }
            className="px-3 py-1.5 text-xs bg-accent hover:bg-accent-hover text-white rounded-md transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {sendTestMutation.isPending ? 'Sending…' : 'Send test to me'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Pass-through wrapper: the body coming back from the API is the raw
 * model output and may be plain text or HTML. We render it as-is inside
 * a fully sandboxed iframe (no scripts allowed) so any HTML markup
 * displays but cannot execute. Plain text falls through with newlines
 * preserved via white-space CSS in the iframe stylesheet.
 */
function escapeForIframe(body: string): string {
  // If the body looks like HTML, render it directly. Otherwise wrap
  // it so newlines are preserved.
  const looksHtml = /<[a-z][\s\S]*>/i.test(body)
  if (looksHtml) return body
  // Plain text — escape and preserve newlines.
  const escaped = body
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return `<pre style="white-space: pre-wrap; font-family: inherit; margin: 0;">${escaped}</pre>`
}
