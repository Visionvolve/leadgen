/**
 * Time-series block for EchoPage.
 *
 * Lazy-loaded so Recharts (~95 kB) stays out of the main bundle. Consumed
 * by `EchoPage.tsx` via `React.lazy`.
 *
 * Data source: `/api/campaigns/:id/analytics/timeseries` (BL-1037). The
 * server zero-fills empty buckets so the chart renders a continuous line
 * without client-side padding.
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import {
  useCampaignAnalyticsTimeseries,
  type TimeSeriesRange,
  type TimeSeriesBucketPoint,
} from '../../api/queries/useCampaigns'

export interface TimeSeriesBlockProps {
  campaignId: string
  range: TimeSeriesRange
  /**
   * When true, renders a denser chart suitable for embedding in a tab or
   * side-by-side grid (shorter height, smaller tick fonts, tighter padding).
   * The accessibility <details> table is preserved in both modes.
   */
  compact?: boolean
}

export default function TimeSeriesBlock({
  campaignId,
  range,
  compact = false,
}: TimeSeriesBlockProps) {
  const { data, isLoading, error } = useCampaignAnalyticsTimeseries(campaignId, range)

  const wrapperSize = compact ? 'h-[200px] p-2' : 'h-64 p-3'
  const tickFont = compact ? 10 : 11

  if (isLoading && !data) {
    return (
      <div
        className={`bg-surface-alt border border-border rounded-lg ${wrapperSize} animate-pulse`}
      />
    )
  }

  if (error) {
    return (
      <div
        className={`bg-surface-alt border border-border rounded-lg px-4 ${
          compact ? 'py-6' : 'py-8'
        } text-center`}
      >
        <p className="text-xs text-text-dim">
          Unable to load activity time series.
        </p>
      </div>
    )
  }

  const buckets = data?.buckets ?? []
  const activeBucket = data?.bucket ?? (range === '24h' ? 'hour' : 'day')

  const hasData = buckets.some(
    (b) => b.delivered + b.opened + b.clicked + b.sent + b.bounced > 0,
  )

  if (!hasData) {
    return (
      <div
        className={`bg-surface-alt border border-border rounded-lg px-4 ${
          compact ? 'py-6' : 'py-8'
        } text-center`}
      >
        <p className="text-xs text-text-dim">
          No activity yet in the selected {range} window.
        </p>
      </div>
    )
  }

  // Chart data uses a formatted label, but we keep the raw timestamp on each
  // row so the accessibility table below can show it in its native form.
  const series = buckets.map((b) => ({
    ...b,
    label: formatBucketLabel(b.bucket_start, activeBucket),
  }))

  return (
    <>
      <div className={`bg-surface-alt border border-border rounded-lg ${wrapperSize}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={series}
            margin={
              compact
                ? { top: 6, right: 12, bottom: 2, left: -12 }
                : { top: 8, right: 16, bottom: 4, left: -8 }
            }
          >
            <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.15} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: tickFont }}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <YAxis
              tick={{ fontSize: tickFont }}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface, #1a1f2e)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '6px',
                fontSize: '11px',
              }}
            />
            <Line
              type="monotone"
              dataKey="delivered"
              name="Delivered"
              stroke="#00B8CF"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="opened"
              name="Opened"
              stroke="#8b5cf6"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="clicked"
              name="Clicked"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <TimeSeriesA11yTable buckets={buckets} bucketUnit={activeBucket} />
    </>
  )
}

function TimeSeriesA11yTable({
  buckets,
  bucketUnit,
}: {
  buckets: TimeSeriesBucketPoint[]
  bucketUnit: 'hour' | 'day'
}) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-text-muted hover:text-text text-xs">
        View as table
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider">
                Bucket
              </th>
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                Sent
              </th>
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                Delivered
              </th>
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                Opened
              </th>
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                Clicked
              </th>
              <th className="py-1 pr-3 font-semibold text-text-dim uppercase tracking-wider text-right">
                Bounced
              </th>
              <th className="py-1 font-semibold text-text-dim uppercase tracking-wider text-right">
                Unsub
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {buckets.map((b) => (
              <tr key={b.bucket_start}>
                <td className="py-1 pr-3 text-text-muted">
                  {formatBucketLabel(b.bucket_start, bucketUnit)}
                </td>
                <td className="py-1 pr-3 text-text tabular-nums text-right">{b.sent}</td>
                <td className="py-1 pr-3 text-text tabular-nums text-right">
                  {b.delivered}
                </td>
                <td className="py-1 pr-3 text-text tabular-nums text-right">{b.opened}</td>
                <td className="py-1 pr-3 text-text tabular-nums text-right">{b.clicked}</td>
                <td className="py-1 pr-3 text-text tabular-nums text-right">
                  {b.bounced}
                </td>
                <td className="py-1 text-text tabular-nums text-right">{b.unsubscribed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

function formatBucketLabel(iso: string, bucketUnit: 'hour' | 'day'): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  if (bucketUnit === 'hour') {
    return d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: false }) + ':00'
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
