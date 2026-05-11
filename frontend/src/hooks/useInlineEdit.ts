import { useState, useCallback, useRef } from 'react'
import { useUpdateContact } from '../api/queries/useContacts'
import { useUpdateCompany } from '../api/queries/useCompanies'

type CellStatus = 'saving' | 'saved' | 'error'

/**
 * Hook for inline cell editing in list views.
 * Wraps existing useUpdateContact / useUpdateCompany mutations.
 * Tracks per-cell save status (saving/saved/error) with auto-clear.
 */
export function useInlineEdit(entityType: 'contact' | 'company') {
  const contactMutation = useUpdateContact()
  const companyMutation = useUpdateCompany()
  const [cellStates, setCellStates] = useState<Map<string, CellStatus>>(new Map())
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const setCellState = useCallback((key: string, status: CellStatus | null) => {
    setCellStates((prev) => {
      const next = new Map(prev)
      if (status === null) {
        next.delete(key)
      } else {
        next.set(key, status)
      }
      return next
    })
  }, [])

  const save = useCallback(async (id: string, field: string, value: string) => {
    const cellKey = `${id}:${field}`

    // Clear any existing timer for this cell
    const existingTimer = timers.current.get(cellKey)
    if (existingTimer) clearTimeout(existingTimer)

    setCellState(cellKey, 'saving')

    const mutation = entityType === 'contact' ? contactMutation : companyMutation

    const finish = (state: 'saved' | 'error') => {
      setCellState(cellKey, state)
      const ttl = state === 'saved' ? 2000 : 3000
      const timer = setTimeout(() => {
        setCellState(cellKey, null)
        timers.current.delete(cellKey)
      }, ttl)
      timers.current.set(cellKey, timer)
    }

    const submit = async (params?: Record<string, string>) => {
      await mutation.mutateAsync({ id, data: { [field]: value }, params })
    }

    try {
      await submit()
      finish('saved')
    } catch (err) {
      // Duplicate-email gate: ask the user to confirm and retry once.
      const apiErr = err as { status?: number; code?: string; details?: { existing_name?: string } }
      if (
        entityType === 'contact'
        && field === 'email_address'
        && apiErr?.status === 409
        && apiErr.code === 'duplicate_email'
      ) {
        const existing = apiErr.details?.existing_name ?? 'another contact'
        const ok = typeof window !== 'undefined'
          ? window.confirm(`Email already used by ${existing}. Save anyway?`)
          : false
        if (ok) {
          try {
            await submit({ confirm_duplicate: 'true' })
            finish('saved')
            return
          } catch {
            finish('error')
            throw new Error('Save failed')
          }
        }
        finish('error')
        throw new Error('Cancelled')
      }
      finish('error')
      throw new Error('Save failed')
    }
  }, [entityType, contactMutation, companyMutation, setCellState])

  return { save, cellStates }
}
