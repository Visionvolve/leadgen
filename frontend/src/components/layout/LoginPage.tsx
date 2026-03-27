/**
 * Login page — full-screen overlay with brand card.
 * Email/password as primary login, SSO (Google, GitHub) as secondary.
 */

import { useState, useEffect, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useAuth } from '../../hooks/useAuth'
import { getDefaultNamespace } from '../../lib/auth'

export function LoginPage() {
  const { isAuthenticated, user, login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const [entered, setEntered] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Handle IAM redirect error params (?error=..., ?login_required=true)
  useEffect(() => {
    const iamError = searchParams.get('error')
    const loginRequired = searchParams.get('login_required')

    if (iamError) {
      const errorMessages: Record<string, string> = {
        token_exchange_failed: 'Sign-in failed. Please try again.',
        iam_unreachable: 'Authentication service is temporarily unavailable.',
        iam_not_configured: 'Single sign-on is not configured.',
        missing_code: 'Invalid authentication response. Please try again.',
        no_access_token: 'Sign-in failed. Please try again.',
        invalid_token: 'Invalid authentication response. Please try again.',
        user_sync_failed: 'Account setup failed. Please try again.',
      }
      setError(errorMessages[iamError] || `Sign-in error: ${iamError}`)
    } else if (loginRequired === 'true') {
      setError('Please sign in to continue.')
    }
  }, [searchParams])

  // Card entrance animation
  useEffect(() => {
    const timer = requestAnimationFrame(() => setEntered(true))
    return () => cancelAnimationFrame(timer)
  }, [])

  // Redirect if already authenticated
  useEffect(() => {
    if (!isAuthenticated || !user) return

    const returnUrl = searchParams.get('return')
    if (returnUrl && returnUrl.startsWith('/') && returnUrl !== '/' && returnUrl !== '/index.html') {
      navigate(returnUrl, { replace: true })
      return
    }

    const ns = getDefaultNamespace(user)
    if (ns) {
      navigate(user.is_super_admin ? `/${ns}/admin` : `/${ns}/contacts`, { replace: true })
    }
  }, [isAuthenticated, user, navigate, searchParams])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (isSubmitting) return

    setError(null)
    setIsSubmitting(true)

    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Don't render login form if already authenticated (will redirect via useEffect)
  if (isAuthenticated) return null

  const inputClass =
    'w-full px-4 py-3 bg-bg/60 border border-accent/20 rounded-[10px] text-text text-[0.9rem] font-body placeholder:text-text-muted/40 focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all'

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden">
      {/* Animated mesh background */}
      <div className="absolute inset-0 bg-bg">
        <div className="absolute inset-[-50%] w-[200%] h-[200%] animate-[authMeshDrift_20s_ease-in-out_infinite_alternate]"
          style={{
            background: 'radial-gradient(ellipse at 30% 20%, rgba(110,44,139,.18) 0%, transparent 50%), radial-gradient(ellipse at 70% 80%, rgba(0,184,207,.12) 0%, transparent 50%), radial-gradient(ellipse at 50% 50%, rgba(74,29,94,.1) 0%, transparent 60%)',
          }}
        />
      </div>

      {/* Grid overlay */}
      <div className="absolute inset-0"
        style={{
          backgroundImage: 'linear-gradient(rgba(110,44,139,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(110,44,139,.04) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 70%)',
        }}
      />

      {/* Vignette */}
      <div className="absolute inset-0"
        style={{ background: 'radial-gradient(ellipse at center, transparent 40%, rgba(13,15,20,.8) 100%)' }}
      />

      {/* Card */}
      <div className={`relative w-full max-w-[400px] px-10 py-11 bg-surface/85 backdrop-blur-[24px] saturate-150 border border-accent/20 rounded-[20px] shadow-2xl transition-all duration-700 ${
        entered ? 'opacity-100 translate-y-0 scale-100' : 'opacity-0 translate-y-5 scale-[0.98]'
      }`}>
        {/* Brand */}
        <div className="text-center mb-7">
          <div className="flex justify-center mb-4">
            <img src="/visionvolve-logo-white.svg" alt="VisionVolve" className="h-10 w-auto" />
          </div>
          <div className="font-title text-2xl font-bold tracking-tight text-text">Leadgen</div>
          <div className="font-body text-[0.75rem] font-normal tracking-[0.12em] uppercase text-text-muted/70 mt-2">
            Pipeline Command Center
          </div>
        </div>

        {/* Divider */}
        <div className="h-px mb-7"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(110,44,139,.3) 30%, rgba(0,184,207,.2) 70%, transparent)' }}
        />

        {/* Error */}
        {error && (
          <div className="text-error text-[0.82rem] text-center mb-5 px-3.5 py-2.5 bg-error/6 border border-error/15 rounded-lg animate-[authShake_0.4s_ease]">
            {error}
          </div>
        )}

        {/* Email/password form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5 font-body mb-5">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email address"
            required
            autoComplete="email"
            autoFocus
            disabled={isSubmitting}
            className={inputClass}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            required
            autoComplete="current-password"
            disabled={isSubmitting}
            className={inputClass}
          />
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3.5 bg-accent/90 border border-accent/40 rounded-[10px] text-white text-[0.9rem] font-semibold hover:bg-accent hover:translate-y-[-1px] hover:shadow-[0_4px_20px_-2px_rgba(110,44,139,.4)] active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 transition-all cursor-pointer"
          >
            {isSubmitting ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Signing in...
              </span>
            ) : (
              'Sign in'
            )}
          </button>
        </form>

        {/* OR divider */}
        <div className="flex items-center gap-3 mb-5">
          <div className="flex-1 h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(110,44,139,.2))' }} />
          <span className="text-[0.72rem] tracking-[0.08em] uppercase text-text-muted/40 font-body">or</span>
          <div className="flex-1 h-px" style={{ background: 'linear-gradient(90deg, rgba(110,44,139,.2), transparent)' }} />
        </div>

        {/* SSO buttons */}
        <div className="flex flex-col gap-3 font-body">
          <a
            href={`${import.meta.env.VITE_IAM_BASE_URL || 'https://iam.visionvolve.com'}/auth/oauth/google?redirect=${encodeURIComponent(window.location.origin + '/api/auth/iam/callback')}`}
            className="flex items-center justify-center gap-2.5 w-full py-3 bg-bg/60 border border-accent/20 rounded-[10px] text-text text-[0.82rem] font-semibold no-underline hover:border-accent/40 hover:bg-bg/80 hover:translate-y-[-1px] hover:shadow-[0_4px_20px_-2px_rgba(110,44,139,.3)] active:translate-y-0 transition-all cursor-pointer"
          >
            <svg width="16" height="16" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
            Sign in with Google
          </a>
          <a
            href={`${import.meta.env.VITE_IAM_BASE_URL || 'https://iam.visionvolve.com'}/auth/oauth/github?redirect=${encodeURIComponent(window.location.origin + '/api/auth/iam/callback')}`}
            className="flex items-center justify-center gap-2.5 w-full py-3 bg-bg/60 border border-accent/20 rounded-[10px] text-text text-[0.82rem] font-semibold no-underline hover:border-accent/40 hover:bg-bg/80 hover:translate-y-[-1px] hover:shadow-[0_4px_20px_-2px_rgba(110,44,139,.3)] active:translate-y-0 transition-all cursor-pointer"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
            Sign in with GitHub
          </a>
        </div>

        {/* Secure badge */}
        <div className="flex items-center justify-center gap-1.5 mt-6 text-[0.72rem] tracking-[0.04em] text-text-muted/45">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-50">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <span>Encrypted connection</span>
        </div>
      </div>
    </div>
  )
}
