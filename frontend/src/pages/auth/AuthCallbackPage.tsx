/**
 * IAM OAuth callback page — receives tokens from URL hash after backend code exchange.
 *
 * Flow:
 * 1. User clicks SSO button -> IAM OAuth -> IAM redirects to /api/auth/iam/callback?code=X
 * 2. Backend exchanges code, syncs user, redirects to /auth/callback#access_token=...&user=...
 * 3. This page extracts tokens from hash, stores them, and redirects to the app.
 */

import { useEffect, useState } from 'react'
import { storeTokens, storeUser, getDefaultNamespace, type StoredUser } from '../../lib/auth'

export function AuthCallbackPage() {
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    try {
      // Parse tokens from URL hash fragment
      const hash = window.location.hash.slice(1) // remove leading #
      if (!hash) {
        setError('No authentication data received. Please try logging in again.')
        return
      }

      const params = new URLSearchParams(hash)
      const accessToken = params.get('access_token')
      const refreshToken = params.get('refresh_token')
      const userJson = params.get('user')

      if (!accessToken) {
        setError('No access token received. Please try logging in again.')
        return
      }

      // Store tokens
      storeTokens(accessToken, refreshToken || undefined)

      // Store user data
      let user: StoredUser | null = null
      if (userJson) {
        try {
          user = JSON.parse(userJson) as StoredUser
          storeUser(user)
        } catch {
          // User data parsing failed — tokens are stored, /api/auth/me will fill in user
        }
      }

      // Clear the hash from the URL (security: remove tokens from browser history)
      window.history.replaceState(null, '', '/auth/callback')

      // Clear SSO check flag on successful authentication
      sessionStorage.removeItem('sso_checked')

      // Redirect to the app — use full page reload so AuthProvider re-initializes
      // with tokens already in localStorage (SPA navigate would see stale isAuthenticated)
      const ns = user ? getDefaultNamespace(user) : null
      if (ns) {
        window.location.href = user?.is_super_admin ? `/${ns}/admin` : `/${ns}/contacts`
      } else {
        window.location.href = '/'
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication callback failed')
    }
  }, [])

  if (error) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-bg">
        <div className="max-w-[400px] px-10 py-11 bg-surface/85 backdrop-blur-[24px] border border-accent/20 rounded-[20px] shadow-2xl text-center">
          <div className="text-error text-[0.9rem] mb-4">{error}</div>
          <a
            href="/"
            className="inline-block px-6 py-2.5 rounded-[10px] text-white text-[0.85rem] font-semibold no-underline"
            style={{ background: 'linear-gradient(135deg, #6E2C8B, #4A1D5E)' }}
          >
            Back to Login
          </a>
        </div>
      </div>
    )
  }

  // Loading state while processing tokens
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-bg">
      <div className="text-text-muted text-[0.9rem]">Completing sign-in...</div>
    </div>
  )
}
