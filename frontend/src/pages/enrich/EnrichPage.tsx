/**
 * EnrichPage — DAG-based enrichment pipeline configuration and execution.
 * Replaces the vanilla dashboard/enrich.html with a React implementation.
 */

import { useRef, useState, useCallback, useMemo } from 'react'
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

export function EnrichPage() {
  const { data: onboardingStatus } = useOnboardingStatus()
  const state = useEnrichState()
  const {
    filters,
    filterConfigs,
    handleFilterChange,
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

  return (
    <div className="p-6">
      {/* Filters — always visible, disabled during pipeline run */}
      <div className={dagMode === 'running' ? 'opacity-60 pointer-events-none' : ''}>
        <FilterBar
          filters={filterConfigs}
          values={filterValues}
          onChange={handleFilterChange}
        />
      </div>

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
