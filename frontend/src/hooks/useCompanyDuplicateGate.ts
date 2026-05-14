import { useEffect, useState } from 'react'

import { apiFetch } from '../api/client'

export type CompanyMatch = {
  id: string
  name: string
  domain: string | null
  status: string | null
  owner: { id: string; name: string } | null
  contact_count: number
  last_activity_at: string | null
}

export type DuplicateContext = {
  editedCompanyId: string
  attemptedName: string
  matches: CompanyMatch[]
  resolveMerge: (intoId: string) => Promise<void>
  resolveUseExisting: (matchId: string) => void
  resolveKeepBoth: () => Promise<void>
  resolveCancel: () => void
}

type EventDetail = {
  editedCompanyId: string
  attemptedName: string
  matches: CompanyMatch[]
  retryWithKeepBoth: () => Promise<void>
  revertInput: () => void
  afterMerge: () => void
}

/**
 * Window-event subscriber for BL-1203 / Phase 12.
 *
 * useInlineEdit (Companies table) and the CompanyDetail page both dispatch
 * `leadgen:company-duplicate` on a 409 response from PATCH /api/companies.
 * This hook captures the event, stores a DuplicateContext, and exposes the
 * four resolution callbacks the DuplicateCompanyModal renders.
 */
export function useCompanyDuplicateGate(): {
  pendingDuplicate: DuplicateContext | null
  dismiss: () => void
} {
  const [pending, setPending] = useState<DuplicateContext | null>(null)

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<EventDetail>).detail
      const ns = window.location.pathname.split('/')[1] || ''
      const ctx: DuplicateContext = {
        editedCompanyId: detail.editedCompanyId,
        attemptedName: detail.attemptedName,
        matches: detail.matches,
        resolveMerge: async (intoId: string) => {
          // POST /api/companies/<edited>/merge?into=<intoId>
          await apiFetch(`/companies/${detail.editedCompanyId}/merge`, {
            method: 'POST',
            params: { into: intoId },
          })
          detail.afterMerge()
          setPending(null)
          // Navigate to the surviving record's detail page
          window.dispatchEvent(
            new CustomEvent('leadgen:navigate', {
              detail: `/${ns}/companies/${intoId}`,
            }),
          )
        },
        resolveUseExisting: (matchId: string) => {
          detail.revertInput()
          setPending(null)
          window.dispatchEvent(
            new CustomEvent('leadgen:navigate', {
              detail: `/${ns}/companies/${matchId}`,
            }),
          )
        },
        resolveKeepBoth: async () => {
          await detail.retryWithKeepBoth()
          setPending(null)
        },
        resolveCancel: () => {
          detail.revertInput()
          setPending(null)
        },
      }
      setPending(ctx)
    }
    window.addEventListener('leadgen:company-duplicate', handler)
    return () =>
      window.removeEventListener('leadgen:company-duplicate', handler)
  }, [])

  return { pendingDuplicate: pending, dismiss: () => setPending(null) }
}
