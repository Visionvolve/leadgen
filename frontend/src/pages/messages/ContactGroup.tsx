import { useCallback, useMemo } from 'react'
import { Badge } from '../../components/ui/Badge'
import { MessageCard } from './MessageCard'
import { useBatchUpdateMessages, type Message } from '../../api/queries/useMessages'
import { useSendTestEmail } from '../../api/queries/usePreview'
import { useToast } from '../../components/ui/Toast'
import { ApiError } from '../../api/client'

interface ContactGroupProps {
  contactName: string
  contactTitle: string | null
  contactScore: number | null
  contactIcp: string | null
  linkedinUrl: string | null
  companyName: string | null
  companyTier: string | null
  messages: Message[]
  selectedIds?: Set<string>
  onToggleSelect?: (id: string) => void
  onContactClick?: () => void
  onCompanyClick?: () => void
  /** Open the campaign Preview modal pre-selected to this contact. */
  onPreview?: () => void
  /** Optional inline send-test fallback — currently routes through the modal. */
  onRequestSendTest?: () => void
  /** Campaign id needed by inline Send-Test (when wired without a modal). */
  campaignId?: string
}

export function ContactGroup({
  contactName, contactTitle, contactScore, contactIcp,
  linkedinUrl, companyName, companyTier, messages,
  selectedIds, onToggleSelect,
  onContactClick, onCompanyClick,
  onPreview, campaignId,
}: ContactGroupProps) {
  const { toast } = useToast()
  const batchMutation = useBatchUpdateMessages()
  const sendTestMutation = useSendTestEmail()

  const draftAIds = useMemo(
    () => messages
      .filter((m) => m.status === 'draft' && m.variant === 'A')
      .map((m) => m.id),
    [messages],
  )

  const handleApproveAllA = useCallback(async () => {
    if (draftAIds.length === 0) return
    try {
      await batchMutation.mutateAsync({
        ids: draftAIds,
        fields: { status: 'approved', approved_at: new Date().toISOString() },
      })
      toast(`${draftAIds.length} message(s) approved`, 'success')
    } catch {
      toast('Bulk approve failed', 'error')
    }
  }, [draftAIds, batchMutation, toast])

  // Inline Send-Test for the contact group — picks variant A by default,
  // falls back to the first message. Disabled while sending.
  const sendTestMessage = useMemo(() => {
    if (messages.length === 0) return null
    const variantA = messages.find((m) => (m.variant || '').toUpperCase() === 'A')
    return variantA ?? messages[0] ?? null
  }, [messages])

  const handleInlineSendTest = useCallback(async () => {
    if (!sendTestMessage || !campaignId) return
    try {
      const res = await sendTestMutation.mutateAsync({
        campaignId,
        messageId: sendTestMessage.id,
      })
      toast(`Test email sent to ${res.sent_to}`, 'success')
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message || `Send-test failed (${err.status})`
          : 'Send-test failed'
      toast(msg, 'error')
    }
  }, [campaignId, sendTestMessage, sendTestMutation, toast])

  return (
    <div className="border border-border-solid rounded-lg bg-surface/50 overflow-hidden">
      {/* Contact header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-surface-alt/50 border-b border-border-solid flex-wrap">
        <button
          onClick={onContactClick}
          className="text-sm font-medium text-text hover:text-accent-cyan transition-colors"
        >
          {contactName}
        </button>
        {contactTitle && <span className="text-xs text-text-muted">{contactTitle}</span>}
        {contactScore != null && (
          <span className="text-xs font-medium text-accent-cyan">{contactScore}</span>
        )}
        <Badge variant="icp" value={contactIcp} />
        {companyName && (
          <button
            onClick={onCompanyClick}
            className="text-xs text-text-dim hover:text-accent-cyan transition-colors"
          >
            {companyName}
          </button>
        )}
        {companyTier && <Badge variant="tier" value={companyTier} />}
        {linkedinUrl && (
          <a
            href={linkedinUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-accent-cyan hover:underline ml-auto"
            onClick={(e) => e.stopPropagation()}
          >
            LinkedIn
          </a>
        )}
        <div className="ml-auto flex items-center gap-2">
          {onPreview && (
            <button
              data-testid="contact-row-preview"
              onClick={onPreview}
              className="px-2.5 py-1 text-xs text-text-muted border border-border rounded hover:text-text hover:bg-surface-alt transition-colors flex items-center gap-1"
              title="Preview this contact's rendered message"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1.5 8s2.5-5 6.5-5 6.5 5 6.5 5-2.5 5-6.5 5-6.5-5-6.5-5z" />
                <circle cx="8" cy="8" r="2" />
              </svg>
              Preview
            </button>
          )}
          {sendTestMessage && campaignId && (
            <button
              data-testid="contact-row-send-test"
              onClick={handleInlineSendTest}
              disabled={sendTestMutation.isPending}
              className="px-2.5 py-1 text-xs text-text-muted border border-border rounded hover:text-text hover:bg-surface-alt transition-colors flex items-center gap-1 disabled:opacity-50"
              title="Send a test email of this row to your inbox"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M15 1L7.5 8.5M15 1l-4.5 14-3-6.5L1 5l14-4z" />
              </svg>
              {sendTestMutation.isPending ? 'Sending…' : 'Send test'}
            </button>
          )}
          {draftAIds.length > 0 && (
            <button
              onClick={handleApproveAllA}
              disabled={batchMutation.isPending}
              className="px-2.5 py-1 text-xs bg-success/10 text-success border border-success/30 rounded hover:bg-success/20 transition-colors disabled:opacity-50"
            >
              Approve all A ({draftAIds.length})
            </button>
          )}
        </div>
      </div>

      {/* Messages grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-3">
        {messages.map((m) => (
          <MessageCard
            key={m.id}
            message={m}
            selected={selectedIds?.has(m.id) ?? false}
            onToggleSelect={onToggleSelect ? () => onToggleSelect(m.id) : undefined}
          />
        ))}
      </div>
    </div>
  )
}
