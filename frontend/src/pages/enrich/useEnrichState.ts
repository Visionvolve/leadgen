/**
 * Central state hook for the enrich page.
 * Manages filters, DAG mode, stage toggles, soft dep config, and re-enrich settings.
 */

import { useState, useMemo, useCallback } from 'react'
import { useParams } from 'react-router'
import { useLocalStorage } from '../../hooks/useLocalStorage'
import { useTags } from '../../api/queries/useTags'
import { filterOptions, STATUS_DISPLAY, TIER_DISPLAY } from '../../lib/display'
import { STAGES } from './stageConfig'
import type { FilterConfig } from '../../components/ui/FilterBar'
import type { DagMode, EnrichFilters, ReEnrichConfig } from './StageCard.types'

/** Default: all non-terminal stages enabled */
function defaultEnabledStages(): Record<string, boolean> {
  const m: Record<string, boolean> = {}
  for (const s of STAGES) {
    m[s.code] = s.available && !s.isTerminal
  }
  return m
}

export function useEnrichState() {
  // Namespace prefix for localStorage keys to prevent cross-tenant state leakage.
  // Use React Router's useParams for reactive namespace tracking (not window.location).
  const { namespace } = useParams<{ namespace: string }>()
  const ns = namespace ?? '_'
  const nsKey = (suffix: string) => `en_${ns}_${suffix}`

  // Filter state (persisted per namespace)
  const [search, setSearch] = useLocalStorage(nsKey('filter_search'), '')
  const [tag, setTag] = useLocalStorage(nsKey('filter_tag'), '')
  const [owner, setOwner] = useLocalStorage(nsKey('filter_owner'), '')
  const [tier, setTier] = useLocalStorage(nsKey('filter_tier'), '')
  const [status, setStatus] = useLocalStorage(nsKey('filter_status'), '')
  const [entityIds, setEntityIds] = useLocalStorage(nsKey('filter_ids'), '')
  const [limit, setLimit] = useLocalStorage(nsKey('filter_limit'), '')

  // DAG mode
  const [dagMode, setDagMode] = useState<DagMode>('configure')

  // Stage toggles
  const [enabledStages, setEnabledStages] = useLocalStorage<Record<string, boolean>>(
    nsKey('enabled_stages'),
    defaultEnabledStages(),
  )

  // Soft dep config per stage
  const [softDepsConfig, setSoftDepsConfig] = useLocalStorage<Record<string, boolean>>(
    nsKey('soft_deps'),
    {},
  )

  // Re-enrich config per stage
  const [reEnrichConfig, setReEnrichConfig] = useState<Record<string, ReEnrichConfig>>({})

  // Boost mode per stage
  const [boostStages, setBoostStages] = useLocalStorage<Record<string, boolean>>(
    nsKey('boost_stages'),
    {},
  )

  // Pipeline run ID
  const [pipelineRunId, setPipelineRunId] = useState<string | null>(null)

  // Reset non-persisted state when namespace changes to prevent cross-tenant leakage.
  // Uses render-time key comparison (React-recommended "derive state from props" pattern)
  // instead of useEffect to avoid cascading renders.
  const [prevNs, setPrevNs] = useState(ns)
  if (prevNs !== ns) {
    setPrevNs(ns)
    setDagMode('configure')
    setReEnrichConfig({})
    setPipelineRunId(null)
  }

  // Tags data for filter options
  const { data: tagsData } = useTags()

  // Filter change handler
  const handleFilterChange = useCallback(
    (key: string, value: string) => {
      const setters: Record<string, (v: string) => void> = {
        search: setSearch,
        tag: setTag,
        owner: setOwner,
        tier: setTier,
        status: setStatus,
        entityIds: setEntityIds,
        limit: setLimit,
      }
      setters[key]?.(value)
    },
    [setSearch, setTag, setOwner, setTier, setStatus, setEntityIds, setLimit],
  )

  // Filter values object
  const filters: EnrichFilters = useMemo(
    () => ({ search, tag, owner, tier, status, entityIds, limit }),
    [search, tag, owner, tier, status, entityIds, limit],
  )

  // FilterConfig array
  const filterConfigs: FilterConfig[] = useMemo(
    () => [
      {
        key: 'search',
        label: 'companies, contacts',
        type: 'search' as const,
        placeholder: 'Search company, contact...',
      },
      {
        key: 'tag',
        label: 'Tag',
        type: 'select' as const,
        options: (tagsData?.tags ?? []).map((b) => ({ value: b.name, label: b.name })),
      },
      {
        key: 'owner',
        label: 'Owner',
        type: 'select' as const,
        options: (tagsData?.owners ?? []).map((o) => ({ value: o.name, label: o.name })),
      },
      {
        key: 'tier',
        label: 'Tier',
        type: 'select' as const,
        options: filterOptions(TIER_DISPLAY),
      },
      {
        key: 'status',
        label: 'Status',
        type: 'select' as const,
        options: filterOptions(STATUS_DISPLAY),
      },
      {
        key: 'entityIds',
        label: 'Specific IDs',
        type: 'search' as const,
        placeholder: 'Paste company or contact IDs (comma-separated)...',
      },
      {
        key: 'limit',
        label: 'Limit',
        type: 'number' as const,
        placeholder: 'Limit',
        min: 1,
        max: 10000,
      },
    ],
    [tagsData],
  )

  // Stage toggle handler
  const toggleStage = useCallback(
    (code: string, enabled: boolean) => {
      setEnabledStages({ ...enabledStages, [code]: enabled })
    },
    [enabledStages, setEnabledStages],
  )

  // Soft dep toggle handler
  const toggleSoftDep = useCallback(
    (stageCode: string, depCode: string, active: boolean) => {
      setSoftDepsConfig({
        ...softDepsConfig,
        [`${stageCode}:${depCode}`]: active,
      })
    },
    [softDepsConfig, setSoftDepsConfig],
  )

  // Re-enrich toggle handler
  const toggleReEnrich = useCallback(
    (stageCode: string, enabled: boolean) => {
      setReEnrichConfig((prev) => ({
        ...prev,
        [stageCode]: { enabled, horizon: prev[stageCode]?.horizon ?? null },
      }))
    },
    [],
  )

  // Freshness horizon handler
  const setFreshness = useCallback(
    (stageCode: string, horizon: string | null) => {
      setReEnrichConfig((prev) => ({
        ...prev,
        [stageCode]: { enabled: prev[stageCode]?.enabled ?? false, horizon },
      }))
    },
    [],
  )

  // Boost toggle handler
  const toggleBoost = useCallback(
    (stageCode: string, enabled: boolean) => {
      setBoostStages({ ...boostStages, [stageCode]: enabled })
    },
    [boostStages, setBoostStages],
  )

  // Enabled stage codes (for API calls)
  const enabledStageCodes = useMemo(
    () => Object.entries(enabledStages)
      .filter(([, v]) => v)
      .map(([k]) => k),
    [enabledStages],
  )

  // Build soft_deps payload for API
  const softDepsPayload = useMemo(() => {
    const result: Record<string, boolean> = {}
    for (const stage of STAGES) {
      if (stage.softDeps.length > 0 && enabledStages[stage.code]) {
        // Check if ANY soft dep is explicitly disabled
        const allEnabled = stage.softDeps.every(
          (dep) => softDepsConfig[`${stage.code}:${dep}`] !== false,
        )
        result[stage.code] = allEnabled
      }
    }
    return result
  }, [enabledStages, softDepsConfig])

  // Build boost payload for API
  const boostPayload = useMemo(() => {
    const result: Record<string, boolean> = {}
    for (const [code, enabled] of Object.entries(boostStages)) {
      if (enabled && enabledStages[code]) {
        result[code] = true
      }
    }
    return Object.keys(result).length > 0 ? result : undefined
  }, [boostStages, enabledStages])

  // Build re_enrich payload for API
  const reEnrichPayload = useMemo(() => {
    const result: Record<string, { enabled: boolean; horizon: string | null }> = {}
    for (const [code, config] of Object.entries(reEnrichConfig)) {
      if (config.enabled) {
        result[code] = config
      }
    }
    return Object.keys(result).length > 0 ? result : undefined
  }, [reEnrichConfig])

  return {
    // Filters
    filters,
    filterConfigs,
    handleFilterChange,
    setEntityIds,

    // DAG mode
    dagMode,
    setDagMode,

    // Stage config
    enabledStages,
    toggleStage,
    enabledStageCodes,

    // Soft deps
    softDepsConfig,
    toggleSoftDep,
    softDepsPayload,

    // Re-enrich
    reEnrichConfig,
    toggleReEnrich,
    setFreshness,
    reEnrichPayload,

    // Boost
    boostStages,
    toggleBoost,
    boostPayload,

    // Config snapshot (for save/load)
    getConfigSnapshot: () => ({
      stages: enabledStages,
      soft_deps: softDepsConfig,
      re_enrich: reEnrichConfig,
      boost: boostStages,
    }),
    loadConfigSnapshot: (cfg: Record<string, unknown>) => {
      if (cfg.stages) setEnabledStages(cfg.stages as Record<string, boolean>)
      if (cfg.soft_deps) setSoftDepsConfig(cfg.soft_deps as Record<string, boolean>)
      if (cfg.re_enrich) setReEnrichConfig(cfg.re_enrich as Record<string, ReEnrichConfig>)
      if (cfg.boost) setBoostStages(cfg.boost as Record<string, boolean>)
    },

    // Pipeline
    pipelineRunId,
    setPipelineRunId,
  }
}
