import { useEffect, type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router'

interface EntityDetailPageProps {
  /** URL of the origin list (e.g. `/${namespace}/companies`) — X button target */
  closeTo: string
  title: string
  subtitle?: string
  isLoading?: boolean
  children: ReactNode
  /**
   * BL-1203 / Phase 12: when supplied, replaces the static `<h2>{title}</h2>`
   * heading with this slot — used by CompanyDetailPage to render an
   * inline-editable name.
   */
  titleSlot?: ReactNode
}

export function EntityDetailPage({ closeTo, title, subtitle, isLoading, children, titleSlot }: EntityDetailPageProps) {
  const navigate = useNavigate()
  const location = useLocation()

  // Origin from location state, fallback to closeTo prop
  const origin = (location.state as { origin?: string } | null)?.origin ?? closeTo

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        navigate(origin)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [navigate, origin])

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Sticky header */}
      <div className="flex items-center gap-3 py-3 border-b border-border-solid flex-shrink-0">
        {/* Back arrow */}
        <button
          onClick={() => navigate(-1)}
          className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-md text-text-muted hover:text-text hover:bg-surface-alt transition-colors"
          aria-label="Back"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10 3L5 8l5 5" />
          </svg>
        </button>

        {/* Title */}
        <div className="flex-1 min-w-0">
          {titleSlot ? (
            titleSlot
          ) : (
            <h2 className="text-lg font-semibold font-title text-text truncate">{title}</h2>
          )}
          {subtitle && <p className="text-sm text-text-muted truncate">{subtitle}</p>}
        </div>

        {/* X close button → origin list */}
        <button
          onClick={() => navigate(origin)}
          className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-md text-text-muted hover:text-text hover:bg-surface-alt transition-colors"
          aria-label="Close"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto py-5">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="w-full">
            {children}
          </div>
        )}
      </div>
    </div>
  )
}
