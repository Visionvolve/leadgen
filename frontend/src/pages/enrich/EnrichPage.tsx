/**
 * EnrichPage — DAG-based enrichment pipeline configuration and execution.
 * Replaces the vanilla dashboard/enrich.html with a React implementation.
 */

import { useRef, useState, useCallback, useMemo, useEffect } from 'react'
import { useSearchParams, useParams, useNavigate } from 'react-router'
import { FilterBar } from '../../components/ui/FilterBar'
import { useOnboardingStatus } from '../../hooks/useOnboarding'
import { EnrichEmptyState } from '../../components/onboarding/SmartEmptyState'
import { useEnrichState } from './useEnrichState'
import { useEnrichEstimate, computeAdjustedCost, computeUpstreamEligible } from './useEnrichEstimate'
import { useEnrichPipeline } from './useEnrichPipeline'
import { STAGE_MAP } from './stageConfig'
import { DagVisualization } from './DagVisualization'
import { DagEdges } from './DagEdges'
import { DagControls } from './DagControls'
import { CompletionPanel } from './CompletionPanel'
import { SchedulePanel } from './SchedulePanel'
import { StageCard } from './StageCard'

/** UUID v4 validation regex */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Parse and validate comma-separated UUIDs, dropping invalid values */
function parseUUIDs(raw: string): string[] {
  return raw.split(',').map((s) => s.trim()).filter((s) => UUID_RE.test(s))
}

/** Selection mode info derived from URL params */
interface SelectionInfo {
  entityType: 'contact' | 'company'
  ids: string[]
}

export function EnrichPage() {
  const { namespace } = useParams<{ namespace: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: onboardingStatus } = useOnboardingStatus()
  const state = useEnrichState()
  const {
    filters,
    filterConfigs,
    handleFilterChange,
    setEntityIds,
    enabledStages,
    toggleStage,
    enabledStageCodes,
    softDepsConfig,
    toggleSoftDep,
    softDepsPayload,
    reEnrichConfig,
    toggleReEnrich,
    setFreshness,
    reEnrichPayload,
    boostStages,
    toggleBoost,
    boostPayload,
    getConfigSnapshot,
    loadConfigSnapshot,
  } = state

  // ── Selected-entities mode from URL params ────────────────────────
  const selectionInfo = useMemo<SelectionInfo | null>(() => {
    // ?contacts=id1,id2,...
    const contactsParam = searchParams.get('contacts')
    if (contactsParam) {
      const ids = parseUUIDs(contactsParam)
      if (ids.length > 0) return { entityType: 'contact', ids }
    }

    // ?companies=id1,id2,...
    const companiesParam = searchParams.get('companies')
    if (companiesParam) {
      const ids = parseUUIDs(companiesParam)
      if (ids.length > 0) return { entityType: 'company', ids }
    }

    // ?selection=sess_key (sessionStorage fallback for large selections)
    const selectionKey = searchParams.get('selection')
    if (selectionKey) {
      try {
        const raw = sessionStorage.getItem(`enrich_selection_${selectionKey}`)
        if (raw) {
          const parsed = JSON.parse(raw) as { entity_type: string; ids: string[] }
          const ids = parsed.ids.filter((s: string) => UUID_RE.test(s))
          if (ids.length > 0) {
            return {
              entityType: parsed.entity_type === 'company' ? 'company' : 'contact',
              ids,
            }
          }
        }
      } catch {
        // Invalid session data — fall through to standard mode
      }
    }

    // ?entity_type=contact&filters=base64 (all-matching mode)
    // For now, we don't resolve filter-based selections client-side.
    // This would require an API call to resolve filters to IDs.
    // The filters param is a placeholder for future implementation.

    return null
  }, [searchParams])

  const isSelectedMode = selectionInfo !== null

  // Sync URL-derived entity IDs into the enrich state filter
  useEffect(() => {
    if (selectionInfo) {
      setEntityIds(selectionInfo.ids.join(','))
    }
  }, [selectionInfo, setEntityIds])

  // Handlers for selection banner
  const handleChangeSelection = useCallback(() => {
    if (!namespace) return
    const target = selectionInfo?.entityType === 'company' ? 'companies' : 'contacts'
    navigate(`/${namespace}/${target}`)
  }, [namespace, navigate, selectionInfo])

  const handleClearSelection = useCallback(() => {
    // Remove selection params, revert to standard filter mode
    setSearchParams({})
    setEntityIds('')
  }, [setSearchParams, setEntityIds])

  const pipeline = useEnrichPipeline(filters)
  const { dagMode, stageProgress, totalCost, start, stop, reset } = pipeline

  const estimate = useEnrichEstimate(
    filters,
    enabledStageCodes,
    softDepsPayload,
    reEnrichPayload,
  )

  // Card refs for edge drawing
  const containerRef = useRef<HTMLDivElement>(null)
  const cardRefsObj = useRef<Record<string, HTMLDivElement | null>>({})
  const setCardRef = useCallback((code: string) => (el: HTMLDivElement | null) => {
    cardRefsObj.current[code] = el
  }, [])

  // Hovered stage for edge highlighting
  const [hoveredStage, setHoveredStage] = useState<string | null>(null)

  // Run handler
  const handleRun = useCallback(() => {
    start({
      tag_name: filters.tag || undefined,
      owner: filters.owner || undefined,
      tier_filter: filters.tier ? [filters.tier] : undefined,
      stages: enabledStageCodes,
      soft_deps: softDepsPayload,
      sample_size: filters.limit ? Number(filters.limit) : undefined,
      entity_ids: filters.entityIds
        ? filters.entityIds.split(',').map((s) => s.trim()).filter(Boolean)
        : undefined,
      re_enrich: reEnrichPayload,
      boost: boostPayload,
    })
  }, [start, filters, enabledStageCodes, softDepsPayload, reEnrichPayload, boostPayload])

  // Boost-adjusted estimated cost
  const estimatedCost = useMemo(() => {
    if (!estimate.data?.stages) return 0
    return computeAdjustedCost(estimate.data.stages, boostStages)
  }, [estimate.data?.stages, boostStages])

  // Compute upstream eligible counts for stages behind gates
  const upstreamEligibleMap = useMemo(() => {
    if (!estimate.data?.stages) return {} as Record<string, number | null>
    const result: Record<string, number | null> = {}
    for (const code of enabledStageCodes) {
      result[code] = computeUpstreamEligible(code, estimate.data.stages)
    }
    return result
  }, [estimate.data?.stages, enabledStageCodes])

  // Convert typed filters to Record<string, string> for FilterBar
  const filterValues: Record<string, string> = useMemo(
    () => ({ ...filters }),
    [filters],
  )

  // Show smart empty state when namespace has no contacts
  const namespaceHasNoContacts =
    onboardingStatus !== undefined && onboardingStatus.contact_count === 0
  if (namespaceHasNoContacts) {
    return <EnrichEmptyState />
  }

  // Compute selection summary for the banner
  const selectionSummary = useMemo(() => {
    if (!isSelectedMode || !estimate.data?.stages) return null
    const stageEstimates = Object.values(estimate.data.stages)
    const maxEligible = stageEstimates.length > 0
      ? Math.max(...stageEstimates.map((s) => s.eligible_count))
      : 0
    const totalSelected = selectionInfo!.ids.length
    const skipped = totalSelected - maxEligible
    return { eligible: maxEligible, skipped: Math.max(0, skipped), total: totalSelected }
  }, [isSelectedMode, selectionInfo, estimate.data?.stages])

  return (
    <div className="p-6">
      {/* Selected-entities banner OR standard filter bar */}
      {isSelectedMode ? (
        <div className="mb-4">
          <div
            className="flex items-center gap-3 px-4 py-3 rounded-lg bg-accent/5 border-l-4 border-accent/20"
            role="status"
            aria-live="polite"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent flex-shrink-0">
              <path d="M7 2v5.5H4L9 13l5-5.5h-3V2H7z" />
              <path d="M3 16h12" />
            </svg>
            <span className="text-sm font-medium text-text">
              Enriching {selectionInfo!.ids.length} selected {selectionInfo!.entityType === 'company' ? 'companies' : 'contacts'}
            </span>
            <div className="ml-auto flex items-center gap-3">
              <button
                type="button"
                onClick={handleChangeSelection}
                className="text-xs text-accent hover:underline"
                aria-label={`Go back to ${selectionInfo!.entityType === 'company' ? 'companies' : 'contacts'} list to change selection`}
              >
                Change selection
              </button>
              <button
                type="button"
                onClick={handleClearSelection}
                className="text-xs text-text-muted hover:text-text"
              >
                Clear
              </button>
            </div>
          </div>
          {/* Estimate summary */}
          {selectionSummary && (
            <div className="mt-2 px-4 text-xs text-text-muted">
              {selectionSummary.eligible} need enrichment
              {selectionSummary.skipped > 0 && (
                <>, {selectionSummary.skipped} already enriched (will be skipped)</>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className={dagMode === 'running' ? 'opacity-60 pointer-events-none' : ''}>
          <FilterBar
            filters={filterConfigs}
            values={filterValues}
            onChange={handleFilterChange}
          />
        </div>
      )}

      {/* Controls bar */}
      <>
        <DagControls
            mode={dagMode}
            tagName={filters.tag}
            estimatedCost={estimatedCost}
            runningCost={totalCost}
            enabledCount={enabledStageCodes.length}
            onRun={handleRun}
            onStop={stop}
            isLoading={estimate.isFetching && !estimate.isError}
            estimateError={estimate.isError}
            onLoadConfig={loadConfigSnapshot}
            getConfigSnapshot={getConfigSnapshot}
          />

          {/* DAG with edges */}
          <div className="relative" ref={containerRef}>
            <DagEdges
              containerRef={containerRef}
              cardRefs={cardRefsObj.current}
              enabledStages={enabledStages}
              mode={dagMode}
              progress={stageProgress}
              softDepsConfig={softDepsConfig}
              hoveredStage={hoveredStage}
            />
            <DagVisualization>
              {(stageCode) => {
                const stageDef = STAGE_MAP[stageCode]
                if (!stageDef) return null

                // Build soft dep info
                const softDeps = stageDef.softDeps.map((depCode) => ({
                  code: depCode,
                  name: STAGE_MAP[depCode]?.displayName ?? depCode,
                  active: softDepsConfig[`${stageCode}:${depCode}`] !== false,
                }))

                // Get stage estimate with boost adjustment
                const stageEst = estimate.data?.stages?.[stageCode] ?? null
                const boostMultiplier = boostStages[stageCode] ? 2 : 1
                const adjustedEstimate = stageEst ? {
                  ...stageEst,
                  cost_per_item: Math.round(stageEst.cost_per_item * boostMultiplier * 10000) / 10000,
                  estimated_cost: Math.round(stageEst.estimated_cost * boostMultiplier * 100) / 100,
                } : null

                return (
                  <div
                    key={stageCode}
                    ref={setCardRef(stageCode)}
                    onMouseEnter={() => setHoveredStage(stageCode)}
                    onMouseLeave={() => setHoveredStage(null)}
                  >
                    <StageCard
                      stage={stageDef}
                      mode={dagMode}
                      estimate={adjustedEstimate}
                      enabled={enabledStages[stageCode] ?? false}
                      onToggle={(v) => toggleStage(stageCode, v)}
                      progress={stageProgress[stageCode] ?? null}
                      softDeps={softDeps}
                      onSoftDepToggle={(dep, active) => toggleSoftDep(stageCode, dep, active)}
                      reEnrich={reEnrichConfig[stageCode] ?? { enabled: false, horizon: null }}
                      onReEnrichToggle={(v) => toggleReEnrich(stageCode, v)}
                      onFreshnessChange={(h) => setFreshness(stageCode, h)}
                      boost={boostStages[stageCode] ?? false}
                      onBoostToggle={(v) => toggleBoost(stageCode, v)}
                      upstreamEligible={upstreamEligibleMap[stageCode] ?? undefined}
                    />
                  </div>
                )
              }}
            </DagVisualization>
          </div>

          {/* Schedule panel — only in configure mode */}
          {dagMode === 'configure' && <SchedulePanel />}

          {/* Completion panel */}
          {dagMode === 'completed' && (
            <CompletionPanel
              stageProgress={stageProgress}
              totalCost={totalCost}
              onReset={reset}
            />
          )}
      </>
    </div>
  )
}
