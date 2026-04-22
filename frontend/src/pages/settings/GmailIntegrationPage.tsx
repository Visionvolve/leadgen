/**
 * GmailIntegrationPage (BL-1044 foundation).
 *
 * Connects / disconnects the tenant's Gmail inbox for inbound-mail tracking.
 * Inbound polling and reply attribution land in follow-up sub-items
 * (BL-1044-b, BL-1044-c).
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { apiFetch } from '../../api/client'
import { getNamespaceFromPath } from '../../lib/auth'

interface GmailStatus {
  connected: boolean
  email: string | null
  last_synced_at: string | null
  scopes?: string[]
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function GmailIntegrationPage() {
  const { namespace } = useParams<{ namespace: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<GmailStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [disconnecting, setDisconnecting] = useState(false)
  const justConnected = searchParams.get('connected') === '1'

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<GmailStatus>('/auth/gmail/status')
      setStatus(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Clear the `?connected=1` flag after showing the confirmation banner once.
  useEffect(() => {
    if (justConnected) {
      const timer = setTimeout(() => {
        searchParams.delete('connected')
        setSearchParams(searchParams, { replace: true })
      }, 4000)
      return () => clearTimeout(timer)
    }
  }, [justConnected, searchParams, setSearchParams])

  const handleConnect = async () => {
    // OAuth consent flow happens in a top-level navigation. Browsers cannot
    // attach the Authorization header to `window.location` navigations, so we
    // fetch the authorization URL (authed) and then navigate to it.
    setError(null)
    try {
      const ns = getNamespaceFromPath() || namespace || ''
      const returnPath = ns ? `/${ns}/settings/gmail?connected=1` : '/'
      const data = await apiFetch<{ auth_url: string }>(
        `/auth/gmail/connect?format=json&return=${encodeURIComponent(returnPath)}`,
      )
      if (!data.auth_url) {
        throw new Error('Backend returned no auth_url')
      }
      window.location.href = data.auth_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start connect flow')
    }
  }

  const handleDisconnect = async () => {
    if (!window.confirm('Disconnect your Gmail inbox? Reply tracking will stop.')) {
      return
    }
    setDisconnecting(true)
    setError(null)
    try {
      await apiFetch('/auth/gmail/disconnect', { method: 'POST' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect')
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <div className="max-w-[720px] mx-auto px-6 py-8">
      <h1 className="font-title text-[1.5rem] font-semibold tracking-tight mb-2">
        Gmail Integration
      </h1>
      <p className="text-text-muted text-sm mb-6">
        Connect your Gmail inbox so we can track replies to outreach messages
        and compute reply rates. We request read-only access only.
      </p>

      {justConnected && (
        <div className="mb-4 p-3 rounded-md bg-success/10 border border-success/30 text-success text-sm">
          Gmail connected successfully.
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 rounded-md bg-error/10 border border-error/30 text-error text-sm"
        >
          {error}
        </div>
      )}

      <div className="bg-surface border border-border rounded-lg p-5">
        {loading && <p className="text-text-muted text-sm">Loading...</p>}

        {!loading && status && !status.connected && (
          <div>
            <h2 className="font-title text-[1rem] font-semibold mb-2">
              Not connected
            </h2>
            <p className="text-text-muted text-sm mb-4">
              Connect Gmail to unlock reply-rate analytics. Tokens are
              encrypted at rest and scoped to{' '}
              <code className="text-xs">gmail.readonly</code>.
            </p>
            <button
              onClick={handleConnect}
              className="px-4 py-2 rounded-md bg-accent-cyan text-bg font-medium text-sm hover:opacity-90 transition-opacity"
            >
              Connect Gmail
            </button>
          </div>
        )}

        {!loading && status && status.connected && (
          <div>
            <h2 className="font-title text-[1rem] font-semibold mb-2">
              Connected
            </h2>
            <dl className="text-sm mb-4 space-y-2">
              <div className="flex gap-3">
                <dt className="text-text-muted w-32">Email</dt>
                <dd className="text-text">{status.email}</dd>
              </div>
              <div className="flex gap-3">
                <dt className="text-text-muted w-32">Last synced</dt>
                <dd className="text-text">{formatTimestamp(status.last_synced_at)}</dd>
              </div>
            </dl>
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              className="px-4 py-2 rounded-md bg-error/10 border border-error/40 text-error font-medium text-sm hover:bg-error/20 transition-colors disabled:opacity-50"
            >
              {disconnecting ? 'Disconnecting...' : 'Disconnect Gmail'}
            </button>
          </div>
        )}
      </div>

      <p className="mt-4 text-xs text-text-muted/70">
        Inbound message polling and reply attribution are rolling out in a
        follow-up release. Connecting now ensures we can start tracking
        replies as soon as the feature ships.
      </p>
    </div>
  )
}
