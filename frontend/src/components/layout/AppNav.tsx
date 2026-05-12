/**
 * Two-tier pillar navigation — React port of nav.js.
 * Tier 1: pillar icons + brand + user menu
 * Tier 2: sub-page links for active pillar
 *
 * User menu dropdown has 3 groups:
 *   1. Personal — Preferences, Sign Out (all users)
 *   2. Namespace — Users & Roles, Credits (admin only)
 *   3. Super Admin — LLM Costs (super_admin only)
 */

import { useState, useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router'
import { useAuth } from '../../hooks/useAuth'
import { useNamespace } from '../../hooks/useNamespace'
import { useChatContext, useHasUnread } from '../../providers/ChatProvider'
import { useNudgeCount } from '../../hooks/useWorkflowSuggestions'
import { type Role, setLastNamespace } from '../../lib/auth'
import { getRevision, clearRevision } from '../../lib/revision'
import { apiFetch } from '../../api/client'

// ---- Pillar config ----

interface PageDef {
  id: string
  label: string
  path: string
  minRole: Role
}

interface PillarDef {
  id: string
  label: string
  icon: React.ReactNode
  pages: PageDef[]
}

const PILLARS: PillarDef[] = [
  {
    id: 'playbook',
    label: 'Playbook',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /><path d="M8 7h8M8 11h6" />
      </svg>
    ),
    pages: [{ id: 'playbook', label: 'Strategy Overview', path: 'playbook', minRole: 'viewer' }],
  },
  {
    id: 'radar',
    label: 'Radar',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /><path d="M12 2v4M12 18v4" />
      </svg>
    ),
    pages: [
      { id: 'contacts', label: 'Contacts', path: 'contacts', minRole: 'viewer' },
      { id: 'companies', label: 'Companies', path: 'companies', minRole: 'viewer' },
      { id: 'triage', label: 'Triage', path: 'triage', minRole: 'editor' },
      { id: 'import', label: 'Import', path: 'import', minRole: 'editor' },
      { id: 'enrich', label: 'Enrich', path: 'enrich', minRole: 'editor' },
    ],
  },
  {
    id: 'reach',
    label: 'Reach',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 2L11 13" /><path d="M22 2L15 22l-4-9-9-4z" />
      </svg>
    ),
    pages: [
      { id: 'campaigns', label: 'Campaigns', path: 'campaigns', minRole: 'viewer' },
    ],
  },
  {
    id: 'echo',
    label: 'Echo',
    icon: (
      <svg viewBox="0 0 24 24" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" />
      </svg>
    ),
    pages: [{ id: 'echo', label: 'Dashboard Demo', path: 'echo', minRole: 'viewer' }],
  },
]

// ---- Component ----

export function AppNav() {
  const { user, hasRole, logout } = useAuth()
  const namespace = useNamespace()
  const location = useLocation()
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)

  // Derive active pillar/page from URL
  const pathSegments = location.pathname.split('/').filter(Boolean)
  // URL shape: /{namespace}/{page} or /{root-page}
  const currentPage = namespace ? pathSegments[1] ?? '' : pathSegments[0] ?? ''

  const activePillar = PILLARS.find((p) =>
    p.pages.some((pg) => pg.path === currentPage),
  )

  // Close user menu on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('click', handleClick)
    return () => document.removeEventListener('click', handleClick)
  }, [])

  const rev = getRevision()

  function makePath(pagePath: string) {
    const base = namespace ? `/${namespace}/${pagePath}` : `/${pagePath}`
    return rev ? `${base}?rev=${rev}` : base
  }

  return (
    <div className="app-nav">
      {/* Tier 1 */}
      <div className="flex items-center gap-2 px-6 py-3 bg-surface border-b border-border">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2.5 no-underline">
          <img src="/visionvolve-icon-color.svg" alt="VisionVolve" className="h-[26px] w-auto" />
          <span className="font-title text-[1.05rem] font-bold tracking-tight text-text">Leadgen</span>
        </Link>

        {/* Revision indicator */}
        {rev && (
          <span className="ml-3 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[0.7rem] font-mono font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            rev:{rev}
            <button
              onClick={() => {
                clearRevision()
                const url = new URL(window.location.href)
                url.searchParams.delete('rev')
                window.location.href = url.toString()
              }}
              className="ml-0.5 w-3.5 h-3.5 flex items-center justify-center rounded-full bg-transparent hover:bg-amber-500/20 text-amber-400/60 hover:text-amber-400 transition-colors cursor-pointer border-none p-0 text-[0.65rem] leading-none"
              title="Exit revision mode"
            >
              &times;
            </button>
          </span>
        )}

        {/* Pillars */}
        <div className="flex gap-1 ml-6">
          {PILLARS.map((pillar) => {
            const isActive = pillar.id === activePillar?.id
            const defaultPage = pillar.pages[0]!
            if (!hasRole(defaultPage.minRole)) return null

            return (
              <Link
                key={pillar.id}
                to={makePath(defaultPage.path)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[0.82rem] font-medium no-underline transition-colors ${
                  isActive
                    ? 'text-accent-cyan bg-accent-cyan/8'
                    : 'text-text-muted hover:text-text hover:bg-accent/8'
                }`}
              >
                <span className="opacity-70">{pillar.icon}</span>
                <span>{pillar.label}</span>
              </Link>
            )
          })}
        </div>

        {/* Right section */}
        <div className="flex items-center gap-3 ml-auto">
          {/* Chat toggle */}
          <ChatToggleButton />

          {/* Namespace switcher */}
          <NamespaceSwitcher />

          {/* User menu dropdown */}
          {user && (
            <div ref={userMenuRef} className="relative">
              <button
                onClick={(e) => { e.stopPropagation(); setUserMenuOpen(!userMenuOpen) }}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-text-muted hover:text-text hover:bg-surface-alt transition-colors bg-transparent border-none cursor-pointer"
              >
                <span className="text-[0.82rem]">
                  {user.display_name || user.email}
                </span>
                {user.is_super_admin && (
                  <span className="text-[0.65rem] font-semibold text-accent-cyan bg-accent-cyan/10 px-1.5 py-0.5 rounded">
                    Super
                  </span>
                )}
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 opacity-50" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>

              {userMenuOpen && (
                <div className="absolute right-0 top-full mt-1 bg-surface border border-border-solid rounded-lg py-1 min-w-[200px] shadow-lg z-50">
                  {/* Personal section */}
                  <div className="px-3 pt-1.5 pb-1 text-[0.68rem] font-semibold text-text-muted/60 uppercase tracking-wider">
                    Personal
                  </div>
                  <Link
                    to={makePath('preferences')}
                    className="block px-4 py-2 text-[0.82rem] text-text-muted no-underline hover:bg-surface-alt hover:text-text transition-colors"
                    onClick={() => setUserMenuOpen(false)}
                  >
                    Preferences
                  </Link>
                  <button
                    onClick={logout}
                    className="block w-full text-left px-4 py-2 text-[0.82rem] text-text-muted bg-transparent border-none cursor-pointer hover:bg-surface-alt hover:text-error transition-colors"
                  >
                    Sign Out
                  </button>

                  {/* Namespace section — admin only */}
                  {hasRole('admin') && (
                    <>
                      <div className="my-1 border-t border-border" />
                      <div className="px-3 pt-1.5 pb-1 text-[0.68rem] font-semibold text-text-muted/60 uppercase tracking-wider">
                        Namespace
                      </div>
                      <Link
                        to={makePath('admin')}
                        className="block px-4 py-2 text-[0.82rem] text-text-muted no-underline hover:bg-surface-alt hover:text-text transition-colors"
                        onClick={() => setUserMenuOpen(false)}
                      >
                        Users &amp; Roles
                      </Link>
                      <Link
                        to={makePath('admin/tokens')}
                        className="block px-4 py-2 text-[0.82rem] text-text-muted no-underline hover:bg-surface-alt hover:text-text transition-colors"
                        onClick={() => setUserMenuOpen(false)}
                      >
                        Credits &amp; Usage
                      </Link>
                    </>
                  )}

                  {/* Super Admin section — super_admin only */}
                  {user.is_super_admin && (
                    <>
                      <div className="my-1 border-t border-border" />
                      <div className="px-3 pt-1.5 pb-1 text-[0.68rem] font-semibold text-accent-cyan/60 uppercase tracking-wider">
                        Super Admin
                      </div>
                      <Link
                        to={makePath('llm-costs')}
                        className="block px-4 py-2 text-[0.82rem] text-text-muted no-underline hover:bg-surface-alt hover:text-text transition-colors"
                        onClick={() => setUserMenuOpen(false)}
                      >
                        LLM Costs
                      </Link>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tier 2 — sub-nav for active pillar */}
      {activePillar && activePillar.pages.length > 1 && (
        <div className="flex gap-1 px-6 py-1.5 bg-surface-alt border-b border-border">
          {activePillar.pages.map((page) => {
            if (!hasRole(page.minRole)) return null
            const isActive = page.path === currentPage

            return (
              <Link
                key={page.id}
                className={`px-3 py-1 rounded text-[0.78rem] font-medium no-underline transition-colors ${
                  isActive
                    ? 'text-accent-cyan bg-accent-cyan/10'
                    : 'text-text-muted hover:text-text hover:bg-accent/8'
                }`}
                to={makePath(page.path)}
              >
                {page.label}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---- Chat toggle button sub-component ----

function ChatToggleButton() {
  const { toggleChat, isOpen } = useChatContext()
  const hasUnread = useHasUnread()
  const { data: nudgeCount = 0 } = useNudgeCount(true)

  // Show badge: nudge count when panel is closed, or unread dot
  const showNudgeBadge = !isOpen && nudgeCount > 0
  const showUnreadDot = hasUnread && !showNudgeBadge

  return (
    <button
      onClick={toggleChat}
      className="relative p-1.5 rounded-md border border-border text-text-muted hover:text-accent-cyan hover:border-accent-cyan/40 transition-colors bg-transparent cursor-pointer hidden md:flex items-center justify-center"
      aria-label="Toggle AI Chat (Cmd+K)"
      title="AI Chat (Cmd+K)"
    >
      <svg
        viewBox="0 0 24 24"
        className="w-4 h-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
      {showNudgeBadge && (
        <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 flex items-center justify-center bg-accent-cyan text-white text-[10px] font-bold rounded-full leading-none">
          {nudgeCount}
        </span>
      )}
      {showUnreadDot && (
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-accent-cyan rounded-full" />
      )}
    </button>
  )
}

// ---- Namespace switcher sub-component ----

function NamespaceSwitcher() {
  const { user } = useAuth()
  const namespace = useNamespace()
  const [namespaces, setNamespaces] = useState<string[]>([])

  useEffect(() => {
    if (!user) return

    const userNs = Object.keys(user.roles)
    setNamespaces(userNs)

    // Super admin: fetch all tenants
    if (user.is_super_admin) {
      apiFetch<Array<{ slug: string; is_active: boolean }>>('/tenants')
        .then((tenants) => {
          const slugs = tenants.filter((t) => t.is_active).map((t) => t.slug)
          if (slugs.length > 0) setNamespaces(slugs)
        })
        .catch(() => { /* keep user namespaces */ })
    }
  }, [user])

  const showSwitcher = user && (user.is_super_admin || namespaces.length > 1)
  if (!showSwitcher) return null

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newNs = e.target.value
    if (!newNs || newNs === namespace) return

    // Persist namespace selection
    setLastNamespace(newNs)

    // Preserve current sub-page
    const path = window.location.pathname
    let subPage = ''
    if (namespace) {
      const prefix = `/${namespace}`
      if (path.startsWith(prefix)) {
        subPage = path.substring(prefix.length)
      }
    }
    if (!subPage || subPage === '/') subPage = '/contacts'
    const revParam = getRevision()
    const revSuffix = revParam ? `?rev=${revParam}` : ''
    window.location.href = `/${newNs}${subPage}${revSuffix}`
  }

  return (
    <select
      value={namespace ?? ''}
      onChange={handleChange}
      className="bg-surface border border-border rounded px-2 py-1 text-[0.78rem] text-text font-body cursor-pointer outline-none hover:border-accent focus:border-accent transition-colors"
    >
      {namespaces.map((slug) => (
        <option key={slug} value={slug} className="bg-surface text-text">
          {slug}
        </option>
      ))}
    </select>
  )
}
