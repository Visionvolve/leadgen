import { useState, useCallback, useMemo } from 'react'

export interface MultiFilterValue {
  values: string[]
  exclude: boolean
}

export interface AdvancedFilterState {
  // Simple string filters (all optional — unused keys stay empty)
  search: string
  tag_name: string
  owner_name: string
  icp_fit: string
  message_status: string
  // Dynamic multi-select filters keyed by name
  [key: string]: string | MultiFilterValue
}

const EMPTY_MULTI: MultiFilterValue = { values: [], exclude: false }

function isMultiFilter(v: unknown): v is MultiFilterValue {
  return typeof v === 'object' && v !== null && 'values' in v && 'exclude' in v
}

function buildDefaultState(multiKeys: readonly string[]): AdvancedFilterState {
  const state: AdvancedFilterState = {
    search: '',
    tag_name: '',
    owner_name: '',
    icp_fit: '',
    message_status: '',
  }
  for (const key of multiKeys) {
    state[key] = { ...EMPTY_MULTI }
  }
  return state
}

function loadState(storageKey: string, multiKeys: readonly string[]): AdvancedFilterState {
  const defaults = buildDefaultState(multiKeys)
  try {
    const saved = localStorage.getItem(storageKey)
    if (saved) {
      const parsed = JSON.parse(saved)
      const merged = { ...defaults, ...parsed }
      // Ensure multi-keys have correct shape (handles stale localStorage from pre-upgrade)
      for (const key of multiKeys) {
        if (!isMultiFilter(merged[key])) {
          merged[key] = { values: [], exclude: false }
        }
      }
      return merged
    }
  } catch { /* ignore */ }
  return defaults
}

function saveState(storageKey: string, state: AdvancedFilterState) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(state))
  } catch { /* ignore */ }
}

/** Contact-specific multi-keys (default for backward compat) */
export const CONTACT_MULTI_KEYS = [
  'company_tier',
  'industry', 'company_size', 'geo_region', 'revenue_range',
  'seniority_level', 'department', 'job_titles', 'linkedin_activity',
  'skills', 'interests',
] as const

/** Company-specific multi-keys */
export const COMPANY_MULTI_KEYS = [
  'enrichment_stage', 'tier',
  'industry', 'company_size', 'geo_region', 'revenue_range',
] as const

export function useAdvancedFilters(storageKey: string, multiKeys: readonly string[] = CONTACT_MULTI_KEYS) {
  const [filters, setFilters] = useState<AdvancedFilterState>(() => loadState(storageKey, multiKeys))

  const setSimpleFilter = useCallback((key: string, value: string) => {
    setFilters(prev => {
      const next = { ...prev, [key]: value }
      saveState(storageKey, next)
      return next
    })
  }, [storageKey])

  const setMultiFilter = useCallback((key: string, values: string[], exclude?: boolean) => {
    setFilters(prev => {
      const current = prev[key]
      const currentExclude = isMultiFilter(current) ? current.exclude : false
      const next = {
        ...prev,
        [key]: { values, exclude: exclude !== undefined ? exclude : currentExclude },
      }
      saveState(storageKey, next)
      return next
    })
  }, [storageKey])

  const toggleExclude = useCallback((key: string) => {
    setFilters(prev => {
      const current = prev[key]
      if (!isMultiFilter(current)) return prev
      const next = {
        ...prev,
        [key]: { ...current, exclude: !current.exclude },
      }
      saveState(storageKey, next)
      return next
    })
  }, [storageKey])

  const clearFilter = useCallback((key: string) => {
    setFilters(prev => {
      const isMulti = multiKeys.includes(key)
      const next = {
        ...prev,
        [key]: isMulti ? { ...EMPTY_MULTI } : '',
      }
      saveState(storageKey, next)
      return next
    })
  }, [storageKey, multiKeys])

  const clearAll = useCallback(() => {
    const next = buildDefaultState(multiKeys)
    saveState(storageKey, next)
    setFilters(next)
  }, [storageKey, multiKeys])

  const activeFilterCount = useMemo(() => {
    let count = 0
    for (const key of multiKeys) {
      const v = filters[key]
      if (isMultiFilter(v) && v.values.length > 0) count++
    }
    return count
  }, [filters, multiKeys])

  const getMulti = useCallback((key: string): MultiFilterValue => {
    const v = filters[key]
    return isMultiFilter(v) ? v : { ...EMPTY_MULTI }
  }, [filters])

  const toQueryParams = useCallback((): Record<string, string> => {
    const params: Record<string, string> = {}
    // Simple filters
    if (filters.search) params.search = filters.search as string
    if (filters.tag_name) params.tag_name = filters.tag_name as string
    if (filters.owner_name) params.owner_name = filters.owner_name as string
    if (filters.icp_fit) params.icp_fit = filters.icp_fit as string
    if (filters.message_status) params.message_status = filters.message_status as string
    // Multi-value filters
    for (const key of multiKeys) {
      const f = filters[key]
      if (isMultiFilter(f) && f.values.length > 0) {
        params[key] = f.values.join(',')
        if (f.exclude) params[`${key}_exclude`] = 'true'
      }
    }
    return params
  }, [filters, multiKeys])

  const toCountsPayload = useCallback(() => {
    const filtersPayload: Record<string, { values: string[]; exclude: boolean }> = {}
    for (const key of multiKeys) {
      const f = filters[key]
      if (isMultiFilter(f) && f.values.length > 0) {
        filtersPayload[key] = { values: f.values, exclude: f.exclude }
      }
    }
    return {
      filters: filtersPayload,
      search: (filters.search as string) || undefined,
      tag_name: (filters.tag_name as string) || undefined,
      owner_name: (filters.owner_name as string) || undefined,
    }
  }, [filters, multiKeys])

  return {
    filters,
    setSimpleFilter,
    setMultiFilter,
    toggleExclude,
    clearFilter,
    clearAll,
    activeFilterCount,
    getMulti,
    toQueryParams,
    toCountsPayload,
  }
}
