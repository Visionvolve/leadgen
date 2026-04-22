/**
 * Echo Analytics Page (BL-1040)
 *
 * Campaign analytics surface replacing the /echo PlaceholderPage.
 * Two views, controlled by the `campaign` query-param:
 *   - CampaignListView (default): table of campaigns with inline KPI preview
 *   - CampaignDetailView: hero CTR + supporting tiles, funnel, time series,
 *     microsite block, contact drill-down.
 *
 * This file keeps all sub-components inline so the shared abstractions stay
 * deferred (BL-1041 can copy patterns or we refactor once both views exist).
 *
 * Data strategy:
 *   - `/api/campaigns/:id/analytics` via `useCampaignAnalytics` (10s poll)
 *     for hero KPIs, funnel totals, and microsite tile values.
 *   - `/api/campaigns/:id/analytics/timeseries` via
 *     `useCampaignAnalyticsTimeseries` (BL-1037) for the real per-bucket
 *     time series, rendered inside the lazy-loaded TimeSeriesBlock.
 *   - Live updates via `useCampaignAnalyticsStream` (BL-1039 consumer) —
 *     SSE on `/api/campaigns/:id/analytics/stream`. Polling is kept as
 *     a fallback so disconnects never blank the UI.
 *
 * Bundle hygiene: Recharts lives only in `./echo/TimeSeriesBlock.tsx` and
 * is split out via `React.lazy` so it does not weigh on the main bundle.
 */

import { lazy, Suspense, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  useCampaigns,
  useCampaignAnalytics,
  useCampaignRecipients,
  type Campaign,
  type CampaignAnalyticsData,
} from '../api/queries/useCampaigns'
import { useCampaignAnalyticsStream } from '../api/hooks/useCampaignAnalyticsStream'

// Recharts (~95 kB) is lazy-loaded so it does not bloat the main bundle.
// Only imported for the campaign-detail view's time series.
const TimeSeriesBlock = lazy(() => import('./echo/TimeSeriesBlock'))

// ── Types ────────────────────────────────────────────────

type RangeKey = '24h' | '7d' | '30d' | 'all'

// Extend the analytics payload locally — backend already returns
// `microsite` but it isn't yet modelled in the shared type.
interface MicrositePayload {
  visits: number
  unique_visitors: number
  product_views: number
  visit_rate: number
}

interface AnalyticsWithMicrosite extends CampaignAnalyticsData {
  microsite?: MicrositePayload
  posthog_available?: boolean
}

// ── Helpers ──────────────────────────────────────────────

function pct(num: number, den: number): number {
  if (den <= 0) return 0
  return Math.round((num / den) * 100 * 10) / 10
}

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

// ── Page root ────────────────────────────────────────────

export default function EchoPage() {
  const [searchParams] = useSearchParams()
  const campaignId = searchParams.get('campaign')
  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-border">
        <h1 className="font-title text-[1.3rem] font-semibold tracking-tight mb-1.5 text-text">
          Echo
        </h1>
        <p className="text-text-muted text-[0.9rem]">
          Campaign performance — delivery, engagement, microsite signals.
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {campaignId ? (
          <CampaignDetailView id={campaignId} />
        ) : (
          <CampaignListView />
        )}
      </div>
    </div>
  )
}

export { EchoPage }

// ── Campaign list view ───────────────────────────────────

function CampaignListView() {
  const { data, isLoading, error, refetch } = useCampaigns()
  const campaigns = data?.campaigns ?? []

  if (isLoading) {
    return <ListSkeleton />
  }

  if (error) {
    return (
      <ErrorCard
        message={error instanceof Error ? error.message : 'Failed to load campaigns'}
        onRetry={() => refetch()}
      />
    )
  }

  if (campaigns.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-sm font-medium text-text-muted">No campaigns yet</p>
        <p className="text-xs text-text-dim mt-1">
          Create a campaign to start tracking outreach performance here.
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {campaigns.map((c) => (
        <CampaignPreviewCard key={c.id} campaign={c} />
      ))}
    </div>
  )
}

function CampaignPreviewCard({ campaign }: { campaign: Campaign }) {
  const { namespace } = useParams<{ namespace: string }>()
  // List view: throttle aggressively to avoid N parallel 10s polls when
  // many cards render. Cards pull from cache; users see fresh data when
  // they open the detail view (which keeps the 10s cadence).
  const { data } = useCampaignAnalytics(campaign.id, {
    staleTime: 60_000,
    refetchInterval: false,
  })
  const email = data?.sending?.email
  // `total` = queued + sent + delivered + bounced + failed. Matches the
  // sentTotal computation in CampaignDetailView; avoids the old
  // sent+delivered double-count.
  const sentTotal = email
    ? (email.sent ?? 0) + (email.delivered ?? 0) + (email.bounced ?? 0) + (email.failed ?? 0)
    : 0
  const delivered = email?.delivered ?? 0
  const clicked = data?.engagement?.clicked ?? 0
  const ctr = pct(clicked, delivered)

  const campaignPath = namespace
    ? `/${namespace}/echo?campaign=${encodeURIComponent(campaign.id)}`
    : `/echo?campaign=${encodeURIComponent(campaign.id)}`

  return (
    <Link
      to={campaignPath}
      className="block bg-surface border border-border rounded-lg p-4 hover:border-accent transition-colors no-underline"
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-text truncate">{campaign.name}</h3>
        <span className="text-[11px] text-text-dim whitespace-nowrap">{campaign.status}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <KpiMini label="Sent" value={formatNumber(sentTotal)} />
        <KpiMini label="CTR" value={`${ctr}%`} highlight />
        <KpiMini label="Reply" value="—" muted />
      </div>
    </Link>
  )
}

function KpiMini({
  label,
  value,
  highlight,
  muted,
}: {
  label: string
  value: string
  highlight?: boolean
  muted?: boolean
}) {
  return (
    <div>
      <p
        className={`text-sm font-semibold tabular-nums ${
          muted ? 'text-text-dim' : highlight ? 'text-accent-cyan' : 'text-text'
        }`}
      >
        {value}
      </p>
      <p className="text-[10px] text-text-dim uppercase tracking-wider mt-0.5">{label}</p>
    </div>
  )
}

// ── Campaign detail view ─────────────────────────────────

function CampaignDetailView({ id }: { id: string }) {
  const { namespace } = useParams<{ namespace: string }>()
  const [range, setRange] = useState<RangeKey>('7d')
  // Live SSE stream (BL-1039). When connected, it pushes snapshot + deltas
  // and we disable the polling refetch cadence. When disconnected (initial
  // boot, transient error, server ended stream), polling takes over so the
  // UI never goes stale.
  const { metrics: streamMetrics, connected: streamConnected } =
    useCampaignAnalyticsStream<CampaignAnalyticsData>(id)
  const {
    data: polledData,
    isLoading,
    error,
    refetch,
  } = useCampaignAnalytics(id, !streamConnected)
  const data = streamMetrics ?? polledData ?? null
  const echoHomePath = namespace ? `/${namespace}/echo` : '/echo'
  // TODO(BL-1044): route to the Gmail-connect flow once settings page exists.
  const gmailConnectPath = namespace ? `/${namespace}/preferences` : '/preferences'

  // Only show the skeleton on the very first load — once a stream
  // snapshot or a polled payload has arrived we always prefer the live
  // UI over a blank loading state.
  if (isLoading && !data) {
    return <DetailSkeleton />
  }
  if (error && !data) {
    return (
      <ErrorCard
        message={error instanceof Error ? error.message : 'Failed to load analytics'}
        onRetry={() => refetch()}
      />
    )
  }
  if (!data) {
    return (
      <div className="py-16 text-center text-sm text-text-muted">
        No events recorded yet for this campaign.
      </div>
    )
  }

  const analytics = data as AnalyticsWithMicrosite
  const micrositeAvailable = analytics.posthog_available !== false
  const microsite = analytics.microsite

  const email = analytics.sending?.email ?? {
    total: 0,
    queued: 0,
    sent: 0,
    delivered: 0,
    bounced: 0,
    failed: 0,
  }
  const engagement = analytics.engagement
  const sentTotal = email.sent + email.delivered + email.bounced + email.failed
  const deliveryRate = pct(email.delivered, sentTotal)
  const openRate = engagement?.open_rate ?? 0
  const clickRate = engagement?.click_rate ?? 0
  const ctr = engagement?.click_rate ?? 0 // hero KPI per spec

  return (
    <div className="flex flex-col gap-6">
      {/* Header row */}
      <div className="flex items-center justify-between gap-4">
        <Link
          to={echoHomePath}
          className="flex items-center gap-1 text-xs text-text-muted hover:text-accent-cyan no-underline"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7.5 2.5L4 6l3.5 3.5" />
          </svg>
          All campaigns
        </Link>
        <div className="flex items-center gap-3">
          <LiveIndicator connected={streamConnected} />
          <RangeSelector value={range} onChange={setRange} />
        </div>
      </div>

      {/* Hero KPI — CTR */}
      <HeroKpi
        label="Click-through rate"
        value={`${ctr}%`}
        sub={`${engagement?.clicked ?? 0} clicks on ${email.delivered} delivered`}
      />

      {/* Supporting KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiTile label="Sent" value={formatNumber(sentTotal)} />
        <KpiTile label="Delivered" value={`${deliveryRate}%`} sub={`${email.delivered} emails`} />
        <KpiTile
          label="Open rate"
          value={`${openRate}%`}
          sub={`${engagement?.opened ?? 0} opens`}
        />
        <KpiTile
          label="Click rate"
          value={`${clickRate}%`}
          sub={`${engagement?.clicked ?? 0} clicks`}
        />
        <KpiTile
          label="Microsite visits"
          value={microsite ? String(microsite.visits ?? 0) : '—'}
          sub={microsite ? `${microsite.unique_visitors ?? 0} unique` : 'no data'}
        />
        <KpiTile
          label="Reply rate"
          value="—"
          sub={
            <span className="flex flex-col gap-0.5">
              <span className="text-[11px] text-text-dim">Connect Gmail to track replies</span>
              <Link
                to={gmailConnectPath}
                className="text-[11px] text-accent-cyan hover:underline no-underline"
              >
                Connect →
              </Link>
            </span>
          }
        />
      </div>

      {/* Funnel */}
      <Section title="Funnel">
        <FunnelChart
          stages={[
            { label: 'Sent', value: sentTotal },
            { label: 'Delivered', value: email.delivered },
            { label: 'Opened', value: engagement?.opened ?? 0 },
            { label: 'Clicked', value: engagement?.clicked ?? 0 },
            { label: 'Microsite', value: microsite?.unique_visitors ?? 0 },
          ]}
        />
      </Section>

      {/* Time series */}
      <Section title="Activity over time">
        <Suspense
          fallback={
            <div className="bg-surface-alt border border-border rounded-lg h-64 animate-pulse" />
          }
        >
          <TimeSeriesBlock campaignId={id} range={range} />
        </Suspense>
      </Section>

      {/* Microsite metrics */}
      <Section title="Microsite engagement">
        {!micrositeAvailable && (
          <div className="mb-3 bg-warning/10 border border-warning/30 rounded-lg px-3 py-2 text-xs text-warning">
            Microsite analytics temporarily unavailable — PostHog connection is offline.
          </div>
        )}
        <MicrositeBlock microsite={microsite} contactsTotal={analytics.contacts?.total ?? 0} />
      </Section>

      {/* Contact drill-down */}
      <Section title="Contacts">
        <ContactDrillTable campaignId={id} />
      </Section>
    </div>
  )
}

// ── Live indicator ───────────────────────────────────────

/**
 * Small badge showing whether the SSE analytics stream is open.
 * Green "Live" when connected, grey "Polling" when the 10s fallback
 * is driving the numbers. Static — the colour-coded dot does the
 * "pulsing" heavy lifting; no animation needed.
 */
function LiveIndicator({ connected }: { connected: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-dim"
      title={
        connected
          ? 'Live stream — analytics update as events arrive'
          : 'Polling every 10s — live stream disconnected'
      }
      aria-live="polite"
      data-testid="analytics-live-indicator"
    >
      <span
        className={`inline-block w-2 h-2 rounded-full ${
          connected ? 'bg-success' : 'bg-text-dim'
        }`}
        aria-hidden="true"
      />
      {connected ? 'Live' : 'Polling'}
    </span>
  )
}

// ── Range selector ───────────────────────────────────────

function RangeSelector({
  value,
  onChange,
}: {
  value: RangeKey
  onChange: (v: RangeKey) => void
}) {
  const options: RangeKey[] = ['24h', '7d', '30d', 'all']
  return (
    <div className="inline-flex rounded-md border border-border overflow-hidden text-xs">
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={`px-3 py-1 border-none cursor-pointer transition-colors ${
            value === opt
              ? 'bg-accent text-white'
              : 'bg-transparent text-text-muted hover:text-text'
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

// ── Hero KPI card ────────────────────────────────────────

function HeroKpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface border border-border rounded-lg px-6 py-5">
      <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
      <p className="text-4xl font-semibold text-accent-cyan tabular-nums mt-1">{value}</p>
      {sub && <p className="text-xs text-text-dim mt-2">{sub}</p>}
    </div>
  )
}

// ── KPI tile ─────────────────────────────────────────────

function KpiTile({
  label,
  value,
  sub,
}: {
  label: string
  value: string | number
  sub?: React.ReactNode
}) {
  return (
    <div className="bg-surface-alt border border-border rounded-lg px-4 py-3">
      <p className="text-xl font-semibold text-text tabular-nums">{value}</p>
      <p className="text-xs text-text-muted mt-0.5">{label}</p>
      {sub !== undefined && sub !== null && (
        // Only wrap plain strings in a <p>; ReactNode children may include block
        // elements (e.g., flex-column Link), so we can't nest inside <p>.
        typeof sub === 'string' ? (
          <p className="text-[11px] text-text-dim mt-0.5">{sub}</p>
        ) : (
          <div className="text-[11px] text-text-dim mt-0.5">{sub}</div>
        )
      )}
    </div>
  )
}

// ── Section wrapper ──────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
        {title}
      </h3>
      {children}
    </div>
  )
}

// ── Funnel (hand-rolled Tailwind) ────────────────────────

function FunnelChart({ stages }: { stages: Array<{ label: string; value: number }> }) {
  const max = Math.max(1, ...stages.map((s) => s.value))
  return (
    <div>
      <div className="space-y-2">
        {stages.map((s, idx) => {
          const width = (s.value / max) * 100
          const prev = idx > 0 ? stages[idx - 1].value : max
          const dropoff = idx > 0 ? prev - s.value : 0
          const rate = idx > 0 ? pct(s.value, prev) : 100
          return (
            <div key={s.label} className="flex items-center gap-3">
              <span className="text-xs text-text-muted w-24 shrink-0">{s.label}</span>
              <div className="flex-1 h-6 bg-surface-alt rounded-md overflow-hidden border border-border">
                <div
                  className="h-full bg-accent-cyan transition-all duration-500"
                  style={{ width: `${Math.max(width, 2)}%` }}
                />
              </div>
              <span className="text-xs text-text tabular-nums w-20 text-right">
                {formatNumber(s.value)}
              </span>
              <span className="text-[11px] text-text-dim tabular-nums w-12 text-right">
                {idx === 0 ? '' : `${rate}%`}
              </span>
              <span className="text-[11px] text-text-dim tabular-nums w-16 text-right">
                {idx === 0 || dropoff === 0 ? '' : `-${formatNumber(dropoff)}`}
              </span>
            </div>
          )
        })}
      </div>

      <details className="mt-2">
        <summary className="cursor-pointer text-text-muted hover:text-text text-xs">
          View as table
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider">
                  Stage
                </th>
                <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                  Count
                </th>
                <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                  Stage rate
                </th>
                <th className="py-1 font-semibold text-text-dim uppercase tracking-wider text-right">
                  Drop-off
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {stages.map((s, idx) => {
                const prev = idx > 0 ? stages[idx - 1].value : max
                const dropoff = idx > 0 ? prev - s.value : 0
                const rate = idx > 0 ? pct(s.value, prev) : 100
                return (
                  <tr key={s.label}>
                    <td className="py-1 pr-3 text-text-muted">{s.label}</td>
                    <td className="py-1 pr-3 text-text tabular-nums text-right">
                      {s.value}
                    </td>
                    <td className="py-1 pr-3 text-text tabular-nums text-right">
                      {idx === 0 ? '—' : `${rate}%`}
                    </td>
                    <td className="py-1 text-text tabular-nums text-right">
                      {idx === 0 || dropoff === 0 ? '—' : `-${dropoff}`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

// ── Time series ──────────────────────────────────────────
// Component extracted to ./echo/TimeSeriesBlock.tsx and lazy-loaded above.
// Data source: /api/campaigns/:id/analytics/timeseries (BL-1037).

// ── Microsite block ──────────────────────────────────────

function MicrositeBlock({
  microsite,
  contactsTotal,
}: {
  microsite?: MicrositePayload
  contactsTotal: number
}) {
  if (!microsite) {
    return (
      <div className="bg-surface-alt border border-border rounded-lg px-4 py-6 text-center text-xs text-text-dim">
        No microsite data yet.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <KpiTile label="Total visits" value={microsite.visits} />
      <KpiTile label="Unique visitors" value={microsite.unique_visitors} />
      <KpiTile label="Product views" value={microsite.product_views} />
      <KpiTile
        label="Visit rate"
        value={`${microsite.visit_rate ?? pct(microsite.unique_visitors, contactsTotal)}%`}
      />
    </div>
  )
}

// ── Contact drill table ──────────────────────────────────

function ContactDrillTable({ campaignId }: { campaignId: string }) {
  const { data, isLoading, error } = useCampaignRecipients(campaignId)

  if (isLoading) {
    return (
      <div className="bg-surface-alt border border-border rounded-lg px-4 py-6 text-center text-xs text-text-dim">
        Loading contacts…
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="bg-surface-alt border border-border rounded-lg px-4 py-6 text-center text-xs text-text-dim">
        Unable to load contact activity.
      </div>
    )
  }

  const rows = data.recipients.slice(0, 50) // cap for performance; real pagination is a follow-up
  if (rows.length === 0) {
    return (
      <div className="bg-surface-alt border border-border rounded-lg px-4 py-6 text-center text-xs text-text-dim">
        No recipients in this campaign yet.
      </div>
    )
  }

  return (
    <div className="bg-surface-alt border border-border rounded-lg overflow-hidden">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider">
              Contact
            </th>
            <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider">
              Email
            </th>
            <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider text-right">
              Events
            </th>
            <th className="px-4 py-2 text-[11px] font-semibold text-text-dim uppercase tracking-wider">
              Last activity
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => {
            const last = r.timeline[r.timeline.length - 1]
            const lastLabel = last
              ? 'type' in last
                ? last.type
                : 'event'
              : '—'
            const lastTs = last?.ts ? new Date(last.ts).toLocaleString() : '—'
            return (
              <tr key={r.campaign_contact_id}>
                <td className="px-4 py-2 text-xs text-text">{r.name}</td>
                <td className="px-4 py-2 text-xs text-text-muted">{r.email}</td>
                <td className="px-4 py-2 text-xs text-text tabular-nums text-right">
                  {r.timeline.length}
                </td>
                <td className="px-4 py-2 text-xs text-text-muted">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="text-text">{String(lastLabel)}</span>
                    <span className="text-text-dim">{lastTs}</span>
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {data.recipients.length > 50 && (
        <div className="px-4 py-2 text-[11px] text-text-dim border-t border-border">
          Showing first 50 of {data.recipients.length} recipients.
        </div>
      )}
    </div>
  )
}

// ── Shared loading / error ───────────────────────────────

function ListSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-pulse">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="bg-surface border border-border rounded-lg h-[120px]" />
      ))}
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6 animate-pulse">
      <div className="bg-surface border border-border rounded-lg h-24" />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="bg-surface-alt border border-border rounded-lg h-[72px]" />
        ))}
      </div>
      <div className="bg-surface-alt border border-border rounded-lg h-48" />
      <div className="bg-surface-alt border border-border rounded-lg h-64" />
    </div>
  )
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="bg-error/10 border border-error/30 rounded-lg px-4 py-6 text-center">
      <p className="text-sm font-medium text-error mb-1">Something went wrong</p>
      <p className="text-xs text-text-dim mb-3">{message}</p>
      <button
        onClick={onRetry}
        className="px-3 py-1 text-xs font-medium rounded bg-transparent text-text-muted border border-border cursor-pointer hover:text-text hover:border-accent transition-colors"
      >
        Retry
      </button>
    </div>
  )
}
