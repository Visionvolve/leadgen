import { useCallback } from 'react'
import { useLocalStorage } from './useLocalStorage'

/**
 * Manages which campaigns are shown as columns in the contacts table.
 * Persists selected campaign IDs to localStorage.
 */
export function useCampaignColumns(namespace: string | undefined) {
  const storageKey = `leadgen_campaign_cols_${namespace ?? 'default'}`
  const [campaignColumnIds, setCampaignColumnIds] = useLocalStorage<string[]>(storageKey, [])

  const add = useCallback((id: string) => {
    setCampaignColumnIds((prev) => (prev.includes(id) ? prev : [...prev, id]))
  }, [setCampaignColumnIds])

  const remove = useCallback((id: string) => {
    setCampaignColumnIds((prev) => prev.filter((cid) => cid !== id))
  }, [setCampaignColumnIds])

  const toggle = useCallback((id: string) => {
    setCampaignColumnIds((prev) =>
      prev.includes(id) ? prev.filter((cid) => cid !== id) : [...prev, id],
    )
  }, [setCampaignColumnIds])

  return { campaignColumnIds, add, remove, toggle, set: setCampaignColumnIds }
}
