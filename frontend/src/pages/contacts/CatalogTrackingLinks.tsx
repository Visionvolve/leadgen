/**
 * "Catalog tracking links" section on the Contact detail page (BL-1104).
 *
 * Operators click "Generate link with prices" or "Generate link without
 * prices" to issue (or reuse) a unique tracking URL pointing at the UA
 * microsite. Each visit is recorded against the contact for downstream
 * analytics. The component shows:
 *
 * * Two buttons (one per variant) with last-generated URL + copy.
 * * A table of all tokens for the contact with visit counts +
 *   first/last visit timestamps.
 */

import { useState } from 'react'
import {
  useContactRefTokens,
  useIssueRefToken,
  type RefTokenRow,
  type RefTokenVariant,
} from '../../api/queries/useRefTokens'
import { useToast } from '../../components/ui/Toast'
import { SectionDivider } from '../../components/ui/DetailField'

interface Props {
  contactId: string
}

const VARIANT_LABEL: Record<RefTokenVariant, string> = {
  with_prices: 'with prices',
  without_prices: 'without prices',
}

function formatTs(ts: string | null): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

export function CatalogTrackingLinks({ contactId }: Props) {
  const { toast } = useToast()
  const { data, isLoading } = useContactRefTokens(contactId)
  const issue = useIssueRefToken()
  const [busyVariant, setBusyVariant] = useState<RefTokenVariant | null>(null)

  const handleGenerate = async (variant: RefTokenVariant) => {
    setBusyVariant(variant)
    try {
      const resp = await issue.mutateAsync({ contactId, variant })
      try {
        await navigator.clipboard.writeText(resp.url)
        toast(
          resp.reused
            ? `Existing ${VARIANT_LABEL[variant]} link copied`
            : `New ${VARIANT_LABEL[variant]} link copied`,
          'success',
        )
      } catch {
        // Clipboard may be blocked (e.g. http context) — still show URL via toast.
        toast(`Link ready: ${resp.url}`, 'info')
      }
    } catch {
      toast('Failed to generate link', 'error')
    } finally {
      setBusyVariant(null)
    }
  }

  const handleCopy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      toast('URL copied', 'success')
    } catch {
      toast('Copy not supported', 'error')
    }
  }

  const tokens: RefTokenRow[] = data?.tokens ?? []

  return (
    <div className="space-y-3" data-testid="catalog-tracking-links">
      <SectionDivider title="Catalog tracking links" />
      <p className="text-xs text-text-muted -mt-1">
        Generate a unique URL for this contact. Visits are tracked per token.
      </p>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => handleGenerate('with_prices')}
          disabled={busyVariant !== null}
          className="px-3 py-1.5 text-sm font-medium rounded-md bg-accent hover:bg-accent-hover text-white disabled:opacity-50"
        >
          {busyVariant === 'with_prices' ? 'Generating…' : 'Generate link with prices'}
        </button>
        <button
          type="button"
          onClick={() => handleGenerate('without_prices')}
          disabled={busyVariant !== null}
          className="px-3 py-1.5 text-sm font-medium rounded-md bg-surface-alt border border-border-solid hover:border-accent/50 text-text disabled:opacity-50"
        >
          {busyVariant === 'without_prices'
            ? 'Generating…'
            : 'Generate link without prices'}
        </button>
      </div>

      {isLoading && (
        <div className="text-xs text-text-dim">Loading tokens…</div>
      )}

      {!isLoading && tokens.length === 0 && (
        <div className="text-xs text-text-dim">No tracking links yet.</div>
      )}

      {tokens.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="text-left text-text-muted border-b border-border-solid">
                <th className="py-1.5 pr-2 font-medium">Variant</th>
                <th className="py-1.5 pr-2 font-medium">URL</th>
                <th className="py-1.5 pr-2 font-medium">Visits</th>
                <th className="py-1.5 pr-2 font-medium">First</th>
                <th className="py-1.5 pr-2 font-medium">Last</th>
                <th className="py-1.5 pr-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr
                  key={t.token}
                  className={`border-b border-border-solid/40 ${t.is_expired ? 'opacity-50' : ''}`}
                >
                  <td className="py-1.5 pr-2 whitespace-nowrap">
                    <span
                      className={
                        t.variant === 'without_prices'
                          ? 'text-text'
                          : 'text-accent-hover'
                      }
                    >
                      {VARIANT_LABEL[t.variant]}
                    </span>
                    {t.is_expired && (
                      <span className="ml-1 text-text-dim">(expired)</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2 max-w-[24ch] truncate">
                    <button
                      type="button"
                      onClick={() => handleCopy(t.url)}
                      title={t.url}
                      className="text-accent hover:underline"
                    >
                      copy URL
                    </button>
                  </td>
                  <td className="py-1.5 pr-2">{t.visit_count}</td>
                  <td className="py-1.5 pr-2 whitespace-nowrap">
                    {formatTs(t.first_visited_at)}
                  </td>
                  <td className="py-1.5 pr-2 whitespace-nowrap">
                    {formatTs(t.last_visited_at)}
                  </td>
                  <td className="py-1.5 pr-2 whitespace-nowrap text-text-dim">
                    {formatTs(t.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
