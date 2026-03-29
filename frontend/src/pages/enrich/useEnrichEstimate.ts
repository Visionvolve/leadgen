/**
 * useEnrichEstimate — React Query hook that POSTs to /api/enrich/estimate
 * whenever filters or enabled stages change.
 *
 * Gates (triage etc.) are filtered out before sending to the API since
 * they have zero cost and aren't real enrichment stages.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../../api/client'
import { STAGE_MAP } from './stageConfig'
import type { EnrichFilters, StageEstimate } from './StageCard.types'

export interface EstimateResponse {
  stages: Record<string, StageEstimate>
  total_estimated_cost: number
}

/** Filter out gate stages — the estimate API doesn't know about them */
function filterGates(stages: string[]): string[] {
  return stages.filter((code) => {
    const def = STAGE_MAP[code]
    return def && !def.isGate
  })
}

/**
 * Compute "up to" eligible count for stages behind a gate.
 * When a stage has 0 eligible (nothing passed the gate yet),
 * we propagate the upstream estimate so users see potential throughput.
 */
export function computeUpstreamEligible(
  stageCode: string,
  estimates: Record<string, StageEstimate>,
): number | null {
  const def = STAGE_MAP[stageCode]
  if (!def) return null

  // Walk hard deps — if any dep is a gate, find the gate's upstream estimate
  for (const depCode of def.hardDeps) {
    const depDef = STAGE_MAP[depCode]
    if (depDef?.isGate) {
      // Gate's upstream: find the gate's own hard deps
      for (const gateUpstream of depDef.hardDeps) {
        const upstream = estimates[gateUpstream]
        if (upstream) return upstream.eligible_count
      }
    }
  }
  return null
}

/**
 * Compute boost-adjusted total cost.
 * Stages with boost enabled get 2x cost multiplier.
 */
export function computeAdjustedCost(
  estimates: Record<string, StageEstimate>,
  boostStages: Record<string, boolean>,
): number {
  let total = 0
  for (const [code, est] of Object.entries(estimates)) {
    const multiplier = boostStages[code] ? 2 : 1
    total += est.estimated_cost * multiplier
  }
  return Math.round(total * 100) / 100
}

export function useEnrichEstimate(
  filters: EnrichFilters,
  enabledStages: string[],
  softDepsPayload: Record<string, boolean>,
  reEnrichPayload?: Record<string, { enabled: boolean; horizon: string | null }>,
) {
  // Filter gates before sending to API
  const apiStages = useMemo(() => filterGates(enabledStages), [enabledStages])

  return useQuery({
    queryKey: ['enrich-estimate', filters.tag, filters.owner, filters.tier, filters.status, filters.entityIds, filters.limit, apiStages, reEnrichPayload],
    queryFn: () => {
      const body: Record<string, unknown> = {
        stages: apiStages,
        soft_deps: softDepsPayload,
      }
      if (filters.tag) body.tag_name = filters.tag
      if (filters.owner) body.owner_name = filters.owner
      if (filters.tier) body.tier_filter = [filters.tier]
      if (filters.status) body.status_filter = filters.status
      if (filters.limit) body.limit = Number(filters.limit)
      if (filters.entityIds) {
        body.entity_ids = filters.entityIds.split(',').map((s) => s.trim()).filter(Boolean)
      }
      if (reEnrichPayload) {
        body.re_enrich = reEnrichPayload
      }

      return apiFetch<EstimateResponse>('/enrich/estimate', {
        method: 'POST',
        body,
      })
    },
    enabled: apiStages.length > 0,
    staleTime: 10_000,
    retry: 0,
  })
}
