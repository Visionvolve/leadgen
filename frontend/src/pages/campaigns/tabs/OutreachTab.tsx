import { useState, useCallback } from 'react'
import {
  useCampaignAnalytics,
  useSendEmails,
  useQueueLinkedIn,
  type CampaignDetail,
} from '../../../api/queries/useCampaigns'
import { useToast } from '../../../components/ui/Toast'
import { Modal } from '../../../components/ui/Modal'
import { SectionDivider } from '../../../components/ui/DetailField'

interface Props {
  campaign: CampaignDetail
}

// ── Status badge helper ─────────────────────────────────

function StatusBadge({ label, count, color }: { label: string; count: number; color: string }) {
  if (count === 0) return null
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded ${color}`}>
      {count} {label}
    </span>
  )
}

// ── Stat card ───────────────────────────────────────────

function StatCard({ label, value, sublabel }: { label: string; value: number | string; sublabel?: string }) {
  return (
    <div className="px-4 py-3 bg-surface-alt rounded-lg border border-border text-center">
      <div className="text-xl font-semibold text-text tabular-nums">{value}</div>
      <div className="text-xs text-text-muted mt-0.5">{label}</div>
      {sublabel && <div className="text-[10px] text-text-dim mt-0.5">{sublabel}</div>}
    </div>
  )
}

// ── Progress bar ────────────────────────────────────────

function ProgressBar({ label, current, total }: { label: string; current: number; total: number }) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-text-muted">{label}</span>
        <span className="text-xs text-text-dim tabular-nums">{current}/{total} ({pct}%)</span>
      </div>
      <div className="h-2 bg-surface-alt rounded-full overflow-hidden border border-border/50">
        <div
          className="h-full bg-accent rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────

export function OutreachTab({ campaign }: Props) {
  const { toast } = useToast()
  const sendEmails = useSendEmails()
  const queueLinkedIn = useQueueLinkedIn()
  const { data: analytics, isLoading: analyticsLoading } = useCampaignAnalytics(campaign.id)

  // Confirmation dialog state
  const [confirmAction, setConfirmAction] = useState<'email' | 'linkedin' | null>(null)

  const senderConfig = campaign.sender_config
  const hasEmailSender = !!(senderConfig?.from_email)

  // Derive counts from analytics (matching actual API shape)
  const approvedCount = analytics?.messages?.by_status?.approved ?? 0
  const emailChannelCount = analytics?.messages?.by_channel?.email ?? 0
  const linkedinConnectCount = analytics?.messages?.by_channel?.linkedin_connect ?? 0
  const linkedinMessageCount = analytics?.messages?.by_channel?.linkedin_message ?? 0
  const linkedinTotalMsgs = linkedinConnectCount + linkedinMessageCount

  // Sending stats
  const emailSending = analytics?.sending?.email
  const linkedinSending = analytics?.sending?.linkedin

  // ── Actions ──

  const handleSendEmails = useCallback(async () => {
    setConfirmAction(null)
    try {
      const result = await sendEmails.mutateAsync(campaign.id)
      toast(
        `${result.queued_count} email${result.queued_count !== 1 ? 's' : ''} queued for delivery`,
        'success',
      )
    } catch {
      toast('Failed to send emails', 'error')
    }
  }, [campaign.id, sendEmails, toast])

  const handleQueueLinkedIn = useCallback(async () => {
    setConfirmAction(null)
    try {
      const result = await queueLinkedIn.mutateAsync(campaign.id)
      toast(
        `${result.queued_count} LinkedIn message${result.queued_count !== 1 ? 's' : ''} queued for extension`,
        'success',
      )
    } catch {
      toast('Failed to queue LinkedIn messages', 'error')
    }
  }, [campaign.id, queueLinkedIn, toast])

  // ── Loading state ──

  if (analyticsLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  // ── Empty state (no approved messages) ──

  if (!analytics || approvedCount === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="w-12 h-12 rounded-full bg-surface-alt flex items-center justify-center mb-4">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-dim">
            <path d="M22 2L11 13" />
            <path d="M22 2L15 22L11 13L2 9L22 2Z" />
          </svg>
        </div>
        <p className="text-sm font-medium text-text-muted">No Messages Ready for Outreach</p>
        <p className="text-xs text-text-dim mt-1 max-w-sm">
          Approve messages in the Messages tab first. Once messages are approved,
          you can send emails and queue LinkedIn messages here.
        </p>
      </div>
    )
  }

  // ── Main UI ──

  return (
    <div className="max-w-3xl space-y-6">
      {/* Outreach Summary */}
      <div>
        <SectionDivider title="Outreach Summary" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          <StatCard label="Approved Emails" value={emailChannelCount} />
          <StatCard label="LinkedIn Ready" value={linkedinTotalMsgs} />
          <StatCard
            label="Emails Sent"
            value={emailSending?.sent ?? 0}
            sublabel={emailSending?.delivered ? `${emailSending.delivered} delivered` : undefined}
          />
          <StatCard
            label="LinkedIn Sent"
            value={linkedinSending?.sent ?? 0}
            sublabel={linkedinSending?.queued ? `${linkedinSending.queued} in queue` : undefined}
          />
        </div>
      </div>

      {/* Email Section */}
      {emailChannelCount > 0 && (
        <div>
          <SectionDivider title="Email Delivery" />
          <div className="mt-3 p-4 bg-surface-alt rounded-lg border border-border space-y-4">
            {/* Sender info */}
            {hasEmailSender ? (
              <div className="flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-dim flex-shrink-0">
                  <rect x="2" y="4" width="20" height="16" rx="2" />
                  <path d="M22 4L12 13L2 4" />
                </svg>
                <span className="text-sm text-text">
                  {senderConfig.from_name
                    ? `${senderConfig.from_name} <${senderConfig.from_email}>`
                    : senderConfig.from_email}
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2 px-3 py-2.5 bg-warning/10 border border-warning/20 rounded-lg">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-warning flex-shrink-0 mt-0.5">
                  <path d="M8 1.5L1 14h14L8 1.5z" />
                  <path d="M8 6v3" />
                  <circle cx="8" cy="11.5" r="0.5" fill="currentColor" />
                </svg>
                <div>
                  <p className="text-xs font-medium text-warning">Sender not configured</p>
                  <p className="text-[11px] text-text-dim mt-0.5">
                    Go to the Settings tab to configure your sender email address before sending.
                  </p>
                </div>
              </div>
            )}

            {/* Email readiness */}
            <div className="text-sm text-text-muted">
              <span className="font-medium text-text">{emailChannelCount}</span>{' '}
              email{emailChannelCount !== 1 ? 's' : ''} in this campaign
              {(emailSending?.sent ?? 0) > 0 && (
                <span className="text-text-dim ml-1">
                  ({emailSending!.sent} already sent)
                </span>
              )}
            </div>

            {/* Send button */}
            <button
              onClick={() => setConfirmAction('email')}
              disabled={!hasEmailSender || emailChannelCount === 0 || sendEmails.isPending}
              className="px-4 py-2 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sendEmails.isPending ? 'Sending...' : 'Send All Emails'}
            </button>

            {/* Live status */}
            {emailSending && emailSending.total > 0 && (
              <div className="space-y-2 pt-2 border-t border-border">
                <p className="text-xs font-medium text-text-muted">Delivery Status</p>
                <ProgressBar
                  label="Sent"
                  current={emailSending.sent}
                  total={emailSending.total}
                />
                <div className="flex flex-wrap gap-2">
                  <StatusBadge label="queued" count={emailSending.queued} color="bg-[#8B92A0]/10 text-text-muted" />
                  <StatusBadge label="sent" count={emailSending.sent} color="bg-accent/10 text-accent-hover" />
                  <StatusBadge label="delivered" count={emailSending.delivered} color="bg-success/10 text-success" />
                  <StatusBadge label="bounced" count={emailSending.bounced} color="bg-warning/10 text-warning" />
                  <StatusBadge label="failed" count={emailSending.failed} color="bg-error/10 text-error" />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* LinkedIn Section */}
      {linkedinTotalMsgs > 0 && (
        <div>
          <SectionDivider title="LinkedIn Queue" />
          <div className="mt-3 p-4 bg-surface-alt rounded-lg border border-border space-y-4">
            {/* LinkedIn readiness */}
            <div className="flex items-center gap-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-dim flex-shrink-0">
                <path d="M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-4 0v7h-4v-7a6 6 0 016-6z" />
                <rect x="2" y="9" width="4" height="12" />
                <circle cx="4" cy="4" r="2" />
              </svg>
              <span className="text-sm text-text-muted">
                <span className="font-medium text-text">{linkedinTotalMsgs}</span>{' '}
                LinkedIn message{linkedinTotalMsgs !== 1 ? 's' : ''} in this campaign
              </span>
            </div>

            {/* Queue button */}
            <button
              onClick={() => setConfirmAction('linkedin')}
              disabled={linkedinTotalMsgs === 0 || queueLinkedIn.isPending}
              className="px-4 py-2 text-sm font-medium rounded bg-[#0A66C2] text-white border-none cursor-pointer hover:bg-[#004182] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {queueLinkedIn.isPending ? 'Queuing...' : 'Queue for Extension'}
            </button>

            <p className="text-[11px] text-text-dim">
              Queued messages will be available for the Chrome extension to send via your LinkedIn account.
            </p>

            {/* Live status */}
            {linkedinSending && linkedinSending.total > 0 && (
              <div className="space-y-2 pt-2 border-t border-border">
                <p className="text-xs font-medium text-text-muted">Queue Status</p>
                <ProgressBar
                  label="Processed"
                  current={linkedinSending.sent}
                  total={linkedinSending.total}
                />
                <div className="flex flex-wrap gap-2">
                  <StatusBadge label="queued" count={linkedinSending.queued} color="bg-[#8B92A0]/10 text-text-muted" />
                  <StatusBadge label="sent" count={linkedinSending.sent} color="bg-success/10 text-success" />
                  <StatusBadge label="delivered" count={linkedinSending.delivered} color="bg-accent/10 text-accent-hover" />
                  <StatusBadge label="failed" count={linkedinSending.failed} color="bg-error/10 text-error" />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Message breakdown by step */}
      {analytics.messages.by_step && Object.keys(analytics.messages.by_step).length > 0 && (
        <div>
          <SectionDivider title="Messages by Step" />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 px-2 text-text-muted font-medium">Step</th>
                  <th className="text-right py-2 px-2 text-text-muted font-medium">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(analytics.messages.by_step)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([step, count]) => (
                    <tr key={step} className="border-b border-border/50">
                      <td className="py-2 px-2 text-text">Step {step}</td>
                      <td className="py-2 px-2 text-right text-text tabular-nums">{count}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Confirmation Dialogs */}
      <Modal
        open={confirmAction === 'email'}
        onClose={() => setConfirmAction(null)}
        title="Confirm Email Send"
        actions={
          <>
            <button
              onClick={() => setConfirmAction(null)}
              className="px-3 py-1.5 text-sm rounded border border-border text-text-muted hover:text-text cursor-pointer bg-transparent transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSendEmails}
              disabled={sendEmails.isPending}
              className="px-4 py-1.5 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
            >
              {sendEmails.isPending ? 'Sending...' : 'Send Emails'}
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-text">
            Send{' '}
            <span className="font-semibold text-accent-cyan">{emailChannelCount} email{emailChannelCount !== 1 ? 's' : ''}</span>
            {' '}from{' '}
            <span className="font-semibold text-accent-cyan">
              {senderConfig?.from_name
                ? `${senderConfig.from_name} <${senderConfig.from_email}>`
                : senderConfig?.from_email ?? 'unknown'}
            </span>
            ?
          </p>
          <p className="text-xs text-text-dim">
            {senderConfig?.send_via === 'gmail'
              ? 'Emails will be sent from your Gmail inbox with a 45-second delay between each. Already-sent messages will be skipped.'
              : 'This will dispatch all approved email messages via Resend. Already-sent messages will be skipped.'}
          </p>
        </div>
      </Modal>

      <Modal
        open={confirmAction === 'linkedin'}
        onClose={() => setConfirmAction(null)}
        title="Confirm LinkedIn Queue"
        actions={
          <>
            <button
              onClick={() => setConfirmAction(null)}
              className="px-3 py-1.5 text-sm rounded border border-border text-text-muted hover:text-text cursor-pointer bg-transparent transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleQueueLinkedIn}
              disabled={queueLinkedIn.isPending}
              className="px-4 py-1.5 text-sm font-medium rounded bg-[#0A66C2] text-white border-none cursor-pointer hover:bg-[#004182] transition-colors disabled:opacity-50"
            >
              {queueLinkedIn.isPending ? 'Queuing...' : 'Queue Messages'}
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-text">
            Queue{' '}
            <span className="font-semibold text-accent-cyan">{linkedinTotalMsgs} LinkedIn message{linkedinTotalMsgs !== 1 ? 's' : ''}</span>
            {' '}for the Chrome extension?
          </p>
          <p className="text-xs text-text-dim">
            Messages will be added to the extension queue. Already-queued messages will be skipped.
            The Chrome extension sends them via your LinkedIn account.
          </p>
        </div>
      </Modal>
    </div>
  )
}
