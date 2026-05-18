import { useEffect, useRef, useState } from 'react'

import type {
  DuplicateContext,
  CompanyMatch,
} from '../../hooks/useCompanyDuplicateGate'

export interface DuplicateCompanyModalProps {
  ctx: DuplicateContext
  /** When set, cards whose match.owner.id differs render an "Owner differs"
   * warning. Pass `company.owner_id` from CompanyDetail; pass `null` from
   * the table (per-row owner not trivially available). */
  currentOwnerId?: string | null
}

const SAFE_DOMAIN_RE = /^[a-z0-9.-]+$/i

function safeDomainHref(domain: string | null): string | null {
  if (!domain) return null
  if (!SAFE_DOMAIN_RE.test(domain)) return null
  return `https://${domain}`
}

/**
 * Renders the duplicate-resolution modal that appears when an operator
 * tries to rename a company to a name that collides with an existing one
 * in the same tenant. See BL-1203 / Phase 12.
 *
 * The modal is driven entirely by the {@link DuplicateContext} produced
 * by {@link useCompanyDuplicateGate}. It does not call the API directly
 * (except for the merge fetch which lives inside ctx.resolveMerge).
 */
export function DuplicateCompanyModal({
  ctx,
  currentOwnerId,
}: DuplicateCompanyModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)
  const firstUseBtnRef = useRef<HTMLButtonElement>(null)
  const [busyMatchId, setBusyMatchId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Default focus on the first 'Use this one' button
  useEffect(() => {
    firstUseBtnRef.current?.focus()
  }, [])

  // Esc → cancel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') ctx.resolveCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [ctx])

  // Click on overlay → cancel
  const onOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === overlayRef.current) ctx.resolveCancel()
  }

  const handleMerge = async (intoId: string) => {
    setBusyMatchId(intoId)
    setError(null)
    try {
      await ctx.resolveMerge(intoId)
    } catch (e) {
      setError((e as Error).message || 'Merge failed')
      setBusyMatchId(null)
    }
  }

  const handleKeepBoth = async () => {
    setBusyMatchId('__keep_both__')
    setError(null)
    try {
      await ctx.resolveKeepBoth()
    } catch (e) {
      setError((e as Error).message || 'Save failed')
      setBusyMatchId(null)
    }
  }

  return (
    <div
      ref={overlayRef}
      onClick={onOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="dup-modal-title"
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
    >
      <div className="bg-surface-1 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-border-default">
        <header className="px-6 py-4 border-b border-border-default">
          <h2 id="dup-modal-title" className="text-lg font-semibold">
            Company name already exists
          </h2>
          <p className="text-sm text-text-muted mt-1">
            We found {ctx.matches.length}{' '}
            {ctx.matches.length === 1 ? 'company' : 'companies'} that match
            “{ctx.attemptedName}” after normalization. What would you like
            to do?
          </p>
        </header>
        <ul className="divide-y divide-border-default">
          {ctx.matches.map((m: CompanyMatch, i: number) => {
            const href = safeDomainHref(m.domain)
            const ownerMismatch =
              currentOwnerId && m.owner && m.owner.id !== currentOwnerId
            return (
              <li key={m.id} className="px-6 py-4 flex flex-col gap-2">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{m.name}</div>
                    {href && (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-accent-cyan hover:underline"
                      >
                        {m.domain}
                      </a>
                    )}
                    <div className="flex items-center gap-2 text-xs text-text-muted mt-1 flex-wrap">
                      <span>
                        {m.contact_count} contact
                        {m.contact_count === 1 ? '' : 's'}
                      </span>
                      {m.status && (
                        <span className="px-1.5 py-0.5 rounded bg-surface-2">
                          {m.status}
                        </span>
                      )}
                      {m.owner && <span>Owner: {m.owner.name}</span>}
                      {m.last_activity_at && (
                        <span>
                          Last active{' '}
                          {new Date(m.last_activity_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                    {ownerMismatch && (
                      <p className="text-xs text-status-warn mt-1">
                        Owner differs — after merge, this company will
                        belong to {m.owner!.name}.
                      </p>
                    )}
                  </div>
                  <div className="flex flex-col gap-1 shrink-0">
                    <button
                      ref={i === 0 ? firstUseBtnRef : null}
                      type="button"
                      onClick={() => ctx.resolveUseExisting(m.id)}
                      disabled={busyMatchId !== null}
                      className="text-xs px-3 py-1 rounded bg-accent-cyan/20 hover:bg-accent-cyan/30 disabled:opacity-50"
                    >
                      Use this one
                    </button>
                    <button
                      type="button"
                      onClick={() => handleMerge(m.id)}
                      disabled={busyMatchId !== null}
                      className="text-xs px-3 py-1 rounded bg-surface-2 hover:bg-surface-3 disabled:opacity-50"
                    >
                      {busyMatchId === m.id
                        ? 'Merging…'
                        : 'Merge into this one'}
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
        {error && (
          <div className="px-6 py-2 text-sm text-status-error">{error}</div>
        )}
        <footer className="px-6 py-4 border-t border-border-default flex justify-end gap-2">
          <button
            type="button"
            onClick={handleKeepBoth}
            disabled={busyMatchId !== null}
            className="text-sm px-3 py-1.5 rounded bg-surface-2 hover:bg-surface-3 disabled:opacity-50"
          >
            {busyMatchId === '__keep_both__'
              ? 'Saving…'
              : 'Keep both as separate'}
          </button>
          <button
            type="button"
            onClick={() => ctx.resolveCancel()}
            disabled={busyMatchId !== null}
            className="text-sm px-3 py-1.5 rounded border border-border-default hover:bg-surface-2 disabled:opacity-50"
          >
            Cancel
          </button>
        </footer>
      </div>
    </div>
  )
}
