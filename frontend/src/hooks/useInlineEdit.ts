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

    try {
      await mutation.mutateAsync({ id, data: { [field]: value } })
      setCellState(cellKey, 'saved')
      // Clear saved status after 2s
      const timer = setTimeout(() => {
        setCellState(cellKey, null)
        timers.current.delete(cellKey)
      }, 2000)
      timers.current.set(cellKey, timer)
    } catch {
      setCellState(cellKey, 'error')
      // Clear error status after 3s
      const timer = setTimeout(() => {
        setCellState(cellKey, null)
        timers.current.delete(cellKey)
      }, 3000)
      timers.current.set(cellKey, timer)
      throw new Error('Save failed')
    }
  }, [entityType, contactMutation, companyMutation, setCellState])

  return { save, cellStates }
}
