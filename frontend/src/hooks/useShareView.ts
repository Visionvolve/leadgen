import { useEffect, useCallback, useRef } from 'react'
import type { AdvancedFilterState } from './useAdvancedFilters'

export interface ViewConfig {
  columns: string[]
  campaignColumns?: string[]
  filters: AdvancedFilterState
  sort?: { field: string; dir: string }
}

const VIEW_PARAM = 'view'

/** Encode a ViewConfig to a base64 URL-safe string */
function encodeViewConfig(config: ViewConfig): string {
  const json = JSON.stringify(config)
  return btoa(json)
}

/** Decode a base64 URL-safe string to a ViewConfig (returns null on failure) */
function decodeViewConfig(encoded: string): ViewConfig | null {
  try {
    const json = atob(encoded)
    const parsed = JSON.parse(json)
    if (parsed && typeof parsed === 'object' && Array.isArray(parsed.columns)) {
      return parsed as ViewConfig
    }
    return null
  } catch {
    return null
  }
}

interface UseShareViewOptions {
  /** Current visible column keys */
  visibleKeys: string[]
  /** Current campaign column IDs (optional) */
  campaignColumnIds?: string[]
  /** Current advanced filter state */
  filters: AdvancedFilterState
  /** Current sort field */
  sortField: string
  /** Current sort direction */
  sortDir: string
  /** Setter for column visibility (writes to localStorage) */
  setVisibleKeys: (keys: string[]) => void
  /** Setter for campaign column IDs (writes to localStorage) */
  setCampaignColumnIds?: (ids: string[]) => void
  /** Replace all filters at once */
  replaceAllFilters: (state: AdvancedFilterState) => void
  /** Setter for sort field */
  setSortField: (field: string) => void
  /** Setter for sort direction */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setSortDir: (dir: any) => void
  /** Toast function */
  toast: (message: string, variant?: 'success' | 'error' | 'info') => void
}

/**
 * Manages sharing and applying list view configurations via URL parameter.
 *
 * - `shareView()` encodes current columns + filters + sort into a `?view=` URL param,
 *   copies the full URL to clipboard, and shows a toast.
 * - On mount, if `?view=` is present, decodes and applies the config, then removes the param.
 */
export function useShareView(options: UseShareViewOptions) {
  const {
    visibleKeys,
    campaignColumnIds,
    filters,
    sortField,
    sortDir,
    setVisibleKeys,
    setCampaignColumnIds,
    replaceAllFilters,
    setSortField,
    setSortDir,
    toast,
  } = options

  const appliedRef = useRef(false)

  // On mount: check for ?view= param and apply if present
  useEffect(() => {
    if (appliedRef.current) return
    const url = new URL(window.location.href)
    const encoded = url.searchParams.get(VIEW_PARAM)
    if (!encoded) return

    const config = decodeViewConfig(encoded)
    if (!config) {
      // Invalid payload — clean up the param silently
      url.searchParams.delete(VIEW_PARAM)
      window.history.replaceState({}, '', url.toString())
      return
    }

    appliedRef.current = true

    // Apply columns
    if (config.columns.length > 0) {
      setVisibleKeys(config.columns)
    }

    // Apply campaign columns
    if (config.campaignColumns && setCampaignColumnIds) {
      setCampaignColumnIds(config.campaignColumns)
    }

    // Apply filters
    if (config.filters) {
      replaceAllFilters(config.filters)
    }

    // Apply sort
    if (config.sort) {
      setSortField(config.sort.field)
      setSortDir(config.sort.dir)
    }

    // Remove ?view= param from URL
    url.searchParams.delete(VIEW_PARAM)
    window.history.replaceState({}, '', url.toString())

    toast('View settings applied', 'success')
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- run once on mount

  const shareView = useCallback(async () => {
    const config: ViewConfig = {
      columns: visibleKeys,
      filters,
      sort: { field: sortField, dir: sortDir },
    }
    if (campaignColumnIds && campaignColumnIds.length > 0) {
      config.campaignColumns = campaignColumnIds
    }

    const encoded = encodeViewConfig(config)
    const url = new URL(window.location.href)
    // Remove any existing view param first
    url.searchParams.delete(VIEW_PARAM)
    url.searchParams.set(VIEW_PARAM, encoded)

    try {
      await navigator.clipboard.writeText(url.toString())
      toast('View link copied! Share it with your team.', 'success')
    } catch {
      // Fallback: select-and-copy approach for non-secure contexts
      toast('Could not copy to clipboard', 'error')
    }
  }, [visibleKeys, campaignColumnIds, filters, sortField, sortDir, toast])

  return { shareView }
}
