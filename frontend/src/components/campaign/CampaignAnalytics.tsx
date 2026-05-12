import { useCampaignAnalytics, type CampaignAnalyticsData } from '../../api/queries/useCampaigns'

// ── Helpers ──────────────────────────────────────────────

function formatCost(usd: number): string {
  if (usd === 0) return '-'
  return `${Math.round(usd * 1000)} credits`
}

function pct(num: number, den: number): number {
  if (den === 0) return 0
  return Math.round((num / den) * 100)
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ── Sub-components ───────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-surface-alt rounded-lg px-4 py-3 border border-border">
      <p className="text-2xl font-semibold text-text tabular-nums">{value}</p>
      <p className="text-xs text-text-muted mt-0.5">{label}</p>
      {sub && <p className="text-[11px] text-text-dim mt-0.5">{sub}</p>}
    </div>
  )
}

function ProgressBar({
  label,
  current,
  total,
  color = 'bg-accent-cyan',
}: {
  label: string
  current: number
  total: number
  color?: string
}) {
  const percentage = pct(current, total)
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-text-muted">{label}</span>
        <span className="text-xs text-text tabular-nums">
          {percentage}% ({current}/{total})
        </span>
      </div>
      <div className="w-full h-2 bg-surface-alt rounded-full overflow-hidden border border-border">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
}

function ChannelBadge({ channel, count }: { channel: string; count: number }) {
  const labels: Record<string, { short: string; color: string }> = {
    email: { short: 'Email', color: 'bg-accent/15 text-accent border-accent/30' },
    linkedin_connect: { short: 'LI Connect', color: 'bg-[#0077b5]/15 text-[#0077b5] border-[#0077b5]/30' },
    linkedin_message: { short: 'LI Message', color: 'bg-[#0077b5]/15 text-[#0077b5] border-[#0077b5]/30' },
    call_script: { short: 'Call', color: 'bg-warning/15 text-warning border-warning/30' },
  }
  const info = labels[channel] ?? { short: channel, color: 'bg-surface-alt text-text-muted border-border' }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded border ${info.color}`}>
      {info.short}
      <span className="tabular-nums">{count}</span>
    </span>
  )
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-text-dim',
    generated: 'bg-text-muted',
    approved: 'bg-success',
    rejected: 'bg-error',
    sent: 'bg-accent-cyan',
    queued: 'bg-warning',
    delivered: 'bg-success',
    bounced: 'bg-error',
    failed: 'bg-error',
  }
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${colors[status] ?? 'bg-text-dim'}`} />
  )
}

function TimelineItem({ label, date }: { label: string; date: string | null }) {
  const formatted = formatDate(date)
  const isSet = date !== null
  return (
    <div className="flex items-center gap-3">
      <div className="flex flex-col items-center">
        <div className={`w-2.5 h-2.5 rounded-full border-2 ${isSet ? 'bg-accent-cyan border-accent-cyan' : 'bg-transparent border-border-solid'}`} />
      </div>
      <div className="flex items-center justify-between flex-1 py-1.5">
        <span className="text-xs text-text-muted">{label}</span>
        <span className={`text-xs tabular-nums ${isSet ? 'text-text' : 'text-text-dim'}`}>{formatted}</span>
      </div>
    </div>
  )
}

// ── Loading skeleton ─────────────────────────────────────

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-surface-alt rounded-lg px-4 py-3 border border-border h-[72px]" />
        ))}
      </div>
      <div className="space-y-3">
        <div className="h-4 bg-surface-alt rounded w-32" />
        <div className="h-2 bg-surface-alt rounded" />
        <div className="h-2 bg-surface-alt rounded" />
      </div>
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────

function AnalyticsEmpty() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-full bg-surface-alt flex items-center justify-center mb-4">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-dim">
          <path d="M18 20V10" />
          <path d="M12 20V4" />
          <path d="M6 20v-6" />
        </svg>
      </div>
      <p className="text-sm font-medium text-text-muted">No analytics data yet</p>
      <p className="text-xs text-text-dim mt-1">Generate messages and start outreach to see metrics here</p>
    </div>
  )
}

// ── Error state ──────────────────────────────────────────

function AnalyticsError({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-full bg-error/10 flex items-center justify-center mb-4">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-error">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v4" />
          <circle cx="12" cy="16" r="0.5" fill="currentColor" />
        </svg>
      </div>
      <p className="text-sm font-medium text-text-muted">Failed to load analytics</p>
      <p className="text-xs text-text-dim mt-1">{message}</p>
    </div>
  )
}

// ── Main analytics view ──────────────────────────────────

function EngagementRateBar({ label, rate, color }: { label: string; rate: number; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-text-muted w-20 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-surface-alt rounded-full overflow-hidden border border-border">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${Math.min(rate, 100)}%` }}
        />
      </div>
      <span className="text-xs text-text tabular-nums w-12 text-right">{rate}%</span>
    </div>
  )
}

function AnalyticsView({ data }: { data: CampaignAnalyticsData }) {
  const { messages, sending, contacts, cost, timeline, engagement } = data

  const approved = messages.by_status['approved'] ?? 0
  const rejected = messages.by_status['rejected'] ?? 0
  const draft = messages.by_status['draft'] ?? 0
  const generated = messages.by_status['generated'] ?? 0
  const sent = (messages.by_status['sent'] ?? 0)

  // Email delivery: sent + delivered counts
  const emailSent = sending.email.sent + sending.email.delivered
  const emailTarget = sending.email.total || (messages.by_channel['email'] ?? 0)

  // LinkedIn delivery
  const linkedInSent = sending.linkedin.sent + sending.linkedin.delivered
  const linkedInTarget = sending.linkedin.total || (messages.by_channel['linkedin_connect'] ?? 0) + (messages.by_channel['linkedin_message'] ?? 0)

  const isEmptyCampaign = messages.total === 0 && contacts.total === 0

  if (isEmptyCampaign) {
    return <AnalyticsEmpty />
  }

  return (
    <div className="space-y-6">
      {/* ── Overview stat cards ── */}
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Overview</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label="Contacts"
            value={contacts.total}
            sub={contacts.both_channels > 0 ? `${contacts.both_channels} with both channels` : undefined}
          />
          <StatCard
            label="Messages"
            value={messages.total}
            sub={messages.total > 0 ? `${approved} approved, ${draft + generated} pending` : undefined}
          />
          <StatCard
            label="Approved"
            value={approved}
            sub={rejected > 0 ? `${rejected} rejected` : undefined}
          />
          <StatCard
            label="Cost"
            value={formatCost(cost.generation_usd)}
            sub={cost.email_sends > 0 ? `${cost.email_sends} email sends` : undefined}
          />
        </div>
      </div>

      {/* ── Channel breakdown ── */}
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Messages by Channel</h3>
        <div className="flex flex-wrap gap-2">
          {Object.entries(messages.by_channel).map(([channel, count]) => (
            <ChannelBadge key={channel} channel={channel} count={count} />
          ))}
          {Object.keys(messages.by_channel).length === 0 && (
            <span className="text-xs text-text-dim">No messages generated yet</span>
          )}
        </div>
      </div>

      {/* ── Delivery progress ── */}
      {(sending.email.total > 0 || sending.linkedin.total > 0) && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Delivery Status</h3>
          <div className="space-y-4">
            {sending.email.total > 0 && (
              <div className="space-y-2">
                <ProgressBar
                  label="Email"
                  current={emailSent}
                  total={emailTarget}
                  color="bg-accent"
                />
                <div className="flex flex-wrap gap-3 ml-1">
                  {sending.email.queued > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="queued" /> {sending.email.queued} queued
                    </span>
                  )}
                  {sending.email.sent > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="sent" /> {sending.email.sent} sent
                    </span>
                  )}
                  {sending.email.delivered > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="delivered" /> {sending.email.delivered} delivered
                    </span>
                  )}
                  {sending.email.bounced > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="bounced" /> {sending.email.bounced} bounced
                    </span>
                  )}
                  {sending.email.failed > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="failed" /> {sending.email.failed} failed
                    </span>
                  )}
                </div>
              </div>
            )}

            {sending.linkedin.total > 0 && (
              <div className="space-y-2">
                <ProgressBar
                  label="LinkedIn"
                  current={linkedInSent}
                  total={linkedInTarget}
                  color="bg-[#0077b5]"
                />
                <div className="flex flex-wrap gap-3 ml-1">
                  {sending.linkedin.queued > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="queued" /> {sending.linkedin.queued} queued
                    </span>
                  )}
                  {sending.linkedin.sent > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="sent" /> {sending.linkedin.sent} sent
                    </span>
                  )}
                  {sending.linkedin.delivered > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="delivered" /> {sending.linkedin.delivered} delivered
                    </span>
                  )}
                  {sending.linkedin.failed > 0 && (
                    <span className="flex items-center gap-1.5 text-[11px] text-text-dim">
                      <StatusDot status="failed" /> {sending.linkedin.failed} failed
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Email Engagement Tracking ── */}
      {engagement && (engagement.opened > 0 || engagement.replied > 0 || engagement.bounced > 0 || engagement.clicked > 0) && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Email Engagement</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <StatCard
              label="Opened"
              value={engagement.opened}
              sub={`${engagement.open_rate}% open rate`}
            />
            <StatCard
              label="Replied"
              value={engagement.replied}
              sub={`${engagement.reply_rate}% reply rate`}
            />
            <StatCard
              label="Clicked"
              value={engagement.clicked}
              sub={`${engagement.click_rate}% click rate`}
            />
            <StatCard
              label="Bounced"
              value={engagement.bounced}
              sub={engagement.hard_bounces > 0 ? `${engagement.hard_bounces} hard, ${engagement.soft_bounces} soft` : `${engagement.bounce_rate}% bounce rate`}
            />
          </div>
          <div className="space-y-2">
            <EngagementRateBar label="Open Rate" rate={engagement.open_rate} color="bg-accent-cyan" />
            <EngagementRateBar label="Reply Rate" rate={engagement.reply_rate} color="bg-success" />
            <EngagementRateBar label="Click Rate" rate={engagement.click_rate} color="bg-accent" />
            <EngagementRateBar label="Bounce Rate" rate={engagement.bounce_rate} color="bg-error" />
          </div>
        </div>
      )}

      {/* ── Engagement placeholder when no data yet ── */}
      {engagement && engagement.opened === 0 && engagement.replied === 0 && engagement.bounced === 0 && (sending.email.sent > 0 || sending.email.delivered > 0) && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Email Engagement</h3>
          <div className="bg-surface-alt rounded-lg border border-border px-4 py-6 text-center">
            <p className="text-xs text-text-dim">No engagement data received yet. Open/reply/bounce tracking will appear here once webhook events arrive.</p>
          </div>
        </div>
      )}

      {/* ── Message status breakdown ── */}
      {messages.total > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Message Status</h3>
          <div className="bg-surface-alt rounded-lg border border-border overflow-hidden">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider">Status</th>
                  <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider text-right">Count</th>
                  <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider text-right">Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {Object.entries(messages.by_status)
                  .sort(([, a], [, b]) => b - a)
                  .map(([status, count]) => (
                    <tr key={status}>
                      <td className="px-4 py-2">
                        <span className="flex items-center gap-2 text-xs text-text">
                          <StatusDot status={status} />
                          {status.charAt(0).toUpperCase() + status.slice(1)}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-text tabular-nums text-right">{count}</td>
                      <td className="px-4 py-2 text-xs text-text-muted tabular-nums text-right">
                        {pct(count, messages.total)}%
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Messages by step ── */}
      {Object.keys(messages.by_step).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">By Sequence Step</h3>
          <div className="bg-surface-alt rounded-lg border border-border overflow-hidden">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider">Step</th>
                  <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider text-right">Messages</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {Object.entries(messages.by_step)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([step, count]) => (
                    <tr key={step}>
                      <td className="px-4 py-2 text-xs text-text">Step {step}</td>
                      <td className="px-4 py-2 text-xs text-text tabular-nums text-right">{count}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Contact reach ── */}
      {contacts.total > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Contact Reach</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Total Contacts" value={contacts.total} />
            <StatCard label="With Email" value={contacts.with_email} />
            <StatCard label="With LinkedIn" value={contacts.with_linkedin} />
            <StatCard label="Both Channels" value={contacts.both_channels} />
          </div>
        </div>
      )}

      {/* ── Timeline ── */}
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">Timeline</h3>
        <div className="bg-surface-alt rounded-lg border border-border px-4 py-3">
          <div className="space-y-0.5 relative">
            {/* Vertical connector line */}
            <div className="absolute left-[4px] top-3 bottom-3 w-px bg-border-solid" />
            <TimelineItem label="Campaign Created" date={timeline.created_at} />
            <TimelineItem label="Generation Started" date={timeline.generation_started_at} />
            <TimelineItem label="Generation Completed" date={timeline.generation_completed_at} />
            <TimelineItem label="First Send" date={timeline.first_send_at} />
            <TimelineItem label="Last Send" date={timeline.last_send_at} />
          </div>
        </div>
      </div>

      {/* ── Sent counter at bottom ── */}
      {sent > 0 && (
        <div className="text-[11px] text-text-dim text-center pt-2 border-t border-border">
          {sent} message{sent !== 1 ? 's' : ''} marked as sent
        </div>
      )}
    </div>
  )
}

// ── Main exported component ──────────────────────────────

interface Props {
  campaignId: string
}

export function CampaignAnalytics({ campaignId }: Props) {
  const { data, isLoading, error } = useCampaignAnalytics(campaignId)

  if (isLoading) {
    return <AnalyticsSkeleton />
  }

  if (error) {
    return <AnalyticsError message={error instanceof Error ? error.message : 'Unknown error'} />
  }

  if (!data) {
    return <AnalyticsEmpty />
  }

  return <AnalyticsView data={data} />
}
